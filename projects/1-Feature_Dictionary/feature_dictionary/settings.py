"""Reading, validating and resolving ``settings.json``.

The settings file is the single source of truth for the prompt, the list of
Ollama models to run, and the output/log locations. Relative paths are resolved
against the directory that contains ``settings.json`` so the project stays
portable, and ``~`` is still expanded for convenience.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DEFAULT_SETTINGS_FILENAME = "settings.json"
DEFAULT_PLACEHOLDER = "{species_database}"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_LOOP_GUARD_REPEATS = 25
"""How often one line may repeat inside the loop-guard window before aborting."""


class SettingsError(RuntimeError):
    """Raised when the settings file is missing, malformed or inconsistent."""


class ExtractorSettings(BaseModel):
    """Validated contents of ``settings.json`` (unknown keys are rejected)."""

    model_config = ConfigDict(extra="forbid")

    host: str | None = Field(
        default=None,
        description="Ollama base URL; falls back to $OLLAMA_HOST, then http://127.0.0.1:11434.",
    )
    input_file: Path = Path("species_database.txt")
    prompt: str | None = None
    prompt_file: Path | None = None
    models: list[str] = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)
    output_dir: Path = Path("extractor_outputs")
    log_dir: Path = Path("extractor_logs")
    index_base: int = 0
    log_date_format: str = "%m_%d"
    log_append: bool = True
    stream: bool = False
    keep_alive: str | float | None = "5m"
    request_timeout_seconds: float = Field(default=900.0, gt=0)
    max_concurrency: int = Field(default=1, ge=1)
    include_thinking: bool = False
    output_metadata_header: bool = True
    continue_on_error: bool = True
    write_run_summary: bool = True
    prompt_placeholder: str = DEFAULT_PLACEHOLDER
    fail_on_context_overrun: bool = Field(
        default=False,
        description="Abort before running when the prompt cannot fit inside num_ctx.",
    )
    max_input_characters: int | None = Field(
        default=None,
        gt=0,
        description="Optional cap on how much of the input file is embedded in the prompt.",
    )
    max_output_tokens: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Cap on generated tokens. Applied as num_predict unless options.num_predict "
            "is set explicitly."
        ),
    )
    loop_guard: bool = Field(
        default=False,
        description="Stop a model that has locked into repeating the same lines over and over.",
    )
    loop_guard_repeats: int = Field(
        default=DEFAULT_LOOP_GUARD_REPEATS,
        ge=2,
        description="How often a line may repeat inside the loop-guard window before aborting.",
    )
    fail_on_context_overrun: bool = False

    @model_validator(mode="after")
    def _validate_prompt_source(self) -> ExtractorSettings:
        if self.prompt is None and self.prompt_file is None:
            raise ValueError("set either 'prompt' or 'prompt_file'")
        if self.prompt is not None and self.prompt_file is not None:
            raise ValueError("set either 'prompt' or 'prompt_file', not both")
        return self


@dataclass(frozen=True)
class LoadedSettings:
    """A validated settings file plus every path resolved to an absolute location."""

    settings: ExtractorSettings
    path: Path
    base_dir: Path
    input_path: Path
    output_dir: Path
    log_dir: Path
    prompt_text: str
    ollama_host: str

    @property
    def models(self) -> list[str]:
        return self.settings.models


def read_text_file(path: Path) -> str:
    """Read a text file as UTF-8, falling back to cp1252 for Windows-authored data."""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def resolve_path(value: str | Path, base_dir: Path) -> Path:
    """Expand ``~`` and resolve a possibly relative path against ``base_dir``."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def render_prompt(
    prompt_text: str,
    database_text: str,
    placeholder: str = DEFAULT_PLACEHOLDER,
) -> str:
    """Insert the species database text into the prompt.

    ``{species_database}`` receives the text of the input file. When the
    placeholder is missing, the database is appended to the prompt instead so a
    custom prompt never silently loses the data.
    """
    if placeholder and placeholder in prompt_text:
        return prompt_text.replace(placeholder, database_text.strip())
    return f"{prompt_text.rstrip()}\n\n{database_text.strip()}\n"


def read_prompt(settings: ExtractorSettings, base_dir: Path) -> str:
    """Return the raw prompt text (from ``prompt_file`` or the inline ``prompt``)."""
    if settings.prompt_file is not None:
        prompt_path = resolve_path(settings.prompt_file, base_dir)
        if not prompt_path.is_file():
            raise SettingsError(f"prompt file not found: {prompt_path}")
        text = read_text_file(prompt_path)
    else:
        text = settings.prompt or ""
    if not text.strip():
        raise SettingsError("the configured prompt is empty")
    return text


def resolve_settings(settings: ExtractorSettings, settings_path: Path) -> LoadedSettings:
    """Turn a validated settings object into absolute paths (no network access)."""
    base_dir = settings_path.parent
    input_path = resolve_path(settings.input_file, base_dir)
    if not input_path.is_file():
        raise SettingsError(f"input file not found: {input_path}")
    return LoadedSettings(
        settings=settings,
        path=settings_path,
        base_dir=base_dir,
        input_path=input_path,
        output_dir=resolve_path(settings.output_dir, base_dir),
        log_dir=resolve_path(settings.log_dir, base_dir),
        prompt_text=read_prompt(settings, base_dir),
        ollama_host=settings.host or os.getenv("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST,
    )


def load_settings(
    path: str | Path = DEFAULT_SETTINGS_FILENAME,
    *,
    overrides: dict[str, Any] | None = None,
) -> LoadedSettings:
    """Read, validate and resolve ``settings.json``.

    ``overrides`` are merged into the raw JSON before validation, which is how
    command line flags (``--models``, ``--input``, ...) take precedence while
    still being checked by the same rules.
    """
    settings_path = Path(path).expanduser()
    if not settings_path.is_absolute():
        settings_path = (Path.cwd() / settings_path).resolve()
    if not settings_path.is_file():
        raise SettingsError(f"settings file not found: {settings_path}")

    try:
        raw = json.loads(read_text_file(settings_path))
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{settings_path.name} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SettingsError(f"{settings_path.name} must contain a JSON object at the top level")

    if overrides:
        raw = {**raw, **overrides}

    try:
        settings = ExtractorSettings.model_validate(raw)
    except ValidationError as exc:
        raise SettingsError(f"invalid settings in {settings_path.name}:\n{exc}") from exc
    return resolve_settings(settings, settings_path)
