"""Deterministic checks; evidence provenance never establishes biological verification."""

from __future__ import annotations

import base64
import json
from collections import Counter, deque

from .ingest import EMPTY, digest, normalize, parse_source
from .schema import Dictionary, DictionaryProposal, InputBundle, Issue, SynthesisRun

PLACEHOLDERS = EMPTY | {"unknown", "placeholder", "tbd", "null"}


def validate_proposal(
    proposal: DictionaryProposal, bundle: InputBundle, *, owned_ids: set[str] | None = None
) -> list[Issue]:
    issues = list(bundle.issues)

    def add(code, path, message, severity="error"):
        issues.append(Issue(severity=severity, code=code, path=path, message=message))

    def check_ids(items, field, path):
        values = [getattr(item, field) for item in items]
        for value, count in Counter(values).items():
            if not value.strip() or count > 1:
                add("DUPLICATE_OR_EMPTY_ID", path, f"Invalid or repeated ID: {value!r}")

    check_ids(bundle.sources, "id", "/sources")
    check_ids(bundle.observations, "id", "/observations")
    check_ids(proposal.terms, "ref", "/terms")
    sources = {s.id: s for s in bundle.sources}
    observations = {o.id: o for o in bundle.observations}
    required = set(observations) if owned_ids is None else owned_ids
    if not required <= observations.keys():
        add("UNKNOWN_BATCH_OBSERVATION", "/batch", "Batch references unknown observations.")
    terms = {t.ref: t for t in proposal.terms}
    # Reparse archived bytes, detecting edited/dropped observations or forged metadata.
    expected = []
    expected_issues = []
    for i, source in enumerate(bundle.sources):
        try:
            raw = base64.b64decode(source.raw_bytes_b64, validate=True)
            original, records, source_issues = parse_source(source.output_path, raw)
            expected.extend(records)
            expected_issues.extend(source_issues)
            if original != source:
                add("SOURCE_INTEGRITY", f"/sources/{i}", "Source differs from its archived bytes.")
        except (ValueError, TypeError) as exc:
            add("SOURCE_INTEGRITY", f"/sources/{i}", str(exc))
    if tuple(expected) != bundle.observations:
        add(
            "OBSERVATION_INTEGRITY",
            "/observations",
            "Observations differ from deterministic parsing of the archived sources.",
        )
    if tuple(expected_issues) != bundle.issues:
        add("INPUT_ISSUE_INTEGRITY", "/issues", "Input warnings differ from archived sources.")
    for i, obs in enumerate(bundle.observations):
        if obs.source_id not in sources:
            add("UNKNOWN_SOURCE", f"/observations/{i}/source_id", obs.source_id)

    used = {ref: set() for ref in terms}
    identities = {}
    preferred_labels = {}
    expression_owners = {}
    for i, term in enumerate(proposal.terms):
        path = f"/terms/{i}"
        preferred = [e for e in term.expressions if e.role == "preferred"]
        if len(preferred) != 1:
            add("PREFERRED_EXPRESSION_COUNT", path, "Exactly one preferred expression is required.")
        if not term.expressions:
            add("PLACEHOLDER_TERM", path, "Concept has no expressions.")
        if term.kind != "characteristic" and term.characteristic_type is not None:
            add("CHARACTERISTIC_TYPE", path, "Only characteristics may have characteristic_type.")
        if term.kind == "unresolved":
            add("UNRESOLVED_KIND", path, "Concept classification requires review.", "warning")
        if preferred:
            label = normalize(preferred[0].text)
            identity = (
                label,
                term.kind,
                normalize(term.scope_note or ""),
                normalize(term.sense_note or ""),
            )
            if identity in identities:
                add(
                    "DUPLICATE_CONCEPT",
                    path,
                    f"Same label/kind/scope/sense as {identities[identity]}; resolve explicitly.",
                )
            identities[identity] = term.ref
            preferred_labels.setdefault(label, []).append(term.ref)
        expression_keys = set()
        for j, expression in enumerate(term.expressions):
            ep = f"{path}/expressions/{j}"
            word = normalize(expression.text)
            expression_owners.setdefault(word, set()).add(term.ref)
            if word in PLACEHOLDERS:
                add(
                    "PLACEHOLDER_EXPRESSION",
                    ep,
                    "Empty or placeholder expression is not a concept.",
                )
            key = (word, expression.role)
            if key in expression_keys:
                add("DUPLICATE_EXPRESSION", ep, "Repeated normalized expression and role.")
            expression_keys.add(key)
            if (
                preferred
                and expression.role != "preferred"
                and word == normalize(preferred[0].text)
            ):
                add("REDUNDANT_ALIAS", ep, "Alias repeats the preferred expression.")
            if not expression.observation_ids:
                add("MISSING_EVIDENCE", ep, "Expression needs observation references.")
            if len(expression.observation_ids) != len(set(expression.observation_ids)):
                add("DUPLICATE_EVIDENCE", ep, "Observation references must be unique.")
            vocabulary = set()
            for oid in expression.observation_ids:
                if oid not in required:
                    add(
                        "BATCH_OWNERSHIP", ep, "Expression cites an observation outside this batch."
                    )
                if oid not in observations:
                    add("UNKNOWN_OBSERVATION", ep + "/observation_ids", oid)
                else:
                    used[term.ref].add(oid)
                    vocabulary.update(normalize(w) for w in observations[oid].observed_terms)
            if word not in vocabulary:
                add(
                    "UNSUPPORTED_EXPRESSION",
                    ep,
                    f"{expression.text!r} absent from cited observations.",
                )
            if expression.expansion is not None:
                if expression.role != "acronym":
                    add("INVALID_EXPANSION", ep, "Only acronym expressions may have an expansion.")
                if normalize(expression.expansion) not in vocabulary:
                    add("UNSUPPORTED_EXPANSION", ep, "Expansion absent from cited observations.")
            if expression.language is not None and not expression.language.strip():
                add("INVALID_LANGUAGE", ep, "Use null for unknown language.")
    for label, refs in preferred_labels.items():
        if len(refs) > 1:
            add(
                "AMBIGUOUS_LABEL",
                "/terms",
                f"{label!r} has separate sense/scope records: {refs}; not automatically merged.",
                "warning",
            )
    for label, refs in expression_owners.items():
        if len(refs) > 1:
            add(
                "SHARED_EXPRESSION",
                "/terms",
                f"{label!r} belongs to multiple concepts {sorted(refs)}; "
                "review ambiguity or synonymy.",
                "warning",
            )

    seen_dispositions = set()
    for i, disposition in enumerate(proposal.observation_dispositions):
        path = f"/observation_dispositions/{i}"
        oid = disposition.observation_id
        if oid not in required:
            add("BATCH_OWNERSHIP", path, "Disposition belongs to another batch.")
        if oid in seen_dispositions:
            add("DUPLICATE_DISPOSITION", path, oid)
        seen_dispositions.add(oid)
        if oid not in observations:
            add("UNKNOWN_OBSERVATION", path, oid)
            continue
        if len(disposition.term_refs) != len(set(disposition.term_refs)):
            add("DUPLICATE_TERM_REFERENCE", path, "Repeated concept reference.")
        for ref in disposition.term_refs:
            if ref not in terms:
                add("UNKNOWN_TERM_REFERENCE", path, ref)
        if disposition.status == "mapped":
            if not disposition.term_refs:
                add("EMPTY_MAPPING", path, "Mapped observation needs at least one concept.")
            vocabulary = set()
            for ref in disposition.term_refs:
                if ref in terms:
                    if oid not in used[ref]:
                        add("MAPPING_EVIDENCE_MISMATCH", path, f"{ref} does not cite {oid}.")
                    vocabulary.update(normalize(e.text) for e in terms[ref].expressions)
                    vocabulary.update(
                        normalize(e.expansion)
                        for e in terms[ref].expressions
                        if e.expansion is not None
                    )
            missing = {normalize(w) for w in observations[oid].observed_terms} - vocabulary
            if missing:
                add("LOST_TERMINOLOGY", path, f"Observed expressions missing: {sorted(missing)}")
        else:
            if disposition.term_refs or any(oid in evidence for evidence in used.values()):
                add("DISPOSITION_CONFLICT", path, "Unmapped observation is cited by a concept.")
            if not disposition.reason or not disposition.reason.strip():
                add("MISSING_DISPOSITION_REASON", path, "Exclusion/uncertainty needs a reason.")
            if disposition.status == "unresolved":
                add("UNRESOLVED_OBSERVATION", path, disposition.reason or "", "warning")
        actual = {ref for ref, evidence in used.items() if oid in evidence}
        if disposition.status == "mapped" and actual != set(disposition.term_refs):
            add("MAPPING_EVIDENCE_MISMATCH", path, "Mapping and expression citations disagree.")
    for oid in required - seen_dispositions:
        add("MISSING_DISPOSITION", "/observation_dispositions", oid)

    seen_links = set()
    graphs = {"part_of": {}, "subtype_of": {}}
    for i, link in enumerate(proposal.relationships):
        path = f"/relationships/{i}"
        key = (link.subject_ref, link.predicate, link.object_ref)
        if key in seen_links:
            add("DUPLICATE_RELATIONSHIP", path, str(key))
        seen_links.add(key)
        if link.subject_ref == link.object_ref:
            add("SELF_RELATIONSHIP", path, "Concept cannot relate to itself.")
        endpoints = (terms.get(link.subject_ref), terms.get(link.object_ref))
        for ref, term in zip((link.subject_ref, link.object_ref), endpoints, strict=True):
            if term is None:
                add("UNKNOWN_TERM_REFERENCE", path, ref)
        if not link.observation_ids:
            add("MISSING_EVIDENCE", path, "Relationship needs observation references.")
        if len(link.observation_ids) != len(set(link.observation_ids)):
            add("DUPLICATE_EVIDENCE", path, "Repeated observation reference.")
        for oid in link.observation_ids:
            if oid not in observations:
                add("UNKNOWN_OBSERVATION", path, oid)
            elif oid not in used.get(link.subject_ref, set()) | used.get(link.object_ref, set()):
                add("UNRELATED_RELATIONSHIP_EVIDENCE", path, oid)
        if not link.rationale.strip():
            add("MISSING_RATIONALE", path, "Explain the inferred relationship.")
        if all(endpoints):
            subject, obj = endpoints
            valid = {
                "part_of": subject.kind == obj.kind == "structure",
                "subtype_of": subject.kind == obj.kind
                and subject.kind in {"structure", "characteristic"},
                "describes": subject.kind == "characteristic" and obj.kind == "structure",
                "state_of": subject.kind == "character_state" and obj.kind == "characteristic",
            }[link.predicate]
            if not valid:
                add(
                    "RELATIONSHIP_TYPE_MISMATCH",
                    path,
                    f"{subject.kind} {link.predicate} {obj.kind} is not allowed.",
                )
            if link.predicate in graphs:
                graphs[link.predicate].setdefault(link.subject_ref, set()).add(link.object_ref)
    for predicate, graph in graphs.items():
        nodes = set(graph) | {n for targets in graph.values() for n in targets}
        incoming = dict.fromkeys(nodes, 0)
        for targets in graph.values():
            for target in targets:
                incoming[target] += 1
        queue = deque(sorted(n for n in nodes if incoming[n] == 0))
        count = 0
        while queue:
            node = queue.popleft()
            count += 1
            for target in sorted(graph.get(node, ())):
                incoming[target] -= 1
                if incoming[target] == 0:
                    queue.append(target)
        if count != len(nodes):
            add("HIERARCHY_CYCLE", "/relationships", f"{predicate} contains a cycle.")
    return sorted(issues, key=lambda x: (x.path, x.code, x.message))


