"""Opt-in v3 contracts and offline quotation checking; no runners or filesystem I/O.

Evidence validity means exact textual support, not biological correctness or
extraction completeness. Annotations are unverified suggestions, never evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

FORMAT_VERSION = "extraction-3.0"
FORMAT_VERSION_V31 = "extraction-3.1"
FORMS = frozenset(
    {"abbreviation", "acronym", "shorthand", "historical_expression", "spelling_variant"}
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CandidateEntry(Contract):
    """Model output: quotations only; positions and canonical names are not requested."""

    term: str = Field(min_length=1)
    evidence_type: Literal["complete", "embedded"]
    matched_text: str = Field(min_length=1)
    source_phrase: str = Field(min_length=1)
    proposed_annotations: Any = Field(
        default=None,
        description=(
            "Optional unverified suggestions, conventionally an object with language "
            "(string or null) and forms (string array). Malformed suggestions yield warnings."
        ),
    )


class CandidateResponse(Contract):
    format_version: Literal["extraction-3.0"]
    entries: list[CandidateEntry]


class CandidateEntryV31(Contract):
    """V3.1 asks only for quotations and optional unverified annotations."""

    matched_text: str = Field(min_length=1)
    source_phrase: str = Field(min_length=1)
    proposed_annotations: Any = Field(
        default=None,
        description=(
            "Optional unverified language/form suggestions; malformed values yield warnings."
        ),
    )


class CandidateResponseV31(Contract):
    format_version: Literal["extraction-3.1"]
    entries: list[CandidateEntryV31]


class Span(Contract):
    """Zero-based Python string positions; end is excluded. Never UTF-8 byte offsets."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)


class LocationCandidate(Contract):
    match_span: Span
    phrase_span: Span


class Location(Contract):
    status: Literal["resolved", "ambiguous", "unmatched"]
    candidates: list[LocationCandidate]


class Issue(Contract):
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


class EvidenceEntry(Contract):
    term: str
    model_term: str
    evidence_type: Literal["complete", "embedded"]
    matched_text: str
    source_phrase: str
    location: Location
    proposed_annotations: Any = None
    issues: list[Issue]


class EvidenceEntryV31(EvidenceEntry):
    """No independent label was requested; null explicitly records that absence."""

    model_term: None = None


class ExtractionInput(Contract):
    """Host-supplied metadata. Archive reference must identify unchanged original bytes."""

    source_path: str
    original_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_file_archive: str
    supplied_text: str
    supplied_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    truncated: bool


class ExtractionRun(Contract):
    """Provider completion is recorded separately from evidence validity."""

    run_id: str
    provider: Literal["ollama", "openai", "anthropic", "gemini"]
    model: str
    prompt_version: str
    prompt_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_prompt_fingerprint: str
    completion_status: str
    completion_reason: str | None


class ExtractionDocument(Contract):
    """Host-assembled artifact; loading its shape alone does not validate its evidence."""

    format_version: Literal["extraction-3.0"]
    input: ExtractionInput
    run: ExtractionRun
    entries: list[EvidenceEntry]


class ExtractionDocumentV31(ExtractionDocument):
    format_version: Literal["extraction-3.1"]
    entries: list[EvidenceEntryV31]


