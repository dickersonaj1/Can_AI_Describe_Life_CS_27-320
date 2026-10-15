"""Cloud extraction cleanup regressions; mocked SDK responses, no network calls."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from test_cli import write_project

from feature_dictionary import cli
from feature_dictionary.context import RunContext
from feature_dictionary.runners import anthropic_runner, cloud_runner, gemini_runner
from feature_dictionary.settings import load_settings


def fake(provider, reason=None, text="retained raw answer"):
    usage = NS(input_tokens=10, output_tokens=5, prompt_token_count=10, candidates_token_count=5)
    if provider == "openai":
        response = NS(
            status=reason or "completed",
            output_text=text,
            usage=usage,
            output=[],
            incomplete_details=NS(reason="max_output_tokens") if reason == "incomplete" else None,
        )
    elif provider == "anthropic":
        response = NS(
            stop_reason=reason or "end_turn", content=[NS(type="text", text=text)], usage=usage
        )
    else:
        response = NS(
            text=text,
            usage_metadata=usage,
            candidates=[NS(finish_reason=reason or "STOP")],
            prompt_feedback=None,
        )
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return response

    client = NS(
        responses=NS(create=create),
        messages=NS(create=create),
        models=NS(generate_content=create),
        close=lambda: None,
    )
    return client, calls, response


RUNNERS = {"openai": cloud_runner, "anthropic": anthropic_runner, "gemini": gemini_runner}


@pytest.mark.parametrize(
    "provider,field",
    [("openai", "max_output_tokens"), ("anthropic", "max_tokens"), ("gemini", "max_output_tokens")],
)
def test_configured_output_limit_uses_provider_parameter(provider, field):
    client, calls, _ = fake(provider)
    result = RUNNERS[provider].run_model(
        client, model="fake", prompt="same instructions", max_output_tokens=8765
    )
    kwargs = calls[0]["config"] if provider == "gemini" else calls[0]
    assert kwargs[field] == 8765
    assert result.completion_status == "success"
    assert result.response_text == "retained raw answer"


@pytest.mark.parametrize("provider", list(RUNNERS))
def test_unset_limits_use_provider_defaults(provider):
    client, calls, _ = fake(provider)
    RUNNERS[provider].run_model(client, model="fake", prompt="same instructions")
    if provider == "anthropic":
        assert calls[0]["max_tokens"] == 4096
    elif provider == "openai":
        assert "max_output_tokens" not in calls[0]
    else:
        assert "config" not in calls[0]


@pytest.mark.parametrize(
    "provider,reason,status",
    [
        ("openai", "completed", "success"),
        ("openai", "incomplete", "incomplete"),
        ("openai", "failed", "failed"),
        ("openai", "cancelled", "cancelled"),
        ("anthropic", "end_turn", "success"),
        ("anthropic", "stop_sequence", "success"),
        ("anthropic", "max_tokens", "incomplete"),
        ("anthropic", "model_context_window_exceeded", "incomplete"),
        ("anthropic", "pause_turn", "incomplete"),
        ("anthropic", "tool_use", "incomplete"),
        ("anthropic", "refusal", "blocked"),
        ("gemini", "STOP", "success"),
        ("gemini", "MAX_TOKENS", "incomplete"),
        ("gemini", "SAFETY", "blocked"),
        ("gemini", "OTHER", "unknown"),
    ],
)
def test_completion_reasons_and_partial_text_preserved(provider, reason, status):
    client, _, _ = fake(provider, reason)
    result = RUNNERS[provider].run_model(client, model="fake", prompt="same instructions")
    assert result.completion_status == status
    assert reason in result.metrics.done_reason
    assert result.response_text == "retained raw answer"


@pytest.mark.parametrize("provider", list(RUNNERS))
def test_empty_completed_response_is_not_success(provider):
    client, _, _ = fake(provider, text="")
    assert (
        RUNNERS[provider].run_model(client, model="fake", prompt="instructions").completion_status
        == "empty"
    )


def test_openai_refusal_and_missing_usage():
    client, _, response = fake("openai")
    response.output = [NS(content=[NS(type="refusal")])]
    response.usage = None
    result = cloud_runner.run_model(client, model="fake", prompt="instructions")
    assert result.completion_status == "blocked"
    assert result.metrics.done_reason == "completed:refusal"
    assert result.metrics.total_tokens is None


def test_gemini_blocked_prompt_without_candidates():
    client, _, response = fake("gemini", text="")
    response.candidates = []
    response.prompt_feedback = NS(block_reason="SAFETY")
    result = gemini_runner.run_model(client, model="fake", prompt="instructions")
    assert result.completion_status == "blocked"
    assert result.metrics.done_reason == "SAFETY"


@pytest.mark.parametrize(
    "provider,reason",
    [("openai", "incomplete"), ("anthropic", "max_tokens"), ("gemini", "MAX_TOKENS")],
)
def test_cli_records_incomplete_status_returns_failure_and_passes_limit(
    tmp_path, monkeypatch, provider, reason
):
    path = write_project(
        tmp_path, models=[dict(provider=provider, model="fake")], max_output_tokens=4321
    )
    client, calls, _ = fake(provider, reason)
    monkeypatch.setattr(cli, "OpenAI", lambda **kw: client)
    monkeypatch.setattr(cli, "Anthropic", lambda **kw: client)
    monkeypatch.setattr(cli.genai, "Client", lambda **kw: client)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    assert len(calls) == 1
    request = calls[0]
    assert (request.get("config") or request).get(
        "max_tokens" if provider == "anthropic" else "max_output_tokens"
    ) == 4321
    output = next((tmp_path / "extractor_outputs").glob("*.md")).read_text()
    assert "status: incomplete" in output and "retained raw answer" in output
    assert reason in output
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    assert "incomplete" in summary
    log = next(
        p for p in (tmp_path / "extractor_logs").glob("*.md") if not p.name.startswith("summary")
    )
    assert "| Status | incomplete |" in log.read_text()
    assert reason in log.read_text()


@pytest.mark.parametrize("provider", list(RUNNERS))
def test_cloud_only_ignores_ollama_context_guard(tmp_path, monkeypatch, provider):
    path = write_project(
        tmp_path,
        models=[dict(provider=provider, model="fake")],
        options={"num_ctx": 1},
        fail_on_context_overrun=True,
    )
    client, calls, _ = fake(provider)
    monkeypatch.setattr(cli, "OpenAI", lambda **kw: client)
    monkeypatch.setattr(cli, "Anthropic", lambda **kw: client)
    monkeypatch.setattr(cli.genai, "Client", lambda **kw: client)
    monkeypatch.setattr(
        cli, "create_client", lambda *_: pytest.fail("Cloud run must not create Ollama client")
    )
    assert cli.main(["--settings", str(path)]) == cli.EXIT_SUCCESS
    assert len(calls) == 1


def test_mixed_run_keeps_ollama_context_guard(tmp_path, monkeypatch):
    path = write_project(
        tmp_path,
        models=[dict(provider="openai", model="fake"), "local-model"],
        options={"num_ctx": 1},
        fail_on_context_overrun=True,
    )
    monkeypatch.setattr(cli, "OpenAI", lambda: pytest.fail("Guard must run before clients"))
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR


def test_prompt_override_metadata_version_and_fingerprints(tmp_path, monkeypatch, capsys):
    path = write_project(tmp_path, models=[dict(provider="openai", model="fake")])
    prompt = tmp_path / "extraction_v2.txt"
    prompt.write_text("Extract terms: {species_database}")
    client, calls, _ = fake("openai")
    monkeypatch.setattr(cli, "OpenAI", lambda **kw: client)
    args = ["--settings", str(path), "--prompt-file", str(prompt)]
    assert cli.main(args) == cli.EXIT_SUCCESS
    context = RunContext.from_settings(
        load_settings(path, overrides={"prompt_file": str(prompt), "prompt": None}),
        (tmp_path / "species_database.txt").read_text(),
    )
    assert context.prompt_version == "v2"
    assert calls[0]["input"] == context.prompt_text
    output = next((tmp_path / "extractor_outputs").glob("*.md")).read_text()
    for value in (
        str(prompt),
        "prompt_version: v2",
        context.prompt_fingerprint,
        context.prompt_template_sha256,
    ):
        assert value in output
    for log in (tmp_path / "extractor_logs").glob("*.md"):
        assert str(prompt) in log.read_text()
        assert context.prompt_fingerprint in log.read_text()
        assert "v2" in log.read_text()
    assert str(prompt) in capsys.readouterr().out
    changed = RunContext.from_settings(context.settings, "different input")
    assert changed.prompt_template_sha256 == context.prompt_template_sha256
    assert changed.prompt_fingerprint != context.prompt_fingerprint


def test_inline_prompt_identity_and_cloud_dry_run(tmp_path, capsys):
    path = write_project(
        tmp_path, models=[dict(provider="openai", model="fake")], options={"num_ctx": 1}
    )
    context = RunContext.from_settings(load_settings(path), "example")
    assert context.prompt_path == "inline"
    assert context.prompt_version.startswith("unversioned@")
    assert cli.main(["--settings", str(path), "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "not applicable to cloud-only run" in output
    assert "WARNING" not in output
    assert not (tmp_path / "extractor_outputs").exists()
