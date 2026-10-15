"""Human-approved corrections preserve archives and never require paid requests."""

from __future__ import annotations

import json

import pytest
from test_synthesis_batching import FakeClient, answer, inputs, new_run, response_for

from feature_dictionary import synthesis as cli
from feature_dictionary.synthesis_core import batching as b
from feature_dictionary.synthesis_core import corrections as c


def failed_run(tmp_path):
    root, bundle = new_run(tmp_path)

    def invalid(request, number):
        if number == 2:
            data = answer(request)
            term = data["terms"][0]
            data["relationships"] = [
                dict(
                    subject_ref=term["ref"],
                    object_ref=term["ref"],
                    predicate="describes",
                    observation_ids=term["expressions"][0]["observation_ids"],
                    rationale="Deliberately invalid fixture",
                )
            ]
            return response_for(data)

    client = FakeClient(invalid)
    with pytest.raises(b.JobFailure):
        b.execute(root, client=client)
    attempt = next(p.parent for p in root.rglob("validation.json") if not b.load(p)["valid"])
    data = json.loads(b.load(attempt / "response.json")["output_text"])
    data["relationships"] = []
    candidate = tmp_path / "corrected.json"
    candidate.write_text(json.dumps(data))
    return root, attempt, candidate, client.calls


def original_bytes(root):
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "corrections" not in p.parts and p.name != "run.lock"
    }


def test_valid_correction_preserves_original_bytes_and_reuses_jobs(tmp_path):
    root, attempt, candidate, earlier_requests = failed_run(tmp_path)
    before = original_bytes(root)
    artifact, path = c.approve_job(
        attempt, candidate, "Omit invalid edges pending biological review"
    )
    assert artifact["accepted"] and artifact["manually_approved"]
    assert artifact["reason"] == "Omit invalid edges pending biological review"
    assert original_bytes(root) == before
    assert b.fingerprint(artifact) == path.stem
    assert artifact["binding"]["request_sha256"] == b.digest(
        (attempt / "request.json").read_bytes()
    )
    assert artifact["binding"]["response_sha256"] == b.digest(
        (attempt / "response.json").read_bytes()
    )
    client = FakeClient()
    result, validation, summary = b.execute(root, client=client)
    assert validation["valid"]
    assert all(request not in client.calls for request in earlier_requests)
    assert "OFFLINE_EDIT" in {i["code"] for i in result["issues"]}
    provenance = summary["corrections"][0]
    assert provenance["warning_code"] == "OFFLINE_EDIT"
    assert provenance["manually_approved"] is True
    assert provenance["binding"] == artifact["binding"]
    assert provenance["correction_id"] == path.stem
    calls = len(client.calls)
    assert b.execute(root, client=client) == (result, validation, summary)
    assert len(client.calls) == calls
    assert b.execute(root) == (result, validation, summary)
    assert not b.load(attempt / "validation.json")["valid"]


@pytest.mark.parametrize(
    "damage", ["schema", "relationship", "missing_observation", "outside_batch"]
)
def test_rejected_corrections_retained_but_never_reused(tmp_path, damage):
    root, attempt, candidate, _ = failed_run(tmp_path)
    before = original_bytes(root)
    data = b.load(candidate)
    if damage == "schema":
        data = {"incorrect": "schema"}
    elif damage == "relationship":
        data = json.loads(b.load(attempt / "response.json")["output_text"])
    elif damage == "missing_observation":
        data["observation_dispositions"] = []
    else:
        data["terms"][0]["expressions"][0]["observation_ids"] = ["o6"]
    candidate.write_text(json.dumps(data))
    artifact, path = c.approve_job(attempt, candidate, "Deliberately invalid test correction")
    assert not artifact["accepted"] and path.exists()
    assert not artifact["validation"]["valid"]
    assert original_bytes(root) == before
    client = FakeClient()
    with pytest.raises(b.JobFailure):
        b.execute(root, client=client)
    assert not client.calls


