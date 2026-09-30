import time
from anthropic import Anthropic
from ..runner import GenerationOutcome, ModelMetrics

def run_model(
    client: Anthropic,
    *,
    model: str,
    prompt: str,
) -> GenerationOutcome:
    
    started = time.perf_counter()
    response = client.messages.create(
        model = model,
        max_tokens = 1200,
        messages = [
            {
                "role": "user",
                "content": prompt,
            }
        ]
    )

    ended = time.perf_counter()
    elapsed = ended - started

    response_text = "".join(
        block.text
        for block in response.content
        if block.type == "text"
    )

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