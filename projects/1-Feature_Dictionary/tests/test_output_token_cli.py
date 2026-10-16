"""CLI output budgets use existing provider interfaces; no live requests."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import LOCAL_MODELS, SELECTION, install_cloud
from test_extraction_v31 import response

from feature_dictionary import cli
from feature_dictionary.context import RunContext
from feature_dictionary.settings import load_settings


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Token budget tests must not contact providers")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true", "no", "8192.0"])
def test_invalid_cli_budget_is_clear_and_exits_before_execution(value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--max-output-tokens", value])
    assert exc.value.code == 2
    assert "must be a positive integer" in capsys.readouterr().err


def test_missing_budget_value_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--max-output-tokens"])
    assert exc.value.code == 2 and "expected one argument" in capsys.readouterr().err


@pytest.mark.parametrize("budget", [1, 8192])
def test_cli_parses_positive_integer(budget):
    args = cli.build_parser().parse_args(["--max-output-tokens", str(budget)])
    assert cli._overrides_from_args(args)["max_output_tokens"] == budget


@pytest.mark.parametrize("override", [False, True])
def test_precedence_preserves_settings_and_legacy_local_limit(tmp_path, override):
    path = write_project(
        tmp_path, max_output_tokens=4096, options={"num_predict": 900, "num_ctx": 6144}
    )
    original = path.read_bytes()
    args = cli.build_parser().parse_args(["--max-output-tokens", "8192"] if override else [])
    loaded = load_settings(path, overrides=cli._overrides_from_args(args))
    assert loaded.settings.max_output_tokens == (8192 if override else 4096)
    assert RunContext.from_settings(loaded, "scales").run_options["num_predict"] == (
        8192 if override else 900
    )
    assert loaded.settings.options["num_ctx"] == 6144 and path.read_bytes() == original


@pytest.mark.parametrize("format", ["v2", "v3"])
def test_six_models_forward_and_archive_effective_cli_budget(tmp_path, monkeypatch, format):
    path = write_project(
        tmp_path,
        extraction_format=format,
        max_output_tokens=4096,
        options={"num_ctx": 32768, "num_predict": 1200},
    )
    (tmp_path / "species_database.txt").write_text("scales")
    answer = response(("scales", "scales"))
    local_calls = []

    def generate(**kwargs):
        local_calls.append(kwargs)
        return NS(response=answer, done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    clouds = {}
    for provider in ["openai", "anthropic", "gemini"]:
        client, calls, _ = fake(provider, text=answer)
        install_cloud(monkeypatch, provider, client)
        clouds[provider] = calls
    assert (
        cli.main(["--settings", str(path), "--models", SELECTION, "--max-output-tokens", "8192"])
        == 0
    )
    assert len(local_calls) == 3
    assert all(c["options"]["num_predict"] == 8192 for c in local_calls)
    assert clouds["openai"][0]["max_output_tokens"] == 8192
    assert clouds["anthropic"][0]["max_tokens"] == 8192
    assert clouds["gemini"][0]["config"]["max_output_tokens"] == 8192
    folder = tmp_path / "extractor_outputs"
    if format == "v3":
        raws = list(folder.glob("*.raw.json"))
        reports = list(folder.glob("*.validation.json"))
        assert len(raws) == len(reports) == 6
        for p in raws + reports:
            assert str(json.loads(p.read_text())["output_token_limit"]) == "8192"
    else:
        outputs = list(folder.glob("*.md"))
        assert len(outputs) == 6
        assert all("output_token_limit: 8192" in p.read_text() for p in outputs)
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    for provider in ["ollama", "openai", "anthropic", "gemini"]:
        assert f"{provider}=8192" in summary
    assert load_settings(path).settings.max_output_tokens == 4096


def test_cloud_only_dry_run_has_no_ollama_budget_restriction(tmp_path, capsys):
    path = write_project(
        tmp_path,
        models=[{"provider": "gemini", "model": "gemini-3.8-flash"}],
        max_output_tokens=4096,
    )
    assert cli.main(["--settings", str(path), "--max-output-tokens", "8192", "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "8192" in text and "not applicable to cloud-only run" in text
    assert not (tmp_path / "extractor_outputs").exists()


def test_provider_budget_rejection_is_reported_without_clamping_or_fallback(tmp_path, monkeypatch):
    path = write_project(
        tmp_path, extraction_format="v3", models=[{"provider": "gemini", "model": "fake"}]
    )
    client, _, _ = fake("gemini")
    calls = []

    def reject(**kwargs):
        calls.append(kwargs)
        raise ValueError("max_output_tokens exceeds the model's supported limit")

    client.models.generate_content = reject
    install_cloud(monkeypatch, "gemini", client)
    assert cli.main(["--settings", str(path), "--max-output-tokens", "8192"]) == 1
    raw = json.loads(next((tmp_path / "extractor_outputs").glob("*.raw.json")).read_text())
    assert "supported limit" in raw["error"] and not raw["response_available"]
    assert str(raw["output_token_limit"]) == "8192"
    assert len(calls) == 1 and calls[0]["config"]["max_output_tokens"] == 8192
