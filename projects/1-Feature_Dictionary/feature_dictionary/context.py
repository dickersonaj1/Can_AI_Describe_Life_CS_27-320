"""An immutable description of one extraction run."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from feature_dictionary import budget
from feature_dictionary.settings import LoadedSettings, render_prompt


@dataclass(frozen=True)
class RunContext:
    """Everything the runner and the writers need to know about this run."""

    run_id: str
    started_at: datetime
    settings: LoadedSettings
    database_text: str
    prompt_text: str
    input_characters_total: int = 0
    input_truncated: bool = False

    @classmethod
    def from_settings(
        cls,
        loaded: LoadedSettings,
        database_text: str,
        *,
        started_at: datetime | None = None,
    ) -> RunContext:
        started = started_at or datetime.now().astimezone()
        limit = loaded.settings.max_input_characters
        truncated = limit is not None and len(database_text) > limit
        embedded = database_text[:limit] if truncated else database_text
        prompt_text = render_prompt(
            loaded.prompt_text,
            embedded,
            loaded.settings.prompt_placeholder,
        )
        return cls(
            run_id=started.isoformat(timespec="seconds"),
            started_at=started,
            settings=loaded,
            database_text=embedded,
            prompt_text=prompt_text,
            input_characters_total=len(database_text),
            input_truncated=truncated,
        )

    @property
    def models(self) -> list[str]:
        return self.settings.settings.models

    @property
    def index_base(self) -> int:
        return self.settings.settings.index_base

    @property
    def output_dir(self) -> Path:
        return self.settings.output_dir

    @property
    def log_dir(self) -> Path:
        return self.settings.log_dir

    @property
    def max_concurrency(self) -> int:
        return self.settings.settings.max_concurrency

    @property
    def is_sequential(self) -> bool:
        return self.max_concurrency <= 1

    @property
    def run_mode(self) -> str:
        if self.is_sequential:
            return f"sequential (max_concurrency={self.max_concurrency})"
        return f"concurrent (max_concurrency={self.max_concurrency})"

    @property
    def keep_alive_label(self) -> str:
        value = self.settings.settings.keep_alive
        return "ollama default" if value is None else str(value)

    @property
    def num_ctx(self) -> int:
        """Context window that will be requested from Ollama."""
        return budget.resolve_num_ctx(self.run_options)

    @property
    def run_options(self) -> dict[str, Any]:
        """Ollama options for this run, with ``max_output_tokens`` applied."""
        options = dict(self.settings.settings.options)
        limit = self.settings.settings.max_output_tokens
        if limit is not None and "num_predict" not in options:
            options["num_predict"] = limit
        return options

    @property
    def instruction_tokens(self) -> int:
        """Tokens used by the prompt scaffolding, excluding the embedded data."""
        template = render_prompt(
            self.settings.prompt_text,
            "",
            self.settings.settings.prompt_placeholder,
        )
        return budget.estimate_tokens(template)

    @property
    def data_budget_characters(self) -> int:
        """Roughly how many characters of input still fit alongside instructions."""
        return budget.data_budget_characters(self.instruction_tokens, self.run_options)

    @property
    def input_fits(self) -> bool:
        """Whether the embedded input stays inside the computed data budget."""
        return len(self.database_text) <= self.data_budget_characters

    @property
    def estimated_prompt_tokens(self) -> int:
        """Rough estimate of the prompt size in tokens."""
        return budget.estimate_tokens(self.prompt_text)

    @property
    def context_overrun(self) -> tuple[int, int] | None:
        """``(estimated_tokens, available_tokens)`` when the prompt will not fit."""
        return budget.context_overrun(self.prompt_text, self.run_options)

    @property
    def prompt_fingerprint(self) -> str:
        """Short SHA-256 digest of the rendered prompt, for traceability."""
        return hashlib.sha256(self.prompt_text.encode("utf-8")).hexdigest()[:16]
