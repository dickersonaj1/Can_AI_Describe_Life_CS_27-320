"""Immutable human-approved job corrections; never modifies original archives."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .inference import write_json
from .ingest import digest


class CorrectionComplete(Exception):
    def __init__(self, artifact, path):
        self.artifact = artifact
        self.path = path


def _binding(root, attempt, config):
    from .batching import fingerprint, load

    request_path, response_path = attempt / "request.json", attempt / "response.json"
    request, response = load(request_path), load(response_path)
    if response.get("request_sha256") != fingerprint(request):
        raise ValueError("CORRECTION_BINDING: original response does not match request")
    return dict(
        attempt=attempt.relative_to(root).as_posix(),
        request_sha256=digest(request_path.read_bytes()),
        response_sha256=digest(response_path.read_bytes()),
        input_sha256=config["input_sha256"],
        plan_sha256=fingerprint(config),
    )


def _artifacts(folder):
    from .batching import fingerprint, load

    artifacts = []
    for path in sorted((folder / "corrections").glob("*.json")):
        artifact = load(path)
        if fingerprint(artifact) != path.stem:
            raise ValueError(f"CORRECTION_INTEGRITY: changed artifact {path}")
        artifacts.append((path, artifact))
    return artifacts


def _evaluate(text, contract, check):
    from .batching import problem, report

    try:
        candidate = contract.model_validate_json(text)
        issues = check(candidate)
    except (ValueError, KeyError, TypeError) as exc:
        candidate = None
        issues = [problem("INVALID_CORRECTION", str(exc))]
    return candidate, report(issues)


def reuse(root, folder, expected, config, contract, check):
    """Revalidate accepted edits every time; hash mismatches always fail closed."""
    from .batching import load

    accepted = [(p, a) for p, a in _artifacts(folder) if a.get("accepted") is True]
    if not accepted:
        return None
    if len(accepted) != 1:
        raise ValueError("CORRECTION_CONFLICT: multiple approved corrections for one job")
    path, artifact = accepted[0]
    binding = artifact["binding"]
    attempt = root / binding["attempt"]
    if attempt.parent != folder or not re.fullmatch(r"attempt_\d{4}", attempt.name):
        raise ValueError("CORRECTION_BINDING: correction belongs to another job")
    if binding != _binding(root, attempt, config) or load(attempt / "request.json") != expected:
        raise ValueError("CORRECTION_BINDING: request, response, input or plan changed")
    if (
        artifact.get("version") != "job-correction-1"
        or artifact.get("manually_approved") is not True
        or not isinstance(artifact.get("reason"), str)
        or not artifact["reason"].strip()
        or digest(artifact["candidate_text"].encode()) != artifact["candidate_sha256"]
    ):
        raise ValueError("CORRECTION_INTEGRITY: missing approval, reason or candidate binding")
    candidate, validation = _evaluate(artifact["candidate_text"], contract, check)
    if not validation["valid"]:
        raise ValueError(
            "CORRECTION_INVALID: approved edit no longer validates: " + json.dumps(validation)
        )
    provenance = dict(
        artifact=path.relative_to(root).as_posix(),
        correction_id=path.stem,
        binding=binding,
        candidate_sha256=artifact["candidate_sha256"],
        manually_approved=True,
        reason=artifact["reason"],
    )
    saved = load(attempt / "response.json")
    # In-memory annotation only; the original response is never rewritten or spoofed.
    saved["_correction"] = provenance
    return candidate, saved


def save(root, folder, expected, config, contract, check, selection):
    from .batching import fingerprint, load

    attempt = selection["attempt"]
    if attempt.parent != folder or load(attempt / "request.json") != expected:
        raise ValueError("CORRECTION_BINDING: selected attempt does not match the scheduled job")
    binding = _binding(root, attempt, config)
    text, reason = selection["text"], selection["reason"]
    _, validation = _evaluate(text, contract, check)
    artifact = dict(
        version="job-correction-1",
        binding=binding,
        candidate_text=text,
        candidate_sha256=digest(text.encode()),
        reason=reason,
        manually_approved=True,
        accepted=validation["valid"],
        validation=validation,
    )
    path = folder / "corrections" / f"{fingerprint(artifact)}.json"
    existing = _artifacts(folder)
    if any(a.get("accepted") is True and p != path for p, a in existing):
        raise ValueError("CORRECTION_CONFLICT: this job already has an accepted correction")
    if not path.exists():
        write_json(path, artifact)
    raise CorrectionComplete(artifact, path)


def approve_job(attempt, candidate_path, reason):
    """Reach the exact job's existing validator offline, then stop immediately."""
    import fcntl

    from .batching import _execute

    attempt = Path(attempt).resolve()
    if (
        not re.fullmatch(r"attempt_\d{4}", attempt.name)
        or attempt.parent.parent.name not in {"local", "reconcile", "relationships"}
        or attempt.parent.parent.parent.name != "jobs"
    ):
        raise ValueError(
            "--correct-job must identify an archived jobs/STAGE/HASH/attempt_NNNN directory"
        )
    if not reason or not reason.strip():
        raise ValueError("A nonempty --correction-reason is required")
    root = attempt.parents[3]
    selection = dict(
        attempt=attempt,
        text=Path(candidate_path).read_text(encoding="utf-8"),
        reason=reason.strip(),
    )
    # Shares the live-run lock. No API client, current extraction reads or dotenv loading.
    with (root / "run.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("RUN_BUSY: stop the live run before approving a correction") from exc
        try:
            _execute(root, correction_request=selection)
        except CorrectionComplete as completed:
            return completed.artifact, completed.path
    raise ValueError("Selected job was not reached in this frozen run; no correction accepted")
