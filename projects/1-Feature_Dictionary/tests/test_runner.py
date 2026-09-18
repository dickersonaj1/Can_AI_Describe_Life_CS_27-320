"""Tests for the Ollama runner: metrics capture, streaming and error handling."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import ollama
import pytest

from feature_dictionary import runner


def make_response(**values: Any) -> SimpleNamespace:
    """An object shaped like ``ollama.GenerateResponse``."""
    defaults: dict[str, Any] = {
        "response": "hello world",
        "thinking": None,
        "total_duration": 1_000_000_000,
        "load_duration": 100_000_000,
        "prompt_eval_count": 10,
        "prompt_eval_duration": 200_000_000,
        "eval_count": 5,
        "eval_duration": 800_000_000,
        "done_reason": "stop",
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def make_chunk(piece: str, thinking: str | None = None, **values: Any) -> SimpleNamespace:
    """An object shaped like one streamed chunk of a generate response."""
    return SimpleNamespace(response=piece, thinking=thinking, **values)


class FakeClient:
    """Stand-in for ``ollama.Client`` so the tests never need a server."""

    def __init__(
        self,
        *,
        response: Any = None,
        chunks: list[Any] | None = None,
        models: tuple[str, ...] = (),
        list_error: Exception | None = None,
        generate_error: Exception | None = None,
        interrupt_after: int | None = None,
    ) -> None:
        self.response = response
        self.chunks = chunks or []
        self.models = models
        self.list_error = list_error
        self.generate_error = generate_error
        self.interrupt_after = interrupt_after
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.generate_error is not None:
            raise self.generate_error
        if kwargs.get("stream"):
            return self._stream()
        return self.response

    def _stream(self) -> Any:
        """Yield the canned chunks, optionally raising ``KeyboardInterrupt``."""
        for position, chunk in enumerate(self.chunks):
            yield chunk
            if self.interrupt_after is not None and position + 1 >= self.interrupt_after:
                raise KeyboardInterrupt

    def list(self) -> Any:
        if self.list_error is not None:
            raise self.list_error
        return SimpleNamespace(
            models=[SimpleNamespace(model=name, name=name) for name in self.models]
        )


def test_request_arguments_are_forwarded():
    client = FakeClient(response=make_response())
    runner.run_model(
        client,
        model="llama3.1:8b",
        prompt="a prompt",
        options={"temperature": 0.2},
        keep_alive="5m",
    )
    call = client.calls[0]
    assert call["model"] == "llama3.1:8b"
    assert call["prompt"] == "a prompt"
    assert call["stream"] is False
    assert call["options"] == {"temperature": 0.2}
    assert call["keep_alive"] == "5m"


def test_non_streaming_metrics_are_captured():
    client = FakeClient(response=make_response())
    outcome = runner.run_model(client, model="llama3.1:8b", prompt="12345")
    metrics = outcome.metrics
    assert outcome.response_text == "hello world"
    assert metrics.wall_clock_seconds >= 0
    assert metrics.total_duration_ns == 1_000_000_000
    assert metrics.load_duration_ns == 100_000_000
    assert metrics.prompt_eval_count == 10
    assert metrics.eval_count == 5
    assert metrics.total_tokens == 15
    assert metrics.generation_tokens_per_second == pytest.approx(6.25)
    assert metrics.prompt_tokens_per_second == pytest.approx(50.0)
    assert metrics.done_reason == "stop"
    assert metrics.prompt_characters == 5
    assert metrics.response_characters == 11


def test_streaming_accumulates_text_and_uses_the_last_chunk_for_metrics():
    received: list[tuple[str, str]] = []
    chunks = [
        make_chunk("Hel"),
        make_chunk(
            "lo",
            "because",
            prompt_eval_count=8,
            prompt_eval_duration=400_000_000,
            eval_count=2,
            eval_duration=500_000_000,
            done_reason="stop",
        ),
    ]
    client = FakeClient(chunks=chunks)
    outcome = runner.run_model(
        client,
        model="qwen3:8b",
        prompt="a prompt",
        stream=True,
        on_chunk=lambda piece, thinking: received.append((piece, thinking)),
    )
    assert outcome.response_text == "Hello"
    assert outcome.thinking_text == "because"
    assert outcome.metrics.eval_count == 2
    assert outcome.metrics.total_tokens == 10
    assert outcome.metrics.thinking_characters == 7
    assert received == [("Hel", ""), ("lo", "because")]
    assert client.calls[0]["stream"] is True


def test_streaming_without_a_callback_is_supported():
    client = FakeClient(chunks=[make_chunk("done", eval_count=1)])
    outcome = runner.run_model(client, model="qwen3:8b", prompt="p", stream=True)
    assert outcome.response_text == "done"


def test_missing_ollama_fields_become_none():
    client = FakeClient(response=make_chunk("answer"))
    metrics = runner.run_model(client, model="m", prompt="p").metrics
    assert metrics.total_duration_ns is None
    assert metrics.total_tokens is None
    assert metrics.generation_tokens_per_second is None
    assert metrics.prompt_tokens_per_second is None
    assert metrics.done_reason is None
    assert metrics.response_characters == 6


def test_empty_response_is_recorded_as_empty_text():
    client = FakeClient(response=make_response(response=""))
    outcome = runner.run_model(client, model="m", prompt="p")
    assert outcome.response_text == ""
    assert outcome.metrics.response_characters == 0


def test_list_installed_models_returns_identifiers():
    client = FakeClient(models=("llama3.1:8b", "qwen3:8b"))
    assert runner.list_installed_models(client) == {"llama3.1:8b", "qwen3:8b"}


def test_list_installed_models_handles_an_empty_server():
    assert runner.list_installed_models(FakeClient()) == set()


def test_unreachable_server_is_wrapped():
    client = FakeClient(list_error=ConnectionError("connection refused"))
    with pytest.raises(runner.OllamaUnavailableError):
        runner.list_installed_models(client)


def test_ollama_response_errors_are_wrapped():
    client = FakeClient(list_error=ollama.ResponseError("boom", 500))
    with pytest.raises(runner.OllamaUnavailableError):
        runner.list_installed_models(client)


def test_run_model_propagates_generation_errors():
    client = FakeClient(generate_error=ollama.ResponseError("model not found", 404))
    with pytest.raises(ollama.ResponseError):
        runner.run_model(client, model="m", prompt="p")


def test_repeat_detector_flags_a_repeated_line():
    detector = runner.RepeatDetector(threshold=5)
    for _ in range(4):
        assert detector.feed("Snout-vent length 190-435 mm\n") is False
    assert detector.feed("Snout-vent length 190-435 mm\n") is True
    assert detector.detected is True


def test_repeat_detector_flags_a_repeated_block():
    detector = runner.RepeatDetector(threshold=5)
    block = "- **Head**: wide and stout\n- **Snout**: rounded\n"
    triggered = False
    for _ in range(5):
        triggered = detector.feed(block) or triggered
    assert triggered is True


def test_repeat_detector_stays_quiet_on_varied_text():
    detector = runner.RepeatDetector(threshold=5)
    for index in range(300):
        assert detector.feed(f"- **Term {index}**: synonym of term {index}\n") is False
    assert detector.detected is False


def test_repeat_detector_ignores_short_lines():
    detector = runner.RepeatDetector(threshold=5)
    for _ in range(50):
        assert detector.feed("yes\n") is False


def test_streaming_loop_guard_stops_the_model_early():
    repeated = [make_chunk("Snout-vent length 190-435 mm\n") for _ in range(30)]
    client = FakeClient(chunks=repeated)
    outcome = runner.run_model(
        client,
        model="m",
        prompt="p",
        stream=True,
        loop_guard=True,
        loop_guard_repeats=5,
    )
    assert outcome.metrics.loop_detected is True
    assert outcome.metrics.interrupted is False
    assert outcome.response_text.count("Snout-vent") == 5


def test_non_streaming_loop_guard_flags_after_the_fact():
    client = FakeClient(response=make_response(response="the same line again\n" * 30))
    outcome = runner.run_model(client, model="m", prompt="p", loop_guard=True, loop_guard_repeats=5)
    assert outcome.metrics.loop_detected is True


def test_loop_guard_is_silent_on_a_normal_answer():
    answer = "- **Head**: wide\n- **Snout**: long\n- **Tail**: short\n"
    client = FakeClient(response=make_response(response=answer))
    outcome = runner.run_model(client, model="m", prompt="p", loop_guard=True, loop_guard_repeats=2)
    assert outcome.metrics.loop_detected is False


def test_interrupt_during_streaming_keeps_the_partial_answer():
    client = FakeClient(chunks=[make_chunk("Partial "), make_chunk("answer")], interrupt_after=2)
    with pytest.raises(runner.GenerationInterrupted) as excinfo:
        runner.run_model(client, model="m", prompt="p", stream=True)
    outcome = excinfo.value.outcome
    assert outcome.response_text == "Partial answer"
    assert outcome.metrics.interrupted is True
    assert outcome.metrics.response_characters == len("Partial answer")
    assert outcome.metrics.estimated_generation_tokens == round(len("Partial answer") / 4)
    assert outcome.metrics.total_tokens is None
