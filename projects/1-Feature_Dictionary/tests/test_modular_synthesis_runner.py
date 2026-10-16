"""Independent model proposals use frozen fixtures and mocked existing adapters."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_cli import write_project
from test_cloud_extraction import fake

from feature_dictionary import modular_synthesis as cli
from feature_dictionary.extraction_v3 import parse_strict_json
from feature_dictionary.settings import load_settings
from feature_dictionary.synthesis_core import inventory_execution as execution
from feature_dictionary.synthesis_core.inventory_ingest import read_inputs
from feature_dictionary.synthesis_core.inventory_schema import Inventory, InventoryReview
from feature_dictionary.synthesis_core.inventory_validation import (
    artifact_sha256,
    validate_inventory,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/synthesis_v1"


@pytest.fixture(autouse=True)
def no_real_clients(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Modular synthesis tests must never contact a provider")

    monkeypatch.setattr(execution, "create_provider_client", fail)


def setup(tmp_path, models="gpt"):
    path = write_project(tmp_path, options={"num_ctx": 32768}, max_output_tokens=8192)
    loaded = load_settings(path, overrides={"models": models})
    inputs = read_inputs(FIXTURES / "inputs.json")
    plan = execution.prepare(inputs, loaded)
    requests = [
        execution.make_request(plan, model, i) for i, model in enumerate(loaded.settings.models)
    ]
    return path, inputs, requests


def answer(request):
    proposal = parse_strict_json((FIXTURES / "proposal.json").read_text())
    proposal.update(request["identity"])
    return json.dumps(proposal)


def fake_client(provider, request, *, text=None, reason=None):
    text = answer(request) if text is None else text
    if provider == "ollama":
        outcome = NS(
            response=text,
            thinking="original reasoning",
            done=True,
            done_reason=reason or "stop",
            eval_count=12,
            prompt_eval_count=20,
        )
        outcome.model_dump = lambda **kwargs: {
            "response": text,
            "thinking": "original reasoning",
            "done_reason": outcome.done_reason,
        }
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            return outcome

        client = NS(
            generate=generate,
            list=lambda: NS(models=[NS(model=request["identity"]["model"], digest="test-digest")]),
            _request_raw=lambda *args, **kwargs: NS(json=lambda: {"version": "test-server"}),
        )
    else:
        client, calls, outcome = fake(provider, text=text, reason=reason)
        outcome.model_dump = lambda **kwargs: {"provider": provider, "original_text": text}
    closed = []
    client.close = lambda: closed.append(True)
    return client, calls, closed


@pytest.mark.parametrize(
    "models",
    [
        "qwen3:8b",
        "gpt",
        "claude",
        "gemini",
        "qwen3:8b,deepseek-r1:8b,llama3.1:8b,gpt,claude,gemini",
    ],
)
def test_independent_provider_jobs_archive_and_replay(tmp_path, monkeypatch, models):
    _, inputs, requests = setup(tmp_path, models)
    clients = {}
    for request in requests:
        identity = request["identity"]
        clients[(identity["provider"], identity["model"])] = fake_client(
            identity["provider"], request
        )

    def create(provider, request):
        return clients[(provider, request["identity"]["model"])][0]

    monkeypatch.setattr(execution, "create_provider_client", create)
    run = tmp_path / "run"
    result = execution.execute_run(run, inputs, requests, {})
    assert all(r["proposal_valid"] for r in result)
    assert len({r["prompt"] for r in requests}) == 1
    assert len({r["input_sha256"] for r in requests}) == 1
    for i, request in enumerate(requests):
        identity = request["identity"]
        job = run / f"job_{i:03d}"
        assert execution.replay_job(job)["proposal_valid"]
        validation = json.loads((job / "validation.json").read_text())
        assert not validation["scientifically_verified"]
        client, calls, closed = clients[(identity["provider"], identity["model"])]
        assert len(calls) == 1 and closed == [True]
        assert (
            calls[0].get(
                "prompt", calls[0].get("input", calls[0].get("contents", request["prompt"]))
            )
            == request["prompt"]
        )
        assert (job / "provider_response_0.json").exists()
        assert json.loads((job / "response.json").read_text())["metrics"] is not None
        if identity["provider"] == "ollama":
            assert calls[0]["format"] == request["output_schema"]
        elif identity["provider"] == "openai":
            assert calls[0]["text"]["format"]["strict"] is True
            assert calls[0]["text"]["format"]["schema"] == request["output_schema"]
        elif identity["provider"] == "anthropic":
            assert calls[0]["output_config"]["format"]["schema"] == request["output_schema"]
        else:
            assert calls[0]["config"]["response_json_schema"] == request["output_schema"]
    assert not list(run.rglob("inventory.json"))
    before = (run / "inputs.json").read_bytes()
    with pytest.raises(FileExistsError):
        execution.execute_run(run, inputs, requests, {})
    assert (run / "inputs.json").read_bytes() == before


@pytest.mark.parametrize(
    "provider,reason,status",
    [
        ("openai", "incomplete", "incomplete"),
        ("anthropic", "max_tokens", "incomplete"),
        ("gemini", "MAX_TOKENS", "incomplete"),
        ("ollama", "length", "incomplete"),
        ("anthropic", "refusal", "blocked"),
    ],
)
def test_incomplete_or_blocked_proposals_remain_archived(
    tmp_path, monkeypatch, provider, reason, status
):
    model = {"ollama": "qwen3:8b", "openai": "gpt", "anthropic": "claude", "gemini": "gemini"}[
        provider
    ]
    _, inputs, requests = setup(tmp_path, model)
    client, calls, _ = fake_client(provider, requests[0], reason=reason)
    monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
    result = execution.execute_run(tmp_path / "run", inputs, requests, {})
    assert result[0]["completion_status"] == status and not result[0]["proposal_valid"]
    report = execution.replay_job(tmp_path / "run/job_000")
    assert report["schema_valid"] and not report["proposal_valid"]
    assert not (tmp_path / "run/job_000/proposal.json").exists() and len(calls) == 1


@pytest.mark.parametrize(
    "failure,code",
    [
        ("fenced", "INVALID_JSON"),
        ("shape", "CONTRACT_ERROR"),
        ("reference", "DISPOSITION_MISMATCH"),
        ("binding", "HOST_BINDING"),
    ],
)
def test_json_contract_and_reference_checks_are_separate(tmp_path, monkeypatch, failure, code):
    _, inputs, requests = setup(tmp_path)
    data = json.loads(answer(requests[0]))
    if failure == "reference":
        data["observation_dispositions"][0]["record_refs"] = ["model_tail"]
    if failure == "binding":
        data["model"] = "another-model"
    if failure == "shape":
        data["definitions"] = []
    text = json.dumps(data)
    if failure == "fenced":
        text = "```json\n" + text + "\n```"
    client, _, _ = fake_client("openai", requests[0], text=text)
    monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
    execution.execute_run(tmp_path / "run", inputs, requests, {})
    report = execution.replay_job(tmp_path / "run/job_000")
    assert code in {i["code"] for i in report["issues"]}
    assert not report["proposal_valid"]
    assert json.loads((tmp_path / "run/job_000/response.json").read_text())["response_text"] == text


def test_api_error_or_interrupt_preserves_request_and_closes_client(tmp_path, monkeypatch):
    _, inputs, requests = setup(tmp_path)
    for i, error in enumerate([ValueError("unsupported schema"), KeyboardInterrupt()]):
        client, calls, closed = fake_client("openai", requests[0])

        def fail(**kwargs):
            raise error

        client.responses.create = fail
        monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
        run = tmp_path / f"run{i}"
        result = execution.execute_run(run, inputs, requests, {})
        assert not result[0]["proposal_valid"] and closed == [True]
        assert (run / "job_000/request.json").exists()
        response = json.loads((run / "job_000/response.json").read_text())
        assert response["error"]["type"] == type(error).__name__
        assert not response["response_available"]


def test_cli_dry_run_and_unknown_selection_are_request_free(tmp_path):
    path, _, _ = setup(tmp_path)
    assert (
        cli.main(
            [
                "--settings",
                str(path),
                "--inputs",
                str(FIXTURES / "inputs.json"),
                "--models",
                "qwen3:8b,gpt,claude,gemini",
                "--run-dir",
                str(tmp_path / "dry"),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not (tmp_path / "dry").exists()
    assert (
        cli.main(
            [
                "--settings",
                str(path),
                "--inputs",
                str(FIXTURES / "inputs.json"),
                "--models",
                "unknown",
                "--run-dir",
                str(tmp_path / "dry"),
                "--dry-run",
            ]
        )
        == 2
    )


def test_local_context_check_and_input_tampering_fail_before_clients(tmp_path):
    path, inputs, _ = setup(tmp_path)
    loaded = load_settings(path, overrides={"models": "qwen3:8b"})
    plan = execution.prepare(inputs, loaded)
    plan["ollama_options"]["num_ctx"] = 128
    with pytest.raises(ValueError, match="context budget"):
        execution.make_request(plan, loaded.settings.models[0], 0)
    altered = inputs.model_dump(mode="json")
    altered["observations"].pop()
    target = tmp_path / "invalid.json"
    target.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="OBSERVATION_COVERAGE"):
        read_inputs(target)


def test_standalone_descriptor_is_allowed_and_evidence_is_not_duplicated():
    inputs = read_inputs(FIXTURES / "inputs.json")
    inventory = Inventory.model_validate_json((FIXTURES / "inventory.json").read_text())
    review = InventoryReview.model_validate_json((FIXTURES / "review.json").read_text())
    compound = inventory.compound_terms[0].model_copy(update={"subterm_ids": ()})
    inventory = inventory.model_copy(
        update={"compound_terms": (compound, inventory.compound_terms[1])}
    )
    review = review.model_copy(update={"inventory_sha256": artifact_sha256(inventory)})
    assert not [i for i in validate_inventory(inventory, inputs, review) if i.severity == "error"]
    assert len(inputs.observations) == 8


def write_extraction_fixture(tmp_path):
    inputs = read_inputs(FIXTURES / "inputs.json")
    snapshot = inputs.sources[0]
    document = snapshot.document.model_dump(mode="json")
    (tmp_path / "fixture.input.bin").write_bytes(snapshot.document.input.supplied_text.encode())
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(document))
    raw = dict(
        input=document["input"],
        run=document["run"],
        response_available=True,
        response_text=snapshot.raw_response,
    )
    report = dict(
        input=document["input"],
        run=document["run"],
        accepted=True,
        evidence_valid=True,
        raw_response=snapshot.raw_response,
        entries=document["entries"],
    )
    path.with_suffix(".raw.json").write_text(json.dumps(raw))
    path.with_suffix(".validation.json").write_text(json.dumps(report))
    return path


def test_ingestion_preserves_evidence_metadata_and_exact_archive_bytes(tmp_path):
    import base64

    from feature_dictionary.synthesis_core.inventory_ingest import freeze_extractions

    path = write_extraction_fixture(tmp_path)
    inputs, archives = freeze_extractions([path])
    fixture = read_inputs(FIXTURES / "inputs.json")
    assert inputs.sources[0].document == fixture.sources[0].document
    assert inputs.sources[0].raw_response == fixture.sources[0].raw_response
    assert len(inputs.observations) == 8 and len(archives) == 4
    assert path.read_bytes() in [base64.b64decode(value) for value in archives.values()]
    again, _ = freeze_extractions([path])
    assert again == inputs
    with pytest.raises(ValueError, match="Duplicate extraction"):
        freeze_extractions([path, path])


@pytest.mark.parametrize("edit", ["rejected", "metadata", "raw", "bytes", "entries", "positions"])
def test_ingestion_rejects_invalid_extractions_before_clients(tmp_path, edit):
    from feature_dictionary.synthesis_core.inventory_ingest import freeze_extractions

    path = write_extraction_fixture(tmp_path)
    if edit == "bytes":
        (tmp_path / "fixture.input.bin").write_text("changed source")
    else:
        target = path.with_suffix(".validation.json")
        data = json.loads(target.read_text())
        if edit == "rejected":
            data["accepted"] = False
        if edit == "metadata":
            data["run"]["model"] = "another-model"
        if edit == "raw":
            data["raw_response"] = "changed response"
        if edit == "entries":
            data["entries"] = []
        if edit == "positions":
            target = path
            data = json.loads(path.read_text())
            data["entries"][0]["location"]["candidates"][0]["match_span"]["start"] = 999
        target.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        freeze_extractions([path])


def test_missing_credentials_are_names_only_and_no_jobs_are_created(tmp_path, monkeypatch, capsys):
    path, _, _ = setup(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    assert (
        cli.main(
            [
                "--settings",
                str(path),
                "--inputs",
                str(FIXTURES / "inputs.json"),
                "--models",
                "gpt",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 2
    )
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def test_callback_archives_before_strict_json_validation(tmp_path, monkeypatch):
    _, inputs, requests = setup(tmp_path)
    client, _, _ = fake_client("openai", requests[0], text="```json\n{}\n```")
    monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
    original = execution.evaluate

    def evaluate(request, response, inputs):
        assert (tmp_path / "run/job_000/provider_response_0.json").exists()
        assert (tmp_path / "run/job_000/response.json").exists()
        return original(request, response, inputs)

    monkeypatch.setattr(execution, "evaluate", evaluate)
    execution.execute_run(tmp_path / "run", inputs, requests, {})


def test_request_input_mutation_is_rejected_without_archives_or_clients(tmp_path):
    _, inputs, requests = setup(tmp_path)
    requests[0]["input_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="bound"):
        execution.execute_run(tmp_path / "run", inputs, requests, {})
    assert not (tmp_path / "run").exists()
