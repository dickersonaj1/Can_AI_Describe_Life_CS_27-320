"""Provider selection regressions with fake SDK/Ollama responses only."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import LOCAL_MODELS, install_cloud
from test_extraction_v3_pipeline import artifacts, project
from test_extraction_v31 import response

from feature_dictionary import cli
from feature_dictionary.settings import SettingsError, load_settings, parse_model_selection


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Routing tests must never construct a live provider client")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


@pytest.mark.parametrize(
    "selection,provider,model",
    [
        ("ollama:qwen3:8b", "ollama", "qwen3:8b"),
        ("qwen3:8b", "ollama", "qwen3:8b"),
        ("deepseek-r1:8b", "ollama", "deepseek-r1:8b"),
        ("llama3.1:8b", "ollama", "llama3.1:8b"),
        ("openai:gpt-5.4-nano", "openai", "gpt-5.4-nano"),
        ("openai=gpt-5.4-nano", "openai", "gpt-5.4-nano"),
        ("gpt-5.4-nano", "openai", "gpt-5.4-nano"),
        ("gpt", "openai", "gpt-5.4-nano"),
        ("openai", "openai", "gpt-5.4-nano"),
        ("anthropic", "anthropic", "claude-sonnet-4-5-20250929"),
        ("claude", "anthropic", "claude-sonnet-4-5-20250929"),
        ("anthropic:claude-sonnet-4-5-20250929", "anthropic", "claude-sonnet-4-5-20250929"),
        ("gemini", "gemini", "gemini-3.8-flash"),
        ("gemini.8-flash", "gemini", "gemini.8-flash"),
        ("gemini:gemini-3.8-flash", "gemini", "gemini-3.8-flash"),
        (" ollama : qwen3:8b ", "ollama", "qwen3:8b"),
    ],
)
def test_provider_qualified_known_and_configured_identifiers(selection, provider, model):
    configured = (
        [{"provider": "gemini", "model": "gemini.8-flash"}] if selection == "gemini.8-flash" else []
    )
    assert parse_model_selection(selection, configured) == [{"provider": provider, "model": model}]


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "ollama"])
def test_configured_provider_identity_is_authoritative(tmp_path, provider):
    path = write_project(tmp_path, models=[{"provider": provider, "model": "research-model"}])
    for selector in ["research-model", provider]:
        loaded = load_settings(path, overrides={"models": selector})
        assert [(m.provider, m.model) for m in loaded.models] == [(provider, "research-model")]


def test_bare_canonical_name_retains_explicit_configured_provider(tmp_path):
    path = write_project(tmp_path, models=[{"provider": "openai", "model": "gpt-5.4-nano"}])
    assert load_settings(path, overrides={"models": "gpt-5.4-nano"}).models[0].provider == "openai"
    custom = write_project(tmp_path, models=[{"provider": "ollama", "model": "gpt-5.4-nano"}])
    assert (
        load_settings(custom, overrides={"models": "gpt-5.4-nano"}).models[0].provider == "ollama"
    )
    assert (
        load_settings(custom, overrides={"models": "openai:gpt-5.4-nano"}).models[0].provider
        == "openai"
    )


def test_arbitrary_local_names_remain_available_when_configured_or_qualified():
    assert parse_model_selection("custom-local:v1", ["custom-local:v1"])[0]["provider"] == "ollama"
    assert parse_model_selection("ollama:custom-local:v1")[0]["model"] == "custom-local:v1"
    assert parse_model_selection("ollama=custom-local:v1")[0]["provider"] == "ollama"


@pytest.mark.parametrize(
    "selector",
    [
        "unknown",
        "unknown:8b",
        "opneai:gpt-5.4-nano",
        "openai.4-nano",
        "gemini.8-flash",
        "bad=model",
        "openai:",
        "=model",
        "",
        " , ",
    ],
)
def test_unknown_or_invalid_names_fail_before_any_request_or_artifact(tmp_path, capsys, selector):
    path = write_project(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["--settings", str(path), "--models", selector]) == cli.EXIT_CONFIGURATION_ERROR
    assert "error:" in capsys.readouterr().err
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "selector", ["gpt,gpt", "gpt,openai:gpt-5.4-nano", "qwen3:8b,ollama=qwen3:8b"]
)
def test_duplicate_identity_is_rejected(selector):
    with pytest.raises(SettingsError, match="duplicate model selection"):
        parse_model_selection(selector)


def test_ambiguous_configured_id_and_provider_require_qualification():
    configured = [
        {"provider": "openai", "model": "same"},
        {"provider": "ollama", "model": "same"},
        {"provider": "openai", "model": "other"},
    ]
    for selector in ["same", "openai"]:
        with pytest.raises(SettingsError, match="ambiguous.*provider:model"):
            parse_model_selection(selector, configured)
    assert parse_model_selection("openai:same,ollama:same", configured) == configured[:2]


def test_omitted_override_preserves_configured_order_and_legacy_strings(tmp_path):
    models = [
        {"provider": "gemini", "model": "custom-cloud"},
        "custom-local:v2",
        {"provider": "openai", "model": "custom-openai"},
    ]
    path = write_project(tmp_path, models=models)
    assert [(m.provider, m.model) for m in load_settings(path).models] == [
        ("gemini", "custom-cloud"),
        ("ollama", "custom-local:v2"),
        ("openai", "custom-openai"),
    ]


@pytest.mark.parametrize("selector", ["gpt-5.4-nano", "openai", "openai:gpt-5.4-nano"])
def test_cloud_only_selection_never_constructs_or_probes_ollama(tmp_path, monkeypatch, selector):
    path = project(tmp_path, models=[cli.MODEL_ALIASES["gpt"]], v3_candidate_version="3.1")
    answer = response(("scales", "scales"))
    client, calls, _ = fake("openai", text=answer)
    install_cloud(monkeypatch, "openai", client)
    monkeypatch.setattr(cli, "list_installed_models", lambda client: pytest.fail("Ollama probe"))
    assert cli.main(["--settings", str(path), "--models", selector]) == 0
    assert len(calls) == 1
    raw, report, output = artifacts(tmp_path, model="gpt-5.4-nano")
    assert raw["run"]["provider"] == "openai" and report["accepted"] and output.exists()


def test_local_only_shorthand_uses_ollama(tmp_path, monkeypatch):
    path = write_project(tmp_path)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return NS(response="original local output", done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"qwen3:8b"})
    assert cli.main(["--settings", str(path), "--models", "qwen3:8b"]) == 0
    assert calls[0]["model"] == "qwen3:8b"
    assert "provider: ollama" in (tmp_path / "extractor_outputs/0_qwen3-8b.md").read_text()


def test_mixed_six_model_selection_preserves_indices_artifacts_and_provider_grouping(
    tmp_path, monkeypatch
):
    path = project(tmp_path, v3_candidate_version="3.1")
    selection = (
        "openai:gpt-5.4-nano,ollama:qwen3:8b,anthropic,ollama:deepseek-r1:8b,"
        "gemini:gemini-3.8-flash,ollama:llama3.1:8b"
    )
    expected = parse_model_selection(selection)
    events = []
    answer = response(("scales", "scales"))

    def generate(**kwargs):
        events.append(("ollama", kwargs["model"]))
        return NS(response=answer, done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    for provider in ["openai", "anthropic", "gemini"]:
        client, _, _ = fake(provider, text=answer)
        original = (
            client.responses.create
            if provider == "openai"
            else client.messages.create
            if provider == "anthropic"
            else client.models.generate_content
        )

        def record(*, _provider=provider, _original=original, **kwargs):
            events.append((_provider, kwargs["model"]))
            return _original(**kwargs)

        client.responses.create = record
        client.messages.create = record
        client.models.generate_content = record
        install_cloud(monkeypatch, provider, client)
    assert cli.main(["--settings", str(path), "--models", selection]) == 0
    assert [provider for provider, _ in events] == ["ollama"] * 3 + [
        "openai",
        "anthropic",
        "gemini",
    ]
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    for index, config in enumerate(expected):
        raw, validation, output = artifacts(
            tmp_path, index, cli.naming.slugify_model(config["model"])
        )
        assert raw["model_index"] == index
        assert raw["run"]["provider"] == config["provider"]
        assert raw["run"]["model"] == config["model"]
        assert validation["accepted"] and output.exists()
        assert f"| {index} | `{config['model']}` | success" in summary
        log = next((tmp_path / "extractor_logs").glob(f"{index}_*.md")).read_text()
        assert f"| Provider | {config['provider']} |" in log


def test_duplicate_selection_fails_without_reserving_output(tmp_path, capsys):
    path = write_project(tmp_path)
    assert cli.main(["--settings", str(path), "--models", "gpt,openai:gpt-5.4-nano"]) == 2
    assert "duplicate model selection" in capsys.readouterr().err
    assert not (tmp_path / "extractor_outputs").exists()
