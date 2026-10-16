"""Lossless source snapshots and immutable, content-addressed observations."""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from pathlib import Path

from .schema import InputBundle, Issue, MetadataItem, Observation, Source

TERM_LINE = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*(.*)$")
EMPTY = {"", "-", "none", "none found", "n/a"}


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_values(tail: str, label: str) -> tuple[str, ...]:
    match = re.search(
        rf"\b{label}\s*:(.*?)(?=\s+-\s+(?:synonyms|homonyms)\s*:|$)", tail, re.IGNORECASE
    )
    if not match:
        return ()
    value = match.group(1).strip()
    items = re.findall(r"`([^`]+)`", value) or re.split(r"[,;]", value)
    return tuple(item.strip() for item in items if normalize(item.strip(" .")) not in EMPTY)


def parse_source(path: str, raw: bytes) -> tuple[Source, list[Observation], list[Issue]]:
    text = raw.decode("utf-8-sig", errors="replace")
    sha = digest(raw)
    sid = "src_" + digest(path.encode() + b"\0" + raw)
    header = re.match(r"\s*<!--(.*?)-->", text, re.DOTALL)
    metadata = {}
    if header:
        for line in header.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
    source = Source(
        id=sid,
        output_path=path,
        model=metadata.get("model"),
        extraction_run_id=metadata.get("run_id"),
        prompt_fingerprint=metadata.get("prompt_fingerprint"),
        sha256=sha,
        raw_bytes_b64=base64.b64encode(raw).decode(),
        metadata=tuple(MetadataItem(key=k, value=v) for k, v in metadata.items()),
    )
    issues = []

    def warn(code, message):
        issues.append(Issue(severity="warning", code=code, path=f"/sources/{sid}", message=message))

    if not metadata:
        warn("MISSING_METADATA", "No extraction metadata is available.")
    if metadata.get("input_characters_used", "").replace(",", "") == "0":
        warn("ZERO_INPUT", "Extraction reports zero input characters.")
    if metadata.get("status") not in (None, "success"):
        warn("EXTRACTION_UNSUCCESSFUL", f"Extraction status: {metadata['status']}")
    observations = []
    section = ""
    for line_no, line in enumerate(text.splitlines(), 1):
        if header and line_no <= text[: header.end()].count("\n") + 1:
            continue
        if line.startswith("## "):
            section = normalize(line[3:])
            continue
        if not line.strip():
            continue
        match = TERM_LINE.match(line)
        if section in {"primary terms", "homonyms"} and match:
            label, tail = match.groups()
            synonyms = parse_values(tail, "synonyms")
            words = (label.strip(), *synonyms)
            category = "term_entry" if section == "primary terms" else "homonym_claim"
            homonyms = parse_values(tail, "homonyms")
        else:
            words, synonyms, homonyms = (), (), ()
            category = "unparsed"
        observations.append(
            Observation(
                id=f"{sid}_line_{line_no}",
                source_id=sid,
                line=line_no,
                raw_text=line,
                category=category,
                observed_terms=tuple(words),
                synonym_claims=tuple(synonyms),
                homonym_claims=tuple(homonyms),
            )
        )
        if category == "unparsed" and normalize(line.strip(" .")) not in EMPTY:
            warn("UNPARSED_CONTENT", f"Line {line_no} retained for review: {line}")
    if not any(o.category == "term_entry" for o in observations):
        warn("NO_PARSED_TERMS", "No term entries parsed; raw output is retained.")
    if "## primary terms" in normalize(text) and "## homonyms" not in normalize(text):
        warn("POSSIBLY_INCOMPLETE", "Expected Homonyms section is absent; review completeness.")
    return source, observations, issues


def read_outputs(directory: Path) -> InputBundle:
    paths = sorted(directory.rglob("*.md"))
    if not paths:
        raise ValueError(f"no Markdown outputs found in {directory}")
    sources, observations, issues = [], [], []
    for path in paths:
        source, records, warnings = parse_source(
            path.relative_to(directory).as_posix(), path.read_bytes()
        )
        sources.append(source)
        observations.extend(records)
        issues.extend(warnings)
    return InputBundle(
        sources=tuple(sources), observations=tuple(observations), issues=tuple(issues)
    )
