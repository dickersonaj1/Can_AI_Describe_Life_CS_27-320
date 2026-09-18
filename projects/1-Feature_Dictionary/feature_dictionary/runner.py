"""Executing one Ollama model and capturing its timing and token metrics."""

from __future__ import annotations

import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama

from feature_dictionary.budget import CHARS_PER_TOKEN_ESTIMATE
from feature_dictionary.context import RunContext
from feature_dictionary.settings import DEFAULT_LOOP_GUARD_REPEATS

OnChunk = Callable[[str, str], None]

LOOP_GUARD_WINDOW_LINES = 200
"""How many of the most recent lines the loop guard inspects."""

LOOP_GUARD_MIN_LINE_CHARS = 8
"""Shorter lines are ignored so short boilerplate rows cannot trip the guard."""


class OllamaUnavailableError(RuntimeError):
    """Raised when the local Ollama server cannot be reached."""


class RepeatDetector:
    """Detects a generation that has locked into repeating the same lines.

    A sliding window of the most recent lines is kept, and a loop is reported once
    a single line has appeared ``threshold`` times inside that window. Repeated
    multi-line blocks are caught as well, because every line of the block repeats
    as often as the block itself does.
    """

    def __init__(
        self,
        threshold: int = DEFAULT_LOOP_GUARD_REPEATS,
        window_lines: int = LOOP_GUARD_WINDOW_LINES,
        min_line_chars: int = LOOP_GUARD_MIN_LINE_CHARS,
    ) -> None:
        self._threshold = threshold
        self._window: deque[str] = deque(maxlen=window_lines)
        self._counts: Counter[str] = Counter()
        self._min_line_chars = min_line_chars
        self._buffer = ""
        self._detected = False

    @property
    def detected(self) -> bool:
        """Whether a repetition loop has been seen."""
        return self._detected

    def feed(self, text: str) -> bool:
        """Add newly generated text and return True once a loop is detected."""
        if self._detected or not text:
            return self._detected
        self._buffer += text
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            stripped = line.strip()
            if len(stripped) < self._min_line_chars:
                continue
            if len(self._window) == self._window.maxlen:
                oldest = self._window[0]
                self._counts[oldest] -= 1
                if self._counts[oldest] <= 0:
                    del self._counts[oldest]
            self._window.append(stripped)
            self._counts[stripped] += 1
            if self._counts[stripped] >= self._threshold:
                self._detected = True
                return True
        return False


class GenerationInterrupted(Exception):
    """Raised when the user interrupts a generation (Ctrl+C).

    Carries the partial :class:`GenerationOutcome` so that what the model produced
    before the interrupt can still be written to disk.
    """

    def __init__(self, outcome: GenerationOutcome) -> None:
        super().__init__("generation interrupted")
        self.outcome = outcome


@dataclass
class ModelMetrics:
    """Timing and token statistics for a single generation."""

    wall_clock_seconds: float
    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration_ns: int | None = None
    eval_count: int | None = None
    eval_duration_ns: int | None = None
    done_reason: str | None = None
    prompt_characters: int = 0
    response_characters: int = 0
    thinking_characters: int = 0
    interrupted: bool = False
    loop_detected: bool = False

    @property
    def total_tokens(self) -> int | None:
        """Prompt tokens plus generated tokens."""
        if self.prompt_eval_count is None and self.eval_count is None:
            return None
        return (self.prompt_eval_count or 0) + (self.eval_count or 0)

    @property
    def estimated_generation_tokens(self) -> int:
        """Rough token count for the text received, for runs Ollama did not finish."""
        return max(0, round(self.response_characters / CHARS_PER_TOKEN_ESTIMATE))

    @property
    def generation_tokens_per_second(self) -> float | None:
        """Generated tokens per second, as reported by Ollama."""
        if not self.eval_count or not self.eval_duration_ns:
            return None
        return self.eval_count / (self.eval_duration_ns / 1_000_000_000)

    @property
    def prompt_tokens_per_second(self) -> float | None:
        """Prompt tokens per second, as reported by Ollama."""
        if not self.prompt_eval_count or not self.prompt_eval_duration_ns:
            return None
        return self.prompt_eval_count / (self.prompt_eval_duration_ns / 1_000_000_000)


@dataclass
class GenerationOutcome:
    """The text and metrics returned by one successful generation."""

    response_text: str
    thinking_text: str
    metrics: ModelMetrics


@dataclass
class ModelRunResult:
    """Bookkeeping for one model: whether it ran, where it was written and why not."""

    index: int
    model: str
    status: str
    started_at: datetime
    finished_at: datetime
    output_path: Path | None = None
    log_path: Path | None = None
    metrics: ModelMetrics | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    @property
    def generation_tokens_per_second(self) -> float | None:
        return self.metrics.generation_tokens_per_second if self.metrics else None


