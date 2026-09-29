import time

from openai import OpenAI

from ..runner import GenerationOutcome,ModelMetrics




def run_model(
    client: OpenAI,
    *,
    model: str,
    prompt: str,
) -> GenerationOutcome:

    started = time.perf_counter()

    response = client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=1200,
    )

    ended = time.perf_counter()
    elapsed = ended - started

    response_text = response.output_text


    metrics = ModelMetrics(
        wall_clock_seconds = elapsed,
        prompt_characters = len(prompt),
        response_characters = len(response_text),
        thinking_characters = 0,
        interrupted = False,
        loop_detected = False,
        prompt_eval_count = response.usage.input_tokens,
        eval_count = response.usage.output_tokens,
    )

    outcome = GenerationOutcome(
        response_text = response_text,
        thinking_text = "",
        metrics = metrics,
    
    )

    return outcome
