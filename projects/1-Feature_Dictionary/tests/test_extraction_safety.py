"""Deterministic output safety tests; no actual model requests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

import pytest
from test_cli import write_project
from test_cloud_extraction import fake

from feature_dictionary import cli, context, writers
from feature_dictionary.context import RunContext
from feature_dictionary.settings import load_settings


@pytest.fixture(autouse=True)
def forbid_real_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A safety check must not construct a real client")

    monkeypatch.setattr(cli, "create_client", forbidden)
    monkeypatch.setattr(cli, "OpenAI", forbidden)
    monkeypatch.setattr(cli, "Anthropic", forbidden)
    monkeypatch.setattr(cli.genai, "Client", forbidden)


def cloud_project(tmp_path, monkeypatch):
    path = write_project(tmp_path, models=[{"provider": "openai", "model": "fake"}])
    client, calls, _ = fake("openai")
    monkeypatch.setattr(cli, "OpenAI", lambda **kwargs: client)
    return path, calls


def test_second_run_cannot_overwrite_answer_or_append_to_logs(tmp_path, monkeypatch, capsys):
    path, calls = cloud_project(tmp_path, monkeypatch)
    assert cli.main(["--settings", str(path)]) == 0
    original = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert len(calls) == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == original


def test_nonconflicting_models_can_share_output_directory(tmp_path, monkeypatch):
    path, calls = cloud_project(tmp_path, monkeypatch)
    assert cli.main(["--settings", str(path)]) == 0
    original = (tmp_path / "extractor_outputs" / "0_fake.md").read_bytes()
    assert cli.main(["--settings", str(path), "--models", "openai=other"]) == 0
    assert len(calls) == 2
    assert (tmp_path / "extractor_outputs" / "0_fake.md").read_bytes() == original
    assert (tmp_path / "extractor_outputs" / "0_other.md").exists()
    assert len(list((tmp_path / "extractor_outputs" / ".extraction_runs").glob("*.json"))) == 2


@pytest.mark.parametrize("target", ["model_log", "summary"])
def test_log_append_false_cannot_replace_existing_log(tmp_path, capsys, target):
    path = write_project(tmp_path, log_append=False)
    run = RunContext.from_settings(load_settings(path), "input")
    existing = (
        writers.log_path_for(run, 0, "llama3.1:8b")
        if target == "model_log"
        else writers.summary_path_for(run)
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"historical experiment\r\n")
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert existing.read_bytes() == b"historical experiment\r\n"
    assert "refusing to overwrite" in capsys.readouterr().err


@pytest.mark.parametrize("directory", ["extractor_outputs", "extractor_logs"])
def test_existing_directory_lock_is_not_removed(tmp_path, capsys, directory):
    path = write_project(tmp_path)
    lock = tmp_path / directory / ".extraction.lock"
    lock.parent.mkdir()
    lock.write_text("other run owns this lock\n")
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert lock.read_text() == "other run owns this lock\n"
    assert "directory is reserved" in capsys.readouterr().err
    other = tmp_path / (
        "extractor_logs" if directory == "extractor_outputs" else "extractor_outputs"
    )
    assert not (other / ".extraction.lock").exists()


def test_dangling_output_symlink_is_a_collision(tmp_path):
    path = write_project(tmp_path)
    output = tmp_path / "extractor_outputs" / "0_llama3.1-8b.md"
    output.parent.mkdir()
    output.symlink_to(tmp_path / "nonexistent-archive")
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert output.is_symlink()
    assert not (tmp_path / "nonexistent-archive").exists()


def test_same_timestamp_has_distinct_run_ids(tmp_path, monkeypatch):
    path = write_project(tmp_path)
    loaded = load_settings(path)
    values = iter([UUID(int=1), UUID(int=2)])
    monkeypatch.setattr(context, "uuid4", lambda: next(values))
    stamp = datetime(2026, 10, 12, 12, 0, 0)
    first = RunContext.from_settings(loaded, "data", started_at=stamp)
    second = RunContext.from_settings(loaded, "data", started_at=stamp)
    assert first.run_id != second.run_id
    assert first.run_id.startswith(stamp.isoformat(timespec="microseconds"))


def test_repeated_run_id_refused_even_with_nonconflicting_filenames(tmp_path):
    path = write_project(tmp_path)
    first = RunContext.from_settings(load_settings(path), "input")
    with writers.reserve_run(first):
        pass
    other_settings = load_settings(path, overrides={"models": ["different-model"]})
    second = replace(first, settings=other_settings)
    with pytest.raises(writers.OutputCollisionError, match="run ID already exists"):
        with writers.reserve_run(second):
            pytest.fail("Reused identity must not be accepted")
    assert not (first.output_dir / ".extraction.lock").exists()
    assert not (first.log_dir / ".extraction.lock").exists()


def test_reservation_excludes_overlapping_run_and_releases_after_failure(tmp_path):
    path = write_project(tmp_path)
    run = RunContext.from_settings(load_settings(path), "input")
    with pytest.raises(RuntimeError, match="simulated failure"):
        with writers.reserve_run(run):
            with pytest.raises(writers.OutputCollisionError, match="directory is reserved"):
                with writers.reserve_run(replace(run, run_id="other")):
                    pytest.fail("Concurrent owner must be refused")
            raise RuntimeError("simulated failure")
    assert not (run.output_dir / ".extraction.lock").exists()
    assert not (run.log_dir / ".extraction.lock").exists()
    with writers.reserve_run(replace(run, run_id="fresh")):
        pass


def test_file_appearing_after_preflight_is_not_overwritten(tmp_path, monkeypatch):
    path, calls = cloud_project(tmp_path, monkeypatch)
    execute = cli._run_extraction
    output = tmp_path / "extractor_outputs" / "0_fake.md"

    def unexpected_writer(run):
        output.write_text("foreign output")
        return execute(run)

    monkeypatch.setattr(cli, "_run_extraction", unexpected_writer)
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert len(calls) == 1  # Only this simulated race occurs after the fake request.
    assert output.read_text() == "foreign output"


def test_dry_run_neither_reserves_nor_overwrites_existing_output(tmp_path):
    path = write_project(tmp_path)
    output = tmp_path / "extractor_outputs" / "0_llama3.1-8b.md"
    output.parent.mkdir()
    output.write_text("historical")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["--settings", str(path), "--dry-run"]) == 0
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("directory", ["extractor_outputs", "extractor_logs"])
def test_directory_path_occupied_by_file_is_preserved(tmp_path, directory):
    path = write_project(tmp_path)
    occupied = tmp_path / directory
    occupied.write_bytes(b"historical file")
    assert cli.main(["--settings", str(path)]) == cli.EXIT_CONFIGURATION_ERROR
    assert occupied.read_bytes() == b"historical file"
