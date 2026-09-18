"""Command line interface for the Feature Dictionary extractor.

The flow is deliberately linear:

1. load and validate ``settings.json`` (plus any command line overrides),
2. read the text chunk in ``species_database.txt``,
3. render the prompt by substituting ``{species_database}``,
4. check that Ollama is reachable and that every requested model exists locally,
5. run the models sequentially by default, writing one answer per model,
6. write one log per model plus a cross-model comparison summary.

Exit codes: ``0`` every model succeeded, ``1`` at least one model failed or was
skipped, ``2`` the configuration or the Ollama connection was unusable.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama

from feature_dictionary import naming, writers
from feature_dictionary.context import RunContext
from feature_dictionary.runner import (
    GenerationInterrupted,
    GenerationOutcome,
    ModelRunResult,
    OllamaUnavailableError,
    create_client,
    list_installed_models,
    run_model,
)
from feature_dictionary.settings import SettingsError, load_settings, read_text_file

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = PROJECT_DIR / "settings.json"
LOGGER = logging.getLogger("feature_dictionary")

EXIT_SUCCESS = 0
EXIT_MODEL_FAILURE = 1
EXIT_CONFIGURATION_ERROR = 2
EXIT_INTERRUPTED = 130

STATUS_MESSAGES = {
    "interrupted": "the run was interrupted by the user; this answer is incomplete",
    "loop_detected": (
        "the loop guard stopped this model because it kept repeating the same lines; "
        "the partial answer was saved"
    ),
}
"""Notes recorded in the log of a run that did not finish on its own."""


class RunInterrupted(Exception):
    """Raised when the user interrupts the run; carries the partial result."""

    def __init__(self, result: ModelRunResult) -> None:
        super().__init__("run interrupted")
        self.result = result


def build_parser() -> argparse.ArgumentParser:
    """Define the command line surface."""
    parser = argparse.ArgumentParser(
        prog="extractor.py",
        description=(
            "Feed species_database.txt, wrapped in a configurable prompt, to several "
            "locally running Ollama models. Every answer is saved to "
            "extractor_outputs/{i}_<model_name>.md and every timing/token figure "
            "to extractor_logs/{i}_<model_name>_MM_DD.md."
        ),
        epilog=(
            "examples:\n"
            "  python extractor.py --dry-run\n"
            "  python extractor.py --models llama3.1:8b\n"
            "  python extractor.py --models llama3.1:8b,qwen3:8b\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--settings",
        default=str(DEFAULT_SETTINGS_PATH),
        help="Path to settings.json (default: the file next to this project).",
    )
    parser.add_argument(
        "--input",
        dest="input_file",
        help="Override 'input_file' from settings.json.",
    )
    parser.add_argument(
        "--prompt-file",
        dest="prompt_file",
        help="Use a prompt file instead of the inline 'prompt' from settings.json.",
    )
    parser.add_argument(
        "--models",
        help="Comma separated models to run instead of the list in settings.json.",
    )
    parser.add_argument("--output-dir", dest="output_dir", help="Override 'output_dir'.")
    parser.add_argument("--log-dir", dest="log_dir", help="Override 'log_dir'.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the resolved configuration and target file names without calling Ollama.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Verbosity of the diagnostic log on stderr.",
    )
    return parser


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )


def _parse_models(value: str) -> list[str]:
    """Split a ``--models a,b,c`` argument."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Translate command line flags into settings.json overrides."""
    overrides: dict[str, Any] = {}
    if args.input_file:
        overrides["input_file"] = args.input_file
    if args.prompt_file:
        overrides["prompt_file"] = args.prompt_file
        overrides["prompt"] = None
    if args.models:
        overrides["models"] = _parse_models(args.models)
    if args.output_dir:
        overrides["output_dir"] = args.output_dir
    if args.log_dir:
        overrides["log_dir"] = args.log_dir
    return overrides


def _console_streamer() -> Callable[[str, str], None]:
    """Return a callback that echoes streamed answer text to stdout."""

    def on_chunk(response_piece: str, _thinking_piece: str) -> None:
        if response_piece:
            sys.stdout.write(response_piece)
            sys.stdout.flush()

    return on_chunk