def test_malformed_json_is_preserved_as_rejected_artifact(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    candidate.write_text("{not json")
    artifact, path = c.approve_job(attempt, candidate, "Review malformed candidate")
    assert not artifact["accepted"]
    assert b.load(path)["candidate_text"] == "{not json"


@pytest.mark.parametrize("changed", ["request.json", "response.json"])
def test_changed_original_binding_blocks_resume_without_api(tmp_path, changed):
    root, attempt, candidate, _ = failed_run(tmp_path)
    c.approve_job(attempt, candidate, "Remove invalid links")
    path = attempt / changed
    path.write_bytes(path.read_bytes() + b"\n")
    client = FakeClient()
    with pytest.raises(ValueError, match="CORRECTION_BINDING"):
        b.execute(root, client=client)
    assert not client.calls


def test_correction_cannot_be_copied_to_another_job(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    _, path = c.approve_job(attempt, candidate, "Remove invalid links")
    other = next(p.parent for p in root.rglob("request.json") if p.parent != attempt)
    dest = other.parent / "corrections" / path.name
    dest.parent.mkdir()
    dest.write_bytes(path.read_bytes())
    client = FakeClient()
    with pytest.raises(ValueError, match="CORRECTION_BINDING"):
        b.execute(root, client=client)
    assert not client.calls


def test_changed_correction_fails_integrity_check(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    _, path = c.approve_job(attempt, candidate, "Remove invalid links")
    artifact = b.load(path)
    artifact["reason"] = "Altered without new approval"
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match="CORRECTION_INTEGRITY"):
        b.execute(root)


def test_accepted_correction_is_revalidated_not_trusted(tmp_path, monkeypatch):
    root, attempt, candidate, _ = failed_run(tmp_path)
    c.approve_job(attempt, candidate, "Remove invalid links")
    original = b.validate_proposal

    def stricter(proposal, bundle, **kwargs):
        issues = original(proposal, bundle, **kwargs)
        if kwargs.get("owned_ids") and proposal.terms[0].ref.startswith("b2:"):
            from feature_dictionary.synthesis_core.schema import Issue

            issues.append(
                Issue(
                    severity="error",
                    code="NEW_CHECK",
                    path="/terms",
                    message="New validator rejects",
                )
            )
        return issues

    monkeypatch.setattr(b, "validate_proposal", stricter)
    client = FakeClient()
    with pytest.raises(ValueError, match="CORRECTION_INVALID"):
        b.execute(root, client=client)
    assert not client.calls


def test_idempotent_approval_and_conflicting_edit_protection(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    first, path = c.approve_job(attempt, candidate, "Remove invalid links")
    assert c.approve_job(attempt, candidate, "Remove invalid links") == (first, path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="CORRECTION_CONFLICT"):
        c.approve_job(attempt, candidate, "Different approval")
    assert path.read_bytes() == before


def test_reason_and_explicit_cli_approval_required(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    with pytest.raises(ValueError, match="reason"):
        c.approve_job(attempt, candidate, " ")
    args = ["--correct-job", str(attempt), "--candidate", str(candidate)]
    assert cli.main(args) == 2
    assert cli.main([*args, "--correction-reason", "Remove invalid edges"]) == 2
    assert not list(root.rglob("corrections/*.json"))


def test_cli_approval_is_offline_and_replay_uses_edit(tmp_path, monkeypatch):
    import openai

    root, attempt, candidate, _ = failed_run(tmp_path)
    monkeypatch.setattr(
        openai, "OpenAI", lambda **kw: pytest.fail("Offline correction must not create client")
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = original_bytes(root)
    assert (
        cli.main(
            [
                "--correct-job",
                str(attempt),
                "--candidate",
                str(candidate),
                "--correction-reason",
                "Remove invalid edges",
                "--approve-correction",
            ]
        )
        == 0
    )
    assert before == original_bytes(root)
    b.execute(root, client=FakeClient())
    output = tmp_path / "replayed.json"
    assert cli.main(["--replay-run", str(root), "--output", str(output)]) == 0
    assert "OFFLINE_EDIT" in {i["code"] for i in b.load(output)["issues"]}


def test_rejected_cli_correction_returns_validation_error(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    candidate.write_text("{}")
    assert (
        cli.main(
            [
                "--correct-job",
                str(attempt),
                "--candidate",
                str(candidate),
                "--correction-reason",
                "Invalid test",
                "--approve-correction",
            ]
        )
        == 2
    )


@pytest.mark.parametrize("stage", ["reconcile", "relationships"])
def test_review_jobs_use_the_same_offline_correction_path(tmp_path, stage):
    root, _ = new_run(tmp_path, inputs(tmp_path, ["head", "scales", "keeling"]))

    def invalid(request, number):
        if request["text"]["format"]["name"] == f"synthesis_{stage}":
            return response_for({"wrong": True})

    with pytest.raises(b.JobFailure):
        b.execute(root, client=FakeClient(invalid))
    attempt = next(p.parent for p in (root / "jobs" / stage).rglob("response.json"))
    candidate = tmp_path / "review.json"
    candidate.write_text(json.dumps({"decisions" if stage == "reconcile" else "relationships": []}))
    artifact, _ = c.approve_job(attempt, candidate, "No supported proposals in this review")
    assert artifact["accepted"]
    result, validation, summary = b.execute(root, client=FakeClient())
    assert validation["valid"]
    assert summary["corrections"][0]["stage"] == stage
    assert b.execute(root)[0] == result


def test_rejected_edit_can_be_followed_by_a_valid_separate_artifact(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    valid_text = candidate.read_text()
    candidate.write_text("{}")
    rejected, rejected_path = c.approve_job(attempt, candidate, "Invalid preliminary correction")
    original = rejected_path.read_bytes()
    candidate.write_text(valid_text)
    accepted, accepted_path = c.approve_job(attempt, candidate, "Corrected full candidate")
    assert not rejected["accepted"] and accepted["accepted"]
    assert accepted_path != rejected_path
    assert rejected_path.read_bytes() == original
    assert b.execute(root, client=FakeClient())[1]["valid"]


def test_incomplete_original_remains_incomplete_after_offline_edit(tmp_path):
    root, attempt, candidate, _ = failed_run(tmp_path)
    raw = b.load(attempt / "response.json")
    raw["response"]["status"] = "incomplete"
    raw["response"]["incomplete_details"] = {"reason": "max_output_tokens"}
    (attempt / "response.json").write_text(json.dumps(raw))
    before = (attempt / "response.json").read_bytes()
    artifact, _ = c.approve_job(
        attempt, candidate, "Reconstruct full candidate manually from observations"
    )
    assert artifact["accepted"]
    assert b.execute(root, client=FakeClient())[1]["valid"]
    assert (attempt / "response.json").read_bytes() == before
    assert b.load(attempt / "response.json")["response"]["status"] == "incomplete"
