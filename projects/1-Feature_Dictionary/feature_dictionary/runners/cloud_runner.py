import time
from collections.abc import Callable
from typing import Any

from openai import OpenAI

from ..runner import GenerationOutcome, ModelMetrics


def run_model(
    client: OpenAI,
    *,
    model: str,
    prompt: str,
    max_output_tokens: int | None = None,
    output_schema: dict[str, Any] | None = None,
    on_response: Callable[[Any], None] | None = None,
) -> GenerationOutcome:

    started = time.perf_counter()

    request: dict[str, object] = dict(model=model, input=prompt)
    if max_output_tokens is not None:
        request["max_output_tokens"] = max_output_tokens
    if output_schema is not None:
        request["text"] = {
            "format": {
                "type": "json_schema",
                "name": "synthesis_proposal",
                "schema": output_schema,
                "strict": True,
            }
        }
    response = client.responses.create(**request)
    if on_response is not None:
        on_response(response)

    ended = time.perf_counter()
    elapsed = ended - started

    response_text = response.output_text or ""
    provider_status = getattr(response, "status", None) or "unknown"
    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None)
    error = getattr(response, "error", None)
    if error is not None:
        reason = getattr(error, "code", None) or reason
    completion_status = "success" if provider_status == "completed" else provider_status
    if provider_status == "completed" and not response_text.strip():
        completion_status = "empty"
    refused = any(
        getattr(block, "type", None) == "refusal"
        for item in getattr(response, "output", []) or []
        for block in getattr(item, "content", []) or []
    )
    if refused:
        completion_status = "blocked"
        reason = "refusal"
    done_reason = provider_status + (f":{reason}" if reason else "")

    metrics = ModelMetrics(
        wall_clock_seconds=elapsed,
        prompt_characters=len(prompt),
        response_characters=len(response_text),
        thinking_characters=0,
        interrupted=False,
        loop_detected=False,
        prompt_eval_count=getattr(getattr(response, "usage", None), "input_tokens", None),
        eval_count=getattr(getattr(response, "usage", None), "output_tokens", None),
        done_reason=done_reason,
    )

    outcome = GenerationOutcome(
        response_text=response_text,
        thinking_text="",
        completion_status=completion_status,
        metrics=metrics,
    )

    return outcome
