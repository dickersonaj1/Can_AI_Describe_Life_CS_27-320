"""Freeze validated v3.1 documents; do not read or reinterpret historical Markdown."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from feature_dictionary.extraction_v3 import ExtractionDocumentV31, parse_strict_json
from feature_dictionary.settings import decode_text

from .inventory_schema import SourceContext, SynthesisInputs
from .inventory_validation import validate_inputs


def read_inputs(path: Path) -> SynthesisInputs:
    value = parse_strict_json(path.read_text(encoding="utf-8"))
    inputs = SynthesisInputs.model_validate_json(json.dumps(value))
    require_valid(inputs)
    return inputs


def require_valid(inputs: SynthesisInputs) -> None:
    errors = [i for i in validate_inputs(inputs) if i.severity == "error"]
    if errors:
        raise ValueError(
            "Invalid frozen inputs: " + "; ".join(f"{i.code} {i.path}: {i.message}" for i in errors)
        )


def with_source_context(inputs: SynthesisInputs, path: Path) -> SynthesisInputs:
    """Attach explicit source quotes without editing observations or choosing locations."""
    value = parse_strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("Context file must be an array of source-grounded context quotes")
    contexts = tuple(SourceContext.model_validate_json(json.dumps(item)) for item in value)
    result = inputs.model_copy(update={"source_context": (*inputs.source_context, *contexts)})
    require_valid(result)
    return result


def freeze_extractions(paths: list[Path]) -> tuple[SynthesisInputs, dict[str, str]]:
    """Snapshot accepted documents and their original local archive bytes.

    No corrections, deduplication by wording, or salvage of rejected entries.
    Raw/validation sidecars must agree with the published document. Source byte
    archives are verified before any synthesis request is possible.
    """
    sources, observations, archives = [], [], {}
    documents = []
    for path in paths:
        documents.extend(
            sorted(
                p
                for p in path.glob("*.json")
                if not p.name.endswith((".raw.json", ".validation.json"))
            )
            if path.is_dir()
            else [path]
        )
    if not documents:
        raise ValueError("No accepted extraction documents found")
    seen = set()
    for path in documents:
        path = path.resolve()
        if path in seen:
            raise ValueError(f"Duplicate extraction selection: {path}")
        seen.add(path)
        data = path.read_bytes()
        document = ExtractionDocumentV31.model_validate_json(
            json.dumps(parse_strict_json(data.decode("utf-8")))
        )
        raw_path, report_path = path.with_suffix(".raw.json"), path.with_suffix(".validation.json")
        raw_bytes, report_bytes = raw_path.read_bytes(), report_path.read_bytes()
        raw = parse_strict_json(raw_bytes.decode("utf-8"))
        report = parse_strict_json(report_bytes.decode("utf-8"))
        if not isinstance(raw, dict) or not isinstance(report, dict):
            raise ValueError(f"Invalid extraction archive object: {path}")
        if report.get("accepted") is not True or raw.get("response_available") is not True:
            raise ValueError(f"Extraction not accepted: {path}")
        for field in ("input", "run"):
            expected = getattr(document, field).model_dump(mode="json")
            if raw.get(field) != expected or report.get(field) != expected:
                raise ValueError(f"Extraction archive {field} mismatch: {path}")
        if report.get("raw_response") != raw.get("response_text"):
            raise ValueError(f"Extraction raw/report mismatch: {path}")
        if report.get("entries") != [e.model_dump(mode="json") for e in document.entries]:
            raise ValueError(f"Extraction report evidence mismatch: {path}")
        byte_path = (path.parent / document.input.original_file_archive).resolve()
        if not byte_path.is_relative_to(path.parent):
            raise ValueError("Input archive must be inside the extraction output directory")
        original_bytes = byte_path.read_bytes()
        if hashlib.sha256(original_bytes).hexdigest() != document.input.original_file_sha256:
            raise ValueError(f"Original input archive hash mismatch: {path}")
        original_text = decode_text(original_bytes)
        supplied = document.input.supplied_text
        expected_text = (
            original_text[: len(supplied)] if document.input.truncated else original_text
        )
        if supplied != expected_text:
            raise ValueError(f"Supplied text differs from archived original input: {path}")
        sid = "src_" + hashlib.sha256(str(path).encode() + b"\0" + data).hexdigest()
        sources.append(
            dict(
                id=sid,
                output_path=str(path),
                document=document.model_dump(mode="json"),
                raw_response=raw["response_text"],
            )
        )
        for index in range(len(document.entries)):
            observations.append(
                dict(
                    id="obs_" + hashlib.sha256(f"{sid}:{index}".encode()).hexdigest(),
                    source_id=sid,
                    entry_index=index,
                )
            )
        for label, content in [
            ("document", data),
            ("raw", raw_bytes),
            ("validation", report_bytes),
            ("original_input", original_bytes),
        ]:
            archives[f"{sid}/{label}"] = base64.b64encode(content).decode("ascii")
        if raw.get("rendered_prompt_archive"):
            prompt_path = (path.parent / raw["rendered_prompt_archive"]).resolve()
            if not prompt_path.is_relative_to(path.parent):
                raise ValueError("Prompt archive must be inside the extraction output directory")
            prompt_bytes = prompt_path.read_bytes()
            if (
                hashlib.sha256(prompt_bytes).hexdigest()[:16]
                != document.run.rendered_prompt_fingerprint
            ):
                raise ValueError(f"Rendered prompt fingerprint mismatch: {path}")
            archives[f"{sid}/rendered_prompt"] = base64.b64encode(prompt_bytes).decode("ascii")
    inputs = SynthesisInputs.model_validate_json(
        json.dumps(
            dict(format_version="synthesis-input-1.0", sources=sources, observations=observations)
        )
    )
    require_valid(inputs)
    return inputs, archives
