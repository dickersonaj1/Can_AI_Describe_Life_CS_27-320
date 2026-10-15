"""Configured aliases reuse model resolution; all integration requests are mocked."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import LOCAL_MODELS, install_cloud
from test_extraction_v3_pipeline import artifacts, project
from test_extraction_v31 import response

from feature_dictionary import cli
from feature_dictionary.settings import (
    MODEL_ALIASES,
    SettingsError,
    load_settings,
    parse_model_selection,
)

ROOT = Path(__file__).resolve().parents[1]
ALIASES = json.loads((ROOT / "settings.json").read_text())["model_aliases"]
ALL_SIX = "qwen,deepseek,llama,gpt,claude,gemini"


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Alias tests must never construct live model clients")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


@pytest.mark.parametrize("name", ["qwen", "deepseek", "llama", "gpt", "claude", "gemini"])
def test_project_aliases_resolve_to_full_identities_without_enabling_extra_models(name):
    input_file = "tests/fixtures/extraction_v31_smoke.txt"
    loaded = load_settings(
        ROOT / "settings.json",
        overrides={"models": name, "input_file": input_file},
    )
    assert [m.model_dump() for m in loaded.models] == [ALIASES[name]]
    assert loaded.settings.model_aliases[name].model_dump() == ALIASES[name]
    assert (
        len(load_settings(ROOT / "settings.json", overrides={"input_file": input_file}).models) == 1
    )


def test_alias_version_changes_need_only_configuration(tmp_path):
    aliases = {"qwen": {"provider": "ollama", "model": "research-qwen:v2"}}
    path = write_project(tmp_path, model_aliases=aliases)
    assert load_settings(path, overrides={"models": "qwen"}).models[0].model == "research-qwen:v2"
    assert parse_model_selection("research-qwen:v2", configured_aliases=aliases) == [
        aliases["qwen"]
    ]
    assert parse_model_selection("ollama:qwen3:8b", configured_aliases=aliases) == [
        {"provider": "ollama", "model": "qwen3:8b"}
    ]
    assert MODEL_ALIASES["gpt"]["model"] == "gpt-5.4-nano"  # Defaults not mutated.


def test_configured_cloud_alias_overrides_compatibility_default(tmp_path):
    aliases = {"gpt": {"provider": "openai", "model": "custom-openai"}}
    path = write_project(tmp_path, model_aliases=aliases)
    assert load_settings(path, overrides={"models": "gpt"}).models[0].model == "custom-openai"
    assert parse_model_selection("openai", configured_aliases=aliases) == [aliases["gpt"]]
    assert parse_model_selection("gpt-5.4-nano", configured_aliases=aliases) == [
        MODEL_ALIASES["gpt"]
    ]


def test_explicit_alias_disambiguates_provider_with_multiple_configured_models():
    configured = [{"provider": "gemini", "model": "one"}, {"provider": "gemini", "model": "two"}]
    assert parse_model_selection("gemini", configured, {"gemini": configured[1]}) == [configured[1]]
    with pytest.raises(SettingsError, match="ambiguous"):
        parse_model_selection("gemini", configured)


def test_alias_native_id_collision_requires_explicit_selection():
    configured = [{"provider": "openai", "model": "qwen"}]
    with pytest.raises(SettingsError, match="ambiguous"):
        parse_model_selection("qwen", configured, ALIASES)
    assert parse_model_selection("ollama:qwen3:8b", configured, ALIASES) == [ALIASES["qwen"]]
    same = [{"provider": "ollama", "model": "qwen3:8b"}]
    assert parse_model_selection("qwen3:8b", same, {"qwen3": same[0]}) == same
    with pytest.raises(SettingsError, match="ambiguous"):
        parse_model_selection("gpt-5.4-nano", configured_aliases={"gpt-5.4-nano": ALIASES["qwen"]})


@pytest.mark.parametrize(
    "selector", ["qwen,qwen", "qwen,ollama:qwen3:8b", "gpt,openai=gpt-5.4-nano"]
)
def test_duplicate_alias_and_native_selection_is_rejected(selector):
    with pytest.raises(SettingsError, match="duplicate model selection"):
        parse_model_selection(selector, configured_aliases=ALIASES)


def test_two_aliases_to_one_identity_are_not_two_independent_models():
    aliases = {"first": ALIASES["qwen"], "second": ALIASES["qwen"]}
    with pytest.raises(SettingsError, match="duplicate model selection"):
        parse_model_selection("first,second", configured_aliases=aliases)


@pytest.mark.parametrize(
    "aliases",
    [
        {"": ALIASES["qwen"]},
        {" qwen": ALIASES["qwen"]},
        {"qwen,other": ALIASES["qwen"]},
        {"ollama:qwen": ALIASES["qwen"]},
        {"qwen=other": ALIASES["qwen"]},
        {"openai": ALIASES["qwen"]},
        {"qwen": "ollama:qwen3:8b"},
        {"qwen": {"provider": "unknown", "model": "qwen3:8b"}},
        {"qwen": {"provider": "ollama", "model": " "}},
        {"qwen": "other_alias"},
        ["qwen"],
    ],
)
def test_invalid_alias_definitions_are_configuration_errors(tmp_path, aliases):
    path = write_project(tmp_path, model_aliases=aliases)
    for overrides in [None, {"models": "qwen"}]:
        with pytest.raises(SettingsError, match="model_aliases"):
            load_settings(path, overrides=overrides)


def test_unknown_alias_does_not_route_to_ollama(tmp_path, capsys):
    path = write_project(tmp_path, model_aliases=ALIASES)
    assert cli.main(["--settings", str(path), "--models", "qwne"]) == 2
    assert "unknown model selector" in capsys.readouterr().err
    assert not (tmp_path / "extractor_outputs").exists()


def test_legacy_configuration_and_selection_syntax_are_preserved(tmp_path):
    path = write_project(tmp_path)
    assert not load_settings(path).settings.model_aliases
    assert [m.model for m in load_settings(path).models] == ["llama3.1:8b", "qwen3:8b"]
    assert load_settings(path, overrides={"models": "gpt"}).models[0].provider == "openai"
    assert parse_model_selection("qwen3:8b")[0]["provider"] == "ollama"
    assert parse_model_selection("ollama=qwen3:8b", configured_aliases=ALIASES) == [ALIASES["qwen"]]


def test_alias_configuration_override_is_used_for_cli_resolution(tmp_path):
    path = write_project(tmp_path, model_aliases=ALIASES)
    changed = {"qwen": {"provider": "ollama", "model": "different:qwen"}}
    assert (
        load_settings(path, overrides={"model_aliases": changed, "models": "qwen"}).models[0].model
        == "different:qwen"
    )
    assert json.loads(path.read_text())["model_aliases"] == ALIASES


@pytest.mark.parametrize("selection", ["qwen,deepseek,llama", "gpt,claude,gemini", ALL_SIX])
def test_local_cloud_and_mixed_aliases_use_existing_runners_and_native_metadata(
    tmp_path, monkeypatch, selection
):
    path = project(tmp_path, model_aliases=ALIASES, v3_candidate_version="3.1")
    answer = response(("scales", "scales"))
    local_calls = []

    def generate(**kwargs):
        local_calls.append(kwargs)
        return NS(response=answer, done=True, done_reason="stop")

    selected = selection.split(",")
    if any(ALIASES[name]["provider"] == "ollama" for name in selected):
        monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
        monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    cloud_calls = {}
    for provider in ["openai", "anthropic", "gemini"]:
        if any(ALIASES[name]["provider"] == provider for name in selected):
            client, calls, _ = fake(provider, text=answer)
            install_cloud(monkeypatch, provider, client)
            cloud_calls[provider] = calls
    assert cli.main(["--settings", str(path), "--models", selection]) == 0
    assert len(local_calls) == sum(ALIASES[name]["provider"] == "ollama" for name in selected)
    assert all(len(calls) == 1 for calls in cloud_calls.values())
    for index, name in enumerate(selected):
        identity = ALIASES[name]
        raw, report, output = artifacts(
            tmp_path, index, cli.naming.slugify_model(identity["model"])
        )
        assert raw["run"]["provider"] == identity["provider"]
        assert raw["run"]["model"] == identity["model"]
        assert raw["model_index"] == index and report["accepted"] and output.exists()


def test_short_alias_dry_run_is_read_only(tmp_path, capsys):
    path = write_project(tmp_path, model_aliases=ALIASES)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["--settings", str(path), "--models", ALL_SIX, "--dry-run"]) == 0
    output = capsys.readouterr().out
    for identity in ALIASES.values():
        assert f"{identity['provider']}:{identity['model']}" in output
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
