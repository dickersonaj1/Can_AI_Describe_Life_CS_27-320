import time

from google import genai

from ..runner import GenerationOutcome, ModelMetrics


def run_model(
    client: genai.Client,
    *,
    model: str,
    prompt: str,
) -> GenerationOutcome:
    started = time.perf_counter()

    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )

    ended = time.perf_counter()
    elapsed = ended - started

    response_text = response.text or ""

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
    )

    outcome = GenerationOutcome(
        response_text=response_text,
        thinking_text="",
        metrics=metrics,
    )

    return outcome