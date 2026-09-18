"""Tests for the run context: prompt rendering, truncation and run metadata."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from feature_dictionary.context import RunContext
from feature_dictionary.settings import ExtractorSettings, LoadedSettings

STARTED = datetime(2026, 9, 18, 14, 3, 11)
DATABASE = "species text"


def build_loaded(tmp_path: Path, **overrides) -> LoadedSettings:
    """Build a LoadedSettings without touching the filesystem."""
    payload = {
        "input_file": Path("species_database.txt"),
        "prompt": "Describe {species_database}",
        "models": ["llama3.1:8b"],
    }
    payload.update(overrides)
    settings = ExtractorSettings(**payload)
    return LoadedSettings(
        settings=settings,
        path=tmp_path / "settings.json",
        base_dir=tmp_path,
        input_path=tmp_path / "species_database.txt",
        output_dir=tmp_path / "extractor_outputs",
        log_dir=tmp_path / "extractor_logs",
        prompt_text=settings.prompt or "",
        ollama_host="http://127.0.0.1:11434",
    )


def test_placeholder_receives_the_database_text(tmp_path):
    context = RunContext.from_settings(build_loaded(tmp_path), DATABASE, started_at=STARTED)
    assert context.prompt_text == "Describe species text"
    assert context.run_id == "2026-09-18T14:03:11"
    assert context.input_characters_total == len(DATABASE)
    assert context.input_truncated is False


def test_missing_placeholder_appends_the_database(tmp_path):
    loaded = build_loaded(tmp_path, prompt="Summarise the records.")
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.prompt_text.startswith("Summarise the records.")
    assert context.prompt_text.endswith("species text\n")


def test_max_input_characters_truncates_the_database(tmp_path):
    loaded = build_loaded(tmp_path, max_input_characters=7)
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.database_text == "species"
    assert len(context.database_text) == 7
    assert context.input_characters_total == len(DATABASE)
    assert context.input_truncated is True
    assert context.prompt_text == "Describe species"


def test_no_truncation_when_the_limit_is_larger_than_the_input(tmp_path):
    loaded = build_loaded(tmp_path, max_input_characters=10_000)
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.input_truncated is False
    assert context.database_text == DATABASE


def test_run_mode_reports_sequential_by_default(tmp_path):
    context = RunContext.from_settings(build_loaded(tmp_path), DATABASE, started_at=STARTED)
    assert context.is_sequential is True
    assert context.run_mode == "sequential (max_concurrency=1)"
    assert context.keep_alive_label == "5m"


def test_run_mode_reports_concurrency_when_configured(tmp_path):
    loaded = build_loaded(tmp_path, max_concurrency=3, keep_alive=None)
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.is_sequential is False
    assert context.run_mode == "concurrent (max_concurrency=3)"
    assert context.keep_alive_label == "ollama default"


def test_context_overrun_is_detected(tmp_path):
    loaded = build_loaded(tmp_path, options={"num_ctx": 100})
    context = RunContext.from_settings(loaded, "x" * 5_000, started_at=STARTED)
    assert context.num_ctx == 100
    overrun = context.context_overrun
    assert overrun is not None
    assert overrun[1] == 100
    assert overrun[0] == context.estimated_prompt_tokens


def test_large_context_has_no_overrun(tmp_path):
    loaded = build_loaded(tmp_path, options={"num_ctx": 100_000})
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.context_overrun is None


def test_prompt_fingerprint_is_stable_and_short(tmp_path):
    loaded = build_loaded(tmp_path)
    first = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    second = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert first.prompt_fingerprint == second.prompt_fingerprint
    assert len(first.prompt_fingerprint) == 16
    assert int(first.prompt_fingerprint, 16) >= 0


def test_different_input_changes_the_fingerprint(tmp_path):
    loaded = build_loaded(tmp_path)
    first = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    second = RunContext.from_settings(loaded, DATABASE + " more", started_at=STARTED)
    assert first.prompt_fingerprint != second.prompt_fingerprint


def test_run_options_apply_max_output_tokens(tmp_path):
    loaded = build_loaded(tmp_path, options={"num_ctx": 512}, max_output_tokens=200)
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.run_options == {"num_ctx": 512, "num_predict": 200}


def test_explicit_num_predict_wins_over_max_output_tokens(tmp_path):
    loaded = build_loaded(tmp_path, options={"num_predict": 50}, max_output_tokens=200)
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.run_options["num_predict"] == 50


def test_run_options_are_a_copy_of_the_configured_options(tmp_path):
    loaded = build_loaded(tmp_path, options={"temperature": 0.2})
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.run_options == {"temperature": 0.2}
    context.run_options["temperature"] = 0.9
    assert loaded.settings.options == {"temperature": 0.2}


def test_data_budget_leaves_room_for_instructions_and_output(tmp_path):
    loaded = build_loaded(tmp_path, options={"num_ctx": 1000}, max_output_tokens=200)
    context = RunContext.from_settings(loaded, DATABASE, started_at=STARTED)
    assert context.instruction_tokens == 2
    assert 3_000 < context.data_budget_characters < 3_200
    assert context.input_fits is True


def test_input_larger_than_the_budget_does_not_fit(tmp_path):
    loaded = build_loaded(tmp_path, options={"num_ctx": 64})
    context = RunContext.from_settings(loaded, "x" * 5_000, started_at=STARTED)
    assert context.data_budget_characters < 5_000
    assert context.input_fits is False