def _failure_result(
    context: RunContext,
    *,
    index: int,
    model: str,
    status: str,
    message: str,
    started_at: datetime,
) -> ModelRunResult:
    """Record a model that could not run (or could not finish) and log it."""
    result = ModelRunResult(
        index=index,
        model=model,
        status=status,
        started_at=started_at,
        finished_at=datetime.now().astimezone(),
        error=message,
    )
    result.log_path = writers.write_log(context, result)
    return result


def _write_outcome(
    context: RunContext,
    *,
    index: int,
    model: str,
    started_at: datetime,
    outcome: GenerationOutcome,
    status: str,
) -> ModelRunResult:
    """Persist an answer (complete or partial) together with its log."""
    finished_at = datetime.now().astimezone()
    output_path = writers.write_output(
        context,
        index=index,
        model=model,
        finished_at=finished_at,
        response_text=outcome.response_text,
        thinking_text=outcome.thinking_text,
        status=status,
    )
    result = ModelRunResult(
        index=index,
        model=model,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        output_path=output_path,
        metrics=outcome.metrics,
        error=STATUS_MESSAGES.get(status),
    )
    result.log_path = writers.write_log(context, result)
    return result


def _run_single(
    context: RunContext,
    client: ollama.Client,
    *,
    index: int,
    model: str,
    position: int | None,
    total: int,
    announce: bool,
) -> ModelRunResult:
    """Run one model, write its answer and its log.

    Every failure is captured in the result. Only a user interrupt escapes, as
    :class:`RunInterrupted`, which still carries the partial answer that was saved.
    """
    settings = context.settings.settings
    started_at = datetime.now().astimezone()
    if announce:
        print(f"[{position}/{total}] {model} - running", flush=True)

    callback = _console_streamer() if announce and settings.stream else None
    try:
        outcome = run_model(
            client,
            model=model,
            prompt=context.prompt_text,
            options=context.run_options,
            keep_alive=settings.keep_alive,
            stream=settings.stream,
            on_chunk=callback,
            loop_guard=settings.loop_guard,
            loop_guard_repeats=settings.loop_guard_repeats,
        )
    except GenerationInterrupted as exc:
        if announce:
            print()
        LOGGER.warning("%s - interrupted by the user, saving the partial answer", model)
        partial = _write_outcome(
            context,
            index=index,
            model=model,
            started_at=started_at,
            outcome=exc.outcome,
            status="interrupted",
        )
        raise RunInterrupted(partial) from exc
    except ConnectionError as exc:
        return _failure_result(
            context,
            index=index,
            model=model,
            status="error",
            message=f"the Ollama server became unreachable ({exc})",
            started_at=started_at,
        )
    except ollama.ResponseError as exc:
        return _failure_result(
            context,
            index=index,
            model=model,
            status="error",
            message=f"Ollama returned status {exc.status_code}: {exc.error}",
            started_at=started_at,
        )
    except Exception as exc:  # one bad model must never abort the whole run
        LOGGER.debug("model %s failed", model, exc_info=True)
        return _failure_result(
            context,
            index=index,
            model=model,
            status="error",
            message=f"{type(exc).__name__}: {exc}",
            started_at=started_at,
        )

    status = "loop_detected" if outcome.metrics.loop_detected else "success"
    if status == "loop_detected":
        LOGGER.warning(
            "%s - stopped by the loop guard after %s repeats; partial answer saved",
            model,
            settings.loop_guard_repeats,
        )
    return _write_outcome(
        context,
        index=index,
        model=model,
        started_at=started_at,
        outcome=outcome,
        status=status,
    )


def _execute(
    context: RunContext,
    client: ollama.Client,
    jobs: list[tuple[int, str]],
) -> list[ModelRunResult]:
    """Run the queued models sequentially (default) or with a small thread pool."""
    total = len(jobs)
    if context.is_sequential:
        return [
            _run_single(
                context,
                client,
                index=index,
                model=model,
                position=position,
                total=total,
                announce=True,
            )
            for position, (index, model) in enumerate(jobs, start=1)
        ]

    LOGGER.warning(
        "running %s models with max_concurrency=%s - timings will include GPU contention",
        total,
        context.max_concurrency,
    )
    results: list[ModelRunResult] = []
    executor = ThreadPoolExecutor(max_workers=context.max_concurrency)
    try:
        futures = [
            executor.submit(
                _run_single,
                context,
                client,
                index=index,
                model=model,
                position=None,
                total=total,
                announce=False,
            )
            for index, model in jobs
        ]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except RunInterrupted:
                for pending in futures:
                    pending.cancel()
                raise
            except Exception as exc:  # defensive: keep the remaining models running
                LOGGER.error("a model worker crashed unexpectedly: %s", exc)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return results


