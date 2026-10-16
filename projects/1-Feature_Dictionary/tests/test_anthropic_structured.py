"""Claude native JSON output with mocked requests and unchanged strict validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anthropic
import httpx2
import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import install_cloud
from test_extraction_v3_pipeline import artifacts
from test_extraction_v31 import response

from feature_dictionary import cli
from feature_dictionary.context import RunContext
from feature_dictionary.extraction_replay import replay_archive
from feature_dictionary.extraction_v3 import CandidateResponseV31
from feature_dictionary.runners import anthropic_runner
from feature_dictionary.settings import SettingsError, load_settings

ROOT = Path(__file__).resolve().parents[1]
ANSWER = response(("scales", "scales"), ("préoculaire", "préoculaire"))


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Claude tests must not contact providers")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


def project(tmp_path, **overrides):
    settings = dict(
        extraction_format="v3",
        v3_candidate_version="3.1",
        anthropic_output_format="candidate_schema",
        v3_prompt_file=str(ROOT / "prompts/extraction_v3_1_3.txt"),
        models=[{"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"}],
        options={"num_ctx": 8192},
    )
    settings.update(overrides)
    path = write_project(tmp_path, **settings)
    (tmp_path / "species_database.txt").write_text("scales; préoculaire; scales")
    return path


def digest(schema):
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def output(tmp_path):
    return artifacts(tmp_path, model="claude-sonnet-4-5-20250929")


def test_schema_projection_preserves_original_contract_and_version_constraint(tmp_path):
    path = project(tmp_path)
    original = CandidateResponseV31.model_json_schema()
    run = RunContext.from_settings(load_settings(path), "scales")
    schema = run.anthropic_output_schema
    assert schema["properties"]["format_version"]["enum"] == ["extraction-3.1"]
    fields = schema["$defs"]["CandidateEntryV31"]["properties"]
    assert "minLength" not in fields["matched_text"]
    assert "minLength: 1" in fields["matched_text"]["description"]
    assert fields["proposed_annotations"]["anyOf"][1]["additionalProperties"] is False
    assert "proposed_annotations" not in schema["$defs"]["CandidateEntryV31"]["required"]
    assert CandidateResponseV31.model_json_schema() == original
    constraint = run.anthropic_output_constraint
    assert constraint["schema_sha256"] == digest(schema)
    assert constraint["original_schema_sha256"] == digest(original)
    assert constraint["sdk_version"] == anthropic.__version__


def test_installed_sdk_serializes_native_output_config_offline(tmp_path, monkeypatch):
    path = project(tmp_path)
    schema = RunContext.from_settings(load_settings(path), "scales").anthropic_output_schema
    _, _, sdk_response = fake("anthropic", text=ANSWER)
    sent = []

    def post(*args, **kwargs):
        sent.append(kwargs["body"])
        return sdk_response

    with anthropic.Anthropic(api_key="offline-test", max_retries=0) as client:
        monkeypatch.setattr(client, "post", post)
        outcome = anthropic_runner.run_model(
            client,
            model="claude-sonnet-4-5-20250929",
            prompt="original",
            output_schema=schema,
        )
    assert outcome.response_text == ANSWER
    assert sent[0]["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert sent[0]["messages"] == [{"role": "user", "content": "original"}]


@pytest.mark.parametrize("enabled", [False, True])
def test_opt_in_request_and_raw_metadata_with_valid_json(tmp_path, monkeypatch, enabled):
    path = project(tmp_path, anthropic_output_format="candidate_schema" if enabled else None)
    client, calls, _ = fake("anthropic", text=ANSWER)
    _, closed = install_cloud(monkeypatch, "anthropic", client)
    assert cli.main(["--settings", str(path)]) == 0
    raw, report, document = output(tmp_path)
    assert raw["response_text"] == ANSWER and raw["run"]["completion_reason"] == "end_turn"
    assert report["accepted"] and report["evidence_valid"] and document.exists()
    assert len(calls) == 1 and closed == [True]
    assert ("output_config" in calls[0]) == enabled
    assert ("anthropic_output_constraint" in raw) == enabled
    if enabled:
        constraint = raw["anthropic_output_constraint"]
        assert constraint == report["anthropic_output_constraint"]
        assert constraint["schema"] == calls[0]["output_config"]["format"]["schema"]
        assert constraint["schema_sha256"] == digest(constraint["schema"])
        assert constraint["schema_identity"].endswith("anthropic-projection-1")
        assert constraint["request_parameter"] == "output_config.format"
        assert constraint["adaptations"]
        logs = "\n".join(p.read_text() for p in (tmp_path / "extractor_logs").glob("*.md"))
        assert constraint["schema_sha256"] in logs
    assert replay_archive(document.with_suffix(".raw.json"))["accepted"]


@pytest.mark.parametrize(
    "text,code",
    [
        ("```json\n" + ANSWER + "\n```", "INVALID_JSON"),
        ("Here is JSON: " + ANSWER, "INVALID_JSON"),
        (ANSWER[:-1], "INVALID_JSON"),
        (response(("praeocular", "praeocular")), "UNMATCHED_EVIDENCE"),
        (response(("", "scales")), "CONTRACT_ERROR"),
        ("", "INVALID_JSON"),
    ],
)
def test_native_mode_does_not_repair_invalid_responses(tmp_path, monkeypatch, text, code):
    path = project(tmp_path)
    client, calls, _ = fake("anthropic", text=text)
    install_cloud(monkeypatch, "anthropic", client)
    assert cli.main(["--settings", str(path)]) == 1
    raw, report, document = output(tmp_path)
    assert raw["response_text"] == text
    assert not report["accepted"] and not document.exists()
    assert code in {i["code"] for i in report["issues"]}
    assert len(calls) == 1 and "output_config" in calls[0]
    assert not replay_archive(document.with_suffix(".raw.json"))["accepted"]


@pytest.mark.parametrize(
    "reason,status",
    [
        ("max_tokens", "incomplete"),
        ("model_context_window_exceeded", "incomplete"),
        ("pause_turn", "incomplete"),
        ("refusal", "blocked"),
    ],
)
def test_native_mode_does_not_accept_incomplete_or_refused_response(
    tmp_path, monkeypatch, reason, status
):
    path = project(tmp_path)
    client, calls, _ = fake("anthropic", reason=reason, text=ANSWER)
    install_cloud(monkeypatch, "anthropic", client)
    assert cli.main(["--settings", str(path)]) == 1
    raw, report, document = output(tmp_path)
    assert raw["run"]["completion_status"] == status
    assert raw["run"]["completion_reason"] == reason
    assert raw["response_text"] == ANSWER and report["evidence_valid"]
    assert not report["accepted"] and not document.exists() and len(calls) == 1
    assert not replay_archive(document.with_suffix(".raw.json"))["accepted"]


def test_api_error_archives_requested_constraint_without_fallback(tmp_path, monkeypatch):
    path = project(tmp_path)
    client, _, _ = fake("anthropic", text=ANSWER)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise anthropic.APIConnectionError(
            request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        )

    client.messages.create = create
    _, closed = install_cloud(monkeypatch, "anthropic", client)
    assert cli.main(["--settings", str(path)]) == 1
    raw, report, document = output(tmp_path)
    assert not raw["response_available"] and "APIConnectionError" in raw["error"]
    assert (
        raw["anthropic_output_constraint"]["schema"]
        == calls[0]["output_config"]["format"]["schema"]
    )
    assert not report["accepted"] and not document.exists() and len(calls) == 1 and closed == [True]


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_anthropic_setting_does_not_change_other_cloud_requests(tmp_path, monkeypatch, provider):
    path = project(tmp_path, models=[{"provider": provider, "model": "fake"}])
    client, calls, _ = fake(provider, text=ANSWER)
    install_cloud(monkeypatch, provider, client)
    assert cli.main(["--settings", str(path)]) == 0
    raw, report, _ = artifacts(tmp_path)
    assert "output_config" not in calls[0] and "output_schema" not in calls[0]
    assert "anthropic_output_constraint" not in raw and report["accepted"]


@pytest.mark.parametrize("format,version", [("v2", "3.1"), ("v3", "3.0")])
def test_constraint_requires_v31(tmp_path, format, version):
    path = project(tmp_path, extraction_format=format, v3_candidate_version=version)
    with pytest.raises(SettingsError, match="anthropic_output_format requires"):
        load_settings(path)


def test_cli_opt_in_default_override_and_dry_run(tmp_path, capsys):
    path = project(tmp_path, anthropic_output_format=None)
    assert (
        cli.main(
            ["--settings", str(path), "--anthropic-output-format", "candidate-schema", "--dry-run"]
        )
        == 0
    )
    assert "anthropic-projection-1" in capsys.readouterr().out
    assert not (tmp_path / "extractor_outputs").exists()
    assert load_settings(path).settings.anthropic_output_format is None
    path = project(tmp_path)
    args = cli.build_parser().parse_args(["--anthropic-output-format", "default"])
    loaded = load_settings(path, overrides=cli._overrides_from_args(args))
    assert loaded.settings.anthropic_output_format is None
