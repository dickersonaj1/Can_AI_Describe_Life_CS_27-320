"""Offline review exports and thin orchestration; all provider responses are mocked."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_modular_synthesis_runner import fake_client, write_extraction_fixture
from test_synthesis_v12 import FIXTURE, case

from feature_dictionary import cli
from feature_dictionary import inventory_workflow as workflow
from feature_dictionary.synthesis_core import inventory_execution as execution
from feature_dictionary.synthesis_core.inventory_evaluation import evaluate_reference
from feature_dictionary.synthesis_core.review_exports import (
    build_export,
    export_job,
    review_findings,
    write_disagreements,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "tests/fixtures/reference/acanthophis_inventory_v1.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("No unmocked provider requests")

    monkeypatch.setattr(execution, "create_provider_client", fail)
    monkeypatch.setattr(cli, "OpenAI", fail)
    monkeypatch.setattr(cli, "Anthropic", fail)
    monkeypatch.setattr(cli, "create_client", fail)
    monkeypatch.setattr(cli.genai, "Client", fail)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test")


def saved_job(tmp_path):
    run = tmp_path / "archived"
    shutil.copytree(FIXTURE, run)
    return run / "job_000"


def test_valid_exports_keep_evidence_and_require_scientific_review(tmp_path):
    job = saved_job(tmp_path)
    before = {p: p.read_bytes() for p in job.parent.rglob("*") if p.is_file()}
    output = tmp_path / "review"
    export = export_job(job, output)
    assert export["proposal_valid"] and not export["scientifically_verified"]
    assert all(
        v["scientific_status"] == "needs_scientific_review"
        for v in export["review_status"].values()
    )
    inputs, _, response = case()
    assert export["raw_model_response"] == response["response_text"]
    assert len(export["observations"]) == len(inputs.observations)
    assert export["sources"] == inputs.model_dump(mode="json")["sources"]
    assert len(list(output.iterdir())) == 3
    text = (output / "terminology_inventory.md").read_text()
    assert text.count("#### tail spine") == 2
    assert "anal entire" in text and "curved tail tip" in text
    assert "needs_scientific_review" in text
    assert "## Evidence details" not in text
    assert all(p.read_bytes() == content for p, content in before.items())
    with pytest.raises(FileExistsError):
        export_job(job, output)
    with pytest.raises(ValueError, match="immutable"):
        export_job(job, job / "review")


@pytest.mark.parametrize(
    "change", ["wrong_evidence", "missing_decision", "invalid_json", "malformed"]
)
def test_invalid_proposals_remain_visible_and_unapproved(tmp_path, change):
    job = saved_job(tmp_path)
    response = json.loads((job / "response.json").read_text())
    data = json.loads(response["response_text"])
    if change == "wrong_evidence":
        data["terms"][0]["text"] = "unobserved anatomy"
    elif change == "missing_decision":
        data["observation_dispositions"].pop()
    elif change == "malformed":
        data["terms"].append("not a record")
    response["response_text"] = "{incomplete" if change == "invalid_json" else json.dumps(data)
    (job / "response.json").write_text(json.dumps(response))
    export = export_job(job, tmp_path / "diagnostic")
    assert not export["proposal_valid"]
    assert "INVALID" in (tmp_path / "diagnostic/terminology_inventory.md").read_text()
    assert export["raw_model_response"] == response["response_text"]
    assert all(
        s["scientific_status"] == "needs_scientific_review"
        for s in export["review_status"].values()
    )
    if change == "wrong_evidence":
        assert export["proposal"]["terms"][0]["text"] == "unobserved anatomy"
    if change == "missing_decision":
        assert any(f["code"] == "MISSING_DECISION" for f in export["findings"])


def annotations(export):
    return dict(
        format_version="scientific-review-1.0",
        input_sha256=export["metadata"]["input_sha256"],
        proposal_sha256=export["metadata"]["proposal_sha256"],
        decisions=[
            dict(
                path="/terms/0",
                decision="approved",
                confirmed=True,
                reviewer="Fixture reviewer (synthetic test only)",
                reviewed_at="2026-10-14",
            )
        ],
    )


def test_only_explicit_bound_review_can_approve_a_record(tmp_path):
    job = saved_job(tmp_path)
    initial = build_export(job)
    approved = build_export(job, annotations(initial))
    assert (
        approved["review_status"]["/terms/0"]["scientific_status"]
        == "scientifically_reviewed_approved"
    )
    assert approved["review_status"]["/terms/1"]["scientific_status"] == "needs_scientific_review"
    assert not approved["scientifically_verified"]
    bad = annotations(initial)
    bad["decisions"][0]["confirmed"] = False
    with pytest.raises(ValueError):
        build_export(job, bad)
    bad = annotations(initial)
    bad["proposal_sha256"] = "other"
    with pytest.raises(ValueError, match="bind"):
        build_export(job, bad)


def test_screening_is_not_classification_or_approval():
    data = {
        "terms": [
            dict(text="distal", type="primary", expressions=[]),
            dict(text="dark cross-bands", type="compound", expressions=[]),
            dict(text="upper labials", type="compound", expressions=[]),
        ],
        "observation_dispositions": [],
    }
    before = copy.deepcopy(data)
    flags = review_findings(data, {"issues": []}, {})
    assert {"ANATOMICAL_SCOPE_REVIEW", "ANATOMICAL_SUBTYPE", "COMPOUND_CLASSIFICATION"} <= {
        f["code"] for f in flags
    }
    assert data == before


def test_deterministic_reports_and_independent_disagreements(tmp_path):
    job = saved_job(tmp_path)
    one = export_job(job, tmp_path / "one")
    two = export_job(job, tmp_path / "two")
    assert (tmp_path / "one/terminology_inventory.md").read_bytes() == (
        tmp_path / "two/terminology_inventory.md"
    ).read_bytes()
    changed = copy.deepcopy(two)
    changed["proposal"]["terms"][0]["type"] = "compound"
    before = copy.deepcopy(changed)
    write_disagreements(tmp_path, [one, changed])
    text = (tmp_path / "proposal_differences.md").read_text()
    assert "anal" in text and "Proposal 000" in text and "Proposal 001" in text
    assert changed == before


def test_provisional_semantic_checks_do_not_change_software_status(tmp_path):
    export = build_export(saved_job(tmp_path))
    reference = json.loads(REFERENCE.read_text())
    result = evaluate_reference(export, reference)
    results = {r["expected"]["text"]: r for r in result["results"]}
    assert results["anal entire"]["status"] == "matches_expectation"
    assert results["tail spine"]["primary_associations_match"]
    assert results["distal"]["status"] == "not_observed_in_input"
    assert result["software_validation"] and not result["advisor_approved"]
    altered = copy.deepcopy(export)
    altered["proposal"]["terms"][0]["expressions"] = []
    outcomes = evaluate_reference(altered, reference)["results"]
    assert (
        next(r for r in outcomes if r["expected"]["text"] == "anal entire")["status"]
        == "missing_term"
    )
    assert export["proposal_valid"]


def install_proposal_client(monkeypatch):
    requests = []

    def create(provider, request):
        requests.append(request)
        obs = request["model_input"]["observations"]
        anal = next(o["id"] for o in obs if o["matched_text"] == "anal")
        data = dict(
            format_version="synthesis-1.2",
            **request["identity"],
            terms=[
                dict(
                    ref="p1",
                    type="primary",
                    text="anal",
                    observation_ids=[anal],
                    primary_refs=[],
                    expressions=[],
                    rationale="Provisional anatomical term",
                )
            ],
            observation_dispositions=[
                dict(
                    observation_id=o["id"],
                    status="mapped" if o["id"] == anal else "unresolved",
                    term_refs=["p1"] if o["id"] == anal else [],
                    reason=None if o["id"] == anal else "Review classification",
                )
                for o in obs
            ],
            equivalence_proposals=[],
            review_notes=[],
        )
        return fake_client(provider, request, text=json.dumps(data))[0]

    monkeypatch.setattr(execution, "create_provider_client", create)
    return requests


def test_reuse_accepted_archives_without_extraction_calls(tmp_path, monkeypatch):
    path = write_extraction_fixture(tmp_path)
    settings = write_project(tmp_path)

    def no_extraction(*args):
        pytest.fail("Reused extraction must never be called")

    monkeypatch.setattr(cli, "main", no_extraction)
    requests = install_proposal_client(monkeypatch)
    output = tmp_path / "workflow"
    args = [
        "--settings",
        str(settings),
        "--reuse-extraction",
        str(path),
        "--synthesis-models",
        "gpt,claude",
        "--output-dir",
        str(output),
    ]
    assert workflow.main(args) == 0
    assert len(requests) == 2 and requests[0]["prompt"] == requests[1]["prompt"]
    assert (output / "review/job_000/terminology_inventory.json").exists()
    assert (output / "review/job_001/scientific_review.md").exists()
    assert workflow.main(args) == 2 and len(requests) == 2


def test_end_to_end_source_extraction_then_synthesis_with_existing_adapters(tmp_path, monkeypatch):
    settings = write_project(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("anal entire; tail spine")
    raw = json.dumps(
        dict(
            format_version="extraction-3.1",
            entries=[
                dict(matched_text="anal", source_phrase="anal entire"),
                dict(matched_text="anal entire", source_phrase="anal entire"),
            ],
        )
    )
    client, calls, _ = fake("openai", text=raw)
    monkeypatch.setattr(cli, "OpenAI", lambda **kwargs: client)
    requests = install_proposal_client(monkeypatch)
    output = tmp_path / "workflow"
    assert (
        workflow.main(
            [
                "--settings",
                str(settings),
                "--source",
                str(source),
                "--extractor-models",
                "gpt",
                "--synthesis-models",
                "claude",
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    assert len(calls) == len(requests) == 1
    assert list((output / "extraction_000").glob("*.raw.json"))
    assert (output / "synthesis/observation_refs.json").exists()


def test_dry_run_no_clients_or_output_and_offline_cli(tmp_path):
    settings = write_project(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("anal entire")
    output = tmp_path / "dry"
    assert (
        workflow.main(
            [
                "--settings",
                str(settings),
                "--source",
                str(source),
                "--extractor-models",
                "gpt",
                "--synthesis-models",
                "claude",
                "--output-dir",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()
    job = saved_job(tmp_path)
    assert (
        workflow.main(
            [
                "--render-job",
                str(job),
                "--output-dir",
                str(tmp_path / "offline"),
                "--reference-fixture",
                str(REFERENCE),
            ]
        )
        == 0
    )
    assert (tmp_path / "offline/proposal_000/semantic_evaluation.json").exists()


def test_failed_extraction_stops_without_synthesis_and_keeps_stage_status(tmp_path, monkeypatch):
    settings = write_project(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("anal")
    calls = []

    def extraction(args):
        calls.append(args)
        return 0 if "--dry-run" in args else 1

    monkeypatch.setattr(cli, "main", extraction)
    output = tmp_path / "failed"
    assert (
        workflow.main(
            [
                "--settings",
                str(settings),
                "--source",
                str(source),
                "--extractor-models",
                "gpt",
                "--synthesis-models",
                "claude",
                "--output-dir",
                str(output),
            ]
        )
        == 1
    )
    assert len(calls) == 2
    assert json.loads((output / "extraction_000_status.json").read_text())["exit_code"] == 1
    assert not (output / "synthesis").exists()


def test_incomplete_synthesis_exports_diagnostic_instead_of_silently_retrying(
    tmp_path, monkeypatch
):
    path = write_extraction_fixture(tmp_path)
    settings = write_project(tmp_path)
    requests = install_proposal_client(monkeypatch)
    create = execution.create_provider_client

    def incomplete(provider, request):
        client = create(provider, request)
        # Use the existing adapter's incomplete finish reason on a separate mock envelope.
        text = client.responses.create(max_output_tokens=1).output_text
        return fake_client(provider, request, text=text, reason="max_output_tokens")[0]

    monkeypatch.setattr(execution, "create_provider_client", incomplete)
    out = tmp_path / "incomplete"
    assert (
        workflow.main(
            [
                "--settings",
                str(settings),
                "--reuse-extraction",
                str(path),
                "--synthesis-models",
                "gpt",
                "--output-dir",
                str(out),
            ]
        )
        == 1
    )
    assert len(requests) == 1
    data = json.loads((out / "review/job_000/terminology_inventory.json").read_text())
    assert not data["proposal_valid"]
    assert (out / "synthesis/job_000/response.json").exists()


def test_invalid_proposal_cannot_receive_approval(tmp_path):
    job = saved_job(tmp_path)
    response = json.loads((job / "response.json").read_text())
    response["completion_status"] = "incomplete"
    (job / "response.json").write_text(json.dumps(response))
    export = build_export(job)
    with pytest.raises(ValueError, match="Invalid proposals"):
        build_export(job, annotations(export))


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{}\n```",
        json.dumps(
            {
                "format_version": "extraction-3.1",
                "entries": [{"matched_text": "invented", "source_phrase": "invented"}],
            }
        ),
    ],
)
def test_rejected_extraction_keeps_raw_without_synthesis(tmp_path, monkeypatch, raw):
    settings = write_project(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("anal entire")
    client, calls, _ = fake("openai", text=raw)
    monkeypatch.setattr(cli, "OpenAI", lambda **kwargs: client)
    out = tmp_path / "rejected"
    assert (
        workflow.main(
            [
                "--settings",
                str(settings),
                "--source",
                str(source),
                "--extractor-models",
                "gpt",
                "--synthesis-models",
                "claude",
                "--output-dir",
                str(out),
            ]
        )
        == 1
    )
    archived = json.loads(next((out / "extraction_000").glob("*.raw.json")).read_text())
    assert archived["response_text"] == raw
    assert not (out / "synthesis").exists() and len(calls) == 1


def test_two_sources_are_frozen_once_for_each_independent_proposal(tmp_path, monkeypatch):
    settings = write_project(tmp_path)
    sources = [tmp_path / "first.txt", tmp_path / "second.txt"]
    for path in sources:
        path.write_text("anal entire")
    raw = json.dumps(
        dict(
            format_version="extraction-3.1",
            entries=[dict(matched_text="anal", source_phrase="anal entire")],
        )
    )
    client, calls, _ = fake("openai", text=raw)
    monkeypatch.setattr(cli, "OpenAI", lambda **kwargs: client)
    requests = install_proposal_client(monkeypatch)
    out = tmp_path / "multi"
    assert (
        workflow.main(
            [
                "--settings",
                str(settings),
                "--source",
                str(sources[0]),
                "--source",
                str(sources[1]),
                "--extractor-models",
                "gpt",
                "--synthesis-models",
                "gpt,claude",
                "--output-dir",
                str(out),
            ]
        )
        == 0
    )
    assert len(calls) == len(requests) == 2
    assert requests[0]["model_input"] == requests[1]["model_input"]
    assert len(requests[0]["model_input"]["observations"]) == 2
    assert len(requests[0]["model_input"]["sources"]) == 2


@pytest.mark.parametrize("variant", ["Tail", "TAIL", "tail"])
def test_reference_label_case_preserves_records_and_exact_evidence(variant):
    reference = {
        "format_version": "anatomical-reference-1.0",
        "advisor_approved": False,
        "expectations": [
            {"text": "tail", "role": "primary"},
            {"text": "tail spine", "role": "compound", "associated_primaries": ["tail"]},
            {"text": "curved", "role": "contextual", "owner": "tail"},
        ],
    }
    export = {
        "proposal_valid": True,
        "observations": {
            "o1": {"matched_text": "tail"},
            "o2": {"matched_text": "tail spine"},
            "o3": {"matched_text": "curved"},
        },
        "proposal": {
            "terms": [
                {
                    "ref": "T1",
                    "text": variant,
                    "type": "primary",
                    "observation_ids": ["o1"],
                    "expressions": [{"text": "curved", "observation_ids": ["o3"]}],
                },
                {
                    "ref": "T2",
                    "text": "tail spine",
                    "type": "compound",
                    "primary_refs": ["T1"],
                    "observation_ids": ["o2"],
                },
                {"ref": "T3", "text": "tail", "type": "primary", "observation_ids": ["o1"]},
            ]
        },
    }
    original = copy.deepcopy(export)
    result = evaluate_reference(export, reference)
    assert all(r["status"] == "matches_expectation" for r in result["results"])
    assert result["results"][0]["occurrence_count"] == 2
    assert result["results"][1]["primary_associations_match"] is True
    assert export == original
    # Case-folding labels must not loosen exact source-evidence checks.
    export["observations"]["o1"]["matched_text"] = "Tail"
    result = evaluate_reference(export, reference)
    assert result["results"][0]["status"] == "not_observed_in_input"
    assert result["results"][0]["exact_evidence_supported"] is False
