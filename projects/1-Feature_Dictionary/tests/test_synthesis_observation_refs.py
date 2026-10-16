"""Offline alias transport checks; no scientific evidence rules are relaxed."""

import copy
import json

import pytest
from test_cli import write_project
from test_modular_synthesis_runner import fake_client
from test_synthesis_v12 import FIXTURE, case

from feature_dictionary import modular_synthesis as cli
from feature_dictionary.settings import load_settings
from feature_dictionary.synthesis_core import inventory_execution as execution
from feature_dictionary.synthesis_core.inventory_report import render_report
from feature_dictionary.synthesis_core.observation_refs import (
    create_mapping,
    expand_proposal,
    model_input,
    verify_mapping,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("No real provider clients allowed")

    monkeypatch.setattr(execution, "create_provider_client", fail)


def prepared(tmp_path, selector="claude"):
    inputs, _, response = case()
    settings = load_settings(
        write_project(tmp_path, options={"num_ctx": 65536}), overrides={"models": selector}
    )
    plan = execution.prepare(inputs, settings, proposal_version="1.2", observation_refs="short")
    request = execution.make_request(plan, settings.settings.models[0], 0)
    original = json.loads(response["response_text"])
    original.update(request["identity"])
    lookup = {e["observation_id"]: e["short_ref"] for e in plan["observation_mapping"]["entries"]}
    # Encode only fixture evidence IDs, not term refs or source wording.
    text = json.dumps(original)
    for oid, alias in lookup.items():
        text = text.replace('"' + oid + '"', '"' + alias + '"')
    return inputs, request, {**response, "response_text": text}, original


def test_mapping_bijection_order_fingerprints_and_exact_view():
    inputs, _, _ = case()
    mapping = create_mapping(inputs)
    assert mapping == create_mapping(inputs)
    assert [e["short_ref"] for e in mapping["entries"]] == [f"O{i:03d}" for i in range(1, 12)]
    assert [e["observation_id"] for e in mapping["entries"]] == [o.id for o in inputs.observations]
    view = model_input(inputs, mapping)
    assert view["observations"][0]["matched_text"] == "anal"
    assert list(view["observations"][0])[:2] == ["id", "matched_text"]
    assert view["sources"] == inputs.model_dump(mode="json")["sources"]
    for key in ("mapping_sha256", "input_sha256", "format_version"):
        bad = copy.deepcopy(mapping)
        bad[key] = "changed"
        with pytest.raises(ValueError):
            verify_mapping(bad, inputs)
    bad = copy.deepcopy(mapping)
    bad["entries"].reverse()
    with pytest.raises(ValueError):
        verify_mapping(bad, inputs)


def test_expansion_is_exact_lossless_and_keeps_raw_and_term_refs(tmp_path):
    inputs, request, response, original = prepared(tmp_path)
    before = copy.deepcopy(response)
    report = execution.evaluate(request, response, inputs)
    assert report["proposal_valid"]
    assert report["derived_proposal"] == original
    assert response == before
    assert (
        expand_proposal(
            json.loads(response["response_text"]), request["observation_mapping"], inputs
        )
        == original
    )
    markdown = render_report(inputs, response, report, request, include_raw_json=True)
    assert inputs.observations[0].id in markdown
    assert '"O001"' in markdown


@pytest.mark.parametrize("bad", ["O999", "o001", "original"])
def test_unknown_or_mixed_reference_is_not_guessed(tmp_path, bad):
    inputs, request, response, _ = prepared(tmp_path)
    data = json.loads(response["response_text"])
    data["terms"][0]["observation_ids"] = [inputs.observations[0].id if bad == "original" else bad]
    response["response_text"] = json.dumps(data)
    report = execution.evaluate(request, response, inputs)
    assert not report["proposal_valid"]
    assert report["derived_proposal"] is None
    assert "Unknown short observation reference" in report["issues"][0]["message"]


def test_wrong_valid_reference_still_fails_direct_evidence(tmp_path):
    inputs, request, response, _ = prepared(tmp_path)
    data = json.loads(response["response_text"])
    data["terms"][0]["observation_ids"] = ["O003"]
    response["response_text"] = json.dumps(data)
    report = execution.evaluate(request, response, inputs)
    assert not report["proposal_valid"]
    assert "UNOBSERVED_EXPRESSION" in {i["code"] for i in report["issues"]}


@pytest.mark.parametrize("selector", ["claude", "gpt", "gemini", "qwen3:8b"])
def test_mocked_archives_and_replay(tmp_path, monkeypatch, selector):
    inputs, request, response, original = prepared(tmp_path, selector)
    client, calls, _ = fake_client(
        request["identity"]["provider"], request, text=response["response_text"]
    )
    monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
    run = tmp_path / "run"
    assert execution.execute_run(run, inputs, [request], {})[0]["proposal_valid"]
    job = run / "job_000"
    assert (
        json.loads((job / "response.json").read_text())["response_text"]
        == response["response_text"]
    )
    assert json.loads((job / "proposal_expanded.json").read_text()) == original
    assert (job / "proposal_expansion.json").exists()
    assert execution.replay_job(job)["proposal_valid"]
    assert len(calls) == 1
    mapping = json.loads((run / "observation_refs.json").read_text())
    mapping["entries"][0]["observation_id"] = "tampered"
    (run / "observation_refs.json").write_text(json.dumps(mapping))
    with pytest.raises(ValueError, match="mapping"):
        execution.replay_job(job)
    assert len(calls) == 1


def test_cli_opt_in_and_legacy_default(tmp_path):
    settings = write_project(tmp_path)
    args = [
        "--settings",
        str(settings),
        "--models",
        "claude",
        "--inputs",
        str(FIXTURE / "inputs.json"),
        "--proposal-version",
        "1.2",
        "--run-dir",
        str(tmp_path / "dry"),
        "--dry-run",
    ]
    assert cli.main(args + ["--observation-refs", "short"]) == 0
    assert not (tmp_path / "dry").exists()
    inputs, _, _ = case()
    loaded = load_settings(settings)
    plan = execution.prepare(inputs, loaded, proposal_version="1.2")
    assert "observation_mapping" not in plan
    assert plan["prompt_path"].endswith("synthesis_inventory_v1_2.txt")
    with pytest.raises(ValueError, match="1.2"):
        execution.prepare(inputs, loaded, observation_refs="short")


def test_equivalence_evidence_expands_but_record_refs_do_not(tmp_path):
    inputs, request, response, _ = prepared(tmp_path)
    data = json.loads(response["response_text"])
    data["equivalence_proposals"] = [
        {
            "record_refs": ["p1", "p2"],
            "observation_ids": ["O001", "O003"],
            "rationale": "Uncertain; review only",
            "status": "pending_review",
        }
    ]
    expanded = expand_proposal(data, request["observation_mapping"], inputs)
    assert expanded["equivalence_proposals"][0]["record_refs"] == ["p1", "p2"]
    assert expanded["equivalence_proposals"][0]["observation_ids"] == [
        inputs.observations[0].id,
        inputs.observations[2].id,
    ]


@pytest.mark.parametrize("status", ["incomplete", "interrupted", "failed"])
def test_incomplete_responses_never_become_accepted(tmp_path, status):
    inputs, request, response, _ = prepared(tmp_path)
    response["completion_status"] = status
    report = execution.evaluate(request, response, inputs)
    assert report["derived_proposal"] is not None
    assert not report["proposal_valid"]


def test_invalid_json_and_missing_decisions_are_not_repaired(tmp_path):
    inputs, request, response, _ = prepared(tmp_path)
    truncated = {**response, "response_text": response["response_text"][:-4]}
    assert not execution.evaluate(request, truncated, inputs)["json_valid"]
    data = json.loads(response["response_text"])
    data["observation_dispositions"].pop()
    response["response_text"] = json.dumps(data)
    report = execution.evaluate(request, response, inputs)
    assert not report["proposal_valid"]
    assert len(report["derived_proposal"]["observation_dispositions"]) == 10


def test_independent_models_receive_identical_input_and_prompts(tmp_path):
    inputs, _, _ = case()
    loaded = load_settings(write_project(tmp_path), overrides={"models": "gpt,claude,gemini"})
    plan = execution.prepare(inputs, loaded, proposal_version="1.2", observation_refs="short")
    requests = [
        execution.make_request(plan, model, i) for i, model in enumerate(loaded.settings.models)
    ]
    assert len({r["prompt"] for r in requests}) == 1
    assert all(r["model_input"] == requests[0]["model_input"] for r in requests)
    assert all('"O001"' in json.dumps(r["output_schema"]) for r in requests)
    assert "DIRECT evidence" in plan["prompt_template"]


def test_equal_wording_and_reordered_input_do_not_merge_observations():
    inputs, _, _ = case()
    # Repeat an evidence location under a distinct observation ID: aliases remain bijective.
    obs = inputs.observations[0].model_copy(update={"id": "obs_distinct"})
    extended = inputs.model_copy(update={"observations": (*inputs.observations, obs)})
    mapping = create_mapping(extended)
    assert mapping["entries"][-1] == {"short_ref": "O012", "observation_id": "obs_distinct"}
    assert len(mapping["entries"]) == 12
    reordered = inputs.model_copy(update={"observations": tuple(reversed(inputs.observations))})
    with pytest.raises(ValueError):
        verify_mapping(create_mapping(inputs), reordered)


def test_bad_mapping_prevents_any_provider_and_existing_run_is_preserved(tmp_path, monkeypatch):
    inputs, request, response, _ = prepared(tmp_path)
    bad = copy.deepcopy(request)
    bad["observation_mapping"]["mapping_sha256"] = "tampered"
    with pytest.raises(ValueError):
        execution.execute_run(tmp_path / "bad", inputs, [bad], {})
    assert not (tmp_path / "bad").exists()
    client, calls, _ = fake_client("anthropic", request, text=response["response_text"])
    monkeypatch.setattr(execution, "create_provider_client", lambda *args: client)
    run = tmp_path / "run"
    execution.execute_run(run, inputs, [request], {})
    before = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        execution.execute_run(run, inputs, [request], {})
    assert all(p.read_bytes() == data for p, data in before.items())
    assert len(calls) == 1
    # Derived output is never trusted during replay.
    (run / "job_000/proposal_expanded.json").write_text("{}")
    assert execution.replay_job(run / "job_000")["proposal_valid"]
    (run / "model_input.json").write_text("{}")
    with pytest.raises(ValueError, match="model input"):
        execution.replay_job(run / "job_000")
