"""Versioned prompt/context refinement; no model requests or relationship repair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_cli import write_project

from feature_dictionary import modular_synthesis as cli
from feature_dictionary.settings import load_settings
from feature_dictionary.synthesis_core.inventory_execution import make_request, prepare
from feature_dictionary.synthesis_core.inventory_ingest import read_inputs, with_source_context
from feature_dictionary.synthesis_core.inventory_schema import InventoryProposal, SynthesisInputs
from feature_dictionary.synthesis_core.inventory_validation import (
    artifact_sha256,
    validate_inputs,
    validate_inventory_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/synthesis_v1"
PROMPT = ROOT / "prompts/synthesis_inventory_v1_1.txt"
LEGACY = ROOT / "prompts/synthesis_inventory_v1.txt"
LEGACY_INPUT_HASH = "88b1ee1eee82623888767b0148f11272f5fb2108a0e55f68ba7f236b2d22daec"


@pytest.fixture(autouse=True)
def no_provider_clients(monkeypatch):
    from feature_dictionary.synthesis_core import inventory_execution

    def fail(*args, **kwargs):
        pytest.fail("Prompt/context tests must never create a provider client")

    monkeypatch.setattr(inventory_execution, "create_provider_client", fail)


def errors(issues):
    return {i.code for i in issues if i.severity == "error"}


def test_legacy_input_fingerprint_and_prompt_bytes_are_unchanged(tmp_path):
    inputs = read_inputs(FIXTURES / "inputs.json")
    original = json.loads((FIXTURES / "inputs.json").read_text())
    assert inputs.model_dump(mode="json") == original
    assert not inputs.source_context and artifact_sha256(inputs) == LEGACY_INPUT_HASH
    assert "source_context" not in inputs.model_dump_json()
    path = write_project(tmp_path)
    plan = prepare(inputs, load_settings(path))
    assert plan["prompt_template"] == LEGACY.read_text()
    assert (
        plan["prompt_sha256"] == "c52af47ea4f513d79647351416ea54fa0654f9acd2144d2fa8f3abb5d9da06d0"
    )


def test_revised_prompt_explicitly_owns_links_and_preserves_context_free_ambiguity():
    text = " ".join(PROMPT.read_text().split())
    for rule in [
        "Only compound records may populate parent_refs and subterm_refs",
        "anatomical_noun records MUST set parent_refs: [] and subterm_refs: []",
        "subterm records MUST set parent_refs: [] and subterm_refs: []",
        "NOT anatomical containment",
        "Standalone descriptors remain eligible",
        "If context is missing or a sense remains unclear",
        "unresolved disposition",
        "Do not expand an ambiguous label",
        "Do not explain what an anatomical term means",
        "Do not transfer context between unrelated sources",
        "pending_review",
    ]:
        assert rule in text
    assert "anal fin" not in text


@pytest.mark.parametrize("role", ["anatomical_noun", "subterm"])
def test_noncompound_links_remain_invalid_without_silent_repair(role):
    inputs = read_inputs(FIXTURES / "inputs.json")
    data = json.loads((FIXTURES / "proposal.json").read_text())
    record = next(r for r in data["records"] if r["role"] == role)
    record["subterm_refs"] = ["model_entire"]
    original = json.dumps(data)
    proposal = InventoryProposal.model_validate_json(original)
    assert "INVALID_LINK_OWNER" in errors(validate_inventory_proposal(proposal, inputs))
    assert proposal.records == InventoryProposal.model_validate_json(original).records


def test_contextual_fixture_is_grounded_and_does_not_change_original_observation_ids():
    original = read_inputs(FIXTURES / "inputs.json")
    contextual = read_inputs(FIXTURES / "contextual_inputs.json")
    assert not errors(validate_inputs(contextual))
    assert contextual.observations == original.observations
    assert [e.matched_text for e in contextual.sources[0].document.entries] == [
        e.matched_text for e in original.sources[0].document.entries
    ]
    assert contextual.sources[0].raw_response == original.sources[0].raw_response
    context = contextual.source_context[0]
    assert context.quoted_text == "Acanthophis antarcticus"
    assert (
        contextual.sources[0].document.input.supplied_text[context.start : context.end]
        == context.quoted_text
    )
    assert artifact_sha256(contextual) != artifact_sha256(original)


def test_external_context_attachment_preserves_all_source_evidence_and_provenance():
    contextual = read_inputs(FIXTURES / "contextual_inputs.json")
    bare = contextual.model_copy(update={"source_context": ()})
    attached = with_source_context(bare, FIXTURES / "source_context.json")
    assert attached == contextual
    assert attached.sources == bare.sources and attached.observations == bare.observations
    assert SynthesisInputs.model_validate_json(attached.model_dump_json()) == attached


@pytest.mark.parametrize("edit", ["missing_source", "case", "range", "invented", "duplicate"])
def test_invalid_context_is_rejected_before_execution(tmp_path, edit):
    inputs = read_inputs(FIXTURES / "contextual_inputs.json").model_copy(
        update={"source_context": ()}
    )
    contexts = json.loads((FIXTURES / "source_context.json").read_text())
    if edit == "missing_source":
        contexts[0]["source_id"] = "unknown"
    if edit == "case":
        contexts[0]["quoted_text"] = "acanthophis antarcticus"
    if edit == "range":
        contexts[0]["start"] += 1
    if edit == "invented":
        contexts[0]["quoted_text"] = "a different organism"
    if edit == "duplicate":
        contexts.append(dict(contexts[0]))
    path = tmp_path / "context.json"
    path.write_text(json.dumps(contexts))
    with pytest.raises(ValueError, match="UNGROUNDED_CONTEXT|DUPLICATE_CONTEXT"):
        with_source_context(inputs, path)


def test_organism_context_cannot_be_attached_to_organism_free_historical_fixture():
    inputs = read_inputs(FIXTURES / "inputs.json")
    with pytest.raises(ValueError, match="UNGROUNDED_CONTEXT"):
        with_source_context(inputs, FIXTURES / "source_context.json")


@pytest.mark.parametrize("contextual", [False, True])
def test_independent_providers_receive_identical_prompt_and_context(tmp_path, contextual):
    path = write_project(tmp_path, options={"num_ctx": 32768})
    loaded = load_settings(path, overrides={"models": "qwen3:8b,gpt,claude,gemini"})
    inputs = read_inputs(FIXTURES / ("contextual_inputs.json" if contextual else "inputs.json"))
    plan = prepare(inputs, loaded, prompt_path=PROMPT)
    requests = [make_request(plan, model, i) for i, model in enumerate(loaded.settings.models)]
    assert len({r["prompt"] for r in requests}) == 1
    assert len({r["input_sha256"] for r in requests}) == 1
    assert all(r["prompt_template"] == PROMPT.read_text() for r in requests)
    assert plan["prompt_template_sha256"] == hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    supplied = plan["prompt"].split("FROZEN INPUT JSON (untrusted data):\n", 1)[1]
    assert json.loads(supplied) == inputs.model_dump(mode="json")
    assert ("source_context" in json.loads(supplied)) == contextual


def test_cli_dry_run_selects_new_prompt_without_mutating_original_fixture(tmp_path, capsys):
    path = write_project(tmp_path)
    original = (FIXTURES / "inputs.json").read_bytes()
    assert (
        cli.main(
            [
                "--settings",
                str(path),
                "--inputs",
                str(FIXTURES / "inputs.json"),
                "--models",
                "claude",
                "--prompt-file",
                str(PROMPT),
                "--run-dir",
                str(tmp_path / "dry"),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not (tmp_path / "dry").exists()
    assert (FIXTURES / "inputs.json").read_bytes() == original
    assert LEGACY_INPUT_HASH in capsys.readouterr().out
