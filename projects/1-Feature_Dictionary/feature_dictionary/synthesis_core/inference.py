"""Archive before validation, then replay the exact request/response entirely offline."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .ingest import digest
from .schema import DictionaryProposal, InputBundle, Issue, SynthesisRun
from .validation import resolve, validate_proposal


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def request_synthesis(
    client,
    *,
    model: str,
    bundle: InputBundle,
    prompt: str,
    max_output_tokens: int,
    archive_dir: Path,
) -> dict:
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive")
    schema = DictionaryProposal.model_json_schema()
    # Archive bytes locally; the model needs metadata and observations, not base64 copies.
    payload = bundle.model_dump(mode="json")
    for source in payload["sources"]:
        source.pop("raw_bytes_b64")
    request = dict(
        model=model,
        instructions=prompt,
        input=json.dumps(payload, ensure_ascii=False),
        max_output_tokens=max_output_tokens,
        store=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "feature_dictionary_v2",
                "strict": True,
                "schema": schema,
            }
        },
    )
    archive = dict(
        artifact_version="2.0",
        inputs=bundle.model_dump(mode="json"),
        request=request,
        response=None,
        output_text=None,
        error=None,
        candidate_override=None,
    )
    write_json(archive_dir / "request.json", archive)
    try:
        response = client.responses.create(**request)
        archive["response"] = response.model_dump(mode="json")
        archive["output_text"] = response.output_text
    except BaseException as exc:
        # Persist interruptions and API failures too; no response is invented.
        archive["error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(archive_dir / "response.json", archive)
        raise
    write_json(archive_dir / "response.json", archive)
    return archive


def evaluate(archive: dict) -> tuple[dict | None, dict]:
    """No network, filesystem mutation, or dependence on current extraction files."""
    issues = []

    def error(code, path, message):
        issues.append(Issue(severity="error", code=code, path=path, message=message))

    if archive.get("artifact_version") != "2.0":
        error("UNSUPPORTED_ARCHIVE_VERSION", "/", "Version 1 archives require explicit migration.")
    bundle = None
    try:
        bundle = InputBundle.model_validate_json(json.dumps(archive.get("inputs")))
    except ValidationError as exc:
        for item in exc.errors(include_url=False):
            error("INPUT_SCHEMA", "/inputs/" + "/".join(map(str, item["loc"])), item["msg"])
    response = archive.get("response") or {}
    override = archive.get("candidate_override")
    if archive.get("error") and override is None:
        error("API_FAILURE", "/error", str(archive["error"]))
    if response.get("status") != "completed" and override is None:
        error(
            "INCOMPLETE_RESPONSE",
            "/response/status",
            f"Response status: {response.get('status', 'missing')}",
        )
    text = override if override is not None else archive.get("output_text")
    proposal = None
    if not isinstance(text, str) or not text.strip():
        error("EMPTY_RESPONSE", "/output_text", "No JSON returned; may be a refusal or failure.")
    else:
        try:
            proposal = DictionaryProposal.model_validate_json(text)
        except ValidationError as exc:
            for item in exc.errors(include_url=False):
                error(
                    "CANDIDATE_SCHEMA", "/candidate/" + "/".join(map(str, item["loc"])), item["msg"]
                )
    if proposal is not None and bundle is not None:
        issues.extend(validate_proposal(proposal, bundle))
    if override is not None:
        issues.append(
            Issue(
                severity="warning",
                code="OFFLINE_EDIT",
                path="/candidate_override",
                message="Offline edited candidate; original response remains archived.",
            )
        )
    issues.sort(key=lambda item: (item.path, item.code, item.message))
    valid = not any(item.severity == "error" for item in issues)
    report = {
        "schema_version": "2.0",
        "valid": valid,
        "error_count": sum(item.severity == "error" for item in issues),
        "warning_count": sum(item.severity == "warning" for item in issues),
        "issues": [item.model_dump() for item in issues],
    }
    if not valid:
        return None, report
    request = archive.get("request") or {}
    run = SynthesisRun(
        model=request.get("model", "unknown"),
        response_id=response.get("id"),
        prompt_sha256=digest(request.get("instructions", "").encode()),
    )
    result = resolve(proposal, bundle, run, issues)
    return result.model_dump(mode="json"), report