def _report(context: RunContext, result: ModelRunResult) -> None:
    """Print one line per model summarising what was measured and written."""
    metrics = result.metrics
    if metrics is None:
        print(f"  {result.index}  {result.model} - {result.status}: {result.error}")
        return
    rate = metrics.generation_tokens_per_second
    rate_text = f"{rate:,.1f} tok/s" if rate else "n/a"
    generated = naming.format_count(metrics.eval_count)
    if metrics.eval_count is None and metrics.response_characters:
        generated = f"~{metrics.estimated_generation_tokens:,} (estimated)"
    print(
        f"  {result.index}  {result.model} - {result.status} after"
        f" {naming.format_seconds(metrics.wall_clock_seconds)}"
        f" | generated {generated} tokens @ {rate_text}"
        f" | total {naming.format_count(metrics.total_tokens)} tokens"
    )
    relative = writers.portable_path
    base_dir = context.settings.base_dir
    if result.output_path:
        print(f"      answer -> {relative(result.output_path, base_dir)}")
    if result.log_path:
        print(f"      log    -> {relative(result.log_path, base_dir)}")


def _print_dry_run(context: RunContext) -> None:
    """Describe the resolved run without contacting Ollama."""
    settings = context.settings.settings

    def portable(path: Path) -> str:
        return writers.portable_path(path, context.settings.base_dir)

    print("dry run - nothing is sent to Ollama")
    print(f"  settings file   : {portable(context.settings.path)}")
    print(f"  ollama host     : {context.settings.ollama_host}")
    print(
        f"  input file      : {portable(context.settings.input_path)}"
        f" ({context.input_characters_total:,} characters)"
    )
    print(
        f"  input used      : {len(context.database_text):,} characters"
        f" (truncated: {'yes' if context.input_truncated else 'no'})"
    )
    print(
        f"  prompt          : {len(context.prompt_text):,} characters,"
        f" about {context.estimated_prompt_tokens:,} tokens,"
        f" fingerprint {context.prompt_fingerprint}"
    )
    print(f"  num_ctx         : {context.num_ctx:,}")
    print(
        f"  data budget     : {context.data_budget_characters:,} characters"
        f" (input fits: {'yes' if context.input_fits else 'no'})"
    )
    print(f"  ollama options  : {writers.format_options(context.run_options)}")
    print(
        f"  loop guard      : {'on' if settings.loop_guard else 'off'}"
        f" (threshold {settings.loop_guard_repeats} repeats)"
    )
    print(f"  run mode        : {context.run_mode}")
    print(f"  keep alive      : {context.keep_alive_label}")
    print(f"  streaming       : {settings.stream}")
    print(f"  output dir      : {portable(context.output_dir)}")
    print(f"  log dir         : {portable(context.log_dir)}")
    print(f"  date stamp      : {context.started_at.strftime(settings.log_date_format)}")
    print("  targets:")
    for position, model in enumerate(context.models):
        index = naming.model_index(position, context.index_base)
        print(f"    {index}  {model}")
        print(f"        answer -> {portable(writers.output_path_for(context, index, model))}")
        print(f"        log    -> {portable(writers.log_path_for(context, index, model))}")

    if not context.input_fits:
        print("")
        print(
            f"  WARNING: the input is {len(context.database_text):,} characters but only about"
            f" {context.data_budget_characters:,} characters"
        )
        print(
            f"           fit alongside the instructions (num_ctx {context.num_ctx:,},"
            f" ~{context.instruction_tokens:,} instruction tokens,"
            f" output cap {settings.max_output_tokens or 'unset'})."
        )
        print("           Ollama keeps only the TAIL of an over-long prompt, so every model would")
        print("           see just the end of the input. Run a smaller excerpt with --input,")
        print("           set 'max_input_characters', raise 'num_ctx' under 'options', or set")
        print("           'fail_on_context_overrun' to true to block the run.")

    preview = context.prompt_text.strip().splitlines()
    print("")
    print("  prompt preview:")
    for line in preview[:10]:
        print(f"    {line[:110]}")
    if len(preview) > 10:
        print(f"    ... ({len(preview):,} prompt lines in total)")


