"""Cross-provider integration regressions with no server, credentials, or network."""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

import pytest
from test_cli import FakeOllama, write_project
from test_cloud_extraction import fake

from feature_dictionary import cli
from feature_dictionary.synthesis_core.ingest import read_outputs

LOCAL_MODELS = ["qwen3:8b", "deepseek-r1:8b", "llama3.1:8b"]
SELECTION = ",".join([*LOCAL_MODELS, "gpt", "claude", "gemini"])
ANSWER = "## Primary terms\n\n* **scales** - synonyms: - homonyms:\n\n## Homonyms\n\nNone found\n"


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Integration tests must not construct a real provider client")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


def install_cloud(monkeypatch, provider, client):
    construction, closed = [], []

    def factory(**kwargs):
        construction.append(kwargs)
        return client

    client.close = lambda: closed.append(True)
    if provider == "gemini":
        monkeypatch.setattr(cli.genai, "Client", factory)
    else:
        monkeypatch.setattr(cli, "OpenAI" if provider == "openai" else "Anthropic", factory)
    return construction, closed


@pytest.mark.parametrize("concurrency", [1, 3])
def test_six_models_share_prompt_outputs_and_synthesis_ingestion(
    tmp_path, monkeypatch, concurrency
):
    path = write_project(
        tmp_path,
        max_concurrency=concurrency,
        max_output_tokens=777,
        request_timeout_seconds=12.5,
    )
    local_requests = []

    def generate(**kwargs):
        local_requests.append(kwargs)
        return NS(response=ANSWER, done=True, done_reason="stop")

    local = NS(generate=generate)
    monkeypatch.setattr(cli, "create_client", lambda context: local)
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    clouds = {}
    for provider in ("openai", "anthropic", "gemini"):
        client, calls, _ = fake(provider, text=ANSWER)
        construction, closed = install_cloud(monkeypatch, provider, client)
        clouds[provider] = calls, construction, closed
    assert cli.main(["--settings", str(path), "--models", SELECTION]) == cli.EXIT_SUCCESS
    assert {call["model"] for call in local_requests} == set(LOCAL_MODELS)
    prompts = {call["prompt"] for call in local_requests}
    for call in local_requests:
        assert call["options"]["num_predict"] == 777
    for provider, (calls, construction, closed) in clouds.items():
        assert len(calls) == 1
        prompts.add(
            calls[0].get("input") or calls[0].get("contents") or calls[0]["messages"][0]["content"]
        )
        assert closed == [True]
        assert construction == (
            [{"http_options": {"timeout": 12500}}] if provider == "gemini" else [{"timeout": 12.5}]
        )
    assert len(prompts) == 1
    outputs = list((tmp_path / "extractor_outputs").glob("*.md"))
    assert len(outputs) == 6 and len({p.name for p in outputs}) == 6
    expected = cli._parse_models(SELECTION)
    run_ids, fingerprints = set(), set()
    for index, model in enumerate(expected):
        output = next(p for p in outputs if p.name.startswith(f"{index}_"))
        text = output.read_text()
        assert f"model: {model['model']}" in text
        assert f"provider: {model['provider']}" in text
        assert "status: success" in text
        run_ids.add(next(line for line in text.splitlines() if line.startswith("run_id:")))
        fingerprints.add(
            next(line for line in text.splitlines() if line.startswith("prompt_fingerprint:"))
        )
    assert len(run_ids) == len(fingerprints) == 1
    bundle = read_outputs(tmp_path / "extractor_outputs")
    assert len(bundle.sources) == 6
    assert len([o for o in bundle.observations if o.category == "term_entry"]) == 6
    assert not bundle.issues
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    for model in expected:
        assert f"`{model['model']}` | success" in summary


