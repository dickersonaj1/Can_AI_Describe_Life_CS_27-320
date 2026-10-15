"""Readable, deterministic offline audits. Invalid model records remain visible."""

from __future__ import annotations

import json
import re
from pathlib import Path

from feature_dictionary.extraction_v3 import parse_strict_json

from .inventory_schema import SynthesisInputs


def safe(value) -> str:
    """Escape untrusted model/source content instead of allowing Markdown injection."""
    value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = value.replace("\n", "\\n").replace("\r", "\\r")
    value = re.sub(r"([\\`*\[\]~])", r"\\\1", value)
    return re.sub(r"(?<!\w)_|_(?!\w)", r"\\_", value)


def render_report(
    inputs: SynthesisInputs,
    response: dict,
    validation: dict,
    request: dict | None = None,
    *,
    include_raw_json: bool = False,
) -> str:
    request = request or {}
    try:
        data = parse_strict_json(response.get("response_text", ""))
    except ValueError:
        data = None
    raw_data = data
    if request.get("observation_refs") == "short":
        # Keep the appendix original; hierarchy uses the separately validated expansion.
        data = validation.get("derived_proposal") or data
    terms = data.get("terms", []) if isinstance(data, dict) else []
    if not isinstance(terms, list):
        terms = []
    issues = validation.get("issues", [])
    lines = [
        "# Synthesis v1.2 — model proposal audit",
        "",
        "**UNVALIDATED MODEL PROPOSAL — NOT A COMPILED DICTIONARY.**",
        "Software checks assess formatting, evidence and references, not biological correctness.",
        "",
        f"Completion: {safe(response.get('completion_status', 'unknown'))}; "
        f"JSON valid: {validation.get('json_valid', False)}; "
        f"schema valid: {validation.get('schema_valid', False)}; "
        f"proposal checks passed: {validation.get('proposal_valid', False)}.",
        "",
    ]
    sources = {s.id: s.document for s in inputs.sources}
    observations = {o.id: o for o in inputs.observations}

    def evidence(refs, indent=""):
        if not isinstance(refs, list):
            lines.append(indent + "- [INVALID] Evidence refs are not an array.")
            return
        for oid in refs:
            obs = observations.get(str(oid))
            if (
                obs is None
                or obs.source_id not in sources
                or obs.entry_index >= len(sources[obs.source_id].entries)
            ):
                lines.append(f"{indent}- [INVALID] Unknown observation {safe(oid)}")
                continue
            entry = sources[obs.source_id].entries[obs.entry_index]
            quote = safe(json.dumps(entry.matched_text, ensure_ascii=False))
            warning = " **[ambiguous location]**" if entry.location.status == "ambiguous" else ""
            lines.append(f"{indent}- Evidence {safe(oid)}: {quote}{warning}")

    def term(record, index, level):
        path = f"/terms/{index}"
        marked = any(
            i.get("severity") == "error"
            and (i.get("path") == path or str(i.get("path", "")).startswith(path + "/"))
            for i in issues
        )
        marker = "INVALID — see issues" if marked else "proposed; scientifically unvalidated"
        lines.extend(
            [
                f"{'#' * level} {safe(record.get('text', '[missing text]'))} — "
                f"{safe(record.get('ref', '[missing ref]'))}",
                "",
                f"[{marker}] {safe(record.get('type', 'missing type'))}",
                "",
                f"Rationale: {safe(record.get('rationale', '[missing]'))}",
                "",
            ]
        )
        if record.get("type") == "compound":
            refs = record.get("primary_refs", [])
            if isinstance(refs, list):
                labels = []
                for ref in refs:
                    names = [
                        safe(p.get("text", "[missing text]"))
                        for _, p in primaries
                        if p.get("ref") == ref
                    ]
                    labels.append(
                        f"{', '.join(names)} ({safe(ref)})" if names else f"[INVALID] {safe(ref)}"
                    )
                lines.extend(["Associated primaries: " + (", ".join(labels) or "none"), ""])
                valid_refs = {ref for ref in refs if isinstance(ref, str) and ref in primary_refs}
                if len(valid_refs) > 1:
                    lines.extend(
                        [
                            "**Shared indexed compound:** stored once; "
                            "displayed under each associated primary.",
                            "",
                        ]
                    )
            else:
                lines.extend(["[INVALID] Primary associations are not an array.", ""])
        evidence(record.get("observation_ids", []))
        expressions = record.get("expressions", [])
        if not isinstance(expressions, list):
            lines.extend(["", "[INVALID] Expressions are not an array."])
        elif not expressions:
            lines.extend(["", "Local contextual expressions: none."])
        else:
            lines.extend(["", "Local contextual expressions:", ""])
            for expression in expressions:
                if not isinstance(expression, dict):
                    lines.append(f"- [INVALID] {safe(expression)}")
                    continue
                lines.append(
                    f"- **{safe(expression.get('text', '[missing text]'))}** — "
                    f"{safe(expression.get('rationale', '[missing rationale]'))}"
                )
                evidence(expression.get("observation_ids", []), indent="  ")
        lines.append("")

    indexed = [(i, t) for i, t in enumerate(terms) if isinstance(t, dict)]

    def ordered(items):
        return sorted(
            items,
            key=lambda item: (
                str(item[1].get("text", "")).casefold(),
                str(item[1].get("text", "")),
                str(item[1].get("ref", "")),
                item[0],
            ),
        )

    primaries = ordered([(i, t) for i, t in indexed if t.get("type") == "primary"])
    compounds = ordered([(i, t) for i, t in indexed if t.get("type") == "compound"])
    primary_refs = {t.get("ref") for _, t in primaries if isinstance(t.get("ref"), str)}
    lines.extend(["## Primary anatomical terms", ""])
    for index, primary in primaries:
        term(primary, index, 3)
        associated = [
            (i, c)
            for i, c in compounds
            if isinstance(c.get("primary_refs"), list) and primary.get("ref") in c["primary_refs"]
        ]
        if not associated:
            lines.extend(["Associated indexed compounds: none.", ""])
        for ci, compound in associated:
            term(compound, ci, 4)
    lines.extend(["## Orphan or unlinked indexed compounds", ""])
    orphans = [
        (i, c)
        for i, c in compounds
        if not isinstance(c.get("primary_refs"), list)
        or not any(isinstance(ref, str) and ref in primary_refs for ref in c["primary_refs"])
    ]
    for index, compound in orphans:
        term(compound, index, 3)
    if not orphans:
        lines.extend(["None.", ""])
    lines.extend(["## Invalid or unclassified records", ""])
    if not isinstance(data, dict):
        lines.extend(
            [
                "[INVALID] The raw response is not a proposal object. See validation issues; "
                "use --include-raw-json to include the archived response.",
                "",
            ]
        )
    for index, record in enumerate(terms):
        if not isinstance(record, dict):
            lines.extend([f"- [INVALID] terms[{index}]: {safe(record)}", ""])
        elif record.get("type") not in ("primary", "compound"):
            term(record, index, 3)
    decisions = data.get("observation_dispositions", []) if isinstance(data, dict) else []
    if not isinstance(decisions, list):
        decisions = []
    for title, status in [("Exclusions", "excluded"), ("Unresolved observations", "unresolved")]:
        lines.extend([f"## {title}", ""])
        matching = [d for d in decisions if isinstance(d, dict) and d.get("status") == status]
        for decision in sorted(matching, key=lambda d: str(d.get("observation_id", ""))):
            lines.append(
                f"- {safe(decision.get('observation_id', '[missing]'))}: "
                f"{safe(decision.get('reason', '[missing reason]'))}"
            )
            evidence([decision.get("observation_id")])
        if status == "unresolved":
            decided = {
                d.get("observation_id")
                for d in decisions
                if isinstance(d, dict)
                and isinstance(d.get("observation_id"), str)
                and d.get("status") in ("mapped", "excluded", "unresolved")
            }
            for oid in sorted(observations.keys() - decided):
                lines.append(
                    f"- [MISSING DECISION — UNRESOLVED] {safe(oid)}. "
                    "No exclusion or attachment inferred."
                )
                evidence([oid])
        lines.append("")
    lines.extend(
        [
            "## Evidence details",
            "",
            "Exact quotations and source locations are preserved below. "
            "Offsets are zero-based, end-exclusive Python character positions.",
            "",
        ]
    )
    for obs in inputs.observations:
        source = sources.get(obs.source_id)
        if source is None or obs.entry_index >= len(source.entries):
            lines.extend([f"### {safe(obs.id)}", "", "[INVALID] Source entry unavailable.", ""])
            continue
        entry = source.entries[obs.entry_index]
        lines.extend(
            [
                f"### {safe(obs.id)}",
                "",
                "- Extracted phrase: " + safe(json.dumps(entry.matched_text, ensure_ascii=False)),
                "- Source phrase: " + safe(json.dumps(entry.source_phrase, ensure_ascii=False)),
                f"- Location status: **{safe(entry.location.status)}**",
            ]
        )
        for candidate in entry.location.candidates:
            lines.append(
                f"- Match offsets: {candidate.match_span.start}:{candidate.match_span.end}; "
                f"source-phrase offsets: {candidate.phrase_span.start}:{candidate.phrase_span.end}"
            )
        lines.extend(
            [
                f"- Source: {safe(obs.source_id)}; entry index: {obs.entry_index}",
                f"- Extractor: {safe(source.run.provider)}:{safe(source.run.model)}",
                f"- Extraction run: {safe(source.run.run_id)}; "
                f"prompt: {safe(source.run.prompt_version)}",
                f"- Original source path: {safe(source.input.source_path)}",
                "",
            ]
        )
    lines.extend(["## Review notes and nonauthoritative equivalence proposals", ""])
    if isinstance(data, dict):
        for key in ["review_notes", "equivalence_proposals"]:
            values = data.get(key, [])
            if not isinstance(values, list):
                lines.append(f"- [INVALID] {safe(key)}: {safe(values)}")
                continue
            for value in values:
                text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
                lines.append(f"- {safe(text)}")
    lines.extend(["", "## Model metadata and audit counts", ""])
    expression_count = sum(
        len(t.get("expressions", [])) for _, t in indexed if isinstance(t.get("expressions"), list)
    )
    excluded = {
        d.get("observation_id")
        for d in decisions
        if isinstance(d, dict)
        and d.get("status") == "excluded"
        and isinstance(d.get("observation_id"), str)
    }
    unresolved = {
        d.get("observation_id")
        for d in decisions
        if isinstance(d, dict)
        and d.get("status") == "unresolved"
        and isinstance(d.get("observation_id"), str)
    }
    decided = {
        d.get("observation_id")
        for d in decisions
        if isinstance(d, dict)
        and d.get("status") in ("mapped", "excluded", "unresolved")
        and isinstance(d.get("observation_id"), str)
    }
    unresolved.update(observations.keys() - decided)
    identity = request.get("identity", {})
    provider = identity.get(
        "provider", data.get("provider", "unknown") if isinstance(data, dict) else "unknown"
    )
    model = identity.get(
        "model", data.get("model", "unknown") if isinstance(data, dict) else "unknown"
    )
    lines.extend(
        [
            f"- Model: {safe(provider)}:{safe(model)}",
            f"- Input SHA-256: {safe(request.get('input_sha256', 'not supplied'))}",
            f"- Prompt SHA-256: {safe(request.get('prompt_sha256', 'not supplied'))}",
            f"- Completion reason: {safe(response.get('completion_reason', 'unknown'))}",
            "- Token/timing metrics: "
            + safe(json.dumps(response.get("metrics"), ensure_ascii=False)),
            f"- Observations: {len(observations)}; stored primaries: {len(primaries)}; "
            f"stored compounds: {len(compounds)}; raw term records: {len(terms)}.",
            f"- Local expressions: {expression_count}; exclusions: {len(excluded)}; "
            f"unresolved (including missing decisions): {len(unresolved)}.",
            "- Compounds displayed beneath several primaries are counted once as stored records, "
            "not biological frequency counts.",
            "",
            "## Validation issues",
            "",
        ]
    )
    for issue in issues:
        lines.append(
            f"- [{safe(issue.get('severity', 'unknown'))}] {safe(issue.get('code', 'unknown'))} "
            f"{safe(issue.get('path', '/'))}: {safe(issue.get('message', ''))}"
        )
    if not issues:
        lines.append(
            "No software validation issues reported. Scientific interpretation remains unvalidated."
        )
    if include_raw_json:
        lines.extend(["", "## Complete raw proposal appendix", ""])
        raw = (
            json.dumps(raw_data, ensure_ascii=True, indent=2)
            if data is not None
            else response.get("response_text", "")
        )
        lines.append(
            "<pre>"
            + str(raw).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            + "</pre>"
        )
    return "\n".join(lines) + "\n"


def write_report(
    path: Path,
    inputs: SynthesisInputs,
    response: dict,
    validation: dict,
    request: dict | None = None,
    *,
    include_raw_json: bool = False,
) -> None:
    text = render_report(inputs, response, validation, request, include_raw_json=include_raw_json)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