def main(argv: list[str] | None = None) -> int:
    """Run the extractor.

    Used by ``extractor.py``, ``python -m feature_dictionary`` and the
    ``feature-dictionary`` console script.
    """
    args = build_parser().parse_args(argv)
    _configure_logging(args.log_level)

    if args.models is not None and not _parse_models(args.models):
        print("error: --models needs at least one model identifier", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    try:
        loaded = load_settings(args.settings, overrides=_overrides_from_args(args))
        database_text = read_text_file(loaded.input_path)
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR
    except OSError as exc:
        print(f"error: cannot read the input file: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    context = RunContext.from_settings(loaded, database_text)

    if args.dry_run:
        _print_dry_run(context)
        return EXIT_SUCCESS

    if not context.input_fits:
        message = (
            f"the input is {len(context.database_text):,} characters but only about"
            f" {context.data_budget_characters:,} fit alongside the instructions;"
            " Ollama keeps only the tail of an over-long prompt, so each model would see"
            " just the end of the input"
        )
        if loaded.settings.fail_on_context_overrun:
            print(f"error: {message}", file=sys.stderr)
            return EXIT_CONFIGURATION_ERROR
        print(f"warning: {message}", file=sys.stderr)

    writers.ensure_directory(context.output_dir)
    writers.ensure_directory(context.log_dir)

    client = create_client(context)
    try:
        installed = list_installed_models(client)
    except OllamaUnavailableError as exc:
        print(
            f"error: cannot reach the Ollama server at {loaded.ollama_host} ({exc})",
            file=sys.stderr,
        )
        print(
            "hint: start it with 'ollama serve' or the Ollama desktop app and try again.",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION_ERROR

    jobs: list[tuple[int, str]] = []
    results: list[ModelRunResult] = []
    for position, model in enumerate(context.models):
        index = naming.model_index(position, context.index_base)
        if model in installed:
            jobs.append((index, model))
            continue
        message = f"model is not installed locally; run `ollama pull {model}` first"
        LOGGER.warning("%s - %s", model, message)
        results.append(
            _failure_result(
                context,
                index=index,
                model=model,
                status="skipped",
                message=message,
                started_at=datetime.now().astimezone(),
            )
        )
        if not loaded.settings.continue_on_error:
            print(f"error: {model} — {message}", file=sys.stderr)
            return EXIT_CONFIGURATION_ERROR

    print(
        f"input : {writers.portable_path(loaded.input_path, loaded.base_dir)}"
        f" ({context.input_characters_total:,} characters)"
    )
    print(
        f"prompt: {len(context.prompt_text):,} characters, about"
        f" {context.estimated_prompt_tokens:,} tokens (num_ctx {context.num_ctx:,})"
    )
    print(
        f"models: {len(context.models)} requested, {len(jobs)} queued"
        f" | run mode: {context.run_mode}"
    )
    print("")

    interrupted = False
    try:
        results.extend(_execute(context, client, jobs))
    except RunInterrupted as exc:
        results.append(exc.result)
        interrupted = True
    except KeyboardInterrupt:
        LOGGER.warning("interrupted before the next model started")
        interrupted = True

    if interrupted:
        known = {result.index for result in results}
        for index, model in jobs:
            if index in known:
                continue
            results.append(
                _failure_result(
                    context,
                    index=index,
                    model=model,
                    status="skipped",
                    message="not run: the run was interrupted by the user",
                    started_at=datetime.now().astimezone(),
                )
            )
    results.sort(key=lambda item: item.index)

    print("")
    for result in results:
        _report(context, result)

    if loaded.settings.write_run_summary:
        summary_path = writers.write_summary(context, results)
        print(f"\nsummary -> {writers.portable_path(summary_path, loaded.base_dir)}")

    if interrupted:
        print(
            "\ninterrupted - the partial answer, log and summary above were saved."
            " Re-run the remaining models with --models to fill in the gaps.",
            file=sys.stderr,
        )
        return EXIT_INTERRUPTED

    failures = [result for result in results if not result.succeeded]
    if failures:
        print(f"\n{len(failures)} of {len(results)} models did not succeed.", file=sys.stderr)
        return EXIT_MODEL_FAILURE
    print(f"\nall {len(results)} models succeeded.")
    return EXIT_SUCCESS
