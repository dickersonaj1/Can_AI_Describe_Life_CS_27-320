"""Offline v1.2 organization, audit rendering, and versioned runner regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_cli import write_project
from test_modular_synthesis_runner import fake_client

from feature_dictionary import modular_synthesis as cli
from feature_dictionary.synthesis_core import inventory_execution as execution
from feature_dictionary.synthesis_core.inventory_ingest import read_inputs
from feature_dictionary.synthesis_core.inventory_report import render_report, safe
from feature_dictionary.synthesis_core.inventory_v12 import (
    IndexedProposal,
    validate_indexed_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/synthesis_v12_run"
JOB = FIXTURE / "job_000"


@pytest.fixture(autouse=True)
def no_live_requests(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("V1.2 tests must never create a real provider client")

    monkeypatch.setattr(execution, "create_provider_client", fail)


def case():
    inputs = read_inputs(FIXTURE / "inputs.json")
    request = json.loads((JOB / "request.json").read_text())
    response = json.loads((JOB / "response.json").read_text())
    return inputs, request, response


def evaluate_changed(edit):
    inputs, request, response = case()
    data = json.loads(response["response_text"])
    edit(data)
    response["response_text"] = json.dumps(data)
    report = execution.evaluate(request, response, inputs)
    return report, render_report(inputs, response, report, request)


def test_sample_matches_exported_schema_and_keeps_shared_compound_once():
    inputs, request, response = case()
    data = json.loads(response["response_text"])
    proposal = IndexedProposal.model_validate_json(response["response_text"])
    assert (
        json.loads((ROOT / "schemas/synthesis_proposal_v1_2.schema.json").read_text())
        == IndexedProposal.model_json_schema()
    )
    assert not [i for i in validate_indexed_proposal(proposal, inputs) if i.severity == "error"]
    assert execution.evaluate(request, response, inputs)["proposal_valid"]
    assert len([t for t in data["terms"] if t["text"] == "tail spine"]) == 1
    tail = next(t for t in data["terms"] if t["text"] == "tail")
    assert len([t for t in data["terms"] if tail["ref"] in t["primary_refs"]]) == 2
    compound = next(t for t in data["terms"] if t["text"] == "tail spine")
    assert compound["primary_refs"] == ["p2", "p3"]


def test_local_expressions_on_both_types_and_reused_modifiers_remain_local():
    _, _, response = case()
    data = json.loads(response["response_text"])
    expressions = {t["text"]: t["expressions"] for t in data["terms"]}
    assert expressions["anal"][0]["text"] == "anal entire"
    assert expressions["tail tip"][0]["text"] == "curved tail tip"
    assert expressions["tail spine"][0]["text"] == "curved tail spine"
    assert all("ref" not in e for values in expressions.values() for e in values)
    assert "subterms" not in data


def test_markdown_is_repeatable_sorted_and_displays_associations_not_duplicate_records():
    inputs, request, response = case()
    report = execution.evaluate(request, response, inputs)
    text = render_report(inputs, response, report, request)
    assert text == render_report(inputs, response, report, request)
    assert "UNVALIDATED MODEL PROPOSAL" in text and "NOT A COMPILED DICTIONARY" in text
    assert (
        text.index("\n### anal —")
        < text.index("\n### spine —")
        < text.index("\n### Tail —")
        < text.index("\n### tail —")
    )
    assert text.count("#### tail spine") == 2
    assert "stored compounds: 2" in text and "ambiguous" in text
    assert "curved tail tip" in text and "anal entire" in text
    assert "Exclusions" in text and "Unresolved observations" in text
    assert "Total length" in text and "o10" in text and "o11" in text


@pytest.mark.parametrize(
    "change,code",
    [
        (
            lambda d: d["terms"][0]["expressions"][0].update(text="Anal entire"),
            "UNOBSERVED_EXPRESSION",
        ),
        (lambda d: d["terms"][-1].update(primary_refs=["missing"]), "INVALID_REFERENCE"),
        (lambda d: d["terms"][-1].update(primary_refs=[]), "MISSING_PRIMARY"),
        (lambda d: d["terms"][0].update(primary_refs=["p2"]), "INVALID_LINK_OWNER"),
        (lambda d: d["observation_dispositions"].pop(), "MISSING_DISPOSITION"),
        (
            lambda d: d["observation_dispositions"][0].update(term_refs=["p3"]),
            "DISPOSITION_MISMATCH",
        ),
    ],
)
def test_invalid_proposals_are_visible_not_repaired(change, code):
    report, text = evaluate_changed(change)
    assert not report["proposal_valid"]
    assert code in {i["code"] for i in report["issues"]}
    assert safe(code) in text
    if code == "MISSING_DISPOSITION":
        assert "MISSING DECISION — UNRESOLVED" in text and "o11" in text
    if code in ["MISSING_PRIMARY", "INVALID_REFERENCE"]:
        orphan = text.split("## Orphan or unlinked indexed compounds", 1)[1]
        assert "### tail spine" in orphan


def test_case_variants_preserved_without_equivalence_or_string_merge():
    _, _, response = case()
    terms = json.loads(response["response_text"])["terms"]
    assert {t["text"] for t in terms} >= {"tail", "Tail"}
    assert json.loads(response["response_text"])["equivalence_proposals"] == []


def test_malformed_json_and_unknown_records_still_appear_safely():
    inputs, request, response = case()
    for text in [
        "```json\n{}\n```",
        '{"terms":[{"type":"unknown","text":"<script>bad</script>"},42]}',
    ]:
        response["response_text"] = text
        validation = execution.evaluate(request, response, inputs)
        rendered = render_report(inputs, response, validation, request)
        assert "Complete raw proposal appendix" not in rendered
        assert "Complete raw proposal appendix" in render_report(
            inputs, response, validation, request, include_raw_json=True
        )
        assert safe("INVALID_JSON") in rendered or safe("CONTRACT_ERROR") in rendered
        assert "<script>" not in rendered
        if "unknown" in text:
            assert "42" in rendered and "bad" in rendered


def test_offline_cli_report_never_overwrites_or_changes_archived_run(tmp_path):
    destination = tmp_path / "audit.md"
    before = {p: p.read_bytes() for p in FIXTURE.rglob("*") if p.is_file()}
    args = ["--render-report", str(JOB), "--report-output", str(destination)]
    assert cli.main(args) == 0 and destination.exists()
    assert cli.main(args) == 2
    assert all(p.read_bytes() == content for p, content in before.items())
    assert cli.main(["--render-report", str(JOB), "--report-output", str(JOB / "new.md")]) == 2


@pytest.mark.parametrize(
    "provider,selector",
    [("openai", "gpt"), ("anthropic", "claude"), ("gemini", "gemini"), ("ollama", "qwen3:8b")],
)
def test_versioned_runner_archives_and_auto_renders_each_provider(
    tmp_path, monkeypatch, provider, selector
):
    from feature_dictionary.settings import load_settings

    path = write_project(tmp_path, options={"num_ctx": 65536}, max_output_tokens=8192)
    loaded = load_settings(path, overrides={"models": selector})
    inputs, _, response = case()
    plan = execution.prepare(inputs, loaded, proposal_version="1.2")
    request = execution.make_request(plan, loaded.settings.models[0], 0)
    data = json.loads(response["response_text"])
    data.update(request["identity"])
    client, _, closed = fake_client(provider, request, text=json.dumps(data))
    monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
    run = tmp_path / "run"
    result = execution.execute_run(run, inputs, [request], {})
    assert result[0]["proposal_valid"] and closed == [True]
    assert (run / "job_000/report.md").exists()
    assert "synthesis v1.2" in plan["prompt_template"].lower()
    assert execution.replay_job(run / "job_000")["proposal_valid"]


def test_v12_default_prompt_and_dry_run_do_not_change_old_default(tmp_path):
    path = write_project(tmp_path)
    args = [
        "--settings",
        str(path),
        "--inputs",
        str(FIXTURE / "inputs.json"),
        "--models",
        "claude",
        "--proposal-version",
        "1.2",
        "--run-dir",
        str(tmp_path / "dry"),
        "--dry-run",
    ]
    assert cli.main(args) == 0 and not (tmp_path / "dry").exists()
    from feature_dictionary.settings import load_settings

    inputs = read_inputs(FIXTURE / "inputs.json")
    assert execution.prepare(inputs, load_settings(path))["prompt_template"].startswith(
        "Modular synthesis proposal instructions v1.0"
    )


def test_prompt_examples_are_explicitly_hypothetical_and_meaning_based():
    text = " ".join((ROOT / "prompts/synthesis_inventory_v1_2.txt").read_text().split())
    for phrase in [
        "anal entire is a local expression",
        "tail tip is an indexed compound",
        "tail spine as ONE indexed compound",
        "curved tail tip is a HYPOTHETICAL",
        "not a rigid noun/adjective",
        "Total length is a property",
        "Coloration patterns are not automatically structures",
        "Missing decisions remain unresolved",
        "NOT anatomical containment",
    ]:
        assert phrase in text


def test_invalid_new_job_still_gets_automatic_audit(tmp_path, monkeypatch):
    from feature_dictionary.settings import load_settings

    path = write_project(tmp_path)
    loaded = load_settings(path, overrides={"models": "claude"})
    inputs, _, response = case()
    request = execution.make_request(
        execution.prepare(inputs, loaded, proposal_version="1.2"), loaded.settings.models[0], 0
    )
    data = json.loads(response["response_text"])
    data.update(request["identity"])
    data["observation_dispositions"].pop()
    client, _, _ = fake_client("anthropic", request, text=json.dumps(data))
    monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
    root = tmp_path / "invalid"
    assert not execution.execute_run(root, inputs, [request], {})[0]["proposal_valid"]
    assert "MISSING DECISION" in (root / "job_000/report.md").read_text()
    assert not (root / "job_000/proposal.json").exists()
