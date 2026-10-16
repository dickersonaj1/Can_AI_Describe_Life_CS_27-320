"""Native constraints preserve strict evidence checking; all execution is mocked."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import ollama
import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import LOCAL_MODELS, SELECTION, install_cloud
from test_extraction_prompt_v311 import examples
from test_extraction_v3_pipeline import artifacts
from test_extraction_v31 import response
from test_runner import FakeClient, make_response

from feature_dictionary import cli, runner
from feature_dictionary.context import RunContext
from feature_dictionary.extraction_replay import replay_archive
from feature_dictionary.extraction_v3 import CandidateResponseV31, validate_response
from feature_dictionary.settings import SettingsError, load_settings

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts/extraction_v3_1_3.txt"
SCHEMA = CandidateResponseV31.model_json_schema()
ANSWER = response(("scales", "dorsal scales"), ("préoculaire", "préoculaire"))
SOURCE = "dorsal scales; préoculaire; scales"


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Structured-output tests must not contact a provider")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


def project(tmp_path, **overrides):
    settings = dict(
        extraction_format="v3",
        v3_candidate_version="3.1",
        ollama_output_format="candidate_schema",
        v3_prompt_file=str(PROMPT),
        models=["qwen3:8b"],
        options={"num_ctx": 8192},
    )
    settings.update(overrides)
    path = write_project(tmp_path, **settings)
    (tmp_path / "species_database.txt").write_text(SOURCE)
    return path


def install_local(monkeypatch, client):
    client.models = tuple(LOCAL_MODELS)
    client._request_raw = lambda *args, **kwargs: NS(json=lambda: {"version": "test-server"})
    monkeypatch.setattr(cli, "create_client", lambda context: client)


@pytest.mark.parametrize("think", [None, False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_runner_schema_and_thinking_preserve_response_metrics(think, stream):
    final = make_response(response=ANSWER, thinking="original reasoning", done=True)
    client = FakeClient(response=final, chunks=[final])
    result = runner.run_model(
        client, model="qwen3:8b", prompt="p", output_schema=SCHEMA, think=think, stream=stream
    )
    call = client.calls[0]
    assert call["format"] == SCHEMA and "format" not in (call["options"] or {})
    assert ("think" in call) == (think is not None)
    assert call.get("think") is think
    assert result.response_text == ANSWER and result.thinking_text == "original reasoning"
    assert result.metrics.eval_count == 5 and result.metrics.total_tokens == 15
    assert result.completion_status == "success"


def test_installed_sdk_serializes_schema_without_network(monkeypatch):
    client = ollama.Client()
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs["json"])
        return make_response()

    monkeypatch.setattr(client, "_request", request)
    try:
        runner.run_model(client, model="qwen3:8b", prompt="p", output_schema=SCHEMA, think=False)
    finally:
        client._client.close()
    assert calls[0]["format"] == SCHEMA and calls[0]["think"] is False


def test_runtime_metadata_uses_installed_sdk_with_mock_http_transport():
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.3"})
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"model": "qwen3:8b", "digest": "sha256:test", "details": {"family": "qwen3"}}
                ]
            },
        )

    runtime = {}
    with ollama.Client(transport=httpx.MockTransport(handle)) as client:
        assert runner.list_installed_models(client, runtime_metadata=runtime) == {"qwen3:8b"}
    assert paths == ["/api/tags", "/api/version"]
    assert runtime["server_version"] == "0.40.3"
    assert runtime["models"]["qwen3:8b"]["digest"] == "sha256:test"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("think", [None, False, True])
def test_pipeline_archives_constraint_and_replays_offline(tmp_path, monkeypatch, stream, think):
    path = project(tmp_path, stream=stream, ollama_think=think)
    final = make_response(response=ANSWER, thinking="unaltered reasoning", done=True)
    client = FakeClient(response=final, chunks=[final])
    install_local(monkeypatch, client)
    client.list = lambda: NS(
        models=[
            NS(
                model="qwen3:8b",
                digest="sha256:test-model",
                modified_at="test-date",
                details=NS(
                    model_dump=lambda **kwargs: {
                        "family": "qwen3",
                        "parameter_size": "8B",
                        "quantization_level": "Q4_K_M",
                    }
                ),
            )
        ]
    )
    assert cli.main(["--settings", str(path)]) == 0
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert raw["response_text"] == ANSWER and raw["thinking_text"] == "unaltered reasoning"
    assert report["accepted"] and output.exists()
    constraint = raw["ollama_output_constraint"]
    assert constraint == report["ollama_output_constraint"]
    assert constraint["schema"] == SCHEMA
    assert constraint["schema_identity"] == "extraction-3.1/candidate"
    assert (
        constraint["schema_sha256"]
        == hashlib.sha256(
            json.dumps(SCHEMA, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    runtime = raw["ollama_runtime"]
    assert runtime["server_version"] == "test-server" and runtime["client_version"]
    assert runtime["model"]["digest"] == "sha256:test-model"
    assert runtime["model"]["details"]["family"] == "qwen3"
    assert len(client.calls) == 1 and client.calls[0]["format"] == SCHEMA
    assert replay_archive(output.with_suffix(".raw.json"))["accepted"]
    logs = "\n".join(p.read_text() for p in (tmp_path / "extractor_logs").glob("*.md"))
    assert constraint["schema_sha256"] in logs and "test-server" in logs


@pytest.mark.parametrize(
    "text,code",
    [
        ("Here is JSON: " + ANSWER, "INVALID_JSON"),
        ("```json\n" + ANSWER + "\n```", "INVALID_JSON"),
        ("<think>reasoning</think>" + ANSWER, "INVALID_JSON"),
        (ANSWER[:-1], "INVALID_JSON"),
        (response(("DS", "DS")), "UNMATCHED_EVIDENCE"),
        (response(("Préoculaire", "Préoculaire")), "UNMATCHED_EVIDENCE"),
        (response(("preoculaire", "preoculaire")), "UNMATCHED_EVIDENCE"),
        ("", "INVALID_JSON"),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
def test_invalid_output_is_archived_without_repair_or_retry(
    tmp_path, monkeypatch, text, code, stream
):
    path = project(tmp_path, stream=stream)
    final = make_response(response=text, done=True)
    client = FakeClient(response=final, chunks=[final])
    install_local(monkeypatch, client)
    assert cli.main(["--settings", str(path)]) == 1
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert raw["response_text"] == text and not output.exists()
    assert code in {i["code"] for i in report["issues"]} and not report["accepted"]
    assert len(client.calls) == 1
    assert not replay_archive(output.with_suffix(".raw.json"))["accepted"]


@pytest.mark.parametrize("stream", [False, True])
def test_truncation_rejects_even_complete_json(tmp_path, monkeypatch, stream):
    path = project(tmp_path, stream=stream)
    final = make_response(response=ANSWER, done=True, done_reason="length", eval_count=4096)
    client = FakeClient(response=final, chunks=[final])
    install_local(monkeypatch, client)
    assert cli.main(["--settings", str(path)]) == 1
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert raw["run"]["completion_status"] == "incomplete"
    assert report["evidence_valid"] and not report["accepted"] and not output.exists()
    assert raw["response_text"] == ANSWER and len(client.calls) == 1
    assert not replay_archive(output.with_suffix(".raw.json"))["accepted"]


def test_ambiguous_quotations_keep_all_locations_and_collision_blocks_second_request(
    tmp_path, monkeypatch
):
    path = project(tmp_path)
    answer = response(("scales", "scales"))
    client = FakeClient(response=make_response(response=answer))
    install_local(monkeypatch, client)
    assert cli.main(["--settings", str(path)]) == 0
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    location = report["entries"][0]["location"]
    assert location["status"] == "ambiguous" and len(location["candidates"]) == 2
    assert report["accepted"] and raw["response_text"] == answer
    before = {p: p.read_bytes() for p in output.parent.rglob("*") if p.is_file()}
    assert cli.main(["--settings", str(path)]) == 2
    assert len(client.calls) == 1 and all(p.read_bytes() == text for p, text in before.items())


def test_interruption_preserves_partial_response_and_reasoning(tmp_path, monkeypatch):
    path = project(tmp_path, stream=True, ollama_think=True)
    partial = make_response(response=ANSWER[:20], thinking="partial reasoning", done=False)
    client = FakeClient(chunks=[partial], interrupt_after=1)
    install_local(monkeypatch, client)
    assert cli.main(["--settings", str(path)]) == 130
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert raw["response_text"] == ANSWER[:20] and raw["thinking_text"] == "partial reasoning"
    assert raw["run"]["completion_status"] == "interrupted" and not report["accepted"]
    assert not output.exists() and len(client.calls) == 1


def test_explicit_schema_rejection_is_not_retried(tmp_path, monkeypatch):
    path = project(tmp_path)
    client = FakeClient(generate_error=ollama.ResponseError("unsupported format", 400))
    install_local(monkeypatch, client)
    assert cli.main(["--settings", str(path)]) == 1
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert not raw["response_available"] and "unsupported format" in raw["error"]
    assert raw["ollama_output_constraint"]["schema"] == SCHEMA
    assert not report["accepted"] and not output.exists() and len(client.calls) == 1


def test_unavailable_version_metadata_does_not_block_or_guess(tmp_path, monkeypatch):
    path = project(tmp_path)
    client = FakeClient(response=make_response(response=ANSWER))
    install_local(monkeypatch, client)

    def unavailable(*args, **kwargs):
        raise ConnectionError("metadata unavailable")

    client._request_raw = unavailable
    assert cli.main(["--settings", str(path)]) == 0
    raw, _, _ = artifacts(tmp_path, model="qwen3-8b")
    assert raw["ollama_runtime"]["server_version"] is None
    assert raw["ollama_runtime"]["server_version_error"] == "ConnectionError"
    assert raw["ollama_runtime"]["model"]["digest"] is None
    assert len(client.calls) == 1


def test_mixed_six_model_run_only_constrains_ollama(tmp_path, monkeypatch):
    path = project(tmp_path)
    client = FakeClient(response=make_response(response=ANSWER))
    install_local(monkeypatch, client)
    cloud_calls = []
    for provider in ["openai", "anthropic", "gemini"]:
        cloud, calls, _ = fake(provider, text=ANSWER)
        install_cloud(monkeypatch, provider, cloud)
        cloud_calls.append(calls)
    assert cli.main(["--settings", str(path), "--models", SELECTION]) == 0
    assert len(client.calls) == 3 and all(c["format"] == SCHEMA for c in client.calls)
    for calls in cloud_calls:
        assert len(calls) == 1
        assert "format" not in calls[0] and "output_schema" not in calls[0]
    for index, model in enumerate(cli._parse_models(SELECTION)[3:], start=3):
        raw, _, _ = artifacts(tmp_path, index, cli.naming.slugify_model(model["model"]))
        assert "ollama_output_constraint" not in raw and "ollama_runtime" not in raw


def test_omitted_constraint_preserves_old_request_and_metadata(tmp_path, monkeypatch):
    path = project(tmp_path, ollama_output_format=None)
    client = FakeClient(response=make_response(response=ANSWER))
    install_local(monkeypatch, client)

    def unexpected(*args, **kwargs):
        pytest.fail("Historical run must not request server version")

    client._request_raw = unexpected
    assert cli.main(["--settings", str(path)]) == 0
    assert "format" not in client.calls[0]
    raw, _, _ = artifacts(tmp_path, model="qwen3-8b")
    assert "ollama_output_constraint" not in raw and "ollama_runtime" not in raw


@pytest.mark.parametrize("format,version", [("v2", "3.1"), ("v3", "3.0")])
def test_schema_constraint_requires_v31(tmp_path, format, version):
    path = project(tmp_path, extraction_format=format, v3_candidate_version=version)
    with pytest.raises(SettingsError, match="requires Extraction v3"):
        load_settings(path)


def test_cli_override_and_dry_run_make_no_metadata_calls(tmp_path, capsys):
    path = project(tmp_path, ollama_output_format=None)
    assert (
        cli.main(
            ["--settings", str(path), "--ollama-output-format", "candidate-schema", "--dry-run"]
        )
        == 0
    )
    assert "extraction-3.1/candidate" in capsys.readouterr().out
    assert not (tmp_path / "extractor_outputs").exists()
    assert load_settings(path).settings.ollama_output_format is None
    path = project(tmp_path)
    args = cli.build_parser().parse_args(["--ollama-output-format", "default"])
    assert (
        load_settings(path, overrides=cli._overrides_from_args(args)).settings.ollama_output_format
        is None
    )


def test_new_prompt_has_one_grounded_example_and_old_default_is_unchanged(tmp_path):
    text = PROMPT.read_text()
    cases = examples(text)
    assert len(cases) == 1
    source, candidate = cases[0]
    assert validate_response(json.dumps(candidate), source).evidence_valid
    assert {"dorsal", "scales", "dorsal scales", "DS", "keeled"} == {
        e["matched_text"] for e in candidate["entries"]
    }
    normalized = " ".join(text.split())
    for policy in [
        "NOT source evidence",
        "Never copy a demonstration term",
        "anatomical head",
        "multilingual terminology",
        "not a universal blacklist",
        "shortest meaningful terminology-bearing expression",
        '"is", "visible"',
    ]:
        assert policy in normalized
    assert "praeocular" not in text and "colouration" not in text
    path = project(tmp_path)
    loaded = load_settings(path)
    run = RunContext.from_settings(loaded, SOURCE)
    assert run.prompt_version == "v3_1_3"
    assert f"BEGIN ACTUAL SOURCE\n{SOURCE}\nEND ACTUAL SOURCE" in run.prompt_text
    defaults = project(tmp_path, v3_prompt_file=None)
    assert load_settings(defaults).prompt_path.name == "extraction_v3_1.txt"
    assert (
        json.loads((ROOT / "schemas/extraction_candidate_v3_1.schema.json").read_text()) == SCHEMA
    )
