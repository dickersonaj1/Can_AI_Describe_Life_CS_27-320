"""V3.1 contracts, exact evidence, version selection, and read-only legacy replay."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import LOCAL_MODELS, SELECTION, install_cloud
from test_extraction_v3 import entry as legacy_entry
from test_extraction_v3 import response as legacy_response
from test_extraction_v3_pipeline import artifacts, project

from feature_dictionary import cli, extraction_replay
from feature_dictionary.context import RunContext
from feature_dictionary.extraction_v3 import (
    FORMAT_VERSION_V31,
    CandidateResponseV31,
    EvidenceReport,
    ExtractionDocumentV31,
    validate_document,
    validate_response,
)
from feature_dictionary.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
SMOKE = Path(__file__).parent / "fixtures" / "extraction_v31_smoke.txt"


def response(*pairs):
    return json.dumps(
        {
            "format_version": FORMAT_VERSION_V31,
            "entries": [{"matched_text": term, "source_phrase": phrase} for term, phrase in pairs],
        },
        ensure_ascii=False,
    )


@pytest.fixture(autouse=True)
def forbid_model_calls(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("V3.1 tests must never construct a real model client")

    monkeypatch.setattr(cli, "create_client", fail)
    monkeypatch.setattr(cli, "OpenAI", fail)
    monkeypatch.setattr(cli, "Anthropic", fail)
    monkeypatch.setattr(cli.genai, "Client", fail)


def test_derived_fields_have_no_fabricated_original_model_label():
    raw = response(("scales", "anterior dorsal scales"), ("keeled", "keeled"))
    report = validate_response(raw, "anterior dorsal scales are keeled")
    assert report.evidence_valid and report.raw_response == raw
    assert [e.term for e in report.entries] == ["scales", "keeled"]
    assert [e.evidence_type for e in report.entries] == ["embedded", "complete"]
    assert all(e.model_term is None for e in report.entries)
    assert (
        EvidenceReport.model_validate_json(report.model_dump_json()).model_dump()
        == report.model_dump()
    )


@pytest.mark.parametrize(
    "field", ["term", "evidence_type", "positions", "expansion", "relationships"]
)
def test_new_contract_rejects_model_derived_or_relationship_fields(field):
    value = json.loads(response(("scales", "scales")))
    value["entries"][0][field] = "invented"
    report = validate_response(json.dumps(value), "scales")
    assert not report.evidence_valid
    assert {i.code for i in report.issues} == {"CONTRACT_ERROR"}


@pytest.mark.parametrize(
    "quote,source",
    [("dorsals", "Dorsals"), ("preoculaire", "préoculaire"), ("é", "e\u0301"), ("A-B", "A–B")],
)
def test_exact_quotations_are_never_corrected(quote, source):
    report = validate_response(response((quote, source)), source)
    assert not report.evidence_valid
    assert {i.code for i in report.issues} == {"UNMATCHED_EVIDENCE"}
    assert report.entries[0].term == quote
    assert report.entries[0].location.candidates == []


@pytest.mark.parametrize("text", ["Dorsals", "préoculaire", "鳞片", "حراشف", "M.B.S.R.", "e\u0301"])
def test_multilingual_and_shorthand_wording_remains_exact(text):
    source = "🐍\r\n" + text
    report = validate_response(response((text, text)), source)
    assert report.evidence_valid
    span = report.entries[0].location.candidates[0].match_span
    assert span.start == 3 and source[span.start : span.end] == text


def test_ambiguity_and_invalid_evidence_are_retained():
    raw = response(("scales", "scales"), ("absent", "absent"))
    report = validate_response(raw, "scales scales")
    assert not report.evidence_valid and len(report.entries) == 2
    assert report.entries[0].location.status == "ambiguous"
    assert len(report.entries[0].location.candidates) == 2
    assert report.entries[1].location.status == "unmatched"
    assert {i.code for i in report.issues} == {"AMBIGUOUS_LOCATION", "UNMATCHED_EVIDENCE"}


def test_optional_annotation_problems_are_warnings():
    value = json.loads(response(("préoculaire", "préoculaire")))
    value["entries"][0]["proposed_annotations"] = {"language": 17, "forms": "uncertain"}
    report = validate_response(json.dumps(value), "préoculaire")
    assert report.evidence_valid and {i.code for i in report.issues} == {"ANNOTATION_REVIEW"}


def test_duplicate_claims_and_whitespace_still_fail():
    report = validate_response(response(("scales", "scales"), ("scales", "scales")), "scales")
    assert not report.evidence_valid and "DUPLICATE_ENTRY" in {i.code for i in report.issues}
    assert not validate_response(response((" ", " ")), " ").evidence_valid


def test_legacy_mismatch_behavior_is_preserved():
    old_entry = legacy_entry("scales", "dorsal scales")
    old_entry["evidence_type"] = "complete"
    legacy = validate_response(legacy_response(old_entry), "dorsal scales")
    revised = validate_response(response(("scales", "dorsal scales")), "dorsal scales")
    assert {i.code for i in legacy.issues} == {"EVIDENCE_TYPE_MISMATCH"}
    assert not legacy.evidence_valid and revised.evidence_valid
    assert legacy.entries[0].model_term == "scales" and revised.entries[0].model_term is None


def test_version_mismatch_is_explicit_without_reinterpreting_entries():
    raw = legacy_response(legacy_entry("scales"))
    report = validate_response(raw, "scales", expected_version=FORMAT_VERSION_V31)
    assert not report.evidence_valid
    assert {i.code for i in report.issues} == {"CANDIDATE_VERSION_MISMATCH"}
    assert report.entries[0].model_term == "scales"


@pytest.mark.parametrize(
    "version,filename", [("3.0", "extraction_v3.txt"), ("3.1", "extraction_v3_1.txt")]
)
def test_explicit_prompt_and_contract_selection(tmp_path, version, filename):
    path = write_project(tmp_path)
    loaded = load_settings(
        path, overrides={"extraction_format": "v3", "v3_candidate_version": version}
    )
    assert loaded.prompt_path.name == filename
    assert f"Output contract: extraction-{version}" in loaded.prompt_text
    assert load_settings(path).settings.extraction_format == "v2"


def test_default_opt_in_v3_uses_new_contract_and_preserves_source(tmp_path, capsys):
    path = write_project(tmp_path)
    loaded = load_settings(path, overrides={"extraction_format": "v3"})
    assert loaded.settings.v3_candidate_version == "3.1"
    assert loaded.prompt_path.name == "extraction_v3_1.txt"
    run = RunContext.from_settings(loaded, "  Dorsals\r\n", original_input_bytes=b"  Dorsals\r\n")
    assert "  Dorsals\r\n" in run.prompt_text
    assert cli.main(["--settings", str(path), "--extraction-format", "v3", "--dry-run"]) == 0
    assert "candidate contract: extraction-3.1" in capsys.readouterr().out
    assert not (tmp_path / "extractor_outputs").exists()


def test_cli_can_select_legacy_version_without_editing_settings(tmp_path, capsys):
    path = write_project(tmp_path)
    original = path.read_bytes()
    assert (
        cli.main(
            [
                "--settings",
                str(path),
                "--extraction-format",
                "v3",
                "--v3-candidate-version",
                "3.0",
                "--dry-run",
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "extraction-3.0" in text and "extraction_v3.txt" in text
    assert path.read_bytes() == original


@pytest.mark.parametrize("concurrency", [1, 3])
def test_six_model_pipeline_uses_new_contract_and_documents(tmp_path, monkeypatch, concurrency):
    path = project(tmp_path, v3_candidate_version="3.1", max_concurrency=concurrency)
    answer = response(("scales", "anterior dorsal scales"), ("keeled", "keeled"))
    prompts = []

    def generate(**kwargs):
        prompts.append(kwargs["prompt"])
        return NS(response=answer, done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    cloud_calls = []
    for provider in ["openai", "anthropic", "gemini"]:
        client, calls, _ = fake(provider, text=answer)
        install_cloud(monkeypatch, provider, client)
        cloud_calls.append(calls)
    assert cli.main(["--settings", str(path), "--models", SELECTION]) == 0
    for calls in cloud_calls:
        call = calls[0]
        prompts.append(call.get("input") or call.get("contents") or call["messages"][0]["content"])
    assert len(set(prompts)) == 1 and "extraction-3.1" in prompts[0]
    for index, model in enumerate(cli._parse_models(SELECTION)):
        raw, report, output = artifacts(
            tmp_path, index=index, model=cli.naming.slugify_model(model["model"])
        )
        assert raw["candidate_format_version"] == FORMAT_VERSION_V31
        assert raw["response_text"] == answer and report["accepted"]
        saved = ExtractionDocumentV31.model_validate_json(output.read_text())
        assert saved.format_version == FORMAT_VERSION_V31
        assert saved.run.prompt_version == "v3_1"
        assert all(e.model_term is None for e in saved.entries)
        assert validate_document(saved, answer).evidence_valid
        reconstructed = extraction_replay.replay_archive(output.with_suffix(".raw.json"))
        assert reconstructed["accepted"] and reconstructed["entries"] == report["entries"]


def test_revalidation_detects_edited_derived_fields(tmp_path, monkeypatch):
    path = project(tmp_path, v3_candidate_version="3.1", models=[cli.MODEL_ALIASES["gpt"]])
    answer = response(("scales", "anterior dorsal scales"))
    client, _, _ = fake("openai", text=answer)
    install_cloud(monkeypatch, "openai", client)
    assert cli.main(["--settings", str(path)]) == 0
    _, _, output = artifacts(tmp_path, model="gpt-5.4-nano")
    saved = ExtractionDocumentV31.model_validate_json(output.read_text())
    saved.entries[0].evidence_type = "complete"
    assert not validate_document(saved, answer).evidence_valid
    with pytest.raises(ValidationError):
        ExtractionDocumentV31.model_validate(
            {**saved.model_dump(), "format_version": "extraction-3.0"}
        )


def test_offline_replay_preserves_original_live_failure_and_files(capsys):
    path = ROOT / "extractor_outputs/v3_live_no_thinking/0_qwen3-8b.raw.json"
    if not path.exists():
        pytest.skip("Optional local research archive is not checked into every checkout")
    saved_report = json.loads(path.with_name("0_qwen3-8b.validation.json").read_text())
    before = {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    assert extraction_replay.main([str(path)]) == 1
    replayed = json.loads(capsys.readouterr().out)
    assert replayed["issues"] == saved_report["issues"]
    assert replayed["entries"] == saved_report["entries"]
    assert replayed["raw_response"] == saved_report["raw_response"]
    assert {p: p.read_bytes() for p in before} == before


def test_prompt_examples_are_valid_and_match_only_their_own_sources():
    path = ROOT / "prompts/extraction_v3_1.txt"
    text = path.read_text()
    decoder = json.JSONDecoder()
    examples = []
    for block in text.split("Example ")[1:]:
        source = block.split("source: ", 1)[1].splitlines()[0]
        value, _ = decoder.raw_decode(block[block.index("{") :])
        report = validate_response(json.dumps(value), source)
        assert report.evidence_valid
        examples.append({e.term for e in report.entries})
    assert len(examples) == 3
    assert {"anterior", "dorsal", "scales", "dorsal scales", "keeled"} <= examples[0]
    assert {"MBSR", "Midbody scale rows"} <= examples[1]
    assert {"Dorsals", "préoculaire", "praeocular", "colouration", "coloration"} <= examples[2]


def test_smoke_fixture_exercises_reviewed_coverage_without_production_inference():
    # Illustrative expected vocabulary, not a biological gold standard or model evaluation.
    text = SMOKE.read_text()
    pairs = [
        (term, "anterior dorsal scales")
        for term in ["anterior", "dorsal", "scales", "dorsal scales", "anterior dorsal scales"]
    ]
    pairs.extend(
        (term, term)
        for term in ["keeled", "Dorsals", "midbody", "prominent", "MBSR", "préoculaire"]
    )
    pairs.extend((term, "rostral scale") for term in ["rostral", "scale", "rostral scale"])
    pairs.extend(
        (term, "Midbody scale rows")
        for term in ["Midbody", "scale", "rows", "scale rows", "Midbody scale rows"]
    )
    report = validate_response(response(*pairs), text)
    assert report.evidence_valid and len(report.entries) == 19
    assert "Midbody scale rows (MBSR)" not in {e.term for e in report.entries}
    assert not validate_response(response(("dorsals", "Dorsals")), text).evidence_valid


@pytest.mark.parametrize(
    "name,model",
    [
        ("extraction_candidate_v3_1.schema.json", CandidateResponseV31),
        ("extraction_v3_1.schema.json", ExtractionDocumentV31),
    ],
)
def test_published_v31_schemas_match_contract(name, model):
    assert json.loads((ROOT / "schemas" / name).read_text()) == model.model_json_schema()


@pytest.mark.parametrize("returned_version", ["3.0", "3.1"])
def test_default_live_version_is_pinned_and_replay_is_read_only(
    tmp_path, monkeypatch, capsys, returned_version
):
    path = write_project(tmp_path, extraction_format="v3", models=[cli.MODEL_ALIASES["gpt"]])
    answer = (
        legacy_response(legacy_entry("head"))
        if returned_version == "3.0"
        else response(("head", "head"))
    )
    client, _, _ = fake("openai", text=answer)
    install_cloud(monkeypatch, "openai", client)
    expected = 1 if returned_version == "3.0" else 0
    assert cli.main(["--settings", str(path)]) == expected
    capsys.readouterr()
    raw, report, output = artifacts(tmp_path, model="gpt-5.4-nano")
    assert raw["candidate_format_version"] == FORMAT_VERSION_V31
    assert output.exists() == (returned_version == "3.1")
    if returned_version == "3.0":
        assert {i["code"] for i in report["issues"]} == {"CANDIDATE_VERSION_MISMATCH"}
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert extraction_replay.main([str(output.with_suffix(".raw.json"))]) == expected
    replayed = json.loads(capsys.readouterr().out)
    assert replayed["issues"] == report["issues"] and replayed["entries"] == report["entries"]
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_replay_without_new_version_metadata_preserves_legacy_errors(tmp_path, capsys):
    source = "dorsal scales"
    value = legacy_entry("scales", source)
    value["evidence_type"] = "complete"
    answer = legacy_response(value)
    # A self-contained legacy archive: no current settings or prompt file required.
    from test_extraction_v3 import document

    old = document(answer, source)
    archive = {
        "format_version": "extraction-raw-3.0",
        "input": old.input.model_dump(),
        "run": old.run.model_dump(),
        "response_text": answer,
        "response_available": True,
    }
    path = tmp_path / "legacy.raw.json"
    path.write_text(json.dumps(archive))
    assert extraction_replay.main([str(path)]) == 1
    result = json.loads(capsys.readouterr().out)
    expected = validate_response(answer, source).model_dump()
    assert result["issues"] == expected["issues"] and result["entries"] == expected["entries"]
    assert {issue["code"] for issue in result["issues"]} == {"EVIDENCE_TYPE_MISMATCH"}


def test_replay_rejects_forged_source_hash_and_invalid_archive(tmp_path):
    from test_extraction_v3 import document

    answer = legacy_response(legacy_entry("scales"))
    old = document(answer, "scales")
    archive = {
        "format_version": "extraction-raw-3.0",
        "input": old.input.model_dump(),
        "run": old.run.model_dump(),
        "response_text": answer,
        "response_available": True,
    }
    archive["input"]["supplied_text_sha256"] = "0" * 64
    path = tmp_path / "tampered.raw.json"
    path.write_text(json.dumps(archive))
    result = extraction_replay.replay_archive(path)
    assert not result["accepted"] and "INPUT_HASH_MISMATCH" in {i["code"] for i in result["issues"]}
    path.write_text('{"format_version":"extraction-raw-3.0","format_version":"x"}')
    assert extraction_replay.main([str(path)]) == 2
    path.write_text(response(("scales", "scales")))
    assert extraction_replay.main([str(path)]) == 2


def test_replay_retains_incomplete_provider_status(tmp_path):
    from test_extraction_v3 import document

    answer = legacy_response(legacy_entry("scales"))
    old = document(answer, "scales")
    old.run.completion_status = "incomplete"
    old.run.completion_reason = "length"
    archive = {
        "format_version": "extraction-raw-3.0",
        "input": old.input.model_dump(),
        "run": old.run.model_dump(),
        "response_text": answer,
        "response_available": True,
    }
    path = tmp_path / "incomplete.raw.json"
    path.write_text(json.dumps(archive))
    result = extraction_replay.replay_archive(path)
    assert result["evidence_valid"] and not result["accepted"]
    assert result["completion_status"] == "incomplete" and result["completion_reason"] == "length"


def test_new_contract_still_requires_strict_json():
    raw = '{"format_version":"extraction-3.1","entries":[],"entries":[]}'
    result = validate_response(raw, "scales")
    assert not result.evidence_valid and {i.code for i in result.issues} == {"INVALID_JSON"}
    empty = validate_response(response(), "scales")
    assert empty.evidence_valid and {i.code for i in empty.issues} == {"NO_ENTRIES"}