class EvidenceReport(Contract):
    """Retains the original response even if parsing fails. Does not write an archive."""

    raw_response: str
    supplied_text_sha256: str | None
    entries: list[EvidenceEntry | EvidenceEntryV31]
    issues: list[Issue]

    @property
    def evidence_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def text_sha256(text: str) -> str:
    """Hash exact UTF-8 text without whitespace, newline, or Unicode normalization."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Nonstandard JSON constant: {value}")


def _finite_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds the finite numeric range")
    return number


def parse_strict_json(text: str) -> Any:
    """Reject duplicate keys and nonfinite values for candidates and offline archives."""
    return json.loads(
        text,
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_reject_constant,
        parse_float=_finite_number,
    )


def _occurrences(text: str, quotation: str):
    """Include overlapping exact matches; callers reject empty quotations."""
    start = text.find(quotation)
    while start != -1:
        yield start
        start = text.find(quotation, start + 1)


def resolve_location(text: str, matched_text: str, source_phrase: str) -> Location:
    """Enumerate only matches contained in each exact phrase occurrence."""
    candidates = []
    if matched_text and source_phrase:
        within = list(_occurrences(source_phrase, matched_text))
        for phrase_start in _occurrences(text, source_phrase):
            for relative_start in within:
                match_start = phrase_start + relative_start
                candidates.append(
                    LocationCandidate(
                        match_span=Span(start=match_start, end=match_start + len(matched_text)),
                        phrase_span=Span(start=phrase_start, end=phrase_start + len(source_phrase)),
                    )
                )
    status = "unmatched" if not candidates else "resolved" if len(candidates) == 1 else "ambiguous"
    return Location(status=status, candidates=candidates)


def _annotation_issues(value: Any, path: str) -> list[Issue]:
    """Check annotation structure only. Language/form correctness needs human review."""
    if value is None:
        return []
    messages = []
    if not isinstance(value, dict):
        messages.append("Expected a language/forms object; suggestion retained unchanged.")
    else:
        if value.keys() - {"language", "forms"}:
            messages.append("Unknown annotation fields are unverified and retained unchanged.")
        language = value.get("language")
        if language is not None and (not isinstance(language, str) or not language.strip()):
            messages.append("Language suggestion should be a nonempty string or null.")
        forms = value.get("forms", [])
        if not isinstance(forms, list) or any(
            not isinstance(form, str) or form not in FORMS for form in forms
        ):
            messages.append("Form suggestions should be an array of recognized form labels.")
    return [
        Issue(severity="warning", code="ANNOTATION_REVIEW", path=path, message=message)
        for message in messages
    ]


def validate_response(
    raw_response: str,
    supplied_text: str,
    *,
    expected_version: Literal["extraction-3.0", "extraction-3.1"] | None = None,
) -> EvidenceReport:
    """Parse strict JSON and resolve evidence offline, preserving errors and ambiguity.

    A valid report may contain ambiguous locations. It never certifies the model's
    completion status, biological quality, or annotation accuracy. Provider status
    remains independent. Archived responses select their declared version
    automatically; live runs may pin the expected version explicitly.
    """
    report = EvidenceReport(
        raw_response=raw_response, supplied_text_sha256=None, entries=[], issues=[]
    )
    try:
        report.supplied_text_sha256 = text_sha256(supplied_text)
    except UnicodeEncodeError:
        report.issues.append(
            Issue(
                severity="error",
                code="INVALID_UNICODE",
                path="/input/supplied_text",
                message="Supplied text contains an unpaired surrogate; exact UTF-8 is required.",
            )
        )
        return report
    try:
        value = parse_strict_json(raw_response)
    except ValueError as exc:
        report.issues.append(
            Issue(severity="error", code="INVALID_JSON", path="/", message=str(exc))
        )
        return report
    version = value.get("format_version") if isinstance(value, dict) else None
    if expected_version is not None and version != expected_version:
        report.issues.append(
            Issue(
                severity="error",
                code="CANDIDATE_VERSION_MISMATCH",
                path="/format_version",
                message=f"Run requested {expected_version}; response declared {version!r}.",
            )
        )
    candidate_type = CandidateResponseV31 if version == FORMAT_VERSION_V31 else CandidateResponse
    try:
        candidate = candidate_type.model_validate(value)
    except ValidationError as exc:
        for error in exc.errors():
            report.issues.append(
                Issue(
                    severity="error",
                    code="CONTRACT_ERROR",
                    path="/" + "/".join(str(part) for part in error["loc"]),
                    message=error["msg"],
                )
            )
        return report

    seen = set()
    for index, entry in enumerate(candidate.entries):
        path = f"/entries/{index}"
        issues = []

        def add(code: str, message: str, *, warning: bool = False) -> None:
            issues.append(
                Issue(
                    severity="warning" if warning else "error",
                    code=code,
                    path=path,
                    message=message,
                )
            )

        model_term = entry.term if isinstance(entry, CandidateEntry) else None
        expressions = [entry.matched_text, entry.source_phrase]
        if model_term is not None:
            expressions.insert(0, model_term)
        if not all(s.strip() for s in expressions):
            add("EMPTY_EXPRESSION", "Term and quotations must contain non-whitespace text.")
        location = resolve_location(supplied_text, entry.matched_text, entry.source_phrase)
        if location.status == "unmatched":
            add("UNMATCHED_EVIDENCE", "No exact contained match exists in the supplied text.")
        elif location.status == "ambiguous":
            add(
                "AMBIGUOUS_LOCATION",
                "All possible locations retained; none selected.",
                warning=True,
            )
        evidence_type = "complete" if entry.matched_text == entry.source_phrase else "embedded"
        if isinstance(entry, CandidateEntry) and evidence_type != entry.evidence_type:
            add("EVIDENCE_TYPE_MISMATCH", "Evidence type disagrees with the exact quotations.")
        if isinstance(entry, CandidateEntry) and entry.term != entry.matched_text:
            add(
                "MODEL_LABEL_DIFFERS_FROM_QUOTE",
                "Term grounded to the exact quote; original model label retained separately.",
                warning=True,
            )
        identity = (entry.matched_text, entry.source_phrase)
        if identity in seen:
            add("DUPLICATE_ENTRY", "Identical quotation claim already appears in this response.")
        seen.add(identity)
        issues.extend(
            _annotation_issues(entry.proposed_annotations, path + "/proposed_annotations")
        )
        evidence_entry_type = (
            EvidenceEntry if isinstance(entry, CandidateEntry) else EvidenceEntryV31
        )
        report.entries.append(
            evidence_entry_type(
                term=entry.matched_text,
                model_term=model_term,
                evidence_type=evidence_type,
                matched_text=entry.matched_text,
                source_phrase=entry.source_phrase,
                location=location,
                proposed_annotations=entry.proposed_annotations,
                issues=issues,
            )
        )
        report.issues.extend(issues)
    if not candidate.entries:
        report.issues.append(
            Issue(
                severity="warning",
                code="NO_ENTRIES",
                path="/entries",
                message="No terminology returned; this does not establish biological completeness.",
            )
        )
    return report


def validate_document(
    document: ExtractionDocument | ExtractionDocumentV31, raw_response: str
) -> EvidenceReport:
    """Recompute evidence from an archived answer instead of trusting saved positions.

    This checks the supplied-text hash and derived entries. Original file bytes,
    archive existence, and run metadata need separate host checks during integration.
    """
    report = validate_response(
        raw_response, document.input.supplied_text, expected_version=document.format_version
    )
    if document.input.supplied_text_sha256 != report.supplied_text_sha256:
        report.issues.append(
            Issue(
                severity="error",
                code="INPUT_HASH_MISMATCH",
                path="/input/supplied_text_sha256",
                message="Fingerprint differs from exact supplied text.",
            )
        )
    if document.entries != report.entries:
        report.issues.append(
            Issue(
                severity="error",
                code="DOCUMENT_EVIDENCE_MISMATCH",
                path="/entries",
                message="Saved entries differ from offline reconstruction of the raw response.",
            )
        )
    return report