def test_identical_model_labels_remain_distinct_by_index_and_provider(tmp_path, monkeypatch):
    path = write_project(tmp_path, index_base=10)
    local = NS(generate=lambda **kw: NS(response=ANSWER, done_reason="stop"))
    monkeypatch.setattr(cli, "create_client", lambda context: local)
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"same"})
    client, _, _ = fake("openai", text=ANSWER)
    install_cloud(monkeypatch, "openai", client)
    assert cli.main(["--settings", str(path), "--models", "ollama=same,openai=same"]) == 0
    for index, provider in [(10, "ollama"), (11, "openai")]:
        text = (tmp_path / "extractor_outputs" / f"{index}_same.md").read_text()
        assert f"provider: {provider}" in text
        log = next((tmp_path / "extractor_logs").glob(f"{index}_same_*.md")).read_text()
        assert f"| Provider | {provider} |" in log
        assert ("| num_ctx | n/a (Ollama only) |" in log) == (provider == "openai")


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
@pytest.mark.parametrize("fail_at", ["constructor", "request"])
def test_cloud_failure_is_logged_and_other_providers_continue(
    tmp_path,
    monkeypatch,
    provider,
    fail_at,
):
    path = write_project(
        tmp_path, models=[cli.MODEL_ALIASES[k] for k in ["gpt", "claude", "gemini"]]
    )
    clients = {}
    for name in ["openai", "anthropic", "gemini"]:
        client, calls, _ = fake(name)
        construction, closed = install_cloud(monkeypatch, name, client)
        clients[name] = calls, closed
        if name == provider:

            def fail(**kwargs):
                raise RuntimeError("simulated provider failure")

            if fail_at == "request":
                client.responses.create = fail
                client.messages.create = fail
                client.models.generate_content = fail
            elif name == "gemini":
                monkeypatch.setattr(cli.genai, "Client", fail)
            else:
                monkeypatch.setattr(cli, "OpenAI" if name == "openai" else "Anthropic", fail)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    for name, (calls, closed) in clients.items():
        assert len(calls) == (0 if name == provider else 1)
        assert closed == ([] if name == provider and fail_at == "constructor" else [True])
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    assert "| failed |" in summary and summary.count("| success |") == 2
    logs = "\n".join(p.read_text() for p in (tmp_path / "extractor_logs").glob("*.md"))
    assert "RuntimeError: simulated provider failure" in logs


def test_cloud_interrupt_keeps_prior_result_skips_remaining_and_closes_client(
    tmp_path, monkeypatch
):
    path = write_project(tmp_path)
    client, calls, _ = fake("openai", text=ANSWER)
    create = client.responses.create

    def interrupt_second(**kwargs):
        if calls:
            raise KeyboardInterrupt
        return create(**kwargs)

    client.responses.create = interrupt_second
    _, closed = install_cloud(monkeypatch, "openai", client)
    assert (
        cli.main(["--settings", str(path), "--models", "openai=first,openai=second,claude,gemini"])
        == cli.EXIT_INTERRUPTED
    )
    assert closed == [True]
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    assert "`first` | success" in summary
    assert "`second` | interrupted" in summary
    assert summary.count("| skipped |") == 2
    assert "Run ended: interrupted by the user" in summary


def test_local_interrupt_after_success_retains_result_and_never_starts_cloud(tmp_path, monkeypatch):
    path = write_project(tmp_path, stream=True)
    local = FakeOllama(interrupt_on="llama3.1:8b")
    monkeypatch.setattr(cli, "create_client", lambda context: local)
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    assert (
        cli.main(["--settings", str(path), "--models", "qwen3:8b,llama3.1:8b,gpt"])
        == cli.EXIT_INTERRUPTED
    )
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    assert "`qwen3:8b` | success" in summary
    assert "`llama3.1:8b` | interrupted" in summary
    assert "`gpt-5.4-nano` | skipped" in summary


def test_ollama_override_does_not_change_cloud_cap(tmp_path, monkeypatch):
    path = write_project(
        tmp_path, max_output_tokens=4321, options={"num_predict": 900, "num_ctx": 8192}
    )
    local_requests: list[dict[str, Any]] = []

    def generate(**kwargs):
        local_requests.append(kwargs)
        return NS(response=ANSWER, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"qwen3:8b"})
    client, calls, _ = fake("openai")
    install_cloud(monkeypatch, "openai", client)
    assert cli.main(["--settings", str(path), "--models", "qwen3:8b,gpt"]) == 0
    assert local_requests[0]["options"]["num_predict"] == 900
    assert calls[0]["max_output_tokens"] == 4321
    assert (
        "output_token_limit: 900" in (tmp_path / "extractor_outputs" / "0_qwen3-8b.md").read_text()
    )
    assert (
        "output_token_limit: 4321"
        in (tmp_path / "extractor_outputs" / "1_gpt-5.4-nano.md").read_text()
    )


def test_concurrent_interrupt_waits_for_active_local_writes(tmp_path, monkeypatch):
    from threading import Barrier

    path = write_project(tmp_path, stream=True, max_concurrency=2)
    both_running = Barrier(2)

    def chunks(model):
        yield NS(response=ANSWER, thinking=None)
        both_running.wait(timeout=5)
        if model == "llama3.1:8b":
            raise KeyboardInterrupt
        yield NS(response="", done=True, done_reason="stop")

    client = NS(generate=lambda **kwargs: chunks(kwargs["model"]))
    monkeypatch.setattr(cli, "create_client", lambda context: client)
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    assert (
        cli.main(["--settings", str(path), "--models", "qwen3:8b,llama3.1:8b,gpt"])
        == cli.EXIT_INTERRUPTED
    )
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    assert "`qwen3:8b` | success" in summary
    assert "`llama3.1:8b` | interrupted" in summary
    assert "`gpt-5.4-nano` | skipped" in summary
