"""Version 2 contracts. Candidate handles are resolved into Python-assigned IDs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Kind = Literal["structure", "characteristic", "character_state", "unresolved"]
Predicate = Literal["part_of", "subtype_of", "describes", "state_of"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FrozenModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Issue(FrozenModel):
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


class MetadataItem(FrozenModel):
    key: str
    value: str


class Source(FrozenModel):
    id: str
    output_path: str
    model: str | None
    extraction_run_id: str | None
    prompt_fingerprint: str | None
    sha256: str
    raw_bytes_b64: str
    metadata: tuple[MetadataItem, ...]


class Observation(FrozenModel):
    id: str
    source_id: str
    line: int
    raw_text: str
    category: Literal["term_entry", "homonym_claim", "unparsed"]
    observed_terms: tuple[str, ...]
    synonym_claims: tuple[str, ...]
    homonym_claims: tuple[str, ...]


class InputBundle(FrozenModel):
    sources: tuple[Source, ...]
    observations: tuple[Observation, ...]
    issues: tuple[Issue, ...]


class Expression(StrictModel):
    text: str
    role: Literal[
        "preferred", "synonym", "spelling_variant", "grammatical_variant", "acronym", "translation"
    ]
    language: str | None
    expansion: str | None
    observation_ids: list[str]


class CandidateTerm(StrictModel):
    ref: str
    kind: Kind
    characteristic_type: Literal["measurement", "qualitative"] | None
    sense_note: str | None
    scope_note: str | None
    expressions: list[Expression]
    notes: str


class CandidateRelationship(StrictModel):
    subject_ref: str
    predicate: Predicate
    object_ref: str
    observation_ids: list[str]
    rationale: str


class CandidateDisposition(StrictModel):
    observation_id: str
    status: Literal["mapped", "excluded", "unresolved"]
    term_refs: list[str]
    reason: str | None


class DictionaryProposal(StrictModel):
    terms: list[CandidateTerm]
    relationships: list[CandidateRelationship]
    observation_dispositions: list[CandidateDisposition]
    review_notes: list[str]


class Term(StrictModel):
    id: str
    kind: Kind
    characteristic_type: Literal["measurement", "qualitative"] | None
    sense_note: str | None
    scope_note: str | None
    expressions: list[Expression]
    notes: str


class Relationship(StrictModel):
    subject_id: str
    predicate: Predicate
    object_id: str
    status: Literal["proposed"]
    basis: Literal["model_inference"]
    observation_ids: list[str]
    rationale: str


class Disposition(StrictModel):
    observation_id: str
    status: Literal["mapped", "excluded", "unresolved"]
    term_ids: list[str]
    reason: str | None


class SynthesisRun(StrictModel):
    model: str
    response_id: str | None
    prompt_sha256: str


class Dictionary(StrictModel):
    schema_version: Literal["2.0"]
    status: Literal["proposed_requires_review"]
    synthesis_run: SynthesisRun
    sources: list[Source]
    observations: list[Observation]
    terms: list[Term]
    relationships: list[Relationship]
    observation_dispositions: list[Disposition]
    issues: list[Issue]
    review_notes: list[str]
