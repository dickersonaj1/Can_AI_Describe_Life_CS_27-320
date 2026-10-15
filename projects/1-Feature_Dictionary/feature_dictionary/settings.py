"""Reading, validating and resolving ``settings.json``.

The settings file is the single source of truth for the prompt, the list of
local and cloud models to run, and the output/log locations. Relative paths are resolved
against the directory that contains ``settings.json`` so the project stays
portable, and ``~`` is still expanded for convenience.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

DEFAULT_SETTINGS_FILENAME = "settings.json"
DEFAULT_PLACEHOLDER = "{species_database}"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_LOOP_GUARD_REPEATS = 25
"""How often one line may repeat inside the loop-guard window before aborting."""

DEFAULT_ANTHROPIC_OUTPUT_TOKENS = 4096
"""Fallback when no shared output cap is configured; Anthropic requires a cap."""

MODEL_ALIASES = {
    "gpt": {"provider": "openai", "model": "gpt-5.4-nano"},
    "claude": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
    "gemini": {"provider": "gemini", "model": "gemini-3.8-flash"},
}
LOCAL_MODEL_IDS = frozenset({"qwen3:8b", "deepseek-r1:8b", "llama3.1:8b"})
PROVIDERS = frozenset({"ollama", "openai", "anthropic", "gemini"})


class SettingsError(RuntimeError):
    """Raised when the settings file is missing, malformed or inconsistent."""


class ModelConfig(BaseModel):
    provider: Literal["ollama", "openai", "anthropic", "gemini"]
    model: str = Field(min_length=1)

    @field_validator("model", mode="before")
    @classmethod
    def _strip_model(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


def parse_model_selection(
    value: str,
    configured_models: list[Any] | None = None,
    configured_aliases: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Resolve CLI selectors against configured identities; never guess a provider.

    Explicit provider:model and legacy provider=model bypass the local catalog.
    Bare names must be configured, a known model ID, an alias, or an unambiguous
    provider selection. The settings file's legacy strings still mean Ollama.
    """
    try:
        aliases = _check_alias_names(
            TypeAdapter(dict[str, ModelConfig]).validate_python(
                configured_aliases if configured_aliases is not None else {}
            )
        )
    except ValueError as exc:
        raise SettingsError(f"invalid model_aliases: {exc}") from exc
    alias_models = {name: config.model_dump() for name, config in aliases.items()}
    configured = []
    for item in configured_models or []:
        try:
            config = (
                ModelConfig(provider="ollama", model=item)
                if isinstance(item, str)
                else ModelConfig.model_validate(item)
            )
            configured.append(config.model_dump())
        except ValidationError:
            # A valid CLI override can replace invalid model configuration as before.
            continue
    known = [
        *MODEL_ALIASES.values(),
        *alias_models.values(),
        *({"provider": "ollama", "model": model} for model in sorted(LOCAL_MODEL_IDS)),
    ]
    selected = []
    seen = set()
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        if "=" in item or (":" in item and item.split(":", 1)[0].strip() in PROVIDERS):
            delimiter = "=" if "=" in item else ":"
            provider, model = (part.strip() for part in item.split(delimiter, 1))
            if provider not in PROVIDERS or not model:
                raise SettingsError(
                    f"invalid model selector {item!r}; use provider:model with "
                    "ollama, openai, anthropic, or gemini"
                )
            match = {"provider": provider, "model": model}
        else:
            if item in alias_models:
                candidates = [alias_models[item]]
                # Explicit aliases may select one of several models for a provider.
                # A collision with a different native model ID is genuinely ambiguous.
                native = [c for c in configured if c["model"] == item]
                if not native:
                    native = [c for c in known if c["model"] == item]
                candidates.extend(native)
            elif item in PROVIDERS:
                candidates = [c for c in configured if c["provider"] == item]
                if not candidates:
                    candidates = [
                        c
                        for c in {**MODEL_ALIASES, **alias_models}.values()
                        if c["provider"] == item
                    ]
            elif item in MODEL_ALIASES:
                candidates = [MODEL_ALIASES[item]]
            else:
                candidates = [c for c in configured if c["model"] == item]
                if not candidates:
                    candidates = [c for c in known if c["model"] == item]
            identities = {(c["provider"], c["model"]) for c in candidates}
            if len(identities) != 1:
                reason = "ambiguous" if identities else "unknown"
                raise SettingsError(
                    f"{reason} model selector {item!r}; use an explicit provider:model "
                    "or configure its provider and model in settings.json"
                )
            provider, model = next(iter(identities))
            match = {"provider": provider, "model": model}
        identity = (match["provider"], match["model"])
        if identity in seen:
            raise SettingsError(f"duplicate model selection: {identity[0]}:{identity[1]}")
        seen.add(identity)
        selected.append(match)
    if not selected:
        raise SettingsError("--models needs at least one model identifier")
    return selected


