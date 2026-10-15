import time
from collections.abc import Callable
from typing import Any

from anthropic import Anthropic

from ..runner import GenerationOutcome, ModelMetrics
from ..settings import DEFAULT_ANTHROPIC_OUTPUT_TOKENS


def run_model(
    client: Anthropic,
    *,
    model: str,
    prompt: str,
    max_output_tokens: int | None = None,
    output_schema: dict[str, Any] | None = None,
    on_response: Callable[[Any], None] | None = None,
) -> GenerationOutcome:

    started = time.perf_counter()
    request: dict[str, Any] = {}
    if output_schema is not None:
        request["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}}
    response = client.messages.create(
        model=model,
        # Anthropic requires max_tokens; use a bounded fallback if unset.
        max_tokens=(
            max_output_tokens if max_output_tokens is not None else DEFAULT_ANTHROPIC_OUTPUT_TOKENS
        ),
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        **request,
    )

    if on_response is not None:
        on_response(response)

    ended = time.perf_counter()
    elapsed = ended - started

    response_text = "".join(block.text for block in response.content if block.type == "text")

    reason = getattr(response, "stop_reason", None) or "unknown"
    if reason in {"end_turn", "stop_sequence"}:
        completion_status = "success" if response_text.strip() else "empty"
    elif reason in {"max_tokens", "model_context_window_exceeded", "pause_turn", "tool_use"}:
        completion_status = "incomplete"
    elif reason == "refusal":
        completion_status = "blocked"
    else:
        completion_status = "unknown"
    metrics = ModelMetrics(
        wall_clock_seconds=elapsed,
        prompt_characters=len(prompt),
        response_characters=len(response_text),
        thinking_characters=0,
        interrupted=False,
        loop_detected=False,
        prompt_eval_count=getattr(getattr(response, "usage", None), "input_tokens", None),
        eval_count=getattr(getattr(response, "usage", None), "output_tokens", None),
        done_reason=reason,
    )

    outcome = GenerationOutcome(
        response_text=response_text,
        thinking_text="",
        completion_status=completion_status,
        metrics=metrics,
    )

    return outcome
