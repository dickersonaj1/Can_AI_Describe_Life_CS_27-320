"""Tests for settings.json loading, validation and path resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feature_dictionary.settings import (
    DEFAULT_OLLAMA_HOST,
    ExtractorSettings,
    SettingsError,
    load_settings,
    render_prompt,
    resolve_settings,
)

BASE_PAYLOAD = {
    "input_file": "species_database.txt",
    "prompt": "Describe {species_database}",
    "models": ["llama3.1:8b"],
}


def write_settings(tmp_path: Path, **overrides) -> Path:
    """Create a species_database.txt plus a settings.json inside ``tmp_path``."""
    (tmp_path / "species_database.txt").write_text("Species chunk", encoding="utf-8")
    payload = {**BASE_PAYLOAD, **overrides}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_defaults_are_applied_and_paths_resolved(tmp_path):
    loaded = load_settings(write_settings(tmp_path))
    assert loaded.models == ["llama3.1:8b"]
    assert loaded.base_dir == tmp_path
    assert loaded.input_path == (tmp_path / "species_database.txt").resolve()
    assert loaded.output_dir == (tmp_path / "extractor_outputs").resolve()
    assert loaded.log_dir == (tmp_path / "extractor_logs").resolve()
    assert loaded.ollama_host == DEFAULT_OLLAMA_HOST
    assert loaded.settings.max_concurrency == 1
    assert loaded.settings.log_date_format == "%m_%d"


def test_host_can_be_configured(tmp_path):
    loaded = load_settings(write_settings(tmp_path, host="http://192.168.0.10:11434"))
    assert loaded.ollama_host == "http://192.168.0.10:11434"


def test_ollama_host_environment_variable_is_used(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11500")
    loaded = load_settings(write_settings(tmp_path))
    assert loaded.ollama_host == "http://127.0.0.1:11500"


def test_tilde_paths_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    loaded = load_settings(write_settings(tmp_path, output_dir="~/extractor_outputs"))
    assert loaded.output_dir == (tmp_path / "extractor_outputs").resolve()


def test_command_line_overrides_win(tmp_path):
    path = write_settings(tmp_path, models=["llama3.1:8b", "qwen3:8b"])
    loaded = load_settings(path, overrides={"models": ["gemma3:12b"]})
    assert loaded.models == ["gemma3:12b"]


def test_prompt_file_override_replaces_the_inline_prompt(tmp_path):
    path = write_settings(tmp_path)
    (tmp_path / "prompt.md").write_text("From file: {species_database}", encoding="utf-8")
    loaded = load_settings(path, overrides={"prompt": None, "prompt_file": "prompt.md"})
    assert loaded.prompt_text == "From file: {species_database}"


def test_unknown_keys_are_rejected(tmp_path):
    with pytest.raises(SettingsError, match="invalid settings"):
        load_settings(write_settings(tmp_path, model=["typo"]))


def test_missing_prompt_source_is_rejected(tmp_path):
    with pytest.raises(SettingsError, match="prompt"):
        load_settings(write_settings(tmp_path, prompt=None))


def test_both_prompt_sources_are_rejected(tmp_path):
    with pytest.raises(SettingsError, match="not both"):
        load_settings(write_settings(tmp_path, prompt_file="prompt.md"))


def test_empty_model_list_is_rejected(tmp_path):
    with pytest.raises(SettingsError, match="models"):
        load_settings(write_settings(tmp_path, models=[]))


def test_missing_input_file_is_rejected(tmp_path):
    path = write_settings(tmp_path)
    (tmp_path / "species_database.txt").unlink()
    with pytest.raises(SettingsError, match="input file not found"):
        load_settings(path)


def test_missing_prompt_file_is_rejected(tmp_path):
    path = write_settings(tmp_path, prompt=None, prompt_file="nope.md")
    with pytest.raises(SettingsError, match="prompt file not found"):
        load_settings(path)


def test_invalid_json_is_rejected(tmp_path):
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsError, match="not valid JSON"):
        load_settings(tmp_path / "settings.json")


def test_missing_settings_file_is_rejected(tmp_path):
    with pytest.raises(SettingsError, match="settings file not found"):
        load_settings(tmp_path / "settings.json")


def test_render_prompt_substitutes_the_placeholder():
    assert render_prompt("A {species_database} B", "chunk") == "A chunk B"


def test_render_prompt_appends_when_the_placeholder_is_absent():
    rendered = render_prompt("A B", "chunk")
    assert rendered.startswith("A B")
    assert rendered.endswith("chunk\n")


def test_render_prompt_without_a_placeholder_setting():
    rendered = render_prompt("A B", "chunk", "")
    assert rendered.endswith("chunk\n")


def test_resolve_settings_is_pure_path_resolution(tmp_path):
    (tmp_path / "species_database.txt").write_text("Species chunk", encoding="utf-8")
    settings = ExtractorSettings(**BASE_PAYLOAD)
    loaded = resolve_settings(settings, tmp_path / "settings.json")
    assert loaded.input_path == (tmp_path / "species_database.txt").resolve()


def test_output_cap_and_loop_guard_defaults(tmp_path):
    loaded = load_settings(write_settings(tmp_path))
    assert loaded.settings.max_output_tokens is None
    assert loaded.settings.loop_guard is False
    assert loaded.settings.loop_guard_repeats == 25


def test_max_output_tokens_must_be_positive(tmp_path):
    with pytest.raises(SettingsError, match="max_output_tokens"):
        load_settings(write_settings(tmp_path, max_output_tokens=0))


def test_loop_guard_repeats_must_be_at_least_two(tmp_path):
    with pytest.raises(SettingsError, match="loop_guard_repeats"):
        load_settings(write_settings(tmp_path, loop_guard_repeats=1))


def test_output_cap_and_loop_guard_can_be_configured(tmp_path):
    loaded = load_settings(
        write_settings(tmp_path, max_output_tokens=1200, loop_guard=True, loop_guard_repeats=10)
    )
    assert loaded.settings.max_output_tokens == 1200
    assert loaded.settings.loop_guard is True
    assert loaded.settings.loop_guard_repeats == 10
