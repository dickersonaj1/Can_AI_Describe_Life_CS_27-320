"""Tests for the Markdown writers: answer files, per-model logs and summaries."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from feature_dictionary import writers
from feature_dictionary.context import RunContext
from feature_dictionary.runner import ModelMetrics, ModelRunResult
from feature_dictionary.settings import ExtractorSettings, LoadedSettings

STARTED = datetime(2026, 9, 18, 14, 3, 11)


def build_context(tmp_path: Path, **overrides) -> RunContext:
    payload = {
        "input_file": Path("species_database.txt"),
        "prompt": "Describe {species_database}",
        "models": ["llama3.1:8b", "qwen3:8b"],
    }
    payload.update(overrides)
    settings = ExtractorSettings(**payload)
    loaded = LoadedSettings(
        settings=settings,
        path=tmp_path / "settings.json",
        base_dir=tmp_path,
        input_path=tmp_path / "species_database.txt",
        output_dir=tmp_path / "extractor_outputs",
        log_dir=tmp_path / "extractor_logs",
        prompt_text=settings.prompt or "",
        ollama_host="http://127.0.0.1:11434",
    )
    return RunContext.from_settings(loaded, "species text", started_at=STARTED)


def build_metrics(**overrides) -> ModelMetrics:
    values = {
        "wall_clock_seconds": 41.23,
        "total_duration_ns": 40_980_000_000,
        "load_duration_ns": 310_000_000,
        "prompt_eval_count": 812,
        "prompt_eval_duration_ns": 8_420_000_000,
        "eval_count": 350,
        "eval_duration_ns": 33_180_000_000,
        "done_reason": "stop",
        "prompt_characters": 26,
        "response_characters": 1204,
    }
    values.update(overrides)
    return ModelMetrics(**values)


def build_result(tmp_path: Path, **overrides) -> ModelRunResult:
    values = {
        "index": 0,
        "model": "llama3.1:8b",
        "status": "success",
        "started_at": STARTED,
        "finished_at": STARTED,
        "output_path": tmp_path / "extractor_outputs" / "0_llama3.1-8b.md",
        "metrics": build_metrics(),
    }
    values.update(overrides)
    return ModelRunResult(**values)


def test_output_file_name_uses_index_and_slug(tmp_path):
    context = build_context(tmp_path)
    path = writers.write_output(
        context,
        index=0,
        model="llama3.1:8b",
        finished_at=STARTED,
        response_text="Answer body",
        thinking_text="",
    )
    assert path.name == "0_llama3.1-8b.md"
    assert path.exists()


def test_output_file_contains_a_metadata_header_and_the_answer(tmp_path):
    context = build_context(tmp_path)
    path = writers.write_output(
        context,
        index=1,
        model="qwen3:8b",
        finished_at=STARTED,
        response_text="Answer body",
        thinking_text="",
    )
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!--")
    assert "model: qwen3:8b" in text
    assert "prompt_fingerprint:" in text
    assert text.rstrip().endswith("Answer body")


def test_output_header_can_be_disabled(tmp_path):
    context = build_context(tmp_path, output_metadata_header=False)
    path = writers.write_output(
        context,
        index=0,
        model="llama3.1:8b",
        finished_at=STARTED,
        response_text="Answer body",
        thinking_text="",
    )
    assert path.read_text(encoding="utf-8") == "Answer body\n"


def test_thinking_is_appended_when_requested(tmp_path):
    context = build_context(tmp_path, include_thinking=True)
    path = writers.write_output(
        context,
        index=0,
        model="deepseek-r1:8b",
        finished_at=STARTED,
        response_text="Answer body",
        thinking_text="chain of thought",
    )
    text = path.read_text(encoding="utf-8")
    assert "## Thinking" in text
    assert "chain of thought" in text


def test_empty_response_is_marked(tmp_path):
    context = build_context(tmp_path)
    path = writers.write_output(
        context,
        index=0,
        model="llama3.1:8b",
        finished_at=STARTED,
        response_text="",
        thinking_text="",
    )
    assert "empty response" in path.read_text(encoding="utf-8")


def test_log_file_name_uses_index_model_and_date_stamp(tmp_path):
    context = build_context(tmp_path)
    path = writers.write_log(context, build_result(tmp_path))
    assert path.name == "0_llama3.1-8b_09_18.md"
    assert path.parent == context.log_dir


def test_log_file_records_timings_and_token_counts(tmp_path):
    context = build_context(tmp_path)
    text = writers.write_log(context, build_result(tmp_path)).read_text(encoding="utf-8")
    assert "# Extraction log — llama3.1:8b" in text
    assert "| Wall-clock time | 41.23 s |" in text
    assert "| Ollama total duration | 40.98 s |" in text
    assert "| Model load duration | 310.0 ms |" in text
    assert "| Prompt tokens | 812 |" in text
    assert "| Generated tokens | 350 |" in text
    assert "| Total tokens | 1,162 |" in text
    assert "| Generation rate | 10.55 tok/s |" in text
    assert "| Prompt eval rate | 96.44 tok/s |" in text
    assert "| Done reason | stop |" in text
    assert "| Run mode | sequential (max_concurrency=1) |" in text
    assert "`extractor_outputs/0_llama3.1-8b.md`" in text
    assert "### Notes" in text
    assert "No errors." in text


def test_second_run_of_the_same_day_is_appended(tmp_path):
    context = build_context(tmp_path)
    result = build_result(tmp_path)
    path = writers.write_log(context, result)
    writers.write_log(context, result)
    text = path.read_text(encoding="utf-8")
    assert text.count("# Extraction log") == 1
    assert text.count("## Run") == 2


def test_failed_model_is_logged_without_an_answer_file(tmp_path):
    context = build_context(tmp_path)
    result = build_result(
        tmp_path,
        index=1,
        model="qwen3:8b",
        status="skipped",
        output_path=None,
        metrics=None,
        error="model is not installed locally; run `ollama pull qwen3:8b` first",
    )
    path = writers.write_log(context, result)
    text = path.read_text(encoding="utf-8")
    assert path.name == "1_qwen3-8b_09_18.md"
    assert "| Status | skipped |" in text
    assert "| Wall-clock time | n/a |" in text
    assert "ollama pull qwen3:8b" in text
    assert not (context.output_dir / "1_qwen3-8b.md").exists()


def test_summary_lists_every_model(tmp_path):
    context = build_context(tmp_path)
    results = [
        build_result(tmp_path),
        build_result(
            tmp_path,
            index=1,
            model="qwen3:8b",
            status="error",
            output_path=None,
            metrics=None,
            error="Ollama returned status 500",
        ),
    ]
    path = writers.write_summary(context, results)
    text = path.read_text(encoding="utf-8")
    assert path.name == "summary_09_18.md"
    assert "| # | Model | Status |" in text
    assert "| 0 | `llama3.1:8b` | success |" in text
    assert "| 1 | `qwen3:8b` | error |" in text
    assert "10.55 tok/s" in text
    assert f"- Models requested: {len(context.models)}" in text


def test_second_summary_of_the_same_day_is_appended(tmp_path):
    context = build_context(tmp_path)
    path = writers.write_summary(context, [build_result(tmp_path)])
    writers.write_summary(context, [build_result(tmp_path)])
    text = path.read_text(encoding="utf-8")
    assert text.count("# Extraction summary") == 1
    assert text.count("## Run") == 2


def test_portable_path_falls_back_to_an_absolute_path(tmp_path):
    outside = tmp_path.parent / "elsewhere" / "file.md"
    assert writers.portable_path(outside, tmp_path) == outside.as_posix()


def test_interrupted_answer_is_marked_as_incomplete(tmp_path):
    context = build_context(tmp_path)
    path = writers.write_output(
        context,
        index=0,
        model="llama3.1:8b",
        finished_at=STARTED,
        response_text="Partial text",
        thinking_text="",
        status="interrupted",
    )
    text = path.read_text(encoding="utf-8")
    assert "status: interrupted" in text
    assert "interrupted by the user - this answer is incomplete" in text
    assert "Partial text" in text


def test_loop_detected_answer_is_marked_as_incomplete(tmp_path):
    context = build_context(tmp_path)
    path = writers.write_output(
        context,
        index=0,
        model="llama3.1:8b",
        finished_at=STARTED,
        response_text="looping text",
        thinking_text="",
        status="loop_detected",
    )
    text = path.read_text(encoding="utf-8")
    assert "status: loop_detected" in text
    assert "stopped by the loop guard" in text


def test_log_records_interrupt_rows_and_a_token_estimate(tmp_path):
    context = build_context(tmp_path)
    result = build_result(
        tmp_path,
        status="interrupted",
        error="the run was interrupted by the user; this answer is incomplete",
        metrics=build_metrics(
            eval_count=None,
            eval_duration_ns=None,
            done_reason=None,
            interrupted=True,
            response_characters=400,
        ),
    )
    text = writers.write_log(context, result).read_text(encoding="utf-8")
    assert "| Status | interrupted |" in text
    assert "| Interrupted | yes |" in text
    assert "| Loop detected | no |" in text
    assert "| Estimated generated tokens | ~100 (from 400 characters) |" in text
    assert "| Done reason | n/a |" in text
    assert "| Ollama options |" in text
    assert "| Data budget |" in text
    assert "interrupted by the user; this answer is incomplete" in text


def test_summary_reports_the_loop_guard(tmp_path):
    context = build_context(tmp_path, loop_guard=True, loop_guard_repeats=10)
    results = [
        build_result(tmp_path),
        build_result(
            tmp_path,
            index=1,
            model="qwen3:8b",
            status="loop_detected",
            metrics=build_metrics(loop_detected=True),
        ),
    ]
    text = writers.write_summary(context, results).read_text(encoding="utf-8")
    assert "| 1 | `qwen3:8b` | loop_detected |" in text
    assert "- Loop guard stopped: `qwen3:8b` (partial answers saved)" in text
    assert "- Loop guard: on (threshold 10 repeats)" in text
    assert "- Run ended: normally" in text


def test_summary_marks_an_interrupted_run(tmp_path):
    context = build_context(tmp_path)
    results = [
        build_result(tmp_path, status="interrupted", metrics=build_metrics(interrupted=True))
    ]
    text = writers.write_summary(context, results).read_text(encoding="utf-8")
    assert "- Run ended: interrupted by the user - partial results saved" in text
    assert "| 0 | `llama3.1:8b` | interrupted |" in text