def _check_alias_names(aliases: dict[str, ModelConfig]) -> dict[str, ModelConfig]:
    """Aliases are direct identities, not recursive selectors or syntax-bearing strings."""
    for name, config in aliases.items():
        if not name or any(char.isspace() or char in ",:=" for char in name):
            raise ValueError(
                "alias names must be nonempty tokens without whitespace, comma, : or ="
            )
        if name in PROVIDERS and config.provider != name:
            raise ValueError(f"provider-named alias {name!r} must target provider {name!r}")
    return aliases


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
    extraction_format: Literal["v2", "v3"] = "v2"
    v3_candidate_version: Literal["3.0", "3.1"] = "3.1"
    v3_prompt_file: Path | None = None
    models: list[ModelConfig] = Field(min_length=1)
    model_aliases: dict[str, ModelConfig] = Field(default_factory=dict)

    @field_validator("model_aliases")
    @classmethod
    def _validate_alias_names(cls, value: dict[str, ModelConfig]) -> dict[str, ModelConfig]:
        return _check_alias_names(value)

    @field_validator("models", mode="before")
    @classmethod
    def _normalize_models(cls, value: Any) -> Any:
        """Treat legacy model strings as Ollama model configurations."""
        if not isinstance(value, list):
            return value

        return [
            {"provider": "ollama", "model": model} if isinstance(model, str) else model
            for model in value
        ]

    options: dict[str, Any] = Field(default_factory=dict)
    output_dir: Path = Path("extractor_outputs")
    log_dir: Path = Path("extractor_logs")
    index_base: int = 0
    log_date_format: str = "%m_%d"
    log_append: bool = True
    stream: bool = False
    keep_alive: str | float | None = "5m"
    ollama_think: bool | None = Field(
        default=None,
        strict=True,
        description="Ollama-only thinking request; null omits think for historical compatibility.",
    )
    ollama_output_format: Literal["candidate_schema"] | None = Field(
        default=None,
        description="Opt-in Ollama schema constraint for extraction-3.1; null omits format.",
    )
    anthropic_output_format: Literal["candidate_schema"] | None = Field(
        default=None,
        description="Opt-in Anthropic native JSON output for extraction-3.1; null omits it.",
    )
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
            "Cap on generated tokens for cloud providers and Ollama. Applied as num_predict "
            "unless options.num_predict "
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

    @model_validator(mode="after")
    def _validate_prompt_source(self) -> ExtractorSettings:
        if self.anthropic_output_format is not None and (
            self.extraction_format != "v3" or self.v3_candidate_version != "3.1"
        ):
            raise ValueError("anthropic_output_format requires Extraction v3 candidate version 3.1")
        if self.ollama_output_format is not None and (
            self.extraction_format != "v3" or self.v3_candidate_version != "3.1"
        ):
            raise ValueError("ollama_output_format requires Extraction v3 candidate version 3.1")
        if self.extraction_format == "v3":
            return self  # V3 has its own prompt; legacy prompt settings remain untouched.
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
    def models(self) -> list[ModelConfig]:
        return self.settings.models

    @property
    def prompt_path(self) -> Path | None:
        return resolve_prompt_path(self.settings, self.base_dir)


def read_text_file(path: Path) -> str:
    """Read a text file as UTF-8, falling back to cp1252 for Windows-authored data."""
    return decode_text(path.read_bytes())


def decode_text(data: bytes) -> str:
    """Decode a captured input snapshot with the existing UTF-8/cp1252 policy."""
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
    *,
    preserve_input: bool = False,
) -> str:
    """Insert the species database text into the prompt.

    ``{species_database}`` receives the text of the input file. When the
    placeholder is missing, the database is appended to the prompt instead so a
    custom prompt never silently loses the data.
    """
    embedded = database_text if preserve_input else database_text.strip()
    if placeholder and placeholder in prompt_text:
        return prompt_text.replace(placeholder, embedded)
    return f"{prompt_text.rstrip()}\n\n{embedded}\n"


def resolve_prompt_path(settings: ExtractorSettings, base_dir: Path) -> Path | None:
    """One effective prompt path for loading and provenance; v3 is independent of v2."""
    if settings.extraction_format == "v3":
        return (
            resolve_path(settings.v3_prompt_file, base_dir)
            if settings.v3_prompt_file is not None
            else Path(__file__).resolve().parents[1]
            / "prompts"
            / (
                "extraction_v3.txt"
                if settings.v3_candidate_version == "3.0"
                else "extraction_v3_1.txt"
            )
        )
    return (
        resolve_path(settings.prompt_file, base_dir) if settings.prompt_file is not None else None
    )


def read_prompt(settings: ExtractorSettings, base_dir: Path) -> str:
    """Return the raw prompt text (from ``prompt_file`` or the inline ``prompt``)."""
    prompt_path = resolve_prompt_path(settings, base_dir)
    if prompt_path is not None:
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
        overrides = dict(overrides)
        if overrides.get("max_output_tokens") is not None:
            options = overrides.get("options", raw.get("options", {}))
            if isinstance(options, dict) and "num_predict" in options:
                # An explicit shared-budget override also supersedes a local
                # budget. Without the override, legacy num_predict precedence stays.
                overrides["options"] = {**options, "num_predict": overrides["max_output_tokens"]}
        if isinstance(overrides.get("models"), str):
            configured = raw.get("models")
            overrides["models"] = parse_model_selection(
                overrides["models"],
                configured if isinstance(configured, list) else None,
                overrides.get("model_aliases", raw.get("model_aliases", {})),
            )
        raw = {**raw, **overrides}
        if raw.get("extraction_format", "v2") == "v3" and overrides.get("prompt_file"):
            # --prompt-file targets the selected format; preserve configured v2 instructions.
            raw["v3_prompt_file"] = overrides["prompt_file"]

    try:
        settings = ExtractorSettings.model_validate(raw)
    except ValidationError as exc:
        raise SettingsError(f"invalid settings in {settings_path.name}:\n{exc}") from exc
    return resolve_settings(settings, settings_path)
