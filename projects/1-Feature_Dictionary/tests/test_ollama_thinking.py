"""Thinking configuration uses mocked Ollama and cloud calls, never a model server."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import ollama
import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import LOCAL_MODELS, SELECTION, install_cloud
from test_extraction_v3 import entry, response
from test_extraction_v3_pipeline import artifacts, project
from test_runner import FakeClient, make_chunk, make_response

from feature_dictionary import cli, runner
from feature_dictionary.settings import SettingsError, load_settings


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Thinking tests must not construct real provider clients")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


@pytest.mark.parametrize("think", [None, False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_request_mode_preserves_metrics_and_returned_text(think, stream):
    final = make_response(response="scales", thinking="returned reasoning", done=True)
    client = FakeClient(response=final, chunks=[final])
    outcome = runner.run_model(client, model="qwen3:8b", prompt="p", stream=stream, think=think)
    request = client.calls[0]
    assert ("think" in request) == (think is not None)
    if think is not None:
        assert request["think"] is think
    assert "think" not in (request["options"] or {})
    assert outcome.response_text == "scales" and outcome.thinking_text == "returned reasoning"
    assert outcome.completion_status == "success"
    assert outcome.metrics.eval_count == 5 and outcome.metrics.total_tokens == 15
    assert outcome.metrics.thinking_characters == len("returned reasoning")
    assert outcome.metrics.total_duration_ns == 1_000_000_000


@pytest.mark.parametrize("think", [None, False, True])
def test_installed_client_serializes_top_level_think_without_network(monkeypatch, think):
    client = ollama.Client()
    sent = []

    def fake_request(*args, **kwargs):
        sent.append(kwargs["json"])
        return make_response()

    monkeypatch.setattr(client, "_request", fake_request)
    try:
        runner.run_model(client, model="qwen3:8b", prompt="p", think=think)
    finally:
        client._client.close()
    assert ("think" in sent[0]) == (think is not None)
    if think is not None:
        assert sent[0]["think"] is think


def test_unspecified_mode_supports_client_without_think_parameter():
    def generate(model, prompt, stream, keep_alive, options):
        return NS(response="scales", done_reason="stop")

    outcome = runner.run_model(NS(generate=generate), model="llama3.1:8b", prompt="p")
    assert outcome.completion_status == "success" and outcome.thinking_text == ""


def test_explicit_mode_rejection_is_not_silently_retried():
    client = FakeClient(generate_error=ollama.ResponseError("does not support thinking", 400))
    with pytest.raises(ollama.ResponseError, match="does not support thinking"):
        runner.run_model(client, model="nonthinking", prompt="p", think=True)
    assert len(client.calls) == 1 and client.calls[0]["think"] is True


@pytest.mark.parametrize("think", [False, True])
def test_mode_does_not_change_incomplete_reasoning_only_detection(think):
    client = FakeClient(
        response=make_response(
            response="", thinking="reasoning only", done_reason="length", eval_count=4096
        )
    )
    result = runner.run_model(client, model="qwen3:8b", prompt="p", think=think)
    assert result.completion_status == "incomplete"
    assert result.metrics.eval_count == 4096 and result.metrics.done_reason == "length"
    assert result.response_text == "" and result.thinking_text == "reasoning only"


@pytest.mark.parametrize("think", [False, True])
def test_mode_preserves_partial_interrupted_text(think):
    client = FakeClient(chunks=[make_chunk("partial JSON", "partial reasoning")], interrupt_after=1)
    with pytest.raises(runner.GenerationInterrupted) as caught:
        runner.run_model(client, model="qwen3:8b", prompt="p", stream=True, think=think)
    assert caught.value.outcome.thinking_text == "partial reasoning"
    assert caught.value.outcome.response_text == "partial JSON"
    assert caught.value.outcome.completion_status == "interrupted"


@pytest.mark.parametrize(
    "mode,label", [(None, "model default"), (True, "enabled"), (False, "disabled")]
)
def test_v3_archives_and_logs_record_requested_mode(tmp_path, monkeypatch, mode, label):
    path = project(tmp_path, models=["qwen3:8b"], ollama_think=mode)
    calls = []
    answer = response(entry("scales"))

    def generate(**kwargs):
        calls.append(kwargs)
        return NS(response=answer, thinking="returned thinking", done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"qwen3:8b"})
    assert cli.main(["--settings", str(path)]) == 0
    assert ("think" in calls[0]) == (mode is not None)
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert raw["ollama_think"] is mode and report["ollama_think"] is mode
    assert label in raw["ollama_thinking_request"]
    assert raw["thinking_text"] == "returned thinking" and output.exists() and report["accepted"]
    logs = "\n".join(p.read_text() for p in (tmp_path / "extractor_logs").glob("*.md"))
    assert f"Ollama thinking request | {raw['ollama_thinking_request']}" in logs
    assert f"Ollama thinking request: {raw['ollama_thinking_request']}" in logs


def test_unsupported_model_failure_is_archived_and_other_models_continue(tmp_path, monkeypatch):
    path = project(tmp_path, models=["nonthinking", "qwen3:8b"], ollama_think=False)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] == "nonthinking":
            raise ollama.ResponseError("does not support thinking", 400)
        return NS(response=response(entry("scales")), done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"nonthinking", "qwen3:8b"})
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    assert len(calls) == 2 and all(call["think"] is False for call in calls)
    raw, report, output = artifacts(tmp_path, model="nonthinking")
    assert raw["ollama_think"] is False and "does not support thinking" in raw["error"]
    assert not raw["response_available"] and not report["accepted"] and not output.exists()
    assert artifacts(tmp_path, index=1, model="qwen3-8b")[2].exists()


def test_six_model_selection_only_sends_think_to_ollama(tmp_path, monkeypatch):
    path = project(tmp_path, ollama_think=False)
    local_calls = []
    answer = response(entry("scales"))

    def generate(**kwargs):
        local_calls.append(kwargs)
        return NS(response=answer, done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    cloud_calls = []
    for provider in ["openai", "anthropic", "gemini"]:
        client, calls, _ = fake(provider, text=answer)
        install_cloud(monkeypatch, provider, client)
        cloud_calls.append(calls)
    assert cli.main(["--settings", str(path), "--models", SELECTION]) == 0
    assert len(local_calls) == 3 and all(c["think"] is False for c in local_calls)
    for calls in cloud_calls:
        assert len(calls) == 1 and "think" not in calls[0]
    for index, model in enumerate(cli._parse_models(SELECTION)[3:], start=3):
        raw, _, _ = artifacts(tmp_path, index=index, model=cli.naming.slugify_model(model["model"]))
        assert "ollama_think" not in raw


@pytest.mark.parametrize("flag,expected", [("true", True), ("false", False), ("default", None)])
def test_cli_can_override_configured_thinking(tmp_path, monkeypatch, flag, expected):
    path = project(tmp_path, models=["qwen3:8b"], ollama_think=True)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return NS(response=response(entry("scales")), done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"qwen3:8b"})
    assert cli.main(["--settings", str(path), "--ollama-think", flag]) == 0
    assert ("think" in calls[0]) == (expected is not None)
    assert calls[0].get("think") is expected
    assert load_settings(path).settings.ollama_think is True  # Override never edits the file.


def test_v2_metadata_and_dry_run_show_mode_without_changing_prompt(tmp_path, monkeypatch, capsys):
    path = write_project(tmp_path, models=["qwen3:8b"])
    original = path.read_bytes()
    assert cli.main(["--settings", str(path), "--ollama-think", "false", "--dry-run"]) == 0
    assert "disabled (think=false)" in capsys.readouterr().out
    assert not (tmp_path / "extractor_outputs").exists()
    monkeypatch.setattr(cli, "create_client", lambda context: FakeClient(response=make_response()))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"qwen3:8b"})
    assert cli.main(["--settings", str(path), "--ollama-think", "false"]) == 0
    text = (tmp_path / "extractor_outputs" / "0_qwen3-8b.md").read_text()
    assert "ollama_thinking_request: disabled (think=false)" in text
    assert "hello world" in text and path.read_bytes() == original


@pytest.mark.parametrize("invalid", ["false", 0, 1, "low"])
def test_thinking_configuration_requires_bool_or_null(tmp_path, invalid):
    path = write_project(tmp_path, ollama_think=invalid)
    with pytest.raises(SettingsError, match="ollama_think"):
        load_settings(path)


def test_unconfigured_settings_retain_default(tmp_path):
    path = write_project(tmp_path)
    assert "ollama_think" not in json.loads(path.read_text())
    assert load_settings(path).settings.ollama_think is None
