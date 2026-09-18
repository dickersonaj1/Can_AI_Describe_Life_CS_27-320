"""Tests for the file naming and number formatting helpers."""

from __future__ import annotations

from datetime import datetime

import pytest

from feature_dictionary import naming

STAMP = datetime(2026, 9, 18, 14, 3, 11)


def test_slug_replaces_the_windows_illegal_colon():
    assert naming.slugify_model("llama3.1:8b") == "llama3.1-8b"
    assert naming.slugify_model("qwen3:8b") == "qwen3-8b"
    assert naming.slugify_model("deepseek-coder-v2:latest") == "deepseek-coder-v2-latest"


def test_slug_strips_every_unsupported_character():
    slug = naming.slugify_model('a\\b/c:d*e?f"g<h>i|j')
    for unsafe in '\\/:*?"<>|':
        assert unsafe not in slug


def test_slug_falls_back_for_an_empty_name():
    assert naming.slugify_model("") == "model"
    assert naming.slugify_model("   ") == "model"


def test_output_filename_matches_the_specification():
    assert naming.output_filename(0, "llama3.1:8b") == "0_llama3.1-8b.md"
    assert naming.output_filename(12, "gemma3:12b") == "12_gemma3-12b.md"


def test_log_filename_uses_the_mm_dd_date_stamp():
    assert naming.log_filename(0, "llama3.1:8b", STAMP) == "0_llama3.1-8b_09_18.md"
    assert naming.log_filename(2, "qwen3:8b", STAMP, "%Y-%m-%d") == "2_qwen3-8b_2026-09-18.md"


def test_summary_filename_uses_the_date_stamp():
    assert naming.summary_filename(STAMP) == "summary_09_18.md"


def test_model_index_honours_the_index_base():
    assert naming.model_index(0, 0) == 0
    assert naming.model_index(0, 1) == 1
    assert naming.model_index(3, 1) == 4


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "n/a"), (0, "0"), (1162, "1,162"), (812, "812")],
)
def test_format_count(value, expected):
    assert naming.format_count(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "n/a"), (41.234, "41.23 s"), (0.5, "0.50 s")],
)
def test_format_seconds(value, expected):
    assert naming.format_seconds(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "n/a"),
        (40_980_000_000, "40.98 s"),
        (310_000_000, "310.0 ms"),
        (500, "500 ns"),
    ],
)
def test_format_duration_ns(value, expected):
    assert naming.format_duration_ns(value) == expected


def test_format_rate_needs_both_values():
    assert naming.format_rate(350, 33_180_000_000) == "10.55 tok/s"
    assert naming.format_rate(350, None) == "n/a"
    assert naming.format_rate(None, 33_180_000_000) == "n/a"
    assert naming.format_rate(0, 33_180_000_000) == "n/a"
