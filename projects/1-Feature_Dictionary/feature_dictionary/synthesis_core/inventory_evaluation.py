"""Provisional, advisor-unapproved expectations; semantic scores never approve biology."""

from __future__ import annotations

from .observation_refs import fingerprint
from .review_exports import records


def evaluate_reference(export: dict, reference: dict) -> dict:
    if (
        reference.get("format_version") != "anatomical-reference-1.0"
        or reference.get("advisor_approved") is not False
    ):
        raise ValueError(
            "This evaluator requires the provisional, advisor-unapproved reference contract"
        )

    # Normalize comparison labels only; source evidence and proposal records stay exact.
    def label(value):
        return value.casefold() if isinstance(value, str) else value

    observed = {e["matched_text"] for e in export["observations"].values()}
    views = []
    for i, term in enumerate(records(export["proposal"].get("terms"))):
        if not isinstance(term, dict):
            continue
        views.append((term.get("text"), term.get("type"), None, term, f"/terms/{i}"))
        for j, expression in enumerate(records(term.get("expressions"))):
            if isinstance(expression, dict):
                views.append(
                    (
                        expression.get("text"),
                        "contextual",
                        term.get("text"),
                        expression,
                        f"/terms/{i}/expressions/{j}",
                    )
                )
    names = {
        str(t.get("ref")): t.get("text")
        for t in records(export["proposal"].get("terms"))
        if isinstance(t, dict)
    }
    decisions = records(export["proposal"].get("observation_dispositions"))
    results = []
    for expected in reference["expectations"]:
        text = expected["text"]
        matches = [v for v in views if label(v[0]) == label(text)]
        if text not in observed:
            status = "not_observed_in_input"
        elif expected["role"] == "not_indexed":
            status = (
                "matches_expectation"
                if not any(v[1] in ("primary", "compound") for v in matches)
                else "classification_difference"
            )
        elif not matches:
            status = "missing_term"
        else:
            status = (
                "matches_expectation"
                if any(
                    v[1] == expected["role"]
                    and (expected.get("owner") is None or label(v[2]) == label(expected["owner"]))
                    for v in matches
                )
                else "classification_difference"
            )
        associations_match = None
        if "associated_primaries" in expected and matches:
            associations_match = any(
                {label(name) for name in expected["associated_primaries"]}
                == {label(names.get(str(ref))) for ref in records(v[3].get("primary_refs"))}
                for v in matches
            )
        disposition_match = None
        if "disposition" in expected and text in observed:
            cited_decisions = [
                d
                for d in decisions
                if isinstance(d, dict)
                and export["observations"].get(str(d.get("observation_id")), {}).get("matched_text")
                == text
            ]
            disposition_match = bool(cited_decisions) and all(
                d.get("status") == expected["disposition"] for d in cited_decisions
            )
        direct = bool(matches) and all(
            any(
                export["observations"].get(str(oid), {}).get("matched_text") == text
                for oid in records(v[3].get("observation_ids"))
            )
            for v in matches
        )
        results.append(
            dict(
                expected=expected,
                status=status,
                exact_evidence_supported=direct if matches else None,
                primary_associations_match=associations_match,
                disposition_matches_expectation=disposition_match,
                occurrence_count=len(matches),
                duplicate_expression_candidates=max(0, len(matches) - 1),
                proposal_paths=[v[4] for v in matches],
            )
        )
    # Exclusion quality must be judged separately from matching a negative indexing expectation.
    return dict(
        format_version="provisional-semantic-evaluation-1.0",
        reference=reference,
        reference_sha256=fingerprint(reference),
        advisor_approved=False,
        scientifically_verified=False,
        software_validation=export["proposal_valid"],
        results=results,
        exclusions=[
            d
            for d in records(export["proposal"].get("observation_dispositions"))
            if isinstance(d, dict) and d.get("status") == "excluded"
        ],
        note="Provisional research expectations; no biological approval or automatic correction.",
    )
