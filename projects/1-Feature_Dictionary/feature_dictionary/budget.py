"""Rough prompt-size accounting so oversized inputs cannot fail silently.

Ollama keeps only the **tail** of a prompt that is longer than the context window
and discards the rest without saying so (verified against a running server: with
``num_ctx`` 512 and a 70k-character prompt, a marker at the head of the prompt was
never seen while a marker at the tail was reproduced exactly). These helpers
estimate the prompt size so the CLI can warn about it - or refuse to run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CHARS_PER_TOKEN_ESTIMATE = 4.0
"""Deliberately rough characters-per-token ratio for English prose."""

DEFAULT_NUM_CTX = 4096
"""Assumed context window when ``num_ctx`` is not set in the Ollama options."""

OVERRUN_THRESHOLD = 0.95
"""Warn once the prompt uses this share of the tokens available for it."""


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in ``text``."""
    return max(1, round(len(text) / CHARS_PER_TOKEN_ESTIMATE))


def resolve_num_ctx(options: Mapping[str, Any] | None) -> int:
    """Return the configured context window, or Ollama's usual default."""
    if options:
        value = options.get("num_ctx")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return DEFAULT_NUM_CTX


def resolve_reserved_output_tokens(options: Mapping[str, Any] | None) -> int:
    """Return the tokens reserved for the answer, i.e. a positive ``num_predict``."""
    if options:
        value = options.get("num_predict")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return 0


def available_prompt_tokens(num_ctx: int, reserved_output_tokens: int = 0) -> int:
    """Tokens left for the prompt once the reserved answer length is set aside."""
    return max(0, num_ctx - reserved_output_tokens)


def context_overrun(
    prompt_text: str,
    options: Mapping[str, Any] | None,
    reserved_output_tokens: int | None = None,
) -> tuple[int, int] | None:
    """Return ``(estimated_tokens, available_tokens)`` when the prompt will not fit."""
    reserved = (
        resolve_reserved_output_tokens(options)
        if reserved_output_tokens is None
        else reserved_output_tokens
    )
    available = available_prompt_tokens(resolve_num_ctx(options), reserved)
    estimated = estimate_tokens(prompt_text)
    if estimated > available * OVERRUN_THRESHOLD:
        return estimated, available
    return None


def data_budget_characters(
    instruction_tokens: int,
    options: Mapping[str, Any] | None,
    reserved_output_tokens: int | None = None,
) -> int:
    """Rough character budget for the embedded data, given the prompt scaffolding."""
    reserved = (
        resolve_reserved_output_tokens(options)
        if reserved_output_tokens is None
        else reserved_output_tokens
    )
    available = available_prompt_tokens(resolve_num_ctx(options), reserved) - instruction_tokens
    return max(0, int(available * CHARS_PER_TOKEN_ESTIMATE))
