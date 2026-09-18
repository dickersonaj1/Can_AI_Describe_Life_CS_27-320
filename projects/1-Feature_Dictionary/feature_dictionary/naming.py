"""Filesystem-safe names and human-readable number formatting.

Windows forbids ``:`` inside file names, so Ollama identifiers such as
``llama3.1:8b`` are converted into a slug (``llama3.1-8b``). The untouched
identifier is always recorded inside the generated files.
"""

from __future__ import annotations

import re
from datetime import datetime

DEFAULT_DATE_FORMAT = "%m_%d"

_UNSAFE_MODEL_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_model(model: str) -> str:
    """Return a filesystem-safe slug for an Ollama model identifier."""
    slug = _UNSAFE_MODEL_CHARS.sub("_", model.strip().replace(":", "-"))
    return slug.strip("._-") or "model"


def model_index(position: int, index_base: int = 0) -> int:
    """Return the ``{i}`` label used in file names for a model position."""
    return position + index_base


def output_filename(index: int, model: str) -> str:
    """``{i}_<model_name>.md`` for the model answer."""
    return f"{index}_{slugify_model(model)}.md"


def log_filename(
    index: int,
    model: str,
    timestamp: datetime,
    date_format: str = DEFAULT_DATE_FORMAT,
) -> str:
    """``{i}_<model_name>_MM_DD.md`` for the per-model run log."""
    return f"{index}_{slugify_model(model)}_{timestamp.strftime(date_format)}.md"


def summary_filename(timestamp: datetime, date_format: str = DEFAULT_DATE_FORMAT) -> str:
    """``summary_MM_DD.md`` for the cross-model comparison table."""
    return f"summary_{timestamp.strftime(date_format)}.md"


def format_count(value: int | None) -> str:
    """Render a token or character count."""
    return "n/a" if value is None else f"{value:,}"


def format_seconds(seconds: float | None) -> str:
    """Render a wall-clock measurement."""
    return "n/a" if seconds is None else f"{seconds:,.2f} s"


def format_duration_ns(duration_ns: int | None) -> str:
    """Render an Ollama duration (given in nanoseconds)."""
    if duration_ns is None:
        return "n/a"
    seconds = duration_ns / 1_000_000_000
    if seconds >= 1:
        return f"{seconds:,.2f} s"
    if seconds >= 0.001:
        return f"{seconds * 1_000:,.1f} ms"
    return f"{duration_ns:,} ns"


def format_rate(count: int | None, duration_ns: int | None) -> str:
    """Render a throughput value in tokens per second."""
    if not count or not duration_ns:
        return "n/a"
    return f"{count / (duration_ns / 1_000_000_000):,.2f} tok/s"
