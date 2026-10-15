"""Command line interface for the Feature Dictionary extractor.

The flow is deliberately linear:

1. load and validate ``settings.json`` (plus any command line overrides),
2. read the text chunk in ``species_database.txt``,
3. render the prompt by substituting ``{species_database}``,
4. check local model availability when Ollama models are selected,
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
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama
from anthropic import Anthropic
from dotenv import load_dotenv
from google import genai
from openai import OpenAI

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
from feature_dictionary.runners import anthropic_runner, cloud_runner, gemini_runner
from feature_dictionary.settings import (
    DEFAULT_ANTHROPIC_OUTPUT_TOKENS,
    SettingsError,
    decode_text,
    load_settings,
    parse_model_selection,
    read_text_file,
)
from feature_dictionary.settings import (
    MODEL_ALIASES as MODEL_ALIASES,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = PROJECT_DIR / "settings.json"
LOGGER = logging.getLogger("feature_dictionary")

EXIT_SUCCESS = 0
EXIT_MODEL_FAILURE = 1
EXIT_CONFIGURATION_ERROR = 2
EXIT_INTERRUPTED = 130

# Retain the existing private helper name for callers/tests; resolution lives with settings.
_parse_models = parse_model_selection

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
        self.completed_results: list[ModelRunResult] = []


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Define the command line surface."""
    parser = argparse.ArgumentParser(
        prog="extractor.py",
        description=(
            "Feed species_database.txt, wrapped in a configurable prompt, to several "
            "local Ollama or cloud models. Every answer is saved to "
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
        "--extraction-format",
        choices=["v2", "v3"],
        help="Extraction format: v2 Markdown (default) or opt-in v3 evidence JSON.",
    )
    parser.add_argument(
        "--v3-candidate-version",
        choices=["3.0", "3.1"],
        help="Candidate contract for v3 runs (default: 3.1); 3.0 preserves legacy validation.",
    )
    parser.add_argument(
        "--ollama-think",
        choices=["true", "false", "default"],
        help="Ollama thinking request; default omits think. Does not affect cloud providers.",
    )
    parser.add_argument(
        "--ollama-output-format",
        choices=["candidate-schema", "default"],
        help="Opt-in Ollama extraction-3.1 schema constraint; default omits format.",
    )
    parser.add_argument(
        "--anthropic-output-format",
        choices=["candidate-schema", "default"],
        help="Opt-in Anthropic native extraction-3.1 JSON schema; default omits output_config.",
    )
    parser.add_argument(
        "--models",
        help=(
            "Comma-separated provider:model selectors, configured IDs, or known aliases. "
            "Legacy provider=model and known local shorthand remain supported."
        ),
    )
    parser.add_argument("--output-dir", dest="output_dir", help="Override 'output_dir'.")
    parser.add_argument(
        "--max-output-tokens",
        type=_positive_integer,
        metavar="N",
        help="Override the generated-token budget for all providers, including Ollama num_predict.",
    )
    parser.add_argument("--log-dir", dest="log_dir", help="Override 'log_dir'.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show the resolved configuration and target file names without contacting a provider."
        ),
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


def _overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Translate command line flags into settings.json overrides."""
    overrides: dict[str, Any] = {}
    if args.input_file:
        overrides["input_file"] = args.input_file
    if args.max_output_tokens is not None:
        overrides["max_output_tokens"] = args.max_output_tokens
    if args.extraction_format is not None:
        overrides["extraction_format"] = args.extraction_format
    if args.v3_candidate_version is not None:
        overrides["v3_candidate_version"] = args.v3_candidate_version
    if args.ollama_think is not None:
        overrides["ollama_think"] = {"true": True, "false": False, "default": None}[
            args.ollama_think
        ]
    if args.ollama_output_format is not None:
        overrides["ollama_output_format"] = (
            "candidate_schema" if args.ollama_output_format == "candidate-schema" else None
        )
    if args.anthropic_output_format is not None:
        overrides["anthropic_output_format"] = (
            "candidate_schema" if args.anthropic_output_format == "candidate-schema" else None
        )
    if args.prompt_file:
        overrides["prompt_file"] = args.prompt_file
        overrides["prompt"] = None
    if args.models is not None:
        overrides["models"] = args.models  # Resolve against configured providers when loading.
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


def _print_cloud_response(outcome: GenerationOutcome) -> None:
    """Print a completed cloud-model response to stdout."""
    print()
    print(outcome.response_text)
    print()


def _failure_result(
    context: RunContext,
    *,
    index: int,
    model: str,
    status: str,
    message: str,
    started_at: datetime,
    response_text: str = "",
    thinking_text: str = "",
    response_available: bool = False,
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
    if context.settings.settings.extraction_format == "v3":
        writers.write_v3_output(
            context,
            index=index,
            model=model,
            finished_at=result.finished_at,
            response_text=response_text,
            thinking_text=thinking_text,
            status=status,
            completion_reason=None,
            response_available=response_available,
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
    validation_error = None
    if context.settings.settings.extraction_format == "v3":
        report = writers.write_v3_output(
            context,
            index=index,
            model=model,
            finished_at=finished_at,
            response_text=outcome.response_text,
            thinking_text=outcome.thinking_text,
            status=status,
            completion_reason=outcome.metrics.done_reason,
        )
        output_path = None
        if status == "success" and report.evidence_valid:
            output_path = writers.output_path_for(context, index, model)
        elif status == "success":
            status = "invalid_output"
            validation_error = "v3 evidence validation failed; inspect the validation report"
    else:
        output_path = writers.write_output(
            context,
            index=index,
            model=model,
            finished_at=finished_at,
            response_text=outcome.response_text,
            thinking_text=outcome.thinking_text,
            status=status,
            completion_reason=outcome.metrics.done_reason,
        )
    result = ModelRunResult(
        index=index,
        model=model,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        output_path=output_path,
        metrics=outcome.metrics,
        error=validation_error
        or STATUS_MESSAGES.get(status)
        or (outcome.metrics.done_reason if status != "success" else None),
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
    received: list[tuple[str, str]] = []
    if settings.extraction_format == "v3" and settings.stream:
        console_callback = callback

        def capture_chunk(response: str, thinking: str) -> None:
            received.append((response, thinking))
            if console_callback is not None:
                console_callback(response, thinking)

        callback = capture_chunk

    def partial_text() -> dict[str, Any]:
        return {
            "response_text": "".join(piece[0] for piece in received),
            "thinking_text": "".join(piece[1] for piece in received),
            "response_available": bool(received),
        }

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
            **({"think": settings.ollama_think} if settings.ollama_think is not None else {}),
            **(
                {"output_schema": context.ollama_output_schema}
                if settings.ollama_output_format is not None
                else {}
            ),
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
    except KeyboardInterrupt as exc:
        if settings.extraction_format != "v3":
            raise
        partial = _failure_result(
            context,
            index=index,
            model=model,
            status="interrupted",
            message=STATUS_MESSAGES["interrupted"],
            started_at=started_at,
            **partial_text(),
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
            **partial_text(),
        )
    except ollama.ResponseError as exc:
        return _failure_result(
            context,
            index=index,
            model=model,
            status="error",
            message=f"Ollama returned status {exc.status_code}: {exc.error}",
            started_at=started_at,
            **partial_text(),
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
            **partial_text(),
        )

    status = outcome.completion_status
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


def _run_single_cloud(
    context: RunContext,
    client: OpenAI | Anthropic | genai.Client,
    *,
    runner: Callable[..., GenerationOutcome],
    index: int,
    model: str,
    position: int,
    total: int,
) -> ModelRunResult:
    """Apply shared reporting and persistence around a cloud provider call."""
    started_at = datetime.now().astimezone()
    print(f"[{position}/{total}] {model} - running", flush=True)
    provider = context.models[index - context.index_base].provider
    try:
        outcome = runner(
            client,
            model=model,
            prompt=context.prompt_text,
            max_output_tokens=context.settings.settings.max_output_tokens,
            **(
                {"output_schema": context.anthropic_output_schema}
                if provider == "anthropic" and context.settings.settings.anthropic_output_format
                else {}
            ),
        )
    except GenerationInterrupted as exc:
        partial = _write_outcome(
            context,
            index=index,
            model=model,
            started_at=started_at,
            outcome=exc.outcome,
            status="interrupted",
        )
        raise RunInterrupted(partial) from exc
    except KeyboardInterrupt as exc:
        result = _failure_result(
            context,
            index=index,
            model=model,
            status="interrupted",
            message=STATUS_MESSAGES["interrupted"],
            started_at=started_at,
        )
        raise RunInterrupted(result) from exc
    except Exception as exc:
        LOGGER.debug("model %s failed", model, exc_info=True)
        return _failure_result(
            context,
            index=index,
            model=model,
            status="failed",
            message=f"{type(exc).__name__}: {exc}",
            started_at=started_at,
        )
    if context.settings.settings.extraction_format == "v2":
        _print_cloud_response(outcome)
    result = _write_outcome(
        context,
        index=index,
        model=model,
        started_at=started_at,
        outcome=outcome,
        status=outcome.completion_status,
    )
    if context.settings.settings.extraction_format == "v3":
        try:
            _print_cloud_response(outcome)
        except KeyboardInterrupt as exc:
            raise RunInterrupted(result) from exc  # Already archived; do not write it again.
        except UnicodeEncodeError:
            LOGGER.warning(
                "response could not be displayed; exact text is preserved in its archive"
            )
    return result


def _execute(
    context: RunContext,
    client: ollama.Client,
    jobs: list[tuple[int, str]],
) -> list[ModelRunResult]:
    """Run the queued models sequentially (default) or with a small thread pool."""
    total = len(jobs)
    if context.is_sequential:
        results: list[ModelRunResult] = []
        for position, (index, model) in enumerate(jobs, start=1):
            try:
                results.append(
                    _run_single(
                        context,
                        client,
                        index=index,
                        model=model,
                        position=position,
                        total=total,
                        announce=True,
                    )
                )
            except RunInterrupted as exc:
                exc.completed_results = results
                raise
        return results

    LOGGER.warning(
        "running %s models with max_concurrency=%s - timings will include GPU contention",
        total,
        context.max_concurrency,
    )
    results: list[ModelRunResult] = []
    executor = ThreadPoolExecutor(max_workers=context.max_concurrency)
    interruption: RunInterrupted | None = None
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
            except RunInterrupted as exc:
                interruption = exc
                for pending in futures:
                    pending.cancel()
                break
            except (OSError, writers.OutputCollisionError):
                raise  # Do not report success after a worker could not preserve its artifacts.
            except Exception as exc:  # defensive: keep the remaining models running
                LOGGER.error("a model worker crashed unexpectedly: %s", exc)
    finally:
        # Running threads cannot be cancelled. Finish their writes before summarizing.
        executor.shutdown(wait=True, cancel_futures=True)
    if interruption is not None:
        known = {result.index for result in results}
        known.add(interruption.result.index)
        for future in futures:
            if future.cancelled():
                continue
            try:
                result = future.result()
            except RunInterrupted as exc:
                result = exc.result
            except Exception:
                continue
            if result.index not in known:
                results.append(result)
                known.add(result.index)
        interruption.completed_results = results
        raise interruption
    return results


def _execute_cloud(
    context: RunContext,
    *,
    factory: Callable[[], OpenAI | Anthropic | genai.Client],
    runner: Callable[..., GenerationOutcome],
    jobs: list[tuple[int, str]],
) -> list[ModelRunResult]:
    """Own one cloud client and run its jobs sequentially, retaining prior results."""
    try:
        client = factory()
    except Exception as exc:
        LOGGER.debug("cloud client initialization failed", exc_info=True)
        return [
            _failure_result(
                context,
                index=index,
                model=model,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
                started_at=datetime.now().astimezone(),
            )
            for index, model in jobs
        ]
    results: list[ModelRunResult] = []
    try:
        for position, (index, model) in enumerate(jobs, start=1):
            try:
                results.append(
                    _run_single_cloud(
                        context,
                        client,
                        runner=runner,
                        index=index,
                        model=model,
                        position=position,
                        total=len(jobs),
                    )
                )
            except RunInterrupted as exc:
                exc.completed_results = results
                raise
    finally:
        try:
            client.close()
        except Exception:
            LOGGER.warning("cloud client could not be closed", exc_info=True)
    return results


def _report(context: RunContext, result: ModelRunResult) -> None:
    """Print one line per model summarising what was measured and written."""
    metrics = result.metrics
    if context.settings.settings.extraction_format == "v3":
        for label, path in writers.v3_artifact_paths(context, result.index, result.model).items():
            if label != "document":
                print(f"      {label} -> {writers.portable_path(path, context.settings.base_dir)}")
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
    """Describe the resolved run without contacting any provider."""
    settings = context.settings.settings

    def portable(path: Path) -> str:
        return writers.portable_path(path, context.settings.base_dir)

    print("dry run - no provider API requests are made")
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
    print(f"  prompt path     : {context.prompt_path}")
    if any(m.provider == "anthropic" for m in context.models) and settings.anthropic_output_format:
        constraint = context.anthropic_output_constraint
        print(f"  Claude constraint: {constraint['schema_identity']}")
        print(f"  Claude schema SHA: {constraint['schema_sha256']}")
    if any(m.provider == "ollama" for m in context.models) and settings.ollama_output_format:
        constraint = context.ollama_output_constraint
        print(f"  output constraint: {constraint['mode']} ({constraint['schema_identity']})")
        print(f"  schema SHA-256  : {constraint['schema_sha256']}")
        print("  Ollama versions : unavailable in dry run (no metadata requests)")
    print(f"  prompt version  : {context.prompt_version}")
    print(f"  extraction format: {settings.extraction_format}")
    if settings.extraction_format == "v3":
        print(f"  candidate contract: extraction-{settings.v3_candidate_version}")
    output_cap = settings.max_output_tokens or (
        f"provider default; Anthropic fallback: {DEFAULT_ANTHROPIC_OUTPUT_TOKENS}"
    )
    print(f"  output cap      : {output_cap}")
    has_ollama = any(m.provider == "ollama" for m in context.models)
    if has_ollama:
        print(f"  Ollama thinking : {context.ollama_think_label}")
        print(f"  num_ctx         : {context.num_ctx:,} (Ollama only)")
        print(
            f"  data budget     : {context.data_budget_characters:,} characters"
            f" (input fits: {'yes' if context.input_fits else 'no'})"
        )
        print(f"  ollama options  : {writers.format_options(context.run_options)}")
    else:
        print("  Ollama budget   : not applicable to cloud-only run")
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
        print(f"    {index}  {model.provider}:{model.model}")
        print(f"        answer -> {portable(writers.output_path_for(context, index, model.model))}")
        print(f"        log    -> {portable(writers.log_path_for(context, index, model.model))}")
        if settings.extraction_format == "v3":
            for label, path in writers.v3_artifact_paths(context, index, model.model).items():
                if label != "document":
                    print(f"        {label} -> {portable(path)}")

    if any(m.provider == "ollama" for m in context.models) and not context.input_fits:
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
        print(
            "           Ollama keeps only the TAIL of an over-long prompt, so Ollama models would"
        )
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
    load_dotenv()

    args = build_parser().parse_args(argv)
    _configure_logging(args.log_level)

    try:
        loaded = load_settings(args.settings, overrides=_overrides_from_args(args))
        original_input_bytes = None
        if loaded.settings.extraction_format == "v3":
            original_input_bytes = loaded.input_path.read_bytes()
            database_text = decode_text(original_input_bytes)
        else:
            database_text = read_text_file(loaded.input_path)
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR
    except OSError as exc:
        print(f"error: cannot read the input file: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    context = RunContext.from_settings(
        loaded, database_text, original_input_bytes=original_input_bytes
    )

    if args.dry_run:
        _print_dry_run(context)
        return EXIT_SUCCESS

    if any(m.provider == "ollama" for m in context.models) and not context.input_fits:
        message = (
            f"the input is {len(context.database_text):,} characters but only about"
            f" {context.data_budget_characters:,} fit alongside the instructions;"
            " Ollama keeps only the tail of an over-long prompt, so Ollama models would see"
            " just the end of the input"
        )
        if loaded.settings.fail_on_context_overrun:
            print(f"error: {message}", file=sys.stderr)
            return EXIT_CONFIGURATION_ERROR
        print(f"warning: {message}", file=sys.stderr)

    try:
        with writers.reserve_run(context):
            return _run_extraction(context)
    except (writers.OutputCollisionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR


def _run_extraction(context: RunContext) -> int:
    """Execute only after output destinations and run identity have been reserved."""
    loaded = context.settings

    has_ollama_models = any(model.provider == "ollama" for model in context.models)

    installed: set[str] = set()

    if has_ollama_models:
        client = create_client(context)

        try:
            if loaded.settings.ollama_output_format is not None:
                runtime_metadata: dict[str, Any] = {}
                installed = list_installed_models(client, runtime_metadata=runtime_metadata)
                context = replace(context, ollama_runtime=runtime_metadata)
            else:
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

    openai_jobs: list[tuple[int, str]] = []
    anthropic_jobs: list[tuple[int, str]] = []
    gemini_jobs: list[tuple[int, str]] = []
    jobs: list[tuple[int, str]] = []
    results: list[ModelRunResult] = []

    for position, model in enumerate(context.models):
        index = naming.model_index(position, context.index_base)

        if model.provider == "ollama":
            if model.model in installed:
                jobs.append((index, model.model))
                continue
            message = f"model is not installed locally; run `ollama pull {model.model}` first"
            LOGGER.warning("%s - %s", model.model, message)
            results.append(
                _failure_result(
                    context,
                    index=index,
                    model=model.model,
                    status="skipped",
                    message=message,
                    started_at=datetime.now().astimezone(),
                )
            )

            if not loaded.settings.continue_on_error:
                print(f"error: {model} — {message}", file=sys.stderr)
                return EXIT_CONFIGURATION_ERROR

        if model.provider == "openai":
            openai_jobs.append((index, model.model))

        if model.provider == "anthropic":
            anthropic_jobs.append((index, model.model))

        if model.provider == "gemini":
            gemini_jobs.append((index, model.model))

    print(
        f"input : {writers.portable_path(loaded.input_path, loaded.base_dir)}"
        f" ({context.input_characters_total:,} characters)"
    )
    print(
        f"prompt path: {context.prompt_path}; version: {context.prompt_version}; "
        f"fingerprint: {context.prompt_fingerprint}"
    )
    if loaded.settings.extraction_format == "v3":
        print(
            "extraction format: v3; "
            f"candidate contract: extraction-{loaded.settings.v3_candidate_version}"
            " (exact evidence JSON; raw responses archived separately)"
        )
    if has_ollama_models:
        print(f"Ollama thinking request: {context.ollama_think_label}")
        if loaded.settings.ollama_output_format:
            print(f"Ollama output constraint: {loaded.settings.ollama_output_format}")
    print(
        f"prompt: {len(context.prompt_text):,} characters, about"
        f" {context.estimated_prompt_tokens:,} tokens "
        f"(Ollama num_ctx {context.num_ctx:,}; not a cloud limit)"
    )

    queued_count = len(jobs) + len(openai_jobs) + len(anthropic_jobs) + len(gemini_jobs)

    print(
        f"models: {len(context.models)} requested, {queued_count} queued"
        f" | run mode: {context.run_mode}"
    )
    print("")

    interrupted = False
    timeout = loaded.settings.request_timeout_seconds
    if jobs:
        try:
            results.extend(_execute(context, client, jobs))
        except RunInterrupted as exc:
            results.extend(exc.completed_results)
            results.append(exc.result)
            interrupted = True
        except KeyboardInterrupt:
            LOGGER.warning("interrupted before the next model started")
            interrupted = True

    # Preserve provider grouping and sequential cloud execution for compatibility.
    cloud_groups = [
        (openai_jobs, lambda: OpenAI(timeout=timeout), cloud_runner.run_model),
        (anthropic_jobs, lambda: Anthropic(timeout=timeout), anthropic_runner.run_model),
        (
            gemini_jobs,
            lambda: genai.Client(http_options={"timeout": max(1, int(timeout * 1000))}),
            gemini_runner.run_model,
        ),
    ]
    for cloud_jobs, factory, runner in cloud_groups:
        if not cloud_jobs or interrupted:
            continue
        try:
            results.extend(_execute_cloud(context, factory=factory, runner=runner, jobs=cloud_jobs))
        except RunInterrupted as exc:
            results.extend(exc.completed_results)
            results.append(exc.result)
            interrupted = True
        except KeyboardInterrupt:
            LOGGER.warning("interrupted before the next model started")
            interrupted = True

    if interrupted:
        known = {result.index for result in results}
        for position, model in enumerate(context.models):
            index = naming.model_index(position, context.index_base)
            if index not in known:
                results.append(
                    _failure_result(
                        context,
                        index=index,
                        model=model.model,
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