def create_client(context: RunContext) -> ollama.Client:
    """Build an Ollama client for the configured host with the configured timeout."""
    return ollama.Client(
        host=context.settings.ollama_host,
        timeout=context.settings.settings.request_timeout_seconds,
    )


def list_installed_models(client: ollama.Client) -> set[str]:
    """Return the identifiers of the models that are available locally."""
    try:
        response = client.list()
    except ConnectionError as exc:
        raise OllamaUnavailableError(str(exc)) from exc
    except ollama.ResponseError as exc:
        raise OllamaUnavailableError(str(exc)) from exc

    names: set[str] = set()
    for model in getattr(response, "models", None) or []:
        for attribute in ("model", "name"):
            value = getattr(model, attribute, None)
            if isinstance(value, str) and value:
                names.add(value)
    return names


def run_model(
    client: ollama.Client,
    *,
    model: str,
    prompt: str,
    options: dict[str, Any] | None = None,
    keep_alive: str | float | None = None,
    stream: bool = False,
    on_chunk: OnChunk | None = None,
    loop_guard: bool = False,
    loop_guard_repeats: int = DEFAULT_LOOP_GUARD_REPEATS,
) -> GenerationOutcome:
    """Send one prompt to one model and collect the answer plus its metrics.

    ``on_chunk`` receives ``(response_piece, thinking_piece)`` as they arrive and is
    only used when ``stream`` is true. A ``KeyboardInterrupt`` while streaming is
    converted into :class:`GenerationInterrupted`, which still carries the text that
    arrived before the interrupt. With ``loop_guard`` enabled, a generation that
    starts repeating the same lines is stopped early and flagged on the metrics.
    """
    request: dict[str, Any] = {"keep_alive": keep_alive, "options": options or None}
    detector = RepeatDetector(loop_guard_repeats) if loop_guard else None
    started = time.perf_counter()
    final: Any = None
    response_pieces: list[str] = []
    thinking_pieces: list[str] = []
    loop_detected = False
    interrupted = False

    if stream:
        try:
            for chunk in client.generate(model=model, prompt=prompt, stream=True, **request):
                piece = getattr(chunk, "response", "") or ""
                reasoning = getattr(chunk, "thinking", "") or ""
                if piece:
                    response_pieces.append(piece)
                if reasoning:
                    thinking_pieces.append(reasoning)
                if on_chunk is not None:
                    on_chunk(piece, reasoning)
                final = chunk
                if detector is not None and piece and detector.feed(piece):
                    loop_detected = True
                    break
        except KeyboardInterrupt:
            interrupted = True
        response_text = "".join(response_pieces)
        thinking_text = "".join(thinking_pieces)
    else:
        final = client.generate(model=model, prompt=prompt, stream=False, **request)
        response_text = getattr(final, "response", "") or ""
        thinking_text = getattr(final, "thinking", "") or ""
        if detector is not None and response_text and detector.feed(response_text):
            loop_detected = True

    wall_clock = time.perf_counter() - started
    metrics = metrics_from_response(
        final,
        wall_clock,
        prompt_characters=len(prompt),
        response_text=response_text,
        thinking_text=thinking_text,
        interrupted=interrupted,
        loop_detected=loop_detected,
    )
    outcome = GenerationOutcome(
        response_text=response_text,
        thinking_text=thinking_text,
        metrics=metrics,
    )
    if interrupted:
        raise GenerationInterrupted(outcome)
    return outcome


def metrics_from_response(
    response: Any,
    wall_clock_seconds: float,
    *,
    prompt_characters: int = 0,
    response_text: str = "",
    thinking_text: str = "",
    interrupted: bool = False,
    loop_detected: bool = False,
) -> ModelMetrics:
    """Convert an Ollama response (or its final stream chunk) into metrics."""

    def integer(name: str) -> int | None:
        value = getattr(response, name, None)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    done_reason = getattr(response, "done_reason", None)
    return ModelMetrics(
        wall_clock_seconds=wall_clock_seconds,
        total_duration_ns=integer("total_duration"),
        load_duration_ns=integer("load_duration"),
        prompt_eval_count=integer("prompt_eval_count"),
        prompt_eval_duration_ns=integer("prompt_eval_duration"),
        eval_count=integer("eval_count"),
        eval_duration_ns=integer("eval_duration"),
        done_reason=str(done_reason) if done_reason else None,
        prompt_characters=prompt_characters,
        response_characters=len(response_text),
        thinking_characters=len(thinking_text),
        interrupted=interrupted,
        loop_detected=loop_detected,
    )
