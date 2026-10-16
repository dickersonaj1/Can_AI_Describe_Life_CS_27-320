"""Offline prompt regressions; these checks do not evaluate a live model's quality."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_cli import write_project

from feature_dictionary import cli
from feature_dictionary.context import RunContext
from feature_dictionary.extraction_v3 import validate_response
from feature_dictionary.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / "prompts/extraction_v3_1.txt"
REVISED = ROOT / "prompts/extraction_v3_1_1.txt"


@pytest.fixture(autouse=True)
def forbid_model_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Prompt tests must not contact a model provider")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


def examples(text):
    decoder = json.JSONDecoder()
    result = []
    for block in text.split("Example ")[1:]:
        source = block.split("source: ", 1)[1].splitlines()[0]
        candidate, _ = decoder.raw_decode(block[block.index("{") :])
        result.append((source, candidate))
    return result


def test_examples_remain_exact_and_demonstrate_embedded_heads_and_states():
    revised = examples(REVISED.read_text())
    assert revised == examples(PREVIOUS.read_text())
    assert len(revised) == 3
    for source, candidate in revised:
        assert candidate["format_version"] == "extraction-3.1"
        report = validate_response(json.dumps(candidate), source)
        assert report.evidence_valid
        assert all(e.term == e.matched_text for e in report.entries)
    first = {e["matched_text"] for e in revised[0][1]["entries"]}
    assert {"scales", "dorsal scales", "anterior dorsal scales", "keeled"} <= first
    assert "scale" not in first
    second = {e["matched_text"] for e in revised[1][1]["entries"]}
    assert {"Midbody scale rows", "MBSR"} <= second
    assert "Midbody scale rows (MBSR)" not in second


def test_guidance_distinguishes_domain_vocabulary_from_reporting_language():
    # Static policy coverage cannot establish that a model will obey these instructions.
    text = " ".join(REVISED.read_text().split())
    assert "anatomical head noun (the word naming the structure)" in text
    assert 'do not singularize "scales" to "scale", pluralize, or generate absent forms' in text
    assert "without assuming English word order" in text
    assert "ordinary reporting language, auxiliary-verb phrases, observation procedures" in text
    assert "generic actions unless they constitute recognized domain-specific terminology" in text
    for expression in ['"were counted"', '"is visible"', '"found to be"']:
        assert expression in text
    assert '"number" when used as an ordinary verb' in text
    assert "not a blanket ban on verbs or descriptors" in text
    assert 'Keep potentially meaningful morphology descriptors such as "prominent" eligible' in text


def test_explicit_prompt_selection_records_new_identity_without_changing_defaults(tmp_path):
    path = write_project(tmp_path)
    args = cli.build_parser().parse_args(
        [
            "--settings",
            str(path),
            "--extraction-format",
            "v3",
            "--prompt-file",
            str(REVISED),
            "--ollama-think",
            "false",
        ]
    )
    loaded = load_settings(path, overrides=cli._overrides_from_args(args))
    source = "Dorsal scales keeled.\n"
    run = RunContext.from_settings(loaded, source, original_input_bytes=source.encode())
    assert loaded.settings.v3_candidate_version == "3.1"
    assert loaded.prompt_path == REVISED
    assert run.prompt_version == "v3_1_1"
    assert run.prompt_template_sha256 == hashlib.sha256(REVISED.read_bytes()).hexdigest()
    assert source in run.prompt_text and loaded.settings.ollama_think is False
    assert "Output contract: extraction-3.1" in run.prompt_text
    default = load_settings(path, overrides={"extraction_format": "v3"})
    assert default.prompt_path == PREVIOUS
    assert default.settings.v3_candidate_version == "3.1"
    assert load_settings(path).settings.extraction_format == "v2"


def test_explicit_revised_prompt_dry_run_writes_no_experiment(tmp_path, capsys):
    path = write_project(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert (
        cli.main(
            [
                "--settings",
                str(path),
                "--extraction-format",
                "v3",
                "--models",
                "qwen3:8b",
                "--prompt-file",
                str(REVISED),
                "--ollama-think",
                "false",
                "--dry-run",
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "prompt version  : v3_1_1" in text
    assert "candidate contract: extraction-3.1" in text
    assert "disabled (think=false)" in text
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