def resolve_term_ids(proposal: DictionaryProposal) -> dict[str, str]:
    """Shared deterministic ID assignment for the dictionary and provenance sidecar."""

    def term_key(term):
        data = term.model_dump(exclude={"ref"})
        for expression in data["expressions"]:
            expression["observation_ids"].sort()
        data["expressions"].sort(key=lambda e: (e["role"], normalize(e["text"])))
        return digest(json.dumps(data, sort_keys=True, ensure_ascii=False).encode())

    return {t.ref: "term_" + term_key(t) for t in proposal.terms}


def resolve(
    proposal: DictionaryProposal, bundle: InputBundle, run: SynthesisRun, issues: list[Issue]
) -> Dictionary:
    """Only called after validation; never merge by label or accept model-assigned final IDs."""
    ids = resolve_term_ids(proposal)
    terms = [dict(t.model_dump(exclude={"ref"}), id=ids[t.ref]) for t in proposal.terms]
    terms.sort(
        key=lambda t: (
            normalize(next(e["text"] for e in t["expressions"] if e["role"] == "preferred")),
            t["id"],
        )
    )
    links = [
        dict(
            subject_id=ids[r.subject_ref],
            predicate=r.predicate,
            object_id=ids[r.object_ref],
            status="proposed",
            basis="model_inference",
            observation_ids=r.observation_ids,
            rationale=r.rationale,
        )
        for r in proposal.relationships
    ]
    dispositions = [
        dict(
            observation_id=d.observation_id,
            status=d.status,
            term_ids=[ids[ref] for ref in d.term_refs],
            reason=d.reason,
        )
        for d in proposal.observation_dispositions
    ]
    return Dictionary.model_validate(
        dict(
            schema_version="2.0",
            status="proposed_requires_review",
            synthesis_run=run,
            sources=list(bundle.sources),
            observations=list(bundle.observations),
            terms=terms,
            relationships=sorted(
                links, key=lambda r: (r["subject_id"], r["predicate"], r["object_id"])
            ),
            observation_dispositions=sorted(dispositions, key=lambda d: d["observation_id"]),
            issues=issues,
            review_notes=proposal.review_notes,
        )
    )
