"""An immutable description of one extraction run."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

from anthropic import transform_schema

from feature_dictionary import budget
from feature_dictionary.extraction_v3 import CandidateResponseV31
from feature_dictionary.settings import LoadedSettings, ModelConfig, render_prompt


def _schema_sha256(schema: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
    original_input_bytes: bytes | None = None
    ollama_runtime: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_settings(
        cls,
        loaded: LoadedSettings,
        database_text: str,
        *,
        started_at: datetime | None = None,
        original_input_bytes: bytes | None = None,
    ) -> RunContext:
        started = started_at or datetime.now().astimezone()
        limit = loaded.settings.max_input_characters
        truncated = limit is not None and len(database_text) > limit
        embedded = database_text[:limit] if truncated else database_text
        prompt_text = render_prompt(
            loaded.prompt_text,
            embedded,
            loaded.settings.prompt_placeholder,
            preserve_input=loaded.settings.extraction_format == "v3",
        )
        return cls(
            run_id=f"{started.isoformat(timespec='microseconds')}_{uuid4().hex}",
            started_at=started,
            settings=loaded,
            database_text=embedded,
            prompt_text=prompt_text,
            input_characters_total=len(database_text),
            input_truncated=truncated,
            original_input_bytes=original_input_bytes,
        )

    @property
    def models(self) -> list[ModelConfig]:
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
    def ollama_think_label(self) -> str:
        value = self.settings.settings.ollama_think
        if value is None:
            return "model default (think omitted)"
        return "enabled (think=true)" if value else "disabled (think=false)"

    @property
    def ollama_output_schema(self) -> dict[str, Any] | None:
        if self.settings.settings.ollama_output_format is None:
            return None
        return CandidateResponseV31.model_json_schema()

    @property
    def ollama_output_constraint(self) -> dict[str, Any]:
        schema = self.ollama_output_schema
        return {
            "mode": self.settings.settings.ollama_output_format,
            "schema_identity": "extraction-3.1/candidate" if schema is not None else None,
            "schema_sha256": (_schema_sha256(schema) if schema is not None else None),
            "schema": schema,
        }

    @property
    def anthropic_output_schema(self) -> dict[str, Any] | None:
        """Provider request projection; the original Python contract stays authoritative."""
        if self.settings.settings.anthropic_output_format is None:
            return None
        schema = CandidateResponseV31.model_json_schema()
        # Anthropic requires typed, closed objects. Optional annotations remain
        # unverified suggestions, with their conventional shape requested here.
        schema["$defs"]["CandidateEntryV31"]["properties"]["proposed_annotations"] = {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "language": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "forms": {"type": "array", "items": {"type": "string"}},
                    },
                    "description": "Optional unverified language/form suggestions.",
                },
            ]
        }
        # SDK 1.9.0 moves const into prose; enum preserves the required version
        # as a native constraint. Unsupported minLength stays in descriptions
        # and is still checked by the unchanged Python validator.
        version_field = schema["properties"]["format_version"]
        version_field["enum"] = [version_field.pop("const")]
        return transform_schema(schema)

    @property
    def anthropic_output_constraint(self) -> dict[str, Any]:
        schema = self.anthropic_output_schema
        return {
            "mode": self.settings.settings.anthropic_output_format,
            "request_parameter": "output_config.format",
            "schema_identity": "extraction-3.1/candidate/anthropic-projection-1",
            "schema_sha256": _schema_sha256(schema) if schema is not None else None,
            "schema": schema,
            "original_schema_sha256": _schema_sha256(CandidateResponseV31.model_json_schema()),
            "sdk_version": version("anthropic"),
            "adaptations": [
                "minLength moved to descriptions; Python still enforces it",
                "format_version const represented as single-value enum",
                "optional annotations constrained to null or language/forms object",
            ],
        }

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

    @property
    def prompt_path(self) -> str:
        value = self.settings.prompt_path
        return str(value) if value is not None else "inline"

    @property
    def prompt_template_sha256(self) -> str:
        return hashlib.sha256(self.settings.prompt_text.encode("utf-8")).hexdigest()

    @property
    def prompt_version(self) -> str:
        """Filename version if declared; content identity for unversioned/inline templates."""
        match = re.search(r"(?:^|[_-])(v\d+(?:[._-]\d+)*)$", Path(self.prompt_path).stem)
        return match.group(1) if match else f"unversioned@{self.prompt_template_sha256[:16]}"
