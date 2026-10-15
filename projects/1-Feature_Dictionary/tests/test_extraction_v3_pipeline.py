"""V3 pipeline integration with mocked SDKs and Ollama; no network requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from test_cli import write_project
from test_cloud_extraction import fake
from test_extraction_pipeline import LOCAL_MODELS, SELECTION, install_cloud
from test_extraction_v3 import entry, response

from feature_dictionary import cli, writers
from feature_dictionary.context import RunContext
from feature_dictionary.extraction_v3 import ExtractionDocument, validate_document
from feature_dictionary.runner import ModelMetrics
from feature_dictionary.settings import decode_text, load_settings

TEXT = "  anterior dorsal scales; keeled; préoculaire\r\n"
ANSWER = response(entry("scales", "anterior dorsal scales"), entry("keeled"), entry("préoculaire"))


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("V3 tests must not construct a real provider client")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


def project(tmp_path, **overrides):
    # These regressions freeze the v3.0 behavior; v3.1 has its own integration tests.
    overrides.setdefault("v3_candidate_version", "3.0")
    path = write_project(tmp_path, extraction_format="v3", options={"num_ctx": 8192}, **overrides)
    (tmp_path / "species_database.txt").write_bytes(TEXT.encode())
    return path


def artifacts(tmp_path, index=0, model="fake"):
    folder = tmp_path / "extractor_outputs"
    stem = f"{index}_{model}"
    raw = json.loads((folder / f"{stem}.raw.json").read_text())
    validation = json.loads((folder / f"{stem}.validation.json").read_text())
    document_path = folder / f"{stem}.json"
    return raw, validation, document_path


def cloud_project(tmp_path, monkeypatch, *, provider="openai", text=ANSWER, reason=None, **options):
    path = project(tmp_path, models=[{"provider": provider, "model": "fake"}], **options)
    client, calls, sdk_response = fake(provider, reason=reason, text=text)
    _, closed = install_cloud(monkeypatch, provider, client)
    return path, client, calls, sdk_response, closed


@pytest.mark.parametrize("concurrency", [1, 3])
def test_all_six_models_share_v3_prompt_writer_and_provenance(tmp_path, monkeypatch, concurrency):
    path = project(tmp_path, max_concurrency=concurrency)
    local_calls = []

    def generate(**kwargs):
        assert list((tmp_path / "extractor_outputs" / ".extraction_runs").glob("*.input.bin"))
        local_calls.append(kwargs)
        return NS(response=ANSWER, thinking="original thinking", done=True, done_reason="stop")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=generate))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: set(LOCAL_MODELS))
    clouds = {}
    for provider in ("openai", "anthropic", "gemini"):
        client, calls, _ = fake(provider, text=ANSWER)
        _, closed = install_cloud(monkeypatch, provider, client)
        clouds[provider] = calls, closed
    assert cli.main(["--settings", str(path), "--models", SELECTION]) == 0
    prompts = {call["prompt"] for call in local_calls}
    for calls, closed in clouds.values():
        assert len(calls) == 1 and closed == [True]
        call = calls[0]
        prompts.add(call.get("input") or call.get("contents") or call["messages"][0]["content"])
    assert len(local_calls) == 3 and len(prompts) == 1
    prompt = prompts.pop()
    assert TEXT in prompt and "Output contract: extraction-3.0" in prompt
    run_ids = set()
    for index, model in enumerate(cli._parse_models(SELECTION)):
        slug = cli.naming.slugify_model(model["model"])
        raw, report, document_path = artifacts(tmp_path, index, slug)
        assert raw["response_text"] == ANSWER
        assert report["accepted"] and report["evidence_valid"]
        document = ExtractionDocument.model_validate_json(document_path.read_text())
        assert validate_document(document, ANSWER).evidence_valid
        assert document.run.provider == model["provider"]
        assert document.run.model == model["model"]
        assert document.run.prompt_version == "v3"
        assert (
            document.run.rendered_prompt_fingerprint
            == hashlib.sha256(prompt.encode()).hexdigest()[:16]
        )
        assert document.input.supplied_text == TEXT
        assert (
            document_path.parent / document.input.original_file_archive
        ).read_bytes() == TEXT.encode()
        run_ids.add(document.run.run_id)
    assert len(run_ids) == 1
    assert not list((tmp_path / "extractor_outputs").glob("*.md"))


def test_raw_response_is_saved_exactly_before_parsing(tmp_path, monkeypatch):
    original = " \r\n" + ANSWER + "\r\n  "
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch, text=original)
    validator = writers.validate_response

    def check_archive_first(text, source, **kwargs):
        raw_path = tmp_path / "extractor_outputs" / "0_fake.raw.json"
        assert json.loads(raw_path.read_text())["response_text"] == original
        return validator(text, source, **kwargs)

    monkeypatch.setattr(writers, "validate_response", check_archive_first)
    assert cli.main(["--settings", str(path)]) == 0
    assert artifacts(tmp_path)[0]["response_text"] == original


@pytest.mark.parametrize("text", ["not JSON", '{"format_version":', "", "```json\n{}\n```"])
def test_bad_and_empty_responses_keep_archives_without_publishing_document(
    tmp_path, monkeypatch, text
):
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch, text=text)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    raw, report, output = artifacts(tmp_path)
    assert raw["response_text"] == text and raw["response_available"]
    assert not report["accepted"] and not report["evidence_valid"] and not output.exists()
    assert report["run"]["completion_status"] == ("empty" if not text else "success")
    summary = next((tmp_path / "extractor_logs").glob("summary*.md")).read_text()
    assert ("| empty |" if not text else "| invalid_output |") in summary


@pytest.mark.parametrize(
    "provider,reason,status",
    [
        ("openai", "incomplete", "incomplete"),
        ("openai", "failed", "failed"),
        ("anthropic", "max_tokens", "incomplete"),
        ("anthropic", "refusal", "blocked"),
        ("gemini", "MAX_TOKENS", "incomplete"),
        ("gemini", "SAFETY", "blocked"),
    ],
)
def test_provider_status_is_independent_of_valid_json(
    tmp_path, monkeypatch, provider, reason, status
):
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch, provider=provider, reason=reason)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    raw, report, output = artifacts(tmp_path)
    assert raw["response_text"] == ANSWER
    assert raw["run"]["completion_status"] == status
    assert reason in raw["run"]["completion_reason"]
    assert report["evidence_valid"] and not report["accepted"] and not output.exists()
    assert len(report["entries"]) == 3


def test_openai_refusal_with_no_text_is_archived(tmp_path, monkeypatch):
    path, _, _, sdk_response, _ = cloud_project(tmp_path, monkeypatch, text="")
    sdk_response.output = [NS(content=[NS(type="refusal")])]
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    raw, report, _ = artifacts(tmp_path)
    assert raw["response_available"] and raw["response_text"] == ""
    assert raw["run"]["completion_status"] == "blocked"
    assert raw["run"]["completion_reason"] == "completed:refusal"
    assert not report["accepted"]


def test_ambiguous_and_unmatched_evidence_remain_in_reports(tmp_path, monkeypatch):
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch, text=response(entry("scales")))
    (tmp_path / "species_database.txt").write_text("scales scales")
    assert cli.main(["--settings", str(path)]) == 0
    _, report, output = artifacts(tmp_path)
    assert report["accepted"] and output.exists()
    assert report["entries"][0]["location"]["status"] == "ambiguous"
    assert len(report["entries"][0]["location"]["candidates"]) == 2
    other = tmp_path / "other"
    other.mkdir()
    path, _, _, _, _ = cloud_project(other, monkeypatch, text=response(entry("invented term")))
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    _, report, output = artifacts(other)
    assert report["entries"][0]["location"]["status"] == "unmatched"
    assert not output.exists()


@pytest.mark.parametrize("failure", ["constructor", "request", "interrupt"])
@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_no_response_failures_are_explicit_and_archived(tmp_path, monkeypatch, failure, provider):
    path, client, _, _, closed = cloud_project(tmp_path, monkeypatch, provider=provider)

    def fail(**kwargs):
        if failure == "interrupt":
            raise KeyboardInterrupt
        raise RuntimeError("simulated failure")

    if failure == "constructor":
        if provider == "gemini":
            monkeypatch.setattr(cli.genai, "Client", fail)
        else:
            monkeypatch.setattr(cli, "OpenAI" if provider == "openai" else "Anthropic", fail)
    else:
        client.responses.create = fail
        client.messages.create = fail
        client.models.generate_content = fail
    expected = cli.EXIT_INTERRUPTED if failure == "interrupt" else cli.EXIT_MODEL_FAILURE
    assert cli.main(["--settings", str(path)]) == expected
    raw, report, output = artifacts(tmp_path)
    assert raw["response_available"] is False and raw["response_text"] == ""
    assert raw["error"] and not report["accepted"] and not output.exists()
    assert closed == ([] if failure == "constructor" else [True])


@pytest.mark.parametrize("failure", ["interrupt", "connection"])
def test_ollama_partial_stream_is_retained_on_interrupt_or_transport_error(
    tmp_path, monkeypatch, failure
):
    path = project(tmp_path, models=["qwen3:8b"], stream=True)
    partial = '{"format_version":"extraction-3.0",'

    def chunks():
        yield NS(response=partial, thinking="partial reasoning")
        if failure == "interrupt":
            raise KeyboardInterrupt
        raise ConnectionError("stream disconnected")

    monkeypatch.setattr(cli, "create_client", lambda context: NS(generate=lambda **kw: chunks()))
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"qwen3:8b"})
    expected = cli.EXIT_INTERRUPTED if failure == "interrupt" else cli.EXIT_MODEL_FAILURE
    assert cli.main(["--settings", str(path)]) == expected
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert raw["response_text"] == partial and raw["thinking_text"] == "partial reasoning"
    assert raw["response_available"] and not report["accepted"] and not output.exists()


@pytest.mark.parametrize("target", ["document", "raw", "validation"])
def test_every_v3_artifact_collision_prevents_requests(tmp_path, monkeypatch, target):
    path, _, calls, _, _ = cloud_project(tmp_path, monkeypatch)
    loaded = load_settings(path)
    run = RunContext.from_settings(loaded, TEXT, original_input_bytes=TEXT.encode())
    existing = writers.v3_artifact_paths(run, 0, "fake")[target]
    existing.parent.mkdir()
    existing.write_bytes(b"historical output\r\n")
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert not calls and existing.read_bytes() == b"historical output\r\n"


def test_failed_output_cannot_be_silently_retried_into_same_directory(tmp_path, monkeypatch):
    path, _, calls, _, _ = cloud_project(tmp_path, monkeypatch, text="invalid")
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert len(calls) == 1
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_v3_run_id_collision_is_refused(tmp_path):
    path = project(tmp_path)
    run = RunContext.from_settings(load_settings(path), TEXT, original_input_bytes=TEXT.encode())
    with writers.reserve_run(run):
        pass
    settings = load_settings(path, overrides={"models": ["other-model"]})
    with pytest.raises(writers.OutputCollisionError):
        with writers.reserve_run(replace(run, settings=settings)):
            pytest.fail("Reused run ID was accepted")


@pytest.mark.parametrize("name", ["input", "prompt"])
def test_source_snapshot_collisions_prevent_requests(tmp_path, monkeypatch, name):
    path, _, calls, _, _ = cloud_project(tmp_path, monkeypatch)
    run = RunContext.from_settings(load_settings(path), TEXT, original_input_bytes=TEXT.encode())
    existing = writers.run_archive_paths(run)[name]
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"historical snapshot")
    monkeypatch.setattr(cli.RunContext, "from_settings", lambda *args, **kwargs: run)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert not calls and existing.read_bytes() == b"historical snapshot"


def test_dry_run_v3_is_explicit_and_writes_nothing(tmp_path, capsys):
    path = write_project(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["--settings", str(path), "--extraction-format", "v3", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "extraction format: v3" in output and "extraction_v3_1.txt" in output
    assert ".raw.json" in output and ".validation.json" in output
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_prompt_options_do_not_change_v2_defaults(tmp_path):
    path = write_project(tmp_path)
    assert load_settings(path).settings.extraction_format == "v2"
    assert load_settings(path).prompt_text == "Summarise {species_database}"
    v3 = load_settings(path, overrides={"extraction_format": "v3"})
    assert v3.prompt_path.name == "extraction_v3_1.txt"
    custom = tmp_path / "custom_v3.txt"
    custom.write_text("V3 custom {species_database}")
    changed = load_settings(
        path, overrides={"extraction_format": "v3", "prompt_file": str(custom), "prompt": None}
    )
    assert changed.prompt_text == "V3 custom {species_database}"
    assert load_settings(path).prompt_text == "Summarise {species_database}"


def test_truncated_cp1252_input_preserves_original_bytes_and_exact_supplied_text(
    tmp_path, monkeypatch
):
    path, _, _, _, _ = cloud_project(
        tmp_path, monkeypatch, text=response(entry("scales")), max_input_characters=10
    )
    original = b"  scales\r\npr\xe9oculaire"
    (tmp_path / "species_database.txt").write_bytes(original)
    assert cli.main(["--settings", str(path)]) == 0
    raw, _, output = artifacts(tmp_path)
    document = ExtractionDocument.model_validate_json(output.read_text())
    assert document.input.truncated
    assert document.input.supplied_text == decode_text(original)[:10] == "  scales\r\n"
    assert document.input.original_file_sha256 == hashlib.sha256(original).hexdigest()
    assert (output.parent / document.input.original_file_archive).read_bytes() == original
    assert TEXT not in raw["input"]["supplied_text"]


def test_validator_failure_leaves_raw_response_on_disk(tmp_path, monkeypatch):
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise OSError("simulated validation interruption")

    monkeypatch.setattr(writers, "validate_response", fail)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    raw = tmp_path / "extractor_outputs" / "0_fake.raw.json"
    assert json.loads(raw.read_text())["response_text"] == ANSWER


def test_cloud_carried_partial_outcome_is_archived(tmp_path, monkeypatch):
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch)
    outcome = cli.GenerationOutcome(
        response_text=ANSWER,
        thinking_text="",
        completion_status="interrupted",
        metrics=ModelMetrics(wall_clock_seconds=0.1, done_reason="interrupted"),
    )

    def interrupt(*args, **kwargs):
        raise cli.GenerationInterrupted(outcome)

    monkeypatch.setattr(cli.cloud_runner, "run_model", interrupt)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_INTERRUPTED
    raw, report, output = artifacts(tmp_path)
    assert raw["response_text"] == ANSWER and report["evidence_valid"]
    assert raw["run"]["completion_status"] == "interrupted" and not output.exists()


@pytest.mark.parametrize("reason,text", [("length", ANSWER), ("stop", "")])
def test_ollama_incomplete_and_empty_responses_are_archived(tmp_path, monkeypatch, reason, text):
    path = project(tmp_path, models=["qwen3:8b"])
    monkeypatch.setattr(
        cli,
        "create_client",
        lambda context: NS(generate=lambda **kw: NS(response=text, done=True, done_reason=reason)),
    )
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"qwen3:8b"})
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    raw, report, output = artifacts(tmp_path, model="qwen3-8b")
    assert raw["response_text"] == text and raw["response_available"]
    assert raw["run"]["completion_status"] == ("incomplete" if reason == "length" else "empty")
    assert not report["accepted"] and not output.exists()


def test_annotation_warnings_do_not_block_grounded_document(tmp_path, monkeypatch):
    raw_candidate = response(entry("scales", proposed_annotations={"language": 17, "forms": "?"}))
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch, text=raw_candidate)
    assert cli.main(["--settings", str(path)]) == 0
    _, report, output = artifacts(tmp_path)
    assert output.exists() and report["accepted"]
    assert {issue["code"] for issue in report["issues"]} == {"ANNOTATION_REVIEW"}
    assert json.loads(output.read_text())["entries"][0]["proposed_annotations"]["language"] == 17


def test_malformed_unicode_in_suggestions_cannot_crash_grounded_output(tmp_path, monkeypatch):
    candidate = response(entry("scales", proposed_annotations={"language": "\ud800"}))
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch, text=candidate)
    monkeypatch.setattr(cli, "_print_cloud_response", lambda outcome: None)
    assert cli.main(["--settings", str(path)]) == 0
    _, report, output = artifacts(tmp_path)
    assert report["accepted"]
    saved = ExtractionDocument.model_validate(json.loads(output.read_text()))
    assert saved.entries[0].proposed_annotations["language"] == "\ud800"
    assert validate_document(saved, candidate).evidence_valid


def test_malformed_model_unicode_is_archived_without_crashing(tmp_path, monkeypatch):
    text = "invalid JSON \ud800"
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch, text=text)
    # Console output is unrelated to evidence and may not support the malformed character.
    monkeypatch.setattr(cli, "_print_cloud_response", lambda outcome: None)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_MODEL_FAILURE
    raw, report, _ = artifacts(tmp_path)
    assert raw["response_text"] == text and not report["accepted"]


def test_v3_identical_model_labels_remain_distinct(tmp_path, monkeypatch):
    path = project(tmp_path)
    monkeypatch.setattr(
        cli,
        "create_client",
        lambda context: NS(
            generate=lambda **kw: NS(response=ANSWER, done=True, done_reason="stop")
        ),
    )
    monkeypatch.setattr(cli, "list_installed_models", lambda client: {"same"})
    client, _, _ = fake("openai", text=ANSWER)
    install_cloud(monkeypatch, "openai", client)
    assert cli.main(["--settings", str(path), "--models", "ollama=same,openai=same"]) == 0
    for index, provider in enumerate(["ollama", "openai"]):
        raw, _, output = artifacts(tmp_path, index, "same")
        assert raw["run"]["provider"] == provider and output.exists()


def test_late_collision_preserves_foreign_file_and_raw_response(tmp_path, monkeypatch):
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch)
    validate = writers.validate_response
    target = tmp_path / "extractor_outputs" / "0_fake.json"

    def competing_writer(*args, **kwargs):
        target.write_text("foreign output")
        return validate(*args, **kwargs)

    monkeypatch.setattr(writers, "validate_response", competing_writer)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert target.read_text() == "foreign output"
    assert artifacts(tmp_path)[0]["response_text"] == ANSWER


def test_dangling_raw_symlink_is_a_collision(tmp_path, monkeypatch):
    path, _, calls, _, _ = cloud_project(tmp_path, monkeypatch)
    target = tmp_path / "extractor_outputs" / "0_fake.raw.json"
    target.parent.mkdir()
    target.symlink_to(tmp_path / "missing")
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert not calls and target.is_symlink()


def test_v3_custom_prompt_in_settings_and_format_cli_override(tmp_path, capsys):
    custom = tmp_path / "research_v3.txt"
    custom.write_text("Custom extraction {species_database}")
    path = project(tmp_path, v3_prompt_file=custom.name)
    assert load_settings(path).prompt_text == custom.read_text()
    assert cli.main(["--settings", str(path), "--extraction-format", "v2", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "extraction format: v2" in output and "Summarise" in output
    assert ".raw.json" not in output


@pytest.mark.parametrize("problem", ["interrupt", "encoding"])
def test_console_failure_after_response_does_not_lose_or_overwrite_archive(
    tmp_path, monkeypatch, problem
):
    path, _, _, _, _ = cloud_project(tmp_path, monkeypatch)

    def fail_display(outcome):
        if problem == "interrupt":
            raise KeyboardInterrupt
        raise UnicodeEncodeError("utf-8", "\ud800", 0, 1, "unpaired surrogate")

    monkeypatch.setattr(cli, "_print_cloud_response", fail_display)
    expected = cli.EXIT_INTERRUPTED if problem == "interrupt" else cli.EXIT_SUCCESS
    assert cli.main(["--settings", str(path)]) == expected
    raw, report, output = artifacts(tmp_path)
    assert raw["response_text"] == ANSWER and report["accepted"] and output.exists()
