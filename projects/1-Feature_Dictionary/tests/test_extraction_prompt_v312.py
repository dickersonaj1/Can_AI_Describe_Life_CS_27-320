"""Offline checks for contextual terminology selection; no live quality claims."""

from __future__ import annotations

from pathlib import Path

from test_cli import write_project
from test_extraction_prompt_v311 import examples

from feature_dictionary.context import RunContext
from feature_dictionary.extraction_v3 import validate_response
from feature_dictionary.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts/extraction_v3_1_2.txt"


def test_examples_keep_anatomical_heads_and_technical_compounds_not_generic_rows():
    import json

    cases = examples(PROMPT.read_text())
    assert len(cases) == 3
    for source, candidate in cases:
        assert candidate["format_version"] == "extraction-3.1"
        assert validate_response(json.dumps(candidate), source).evidence_valid
    first = {e["matched_text"]: e["source_phrase"] for e in cases[0][1]["entries"]}
    assert {"scales", "dorsal", "dorsal scales", "anterior dorsal scales", "keeled"} <= first.keys()
    assert first["scales"] == "dorsal scales"
    assert first["dorsal"] == "dorsal scales"
    second = {e["matched_text"]: e["source_phrase"] for e in cases[1][1]["entries"]}
    assert {"scale", "scale rows", "Midbody scale rows", "MBSR"} <= second.keys()
    assert "rows" not in second
    assert second["scale"] == "scale rows"
    assert second["scale rows"] == "scale rows"
    third = {e["matched_text"] for e in cases[2][1]["entries"]}
    assert {"Dorsals", "préoculaire", "praeocular", "colouration", "coloration"} <= third


def test_prompt_quality_exclusions_are_contextual_not_validator_blacklists():
    text = " ".join(PROMPT.read_text().split())
    assert (
        'Exclude "prominent" as a generic description in "The rostral scale is prominent"' in text
    )
    assert 'exclude standalone "rows"' in text
    assert "not an unconditional blacklist" in text
    assert "source context genuinely uses it as recognized domain-specific terminology" in text
    assert "shortest meaningful terminology-bearing expression" in text
    assert "Do not use an entire sentence, predicate, or reporting clause" in text
    # Exact quotation validation must not enforce linguistic quality judgments.
    import json

    for term in ["prominent", "rows"]:
        raw = json.dumps(
            {
                "format_version": "extraction-3.1",
                "entries": [{"matched_text": term, "source_phrase": term}],
            }
        )
        assert validate_response(raw, term).evidence_valid


def test_revised_prompt_identity_changes_without_replacing_previous_default(tmp_path):
    path = write_project(tmp_path)
    loaded = load_settings(path, overrides={"extraction_format": "v3", "prompt_file": str(PROMPT)})
    run = RunContext.from_settings(
        loaded, "Dorsal scales keeled.", original_input_bytes=b"Dorsal scales keeled."
    )
    assert run.prompt_version == "v3_1_2"
    assert loaded.settings.v3_candidate_version == "3.1"
    assert loaded.prompt_path == PROMPT
    assert (
        load_settings(path, overrides={"extraction_format": "v3"}).prompt_path.name
        == "extraction_v3_1.txt"
    )
