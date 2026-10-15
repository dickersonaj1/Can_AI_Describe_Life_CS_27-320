"""Synthesis-1.2 proposals: indexed anatomical terms and local contextual expressions."""

from __future__ import annotations

from typing import Literal

from .inventory_schema import EquivalenceProposal, Hash, SynthesisInputs, Text
from .inventory_validation import artifact_sha256, validate_inputs
from .schema import FrozenModel, Issue


class LocalExpression(FrozenModel):
    text: Text
    observation_ids: tuple[Text, ...]
    rationale: Text


class IndexedTerm(FrozenModel):
    ref: Text
    type: Literal["primary", "compound"]
    text: Text
    observation_ids: tuple[Text, ...]
    primary_refs: tuple[Text, ...]
    expressions: tuple[LocalExpression, ...]
    rationale: Text


class IndexedDisposition(FrozenModel):
    observation_id: Text
    status: Literal["mapped", "excluded", "unresolved"]
    term_refs: tuple[Text, ...]
    reason: str | None


class IndexedProposal(FrozenModel):
    format_version: Literal["synthesis-1.2"]
    proposal_id: Text
    input_sha256: Hash
    provider: Text
    model: Text
    prompt_sha256: Hash
    terms: tuple[IndexedTerm, ...]
    observation_dispositions: tuple[IndexedDisposition, ...]
    equivalence_proposals: tuple[EquivalenceProposal, ...]
    review_notes: tuple[Text, ...]


def validate_indexed_proposal(proposal: IndexedProposal, inputs: SynthesisInputs) -> list[Issue]:
    """Check evidence/references, not biological meaning or appropriateness of attachment."""
    issues = validate_inputs(inputs)

    def add(code, path, message, severity="error"):
        issues.append(Issue(severity=severity, code=code, path=path, message=message))

    def unique(values, path):
        if len(values) != len(set(values)) or any(not v.strip() for v in values):
            add("DUPLICATE_OR_EMPTY_REFERENCE", path, "Empty or repeated reference.")

    if proposal.input_sha256 != artifact_sha256(inputs):
        add("INPUT_BINDING", "/input_sha256", "Proposal belongs to different frozen inputs.")
    observations = {o.id: o for o in inputs.observations}
    sources = {s.id: s.document for s in inputs.sources}
    terms = {t.ref: t for t in proposal.terms}
    unique([t.ref for t in proposal.terms], "/terms")
    used = {oid: set() for oid in observations}

    def evidence(text, refs, owner, path):
        unique(refs, path + "/observation_ids")
        labels = []
        for ref in refs:
            obs = observations.get(ref)
            if obs is None:
                add("UNKNOWN_OBSERVATION", path, ref)
            else:
                used[ref].add(owner)
                source = sources.get(obs.source_id)
                if source is not None and obs.entry_index < len(source.entries):
                    labels.append(source.entries[obs.entry_index].matched_text)
        if not refs or not text.strip() or text not in labels:
            add(
                "UNOBSERVED_EXPRESSION",
                path,
                "Text must exactly equal a cited extraction expression; no normalization.",
            )

    for i, term in enumerate(proposal.terms):
        path = f"/terms/{i}"
        evidence(term.text, term.observation_ids, term.ref, path)
        unique(term.primary_refs, path + "/primary_refs")
        if term.type == "primary" and term.primary_refs:
            add(
                "INVALID_LINK_OWNER",
                path,
                "Only indexed compounds may reference associated primaries.",
            )
        if term.type == "compound" and not term.primary_refs:
            add("MISSING_PRIMARY", path, "Indexed compound needs a proposed primary association.")
        for ref in term.primary_refs:
            if ref not in terms or terms[ref].type != "primary":
                add("INVALID_REFERENCE", path + "/primary_refs", ref)
        seen = set()
        for j, expression in enumerate(term.expressions):
            ep = path + f"/expressions/{j}"
            evidence(expression.text, expression.observation_ids, term.ref, ep)
            key = (expression.text, expression.observation_ids)
            if key in seen:
                add(
                    "DUPLICATE_LOCAL_EXPRESSION",
                    ep,
                    "Identical expression/evidence repeated under this term.",
                )
            seen.add(key)
        if not term.rationale.strip():
            add("MISSING_RATIONALE", path, "Classification needs a concise rationale.")
    by_observation = {}
    for i, decision in enumerate(proposal.observation_dispositions):
        path = f"/observation_dispositions/{i}"
        if decision.observation_id in by_observation:
            add("DUPLICATE_DISPOSITION", path, decision.observation_id)
        by_observation[decision.observation_id] = decision
        unique(decision.term_refs, path + "/term_refs")
        if decision.observation_id not in observations:
            add("UNKNOWN_OBSERVATION", path, decision.observation_id)
        if any(ref not in terms for ref in decision.term_refs):
            add("INVALID_REFERENCE", path, "Unknown indexed term ref.")
        mapped = used.get(decision.observation_id, set())
        if decision.status == "mapped":
            if not decision.term_refs or set(decision.term_refs) != mapped:
                add(
                    "DISPOSITION_MISMATCH",
                    path,
                    "Mapped refs must equal all term/expression owners citing the observation.",
                )
        elif mapped or decision.term_refs or not (decision.reason or "").strip():
            add(
                "DISPOSITION_MISMATCH",
                path,
                "Excluded/unresolved observations need a reason and must not be used by records.",
            )
    for oid in sorted(observations.keys() - by_observation.keys()):
        add(
            "MISSING_DISPOSITION",
            "/observation_dispositions",
            f"{oid}: missing decision remains unresolved; raw proposal unchanged.",
        )
    for i, proposal_link in enumerate(proposal.equivalence_proposals):
        path = f"/equivalence_proposals/{i}"
        unique(proposal_link.record_refs, path)
        if len(proposal_link.record_refs) < 2 or any(
            ref not in terms for ref in proposal_link.record_refs
        ):
            add(
                "INVALID_REFERENCE", path, "Equivalence proposals need two known indexed term refs."
            )
        if (
            not proposal_link.observation_ids
            or not set(proposal_link.observation_ids) <= observations.keys()
        ):
            add(
                "UNKNOWN_OBSERVATION",
                path,
                "Equivalence proposal needs actual observation evidence.",
            )
    return issues
