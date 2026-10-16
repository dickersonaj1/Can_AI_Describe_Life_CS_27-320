"""End-to-end tests for the CLI: artefacts, exit codes, interrupts, loop guard."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from feature_dictionary import cli

DATABASE = "Acanthophis antarcticus\tDiagnosis: a stout elapid with a wide head.\n"
STAMP = datetime.now().strftime("%m_%d")


def write_project(tmp_path: Path, **overrides: Any) -> Path:
    """Create an input file and a settings.json for a run inside ``tmp_path``."""
    (tmp_path / "species_database.txt").write_text(DATABASE, encoding="utf-8")
    payload: dict[str, Any] = {
        "input_file": "species_database.txt",
        "prompt": "Summarise {species_database}",
        "models": ["llama3.1:8b", "qwen3:8b"],
        "options": {"num_ctx": 512},
        "stream": False,
        "output_dir": "extractor_outputs",
        "log_dir": "extractor_logs",
    }
    payload.update(overrides)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class FakeOllama:
    """Client stub with one behaviour per model name."""

    def __init__(self, *, interrupt_on: str | None = None, loop_on: str | None = None) -> None:
        self.interrupt_on = interrupt_on
        self.loop_on = loop_on
        self.calls: list[str] = []

    def generate(self, **kwargs: Any) -> Any:
        model = kwargs["model"]
        self.calls.append(model)
        if kwargs.get("stream"):
            return self._stream(model)
        return SimpleNamespace(
            response=f"answer from {model}",
            thinking=None,
            total_duration=2_000_000_000,
            load_duration=500_000_000,
            prompt_eval_count=20,
            prompt_eval_duration=1_000_000_000,
            eval_count=10,
            eval_duration=1_000_000_000,
            done_reason="stop",
        )

    def _stream(self, model: str) -> Any:
        """Yield answer chunks; optionally raise ``KeyboardInterrupt`` or loop."""
        if model == self.interrupt_on:
            yield SimpleNamespace(response="partial answer", thinking=None)
            raise KeyboardInterrupt
        if model == self.loop_on:
            for _ in range(30):
                yield SimpleNamespace(response="the same line over and over\n", thinking=None)
            return
        yield SimpleNamespace(response=f"answer from {model}", thinking=None)


def install_fakes(monkeypatch: Any, client: FakeOllama, installed: set[str]) -> None:
    """Replace the Ollama client and the model listing with test doubles."""
    monkeypatch.setattr(cli, "create_client", lambda context: client)
    monkeypatch.setattr(cli, "list_installed_models", lambda _client: set(installed))


def test_run_writes_answer_log_and_summary(tmp_path, monkeypatch):
    settings = write_project(tmp_path)
    client = FakeOllama()
    install_fakes(monkeypatch, client, {"llama3.1:8b", "qwen3:8b"})

    assert cli.main(["--settings", str(settings)]) == cli.EXIT_SUCCESS
    assert client.calls == ["llama3.1:8b", "qwen3:8b"]

    answer = (tmp_path / "extractor_outputs" / "1_qwen3-8b.md").read_text(encoding="utf-8")
    assert "model: qwen3:8b" in answer
    assert "answer from qwen3:8b" in answer

    log = (tmp_path / "extractor_logs" / f"0_llama3.1-8b_{STAMP}.md").read_text(encoding="utf-8")
    assert "| Status | success |" in log
    assert "| Generated tokens | 10 |" in log

    summary = (tmp_path / "extractor_logs" / f"summary_{STAMP}.md").read_text(encoding="utf-8")
    assert "| 0 | `llama3.1:8b` | success |" in summary
    assert "| 1 | `qwen3:8b` | success |" in summary


def test_models_flag_overrides_the_settings_list(tmp_path, monkeypatch):
    settings = write_project(tmp_path)
    client = FakeOllama()
    install_fakes(monkeypatch, client, {"llama3.1:8b", "qwen3:8b"})

    assert cli.main(["--settings", str(settings), "--models", "qwen3:8b"]) == cli.EXIT_SUCCESS
    assert client.calls == ["qwen3:8b"]


def test_missing_model_is_skipped_and_logged(tmp_path, monkeypatch):
    settings = write_project(tmp_path)
    client = FakeOllama()
    install_fakes(monkeypatch, client, {"llama3.1:8b"})

    assert cli.main(["--settings", str(settings)]) == cli.EXIT_MODEL_FAILURE
    assert client.calls == ["llama3.1:8b"]

    log = (tmp_path / "extractor_logs" / f"1_qwen3-8b_{STAMP}.md").read_text(encoding="utf-8")
    assert "| Status | skipped |" in log
    assert "ollama pull qwen3:8b" in log


def test_interrupt_saves_partial_artefacts_and_exits_130(tmp_path, monkeypatch):
    settings = write_project(tmp_path, stream=True)
    client = FakeOllama(interrupt_on="llama3.1:8b")
    install_fakes(monkeypatch, client, {"llama3.1:8b", "qwen3:8b"})

    assert cli.main(["--settings", str(settings)]) == cli.EXIT_INTERRUPTED
    assert client.calls == ["llama3.1:8b"], "the second model must not start after an interrupt"

    answer = (tmp_path / "extractor_outputs" / "0_llama3.1-8b.md").read_text(encoding="utf-8")
    assert "status: interrupted" in answer
    assert "partial answer" in answer

    log = (tmp_path / "extractor_logs" / f"0_llama3.1-8b_{STAMP}.md").read_text(encoding="utf-8")
    assert "| Status | interrupted |" in log
    assert "| Interrupted | yes |" in log
    assert "| Estimated generated tokens | ~4 (from 14 characters) |" in log

    skipped = (tmp_path / "extractor_logs" / f"1_qwen3-8b_{STAMP}.md").read_text(encoding="utf-8")
    assert "not run: the run was interrupted" in skipped

    summary = (tmp_path / "extractor_logs" / f"summary_{STAMP}.md").read_text(encoding="utf-8")
    assert "| 1 | `qwen3:8b` | skipped |" in summary
    assert "- Run ended: interrupted by the user - partial results saved" in summary


def test_loop_guard_stops_a_repeating_model(tmp_path, monkeypatch):
    settings = write_project(
        tmp_path,
        stream=True,
        loop_guard=True,
        loop_guard_repeats=5,
        models=["llama3.1:8b"],
    )
    client = FakeOllama(loop_on="llama3.1:8b")
    install_fakes(monkeypatch, client, {"llama3.1:8b"})

    assert cli.main(["--settings", str(settings)]) == cli.EXIT_MODEL_FAILURE

    log = (tmp_path / "extractor_logs" / f"0_llama3.1-8b_{STAMP}.md").read_text(encoding="utf-8")
    assert "| Status | loop_detected |" in log
    assert "| Loop detected | yes |" in log

    answer = (tmp_path / "extractor_outputs" / "0_llama3.1-8b.md").read_text(encoding="utf-8")
    assert "status: loop_detected" in answer
    assert answer.count("the same line over and over") == 5


def test_dry_run_does_not_contact_ollama(tmp_path, monkeypatch, capsys):
    settings = write_project(tmp_path)

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the dry run must not contact Ollama")

    monkeypatch.setattr(cli, "create_client", explode)
    assert cli.main(["--settings", str(settings), "--dry-run"]) == cli.EXIT_SUCCESS

    assert not (tmp_path / "extractor_outputs").exists()
    captured = capsys.readouterr().out
    assert "data budget" in captured
    assert "0_llama3.1-8b.md" in captured


def test_oversized_input_is_refused_when_configured(tmp_path, monkeypatch):
    settings = write_project(tmp_path, options={"num_ctx": 64}, fail_on_context_overrun=True)
    (tmp_path / "species_database.txt").write_text(DATABASE * 60, encoding="utf-8")

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the run must be refused before contacting Ollama")

    monkeypatch.setattr(cli, "create_client", explode)
    assert cli.main(["--settings", str(settings)]) == cli.EXIT_CONFIGURATION_ERROR
