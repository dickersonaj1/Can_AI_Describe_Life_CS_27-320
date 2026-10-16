"""Offline prompt policy and quotation regressions, not live biological-quality tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_cli import write_project
from test_extraction_prompt_v311 import examples
from test_extraction_v31 import response

from feature_dictionary import cli
from feature_dictionary.context import RunContext
from feature_dictionary.extraction_v3 import validate_response
from feature_dictionary.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts/extraction_v3_1_4.txt"
PREVIOUS = ROOT / "prompts/extraction_v3_1_3.txt"
SOURCE = ROOT / "tests/fixtures/acanthophis_antarcticus_real.txt"


@pytest.fixture(autouse=True)
def forbid_model_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Prompt tests must not contact model providers")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


def test_one_compact_demonstration_preserves_existing_contract():
    cases = examples(PROMPT.read_text())
    assert cases == examples(PREVIOUS.read_text()) and len(cases) == 1
    source, candidate = cases[0]
    assert candidate["format_version"] == "extraction-3.1"
    assert validate_response(json.dumps(candidate), source).evidence_valid
    assert {e["matched_text"] for e in candidate["entries"]} == {
        "dorsal",
        "scales",
        "dorsal scales",
        "DS",
        "keeled",
    }


def test_boundary_guidance_preserves_morphology_and_contextual_exclusions():
    text = " ".join(PROMPT.read_text().split())
    for rule in [
        "meaningful reusable biological vocabulary",
        "anatomical head",
        "independently meaningful embedded biological expressions",
        "multilingual terminology",
        "historical expressions",
        "not a universal blacklist",
        "Exclude bibliographic citations, author names, section headings/labels",
        "taxonomic names used only as identifiers",
        "full descriptive or comparative clauses",
        "Do not reject terminology merely because it is descriptive",
        "all adjectives",
        'standalone "terminating"',
    ]:
        assert rule in text
    for term in [
        "laterally compressed",
        "keeled",
        "rugose",
        "striated",
        "anal entire",
        "very faintly keeled",
        "anterior chin-shields",
        "tail spine",
    ]:
        assert f'"{term}"' in text
    assert "Maddock et al. 2015" not in text and "Boulenger 1896: 355" not in text
    assert (
        "Only text between BEGIN ACTUAL SOURCE and END ACTUAL SOURCE is extraction evidence" in text
    )
    assert "terminology illustrations" in text and "are NOT source evidence" in text


def test_verbatim_containment_deduplication_and_ambiguity_instructions():
    text = " ".join(PROMPT.read_text().split())
    for rule in [
        "shortest meaningful terminology-bearing expression",
        "Never substitute unrelated context",
        "matched_text must occur inside source_phrase",
        "quotation boundaries",
        "Never normalize or capitalize the first word",
        'do not quote "Belly" or "Two"',
        "each identical matched_text/source_phrase pair only once",
        "Python retains location ambiguity",
        "Never invent missing expansions",
    ]:
        assert rule in text


@pytest.mark.parametrize(
    "term",
    [
        "laterally compressed",
        "keeled",
        "rugose",
        "striated",
        "anal entire",
        "very faintly keeled",
        "anterior chin-shields",
        "tail spine",
    ],
)
def test_valid_specimen_expressions_remain_exactly_grounded(term):
    source = SOURCE.read_text()
    assert validate_response(response((term, term)), source).evidence_valid


@pytest.mark.parametrize(
    "term,phrase",
    [
        ("Belly yellowish white", "Belly yellowish white"),
        ("Two postoculars", "Two postoculars"),
        ("tail spine", "Tail slender, distal portion laterally compressed"),
    ],
)
def test_reported_case_and_attribution_errors_still_fail_strict_validation(term, phrase):
    report = validate_response(response((term, phrase)), SOURCE.read_text())
    assert not report.evidence_valid


def test_duplicate_claims_still_fail_without_repair():
    raw = response(("tail spine", "tail spine"), ("tail spine", "tail spine"))
    report = validate_response(raw, SOURCE.read_text())
    assert not report.evidence_valid and report.raw_response == raw


def test_experimental_prompt_requires_explicit_selection_and_changes_no_defaults(tmp_path):
    path = write_project(tmp_path)
    original_settings = path.read_bytes()
    loaded = load_settings(path, overrides={"extraction_format": "v3", "prompt_file": str(PROMPT)})
    source = SOURCE.read_text()
    run = RunContext.from_settings(loaded, source)
    assert run.prompt_version == "v3_1_4" and loaded.settings.v3_candidate_version == "3.1"
    assert f"BEGIN ACTUAL SOURCE\n{source}\nEND ACTUAL SOURCE" in run.prompt_text
    assert (
        load_settings(path, overrides={"extraction_format": "v3"}).prompt_path.name
        == "extraction_v3_1.txt"
    )
    assert path.read_bytes() == original_settings
    assert (
        cli.main(
            [
                "--settings",
                str(path),
                "--extraction-format",
                "v3",
                "--prompt-file",
                str(PROMPT),
                "--input",
                str(SOURCE),
                "--models",
                "gpt",
                "--dry-run",
            ]
        )
        == 0
    )
    assert not (tmp_path / "extractor_outputs").exists()
