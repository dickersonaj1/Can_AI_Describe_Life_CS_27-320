"""Markdown writers for model answers, per-model logs and the run summary.

Every artefact is plain UTF-8 Markdown with LF line endings so it renders the
same way on Windows, in GitHub and in an editor:

* ``extractor_outputs/{i}_<model_name>.md`` — the answer itself.
* ``extractor_logs/{i}_<model_name>_MM_DD.md`` — timings and token counts.
* ``extractor_logs/summary_MM_DD.md`` — one row per model for comparing runs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from feature_dictionary import naming
from feature_dictionary.context import RunContext
from feature_dictionary.runner import ModelRunResult

SUMMARY_COLUMNS = (
    "#",
    "Model",
    "Status",
    "Wall-clock",
    "Load",
    "Prompt tokens",
    "Generated tokens",
    "Total tokens",
    "Generation rate",
    "Output",
)

STATUS_NOTES = {
    "interrupted": "interrupted by the user - this answer is incomplete",
    "loop_detected": (
        "stopped by the loop guard because the model kept repeating itself - "
        "this answer is incomplete"
    ),
}
"""Explanatory footer used in the answer file for runs that did not finish."""


def format_options(options: dict[str, Any]) -> str:
    """Render Ollama options compactly for the log file and the dry run."""
    if not options:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(options.items()))


def ensure_directory(path: Path) -> None:
    """Create ``path`` (and its parents) if it does not exist yet."""
    path.mkdir(parents=True, exist_ok=True)


def portable_path(path: Path, base_dir: Path) -> str:
    """Prefer a path relative to the project so logs stay portable."""
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return path.as_posix()


def write_text(path: Path, content: str, *, append: bool = False) -> None:
    """Write UTF-8 text with LF endings, optionally appending to an existing file."""
    ensure_directory(path.parent)
    if append and path.exists():
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n" + content)
        return
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def output_path_for(run: RunContext, index: int, model: str) -> Path:
    """``{i}_<model_name>.md`` inside the output directory."""
    return run.output_dir / naming.output_filename(index, model)


def log_path_for(run: RunContext, index: int, model: str) -> Path:
    """``{i}_<model_name>_MM_DD.md`` inside the log directory."""
    return run.log_dir / naming.log_filename(
        index,
        model,
        run.started_at,
        run.settings.settings.log_date_format,
    )


def summary_path_for(run: RunContext) -> Path:
    """``summary_MM_DD.md`` inside the log directory."""
    return run.log_dir / naming.summary_filename(
        run.started_at,
        run.settings.settings.log_date_format,
    )


def build_output_markdown(
    run: RunContext,
    *,
    index: int,
    model: str,
    finished_at: datetime,
    response_text: str,
    thinking_text: str,
    status: str = "success",
) -> str:
    """Render one model answer, optionally preceded by a metadata comment."""
    parts: list[str] = []
    if run.settings.settings.output_metadata_header:
        parts.append(
            "\n".join(
                [
                    "<!--",
                    f"model: {model}",
                    f"model_index: {index}",
                    f"status: {status}",
                    f"run_id: {run.run_id}",
                    f"input_file: {run.settings.input_path.name}",
                    f"input_characters_used: {len(run.database_text):,}",
                    f"input_characters_total: {run.input_characters_total:,}",
                    f"input_truncated: {'yes' if run.input_truncated else 'no'}",
                    f"prompt_characters: {len(run.prompt_text):,}",
                    f"prompt_fingerprint: {run.prompt_fingerprint}",
                    f"generated_at: {finished_at.isoformat(timespec='seconds')}",
                    "-->",
                ]
            )
        )
    body = response_text.strip()
    parts.append(body or "<!-- the model returned an empty response -->")
    if status in STATUS_NOTES:
        parts.append(f"<!-- {STATUS_NOTES[status]} -->")
    if run.settings.settings.include_thinking and thinking_text.strip():
        parts.append(f"---\n\n## Thinking\n\n{thinking_text.strip()}")
    return "\n\n".join(parts).rstrip("\n") + "\n"


def write_output(
    run: RunContext,
    *,
    index: int,
    model: str,
    finished_at: datetime,
    response_text: str,
    thinking_text: str,
    status: str = "success",
) -> Path:
    """Write the model answer and return the path it was written to."""
    path = output_path_for(run, index, model)
    write_text(
        path,
        build_output_markdown(
            run,
            index=index,
            model=model,
            finished_at=finished_at,
            response_text=response_text,
            thinking_text=thinking_text,
            status=status,
        ),
    )
    return path


def _log_rows(run: RunContext, result: ModelRunResult) -> list[tuple[str, str]]:
    """Every timing and token figure recorded for one model."""
    metrics = result.metrics

    def metric(name: str) -> Any:
        return getattr(metrics, name, None) if metrics is not None else None

    prompt_tokens = metric("prompt_eval_count")
    prompt_duration = metric("prompt_eval_duration_ns")
    generated_tokens = metric("eval_count")
    generation_duration = metric("eval_duration_ns")
    overrun = run.context_overrun
    estimated_generation = "n/a"
    if metrics is not None and metrics.eval_count is None and metrics.response_characters:
        estimated_generation = (
            f"~{metrics.estimated_generation_tokens:,}"
            f" (from {metrics.response_characters:,} characters)"
        )
    output_reference = (
        portable_path(result.output_path, run.settings.base_dir) if result.output_path else "n/a"
    )
    return [
        ("Status", result.status),
        ("Model", f"`{result.model}`"),
        ("Model index", str(result.index)),
        ("Run id", run.run_id),
        ("Run mode", run.run_mode),
        ("Keep alive", run.keep_alive_label),
        ("Ollama options", f"`{format_options(run.run_options)}`"),
        ("Ollama host", run.settings.ollama_host),
        ("Started", result.started_at.isoformat(timespec="seconds")),
        ("Finished", result.finished_at.isoformat(timespec="seconds")),
        ("Wall-clock time", naming.format_seconds(metric("wall_clock_seconds"))),
        ("Ollama total duration", naming.format_duration_ns(metric("total_duration_ns"))),
        ("Model load duration", naming.format_duration_ns(metric("load_duration_ns"))),
        ("Prompt tokens", naming.format_count(prompt_tokens)),
        ("Prompt eval duration", naming.format_duration_ns(prompt_duration)),
        ("Prompt eval rate", naming.format_rate(prompt_tokens, prompt_duration)),
        ("Generated tokens", naming.format_count(generated_tokens)),
        ("Generation duration", naming.format_duration_ns(generation_duration)),
        ("Generation rate", naming.format_rate(generated_tokens, generation_duration)),
        ("Total tokens", naming.format_count(metrics.total_tokens if metrics else None)),
        ("Estimated generated tokens", estimated_generation),
        ("Done reason", metric("done_reason") or "n/a"),
        ("Interrupted", "yes" if metrics is not None and metrics.interrupted else "no"),
        ("Loop detected", "yes" if metrics is not None and metrics.loop_detected else "no"),
        ("Input characters used", naming.format_count(len(run.database_text))),
        ("Input characters in file", naming.format_count(run.input_characters_total)),
        ("Input truncated", "yes" if run.input_truncated else "no"),
        ("Prompt characters", naming.format_count(len(run.prompt_text))),
        ("Prompt fingerprint", run.prompt_fingerprint),
        ("Estimated prompt tokens", naming.format_count(run.estimated_prompt_tokens)),
        ("num_ctx", naming.format_count(run.num_ctx)),
        ("Data budget", f"{run.data_budget_characters:,} characters"),
        ("Input fits budget", "yes" if run.input_fits else "no"),
        (
            "Context overrun",
            f"yes (about {overrun[0]:,} tokens vs {overrun[1]:,} available)" if overrun else "no",
        ),
        ("Response characters", naming.format_count(metric("response_characters"))),
        ("Thinking characters", naming.format_count(metric("thinking_characters"))),
        ("Output file", f"`{output_reference}`"),
    ]


def build_log_markdown(
    run: RunContext,
    result: ModelRunResult,
    *,
    include_title: bool = True,
) -> str:
    """Render the per-model log file (one ``## Run`` block per execution)."""
    table = "\n".join(
        [
            "| Field | Value |",
            "| --- | --- |",
            *(f"| {key} | {value} |" for key, value in _log_rows(run, result)),
        ]
    )
    sections: list[str] = []
    if include_title:
        sections.append(f"# Extraction log — {result.model}")
    sections.append(f"## Run {run.run_id}")
    sections.append(table)
    sections.append(f"### Notes\n\n{result.error or 'No errors.'}")
    return "\n\n".join(sections).rstrip("\n") + "\n"


def write_log(run: RunContext, result: ModelRunResult) -> Path:
    """Write (or append to) the log for one model and return its path."""
    path = log_path_for(run, result.index, result.model)
    append = run.settings.settings.log_append and path.exists()
    write_text(path, build_log_markdown(run, result, include_title=not append), append=append)
    return path


def _summary_row(run: RunContext, result: ModelRunResult) -> list[str]:
    """One comparison-table row for a model."""
    metrics = result.metrics

    def metric(name: str) -> Any:
        return getattr(metrics, name, None) if metrics is not None else None

    output_reference = (
        f"`{portable_path(result.output_path, run.settings.base_dir)}`"
        if result.output_path
        else "n/a"
    )
    return [
        str(result.index),
        f"`{result.model}`",
        result.status,
        naming.format_seconds(metric("wall_clock_seconds")),
        naming.format_duration_ns(metric("load_duration_ns")),
        naming.format_count(metric("prompt_eval_count")),
        naming.format_count(metric("eval_count")),
        naming.format_count(metrics.total_tokens if metrics else None),
        naming.format_rate(metric("eval_count"), metric("eval_duration_ns")),
        output_reference,
    ]


def build_summary_markdown(
    run: RunContext,
    results: list[ModelRunResult],
    *,
    include_title: bool = True,
) -> str:
    """Render the cross-model comparison table."""
    interrupted = any(
        result.metrics is not None and result.metrics.interrupted for result in results
    )
    looped = [
        result.model
        for result in results
        if result.metrics is not None and result.metrics.loop_detected
    ]
    ended = "interrupted by the user - partial results saved" if interrupted else "normally"
    detail_lines = [
        f"- Models requested: {len(run.models)}",
        f"- Run mode: {run.run_mode}",
        f"- Keep alive: {run.keep_alive_label}",
        f"- Ollama options: `{format_options(run.run_options)}`",
        f"- Ollama host: {run.settings.ollama_host}",
        f"- Input file: `{portable_path(run.settings.input_path, run.settings.base_dir)}`"
        f" ({run.input_characters_total:,} characters)",
        f"- Input used: {len(run.database_text):,} characters"
        f" (truncated: {'yes' if run.input_truncated else 'no'})",
        f"- Prompt: {len(run.prompt_text):,} characters, fingerprint `{run.prompt_fingerprint}`",
        f"- Context window: num_ctx {run.num_ctx:,}"
        f" (estimated prompt tokens {run.estimated_prompt_tokens:,})",
        f"- Data budget: {run.data_budget_characters:,} characters"
        f" (fits: {'yes' if run.input_fits else 'NO - the model saw only the tail'})",
        f"- Loop guard: {'on' if run.settings.settings.loop_guard else 'off'}"
        f" (threshold {run.settings.settings.loop_guard_repeats} repeats)",
        f"- Run ended: {ended}",
        f"- Output directory: `{portable_path(run.output_dir, run.settings.base_dir)}`",
        f"- Log directory: `{portable_path(run.log_dir, run.settings.base_dir)}`",
    ]
    if looped:
        names = ", ".join(f"`{name}`" for name in looped)
        detail_lines.append(f"- Loop guard stopped: {names} (partial answers saved)")
    details = "\n".join(detail_lines)
    table = "\n".join(
        [
            "| " + " | ".join(SUMMARY_COLUMNS) + " |",
            "| " + " | ".join("---" for _ in SUMMARY_COLUMNS) + " |",
            *("| " + " | ".join(_summary_row(run, result)) + " |" for result in results),
        ]
    )
    sections: list[str] = []
    if include_title:
        sections.append(f"# Extraction summary — {run.run_id}")
    sections.append(f"## Run {run.run_id}")
    sections.append(details)
    sections.append(table)
    return "\n\n".join(sections).rstrip("\n") + "\n"


def write_summary(run: RunContext, results: list[ModelRunResult]) -> Path:
    """Write the run summary and return its path."""
    path = summary_path_for(run)
    append = run.settings.settings.log_append and path.exists()
    write_text(path, build_summary_markdown(run, results, include_title=not append), append=append)
    return path
