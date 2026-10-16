import time
from collections.abc import Callable
from typing import Any

from google import genai

from ..runner import GenerationOutcome, ModelMetrics


def run_model(
    client: genai.Client,
    *,
    model: str,
    prompt: str,
    max_output_tokens: int | None = None,
    output_schema: dict[str, Any] | None = None,
    on_response: Callable[[Any], None] | None = None,
) -> GenerationOutcome:
    started = time.perf_counter()

    request: dict[str, object] = dict(model=model, contents=prompt)
    if max_output_tokens is not None:
        request["config"] = {"max_output_tokens": max_output_tokens}
    if output_schema is not None:
        config = dict(request.get("config", {}))
        config.update(response_mime_type="application/json", response_json_schema=output_schema)
        request["config"] = config
    response = client.models.generate_content(**request)
    if on_response is not None:
        on_response(response)

    ended = time.perf_counter()
    elapsed = ended - started

    response_text = response.text or ""

    candidates = getattr(response, "candidates", None) or []

    def enum_name(value: object) -> str:
        return getattr(value, "name", None) or str(value or "unknown").split(".")[-1]

    reason = enum_name(getattr(candidates[0], "finish_reason", None)) if candidates else "unknown"
    feedback = getattr(response, "prompt_feedback", None)
    blocked = getattr(feedback, "block_reason", None)
    if blocked and enum_name(blocked) != "BLOCKED_REASON_UNSPECIFIED":
        reason = enum_name(blocked)
        completion_status = "blocked"
    elif reason == "STOP":
        completion_status = "success" if response_text.strip() else "empty"
    elif reason == "MAX_TOKENS":
        completion_status = "incomplete"
    elif reason in {
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    }:
        completion_status = "blocked"
    else:
        completion_status = "unknown"
    usage = response.usage_metadata

    metrics = ModelMetrics(
        wall_clock_seconds=elapsed,
        prompt_characters=len(prompt),
        response_characters=len(response_text),
        thinking_characters=0,
        interrupted=False,
        loop_detected=False,
        prompt_eval_count=usage.prompt_token_count if usage else None,
        eval_count=usage.candidates_token_count if usage else None,
        done_reason=reason,
    )

    outcome = GenerationOutcome(
        response_text=response_text,
        thinking_text="",
        completion_status=completion_status,
        metrics=metrics,
    )

    return outcome
