"""Provisional modular synthesis contracts, independent of historical v2 artifacts.

Shape validation is not biological verification. Model-local refs are never final
IDs. No provider execution, ingestion, merging, or compilation is implemented here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_serializer

from feature_dictionary.extraction_v3 import ExtractionDocumentV31

from .schema import FrozenModel

Text = Annotated[str, Field(min_length=1)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Role = Literal["anatomical_noun", "compound", "subterm"]
SubtermType = Literal[
    "morphological_descriptor", "anatomical_modifier", "supporting_noun", "unresolved"
]


class ExtractionSnapshot(FrozenModel):
    id: Text
    output_path: Text
    document: ExtractionDocumentV31
    raw_response: str


class ObservationReference(FrozenModel):
    """References exactly one unchanged entry in a complete extraction snapshot."""

    id: Text
    source_id: Text
    entry_index: Annotated[int, Field(ge=0)]


class SourceContext(FrozenModel):
    """A source-grounded context quote, not a taxonomic claim about each term."""

    source_id: Text
    quoted_text: Text
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]


class SynthesisInputs(FrozenModel):
    format_version: Literal["synthesis-input-1.0"]
    sources: tuple[ExtractionSnapshot, ...]
    observations: tuple[ObservationReference, ...]
    source_context: tuple[SourceContext, ...] = ()

    @model_serializer(mode="wrap")
    def _preserve_legacy_serialization(self, handler):
        value = handler(self)
        if not self.source_context:
            value.pop("source_context", None)
        return value


class ProposalRecord(FrozenModel):
    """Roles may share observation IDs; parent_refs are presentation anchors only."""

    ref: Text
    role: Role
    text: Text
    observation_ids: tuple[Text, ...]
    parent_refs: tuple[Text, ...] = ()
    subterm_refs: tuple[Text, ...] = ()
    type: SubtermType | None = None
    rationale: Text


class ProposalDisposition(FrozenModel):
    observation_id: Text
    status: Literal["mapped", "excluded", "unresolved"]
    record_refs: tuple[Text, ...]
    reason: str | None


class EquivalenceProposal(FrozenModel):
    """An unresolved semantic suggestion, never an instruction to merge."""

    record_refs: tuple[Text, ...]
    observation_ids: tuple[Text, ...]
    rationale: Text
    status: Literal["pending_review"] = "pending_review"


class InventoryProposal(FrozenModel):
    format_version: Literal["synthesis-proposal-1.0"]
    proposal_id: Text
    input_sha256: Hash
    provider: Text
    model: Text
    prompt_sha256: Hash
    records: tuple[ProposalRecord, ...]
    observation_dispositions: tuple[ProposalDisposition, ...]
    equivalence_proposals: tuple[EquivalenceProposal, ...]
    review_notes: tuple[Text, ...]


class SupportedRecord(FrozenModel):
    id: Text
    text: Text
    observation_ids: tuple[Text, ...]
    # A reviewed classification still makes no claim of biological verification.
    review_status: Literal["proposed", "reviewed"] = "proposed"
    review_note: str | None = None


class AnatomicalNoun(SupportedRecord):
    compound_ids: tuple[Text, ...]


class CompoundTerm(SupportedRecord):
    """Parent IDs organize dictionary presentation, never anatomical containment."""

    parent_ids: tuple[Text, ...]
    subterm_ids: tuple[Text, ...]
    relationship_status: Literal["proposed", "reviewed"] = "proposed"
    relationship_note: str | None = None


class Subterm(SupportedRecord):
    """Reusable supporting vocabulary, including standalone morphological descriptors."""

    type: SubtermType


class Inventory(FrozenModel):
    format_version: Literal["synthesis-1.0"]
    input_sha256: Hash
    anatomical_nouns: tuple[AnatomicalNoun, ...]
    compound_terms: tuple[CompoundTerm, ...]
    subterms: tuple[Subterm, ...]


class ObservationDisposition(FrozenModel):
    observation_id: Text
    status: Literal["mapped", "excluded", "unresolved"]
    record_ids: tuple[Text, ...]
    reason: str | None


class ProposalOrigin(FrozenModel):
    """Host-recorded mapping; model-local refs stay qualified by proposal identity."""

    record_id: Text
    proposal_id: Text
    proposal_ref: Text


class InventoryReview(FrozenModel):
    format_version: Literal["synthesis-review-1.0"]
    input_sha256: Hash
    inventory_sha256: Hash
    observation_dispositions: tuple[ObservationDisposition, ...]
    proposal_origins: tuple[ProposalOrigin, ...]
    proposals: tuple[InventoryProposal, ...]
    review_notes: tuple[Text, ...]
