"""Presentation-only changes retain warning visibility and exclusive report writes."""

from __future__ import annotations

import json

from test_synthesis_v12 import JOB, case

from feature_dictionary import modular_synthesis as cli
from feature_dictionary.synthesis_core.inventory_execution import evaluate
from feature_dictionary.synthesis_core.inventory_report import render_report, safe


def test_natural_punctuation_and_renderer_markup_are_preserved():
    inputs, request, response = case()
    text = render_report(inputs, response, evaluate(request, response, inputs), request)
    assert "### anal — p1" in text
    assert "- **anal entire** —" in text
    assert "Local contextual expressions:\n\n- " in text
    assert r"review\." not in text
    assert r"\['p2'" not in text
    assert "Associated primaries: tail (p2), spine (p3)" in text
    assert safe("term_ref (tail), note: yes! /terms/0.") == "term_ref (tail), note: yes! /terms/0."
    assert "<script>" not in safe("<script>bad</script>")
    assert safe("[click](https://example.com)").startswith(r"\[click\]")


def test_main_hierarchy_is_concise_and_offsets_provenance_are_separate():
    inputs, request, response = case()
    text = render_report(inputs, response, evaluate(request, response, inputs), request)
    hierarchy, details = text.split("## Evidence details", 1)
    assert '- Evidence o2: "anal entire"' in hierarchy
    assert "**[ambiguous location]**" in hierarchy
    for field in ["Match offsets:", "source-phrase offsets:", "Extractor:", "Extraction run:"]:
        assert field not in hierarchy and field in details
    assert "Source phrase:" in details and "Original source path:" in details
    assert text.count("### o3\n") == 1


def test_shared_compounds_are_explicit_and_audit_sections_remain():
    inputs, request, response = case()
    text = render_report(inputs, response, evaluate(request, response, inputs), request)
    assert text.count("#### tail spine — c2") == 2
    assert text.count("**Shared indexed compound:** stored once;") == 2
    assert "stored compounds: 2" in text
    for title in [
        "Exclusions",
        "Unresolved observations",
        "Validation issues",
        "Model metadata and audit counts",
    ]:
        assert "## " + title in text
    assert "AMBIGUOUS_LOCATION" in text
    assert "UNVALIDATED MODEL PROPOSAL" in text


def test_optional_appendix_does_not_change_other_report_content():
    inputs, request, response = case()
    validation = evaluate(request, response, inputs)
    default = render_report(inputs, response, validation, request)
    extended = render_report(inputs, response, validation, request, include_raw_json=True)
    assert "Complete raw proposal appendix" not in default
    assert extended.startswith(default)
    assert "Complete raw proposal appendix" in extended
    assert '"format_version": "synthesis-1.2"' in extended
    assert default == render_report(inputs, response, validation, request)


def test_cli_raw_flag_and_no_overwrite_are_offline(tmp_path):
    response_path = JOB / "response.json"
    original = response_path.read_bytes()
    normal, raw = tmp_path / "normal.md", tmp_path / "raw.md"
    base = ["--render-report", str(JOB), "--report-output"]
    assert cli.main([*base, str(normal)]) == 0
    assert cli.main([*base, str(raw), "--include-raw-json"]) == 0
    assert "Complete raw proposal appendix" not in normal.read_text()
    assert "Complete raw proposal appendix" in raw.read_text()
    before = normal.read_bytes()
    assert cli.main([*base, str(normal), "--include-raw-json"]) == 2
    assert normal.read_bytes() == before and response_path.read_bytes() == original


def test_missing_decisions_and_invalid_evidence_remain_visible_without_raw_appendix():
    inputs, request, response = case()
    data = json.loads(response["response_text"])
    data["observation_dispositions"].pop()
    data["terms"][0]["expressions"][0]["text"] = "Anal entire"
    response["response_text"] = json.dumps(data)
    validation = evaluate(request, response, inputs)
    text = render_report(inputs, response, validation, request)
    assert "MISSING DECISION — UNRESOLVED" in text
    assert "UNOBSERVED_EXPRESSION" in text and "MISSING_DISPOSITION" in text
    assert "[INVALID — see issues]" in text
    assert "Complete raw proposal appendix" not in text
