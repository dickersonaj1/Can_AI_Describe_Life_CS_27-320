"""Offline integrity/reference checks for synthesis-1.0, not scientific review."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from feature_dictionary.extraction_v3 import validate_document

from .inventory_schema import Inventory, InventoryProposal, InventoryReview, SynthesisInputs
from .schema import Issue


def artifact_sha256(artifact) -> str:
    """Bind snapshots by canonical UTF-8 JSON; does not assign final record IDs."""
    raw = json.dumps(
        artifact.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _issue(issues, code, path, message, severity="error"):
    issues.append(Issue(severity=severity, code=code, path=path, message=message))


def _unique(values, path, issues):
    for value, count in Counter(values).items():
        if not value.strip() or count > 1:
            _issue(issues, "DUPLICATE_OR_EMPTY_ID", path, repr(value))


def validate_inputs(inputs: SynthesisInputs) -> list[Issue]:
    issues = []
    _unique([s.id for s in inputs.sources], "/sources", issues)
    _unique([o.id for o in inputs.observations], "/observations", issues)
    sources = {s.id: s for s in inputs.sources}
    expected = {(s.id, i) for s in inputs.sources for i in range(len(s.document.entries))}
    actual = []
    for i, source in enumerate(inputs.sources):
        if source.document.run.completion_status != "success":
            _issue(
                issues,
                "UNACCEPTED_EXTRACTION",
                f"/sources/{i}",
                "Extraction did not complete successfully.",
            )
        report = validate_document(source.document, source.raw_response)
        for issue in report.issues:
            _issue(
                issues,
                issue.code,
                f"/sources/{i}/document{issue.path}",
                issue.message,
                issue.severity,
            )
    for i, obs in enumerate(inputs.observations):
        source = sources.get(obs.source_id)
        if source is None or obs.entry_index >= len(source.document.entries):
            _issue(issues, "UNKNOWN_EXTRACTION_ENTRY", f"/observations/{i}", obs.id)
        actual.append((obs.source_id, obs.entry_index))
    if set(actual) != expected or len(actual) != len(expected):
        _issue(
            issues,
            "OBSERVATION_COVERAGE",
            "/observations",
            "Every extraction entry must be referenced exactly once.",
        )
    seen_context = set()
    for i, context in enumerate(inputs.source_context):
        source = sources.get(context.source_id)
        path = f"/source_context/{i}"
        identity = (context.source_id, context.start, context.end, context.quoted_text)
        if identity in seen_context:
            _issue(issues, "DUPLICATE_CONTEXT", path, "Repeated source context quote.")
        seen_context.add(identity)
        if (
            source is None
            or context.end <= context.start
            or context.end > len(source.document.input.supplied_text)
            or source.document.input.supplied_text[context.start : context.end]
            != context.quoted_text
        ):
            _issue(
                issues,
                "UNGROUNDED_CONTEXT",
                path,
                "Context must exactly match its source and Python character range.",
            )
    return issues


def _check_records(records, inputs, issues):
    # Common graph checks; this is not a compiler and performs no ID assignment.
    _unique([r[0] for r in records], "/records", issues)
    by_id = {r[0]: r for r in records}
    sources = {s.id: s.document for s in inputs.sources}
    observations = {o.id: o for o in inputs.observations}
    for key, role, text, refs, parents, subterms in records:
        path = f"/records/{key}"
        if not text.strip() or not refs:
            _issue(
                issues,
                "MISSING_TERM_OR_EVIDENCE",
                path,
                "A nonblank expression and supporting observations are required.",
            )
        for field, values in [
            ("observation_ids", refs),
            ("parents", parents),
            ("subterms", subterms),
        ]:
            _unique(values, path + "/" + field, issues)
        labels = []
        for ref in refs:
            obs = observations.get(ref)
            if obs is None:
                _issue(issues, "UNKNOWN_OBSERVATION", path, ref)
            elif obs.source_id in sources and obs.entry_index < len(sources[obs.source_id].entries):
                labels.append(sources[obs.source_id].entries[obs.entry_index].matched_text)
        if text not in labels:
            _issue(
                issues,
                "UNOBSERVED_EXPRESSION",
                path,
                "Text must equal a cited extracted expression; no normalization is applied.",
            )
        if role == "compound" and not parents:
            _issue(
                issues,
                "MISSING_PARENT",
                path,
                "A compound needs at least one proposed anatomical parent.",
            )
        if role != "compound" and (parents or subterms):
            _issue(
                issues, "INVALID_LINK_OWNER", path, "Only compounds own parent and subterm links."
            )
        for field, values, target_role in [
            ("parents", parents, "anatomical_noun"),
            ("subterms", subterms, "subterm"),
        ]:
            for ref in values:
                if ref not in by_id or by_id[ref][1] != target_role:
                    _issue(issues, "INVALID_REFERENCE", path + "/" + field, ref)
    # Identical labels are allowed: they can represent different biological senses.
    for label, count in Counter(r[2] for r in records).items():
        if count > 1:
            _issue(
                issues,
                "SHARED_LABEL_REVIEW",
                "/records",
                f"Keep distinct records unless reviewed: {label!r}",
                "warning",
            )
    return by_id


def _check_dispositions(dispositions, records, inputs, issues, *, proposal=False):
    observations = {o.id for o in inputs.observations}
    ids = [d.observation_id for d in dispositions]
    _unique(ids, "/observation_dispositions", issues)
    if set(ids) != observations:
        _issue(
            issues,
            "DISPOSITION_COVERAGE",
            "/observation_dispositions",
            "Every observation needs exactly one disposition.",
        )
    used = {obs: {r[0] for r in records.values() if obs in r[3]} for obs in observations}
    for i, disposition in enumerate(dispositions):
        refs = disposition.record_refs if proposal else disposition.record_ids
        path = f"/observation_dispositions/{i}"
        _unique(refs, path, issues)
        if any(ref not in records for ref in refs):
            _issue(issues, "INVALID_REFERENCE", path, "Unknown disposition record.")
        if disposition.status == "mapped":
            if not refs or set(refs) != used.get(disposition.observation_id, set()):
                _issue(
                    issues,
                    "DISPOSITION_MISMATCH",
                    path,
                    "Mapped records must equal all records citing this observation.",
                )
        elif refs or used.get(disposition.observation_id) or not (disposition.reason or "").strip():
            _issue(
                issues,
                "DISPOSITION_MISMATCH",
                path,
                "Excluded/unresolved observations need a reason and cannot be used by records.",
            )


def validate_inventory_proposal(
    proposal: InventoryProposal, inputs: SynthesisInputs
) -> list[Issue]:
    issues = validate_inputs(inputs)
    if proposal.input_sha256 != artifact_sha256(inputs):
        _issue(issues, "INPUT_BINDING", "/input_sha256", "Proposal belongs to different inputs.")
    records = [
        (r.ref, r.role, r.text, r.observation_ids, r.parent_refs, r.subterm_refs)
        for r in proposal.records
    ]
    by_id = _check_records(records, inputs, issues)
    for i, record in enumerate(proposal.records):
        if (record.role == "subterm") != (record.type is not None):
            _issue(issues, "SUBTERM_TYPE", f"/records/{i}/type", "Only subterms require a type.")
    _check_dispositions(proposal.observation_dispositions, by_id, inputs, issues, proposal=True)
    observations = {o.id for o in inputs.observations}
    for i, equivalence in enumerate(proposal.equivalence_proposals):
        path = f"/equivalence_proposals/{i}"
        _unique(equivalence.record_refs, path, issues)
        _unique(equivalence.observation_ids, path, issues)
        if len(equivalence.record_refs) < 2 or any(
            ref not in by_id for ref in equivalence.record_refs
        ):
            _issue(
                issues,
                "INVALID_REFERENCE",
                path,
                "Equivalence needs at least two known model-local refs.",
            )
        if not equivalence.observation_ids or not set(equivalence.observation_ids) <= observations:
            _issue(
                issues, "MISSING_EVIDENCE", path, "Equivalence needs known supporting observations."
            )
    return issues


def validate_inventory(
    inventory: Inventory, inputs: SynthesisInputs, review: InventoryReview
) -> list[Issue]:
    issues = validate_inputs(inputs)
    binding = artifact_sha256(inputs)
    if inventory.input_sha256 != binding or review.input_sha256 != binding:
        _issue(
            issues,
            "INPUT_BINDING",
            "/input_sha256",
            "Inventory or review belongs to different inputs.",
        )
    if review.inventory_sha256 != artifact_sha256(inventory):
        _issue(
            issues,
            "INVENTORY_BINDING",
            "/inventory_sha256",
            "Review belongs to a different inventory.",
        )
    records = [
        *(
            (r.id, "anatomical_noun", r.text, r.observation_ids, (), ())
            for r in inventory.anatomical_nouns
        ),
        *(
            (r.id, "compound", r.text, r.observation_ids, r.parent_ids, r.subterm_ids)
            for r in inventory.compound_terms
        ),
        *((r.id, "subterm", r.text, r.observation_ids, (), ()) for r in inventory.subterms),
    ]
    by_id = _check_records(records, inputs, issues)
    compounds = {c.id: c for c in inventory.compound_terms}
    for compound in inventory.compound_terms:
        if len(compound.parent_ids) > 1 and not (compound.relationship_note or "").strip():
            _issue(
                issues,
                "RELATIONSHIP_NOTE_REQUIRED",
                f"/records/{compound.id}",
                "Multiple parents require an explicit justification; this does not verify it.",
            )
    for i, noun in enumerate(inventory.anatomical_nouns):
        _unique(noun.compound_ids, f"/anatomical_nouns/{i}/compound_ids", issues)
        expected = {c.id for c in inventory.compound_terms if noun.id in c.parent_ids}
        if set(noun.compound_ids) != expected:
            _issue(
                issues,
                "RECIPROCAL_LINK_MISMATCH",
                f"/anatomical_nouns/{i}",
                "compound_ids must exactly mirror compound parent_ids.",
            )
        if any(ref not in compounds for ref in noun.compound_ids):
            _issue(
                issues,
                "INVALID_REFERENCE",
                f"/anatomical_nouns/{i}/compound_ids",
                "Unknown compound.",
            )
    for collection in [inventory.anatomical_nouns, inventory.compound_terms, inventory.subterms]:
        for record in collection:
            if record.review_status == "reviewed" and not (record.review_note or "").strip():
                _issue(
                    issues,
                    "REVIEW_NOTE_REQUIRED",
                    f"/records/{record.id}",
                    "Reviewed classifications require a note.",
                )
            if (
                getattr(record, "relationship_status", None) == "reviewed"
                and not (record.relationship_note or "").strip()
            ):
                _issue(
                    issues,
                    "REVIEW_NOTE_REQUIRED",
                    f"/records/{record.id}",
                    "Reviewed relationships require a note.",
                )
    _check_dispositions(review.observation_dispositions, by_id, inputs, issues)
    _unique([p.proposal_id for p in review.proposals], "/proposals", issues)
    proposals = {p.proposal_id: p for p in review.proposals}
    for proposal in review.proposals:
        issues.extend(validate_inventory_proposal(proposal, inputs))
    seen = set()
    for i, origin in enumerate(review.proposal_origins):
        proposal = proposals.get(origin.proposal_id)
        identity = (origin.record_id, origin.proposal_id, origin.proposal_ref)
        if (
            identity in seen
            or origin.record_id not in by_id
            or proposal is None
            or origin.proposal_ref not in {r.ref for r in proposal.records}
        ):
            _issue(
                issues,
                "INVALID_PROPOSAL_ORIGIN",
                f"/proposal_origins/{i}",
                "Origin must reference a unique known proposal record and final record.",
            )
        seen.add(identity)
    return issues
