"""Offline, per-proposal review views. Never reconcile or scientifically approve AI output."""

from __future__ import annotations

import json
from pathlib import Path

from feature_dictionary.extraction_v3 import parse_strict_json

from .inventory_execution import replay_job, save, sha
from .inventory_ingest import read_inputs
from .inventory_report import render_report, safe
from .inventory_validation import artifact_sha256
from .observation_refs import fingerprint


def records(value):
    return value if isinstance(value, list) else []


def review_findings(data: dict, validation: dict, observations: dict) -> list[dict]:
    """Conservative screening signals, not biological rules or automatic corrections."""
    findings = []

    def add(priority, code, path, message):
        findings.append(dict(priority=priority, code=code, path=path, message=message))

    for issue in validation["issues"]:
        add(
            1 if issue["severity"] == "error" else 2, issue["code"], issue["path"], issue["message"]
        )
    terms = records(data.get("terms"))
    groups = {}
    for i, term in enumerate(terms):
        path = f"/terms/{i}"
        if not isinstance(term, dict):
            add(1, "MALFORMED_RECORD", path, "Inspect original record; it is not an object.")
            continue
        text = str(term.get("text", ""))
        # Screening only: never modify labels or join concepts/evidence.
        key = text.casefold()
        key = key[:-1] if key.endswith("s") else key
        groups.setdefault(key, []).append((path, text))
        if text.casefold() in {
            "distal",
            "total length",
            "length",
            "coloration",
            "colouration",
            "cross-bands",
            "dark cross-bands",
            "sides",
            "distal portion",
        }:
            add(
                2,
                "ANATOMICAL_SCOPE_REVIEW",
                path,
                "Check independent anatomy versus position, property or pigmentation.",
            )
        if term.get("type") == "compound":
            add(
                3,
                "COMPOUND_CLASSIFICATION",
                path,
                "Confirm distinct anatomy and its proposed primary associations.",
            )
        if "labial" in text.casefold() and term.get("type") == "compound":
            add(
                2,
                "ANATOMICAL_SUBTYPE",
                path,
                "Confirm whether the positional wording names a recognized anatomical subtype.",
            )
        seen = set()
        for j, expression in enumerate(records(term.get("expressions"))):
            ep = f"{path}/expressions/{j}"
            add(
                3,
                "CONTEXTUAL_ATTACHMENT",
                ep,
                "Confirm this expression describes its proposed owner; "
                "evidence does not verify attachment.",
            )
            if isinstance(expression, dict):
                label = str(expression.get("text"))
                if label in seen:
                    add(
                        2,
                        "REPEATED_EXPRESSION",
                        ep,
                        "Repeated local wording; inspect evidence without merging.",
                    )
                seen.add(label)
        for item in [term, *records(term.get("expressions"))]:
            if isinstance(item, dict):
                for oid in records(item.get("observation_ids")):
                    if (
                        observations.get(str(oid), {}).get("location", {}).get("status")
                        == "ambiguous"
                    ):
                        add(
                            2,
                            "AMBIGUOUS_LOCATION",
                            path,
                            f"Evidence {oid} has multiple possible locations.",
                        )
        add(
            4,
            "SCIENTIFIC_REVIEW_REQUIRED",
            path,
            "Review classification; model output is not biological approval.",
        )
    for values in groups.values():
        if len(values) > 1:
            add(
                2,
                "POSSIBLE_VARIANTS",
                values[0][0],
                "Possible duplicate/case/plural variants (not merged): "
                + "; ".join(t for _, t in values),
            )
    decisions = records(data.get("observation_dispositions"))
    decided = set()
    for i, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            continue
        oid = str(decision.get("observation_id", ""))
        decided.add(oid)
        if decision.get("status") in ("excluded", "unresolved"):
            add(
                2 if decision["status"] == "unresolved" else 3,
                decision["status"].upper(),
                f"/observation_dispositions/{i}",
                f"{oid}: {observations.get(oid, {}).get('matched_text', '[unknown]')} "
                f"— {decision.get('reason')}",
            )
    for oid in observations.keys() - decided:
        add(
            1,
            "MISSING_DECISION",
            "/observation_dispositions",
            f"{oid}: unresolved; no decision supplied. Observation is retained.",
        )
    for i, link in enumerate(records(data.get("equivalence_proposals"))):
        add(
            2,
            "EQUIVALENCE_PROPOSAL",
            f"/equivalence_proposals/{i}",
            "Review nonauthoritative equivalence suggestion: "
            + json.dumps(link, ensure_ascii=False),
        )
    return sorted(findings, key=lambda f: (f["priority"], f["path"], f["code"], f["message"]))


def build_export(job: Path, annotations: dict | None = None) -> dict:
    request = parse_strict_json((job / "request.json").read_text())
    if request.get("proposal_version") != "1.2":
        raise ValueError("Review exports require synthesis-1.2; no historical migration")
    inputs = read_inputs(job.parent / "inputs.json")
    validation = replay_job(job)
    response = parse_strict_json((job / "response.json").read_text())
    try:
        raw = parse_strict_json(response["response_text"])
    except ValueError:
        raw = None
    data = validation.get("derived_proposal") or raw
    if not isinstance(data, dict):
        data = {}
    observations = {}
    sources = {s.id: s.document for s in inputs.sources}
    aliases = {
        e["observation_id"]: e["short_ref"]
        for e in request.get("observation_mapping", {}).get("entries", [])
    }
    for obs in inputs.observations:
        doc = sources[obs.source_id]
        evidence = doc.entries[obs.entry_index].model_dump(mode="json")
        observations[obs.id] = dict(
            **evidence,
            id=obs.id,
            short_ref=aliases.get(obs.id),
            source_id=obs.source_id,
            entry_index=obs.entry_index,
        )
    targets = {}
    for i, term in enumerate(records(data.get("terms"))):
        targets[f"/terms/{i}"] = dict(
            structurally_validated=validation["proposal_valid"],
            scientific_status="needs_scientific_review",
        )
        if isinstance(term, dict):
            for j, _ in enumerate(records(term.get("expressions"))):
                targets[f"/terms/{i}/expressions/{j}"] = dict(
                    structurally_validated=validation["proposal_valid"],
                    scientific_status="needs_scientific_review",
                )
    proposal_sha = fingerprint(data)
    if annotations is not None:
        if not isinstance(annotations, dict) or not isinstance(annotations.get("decisions"), list):
            raise ValueError("Review annotations require an object with decisions array")
        if (
            annotations.get("format_version") != "scientific-review-1.0"
            or annotations.get("proposal_sha256") != proposal_sha
            or annotations.get("input_sha256") != artifact_sha256(inputs)
        ):
            raise ValueError("Review annotations must bind to this exact proposal and input")
        seen = set()
        for annotation in annotations.get("decisions", []):
            if not isinstance(annotation, dict):
                raise ValueError("Review decisions must be objects")
            path = annotation.get("path")
            if (
                not isinstance(path, str)
                or path not in targets
                or path in seen
                or annotation.get("confirmed") is not True
                or not isinstance(annotation.get("reviewer"), str)
                or not annotation["reviewer"].strip()
                or not isinstance(annotation.get("reviewed_at"), str)
                or not annotation["reviewed_at"].strip()
                or annotation.get("decision") not in ("approved", "rejected", "needs_review")
            ):
                raise ValueError(
                    "Review decisions need unique targets, reviewer, date and explicit confirmation"
                )
            if annotation["decision"] == "approved" and not validation["proposal_valid"]:
                raise ValueError("Invalid proposals cannot be exported as scientifically approved")
            seen.add(path)
            targets[path]["scientific_status"] = {
                "approved": "scientifically_reviewed_approved",
                "rejected": "scientifically_reviewed_rejected",
                "needs_review": "needs_scientific_review",
            }[annotation["decision"]]
            targets[path]["review_annotation"] = annotation
    return dict(
        format_version="terminology-review-export-1.0",
        compiled_dictionary=False,
        proposal_valid=validation["proposal_valid"],
        scientifically_verified=False,
        metadata=dict(
            job_path=str(job.resolve()),
            **request["identity"],
            response_text_sha256=sha(response["response_text"]),
            request_sha256=sha((job / "request.json").read_text()),
            proposal_sha256=proposal_sha,
            completion_status=response["completion_status"],
            completion_reason=response.get("completion_reason"),
            metrics=response.get("metrics"),
            wall_clock_seconds=response.get("wall_clock_seconds"),
            observation_reference_mode=request.get("observation_refs", "original"),
            proposal_reference_space=(
                "original"
                if validation.get("derived_proposal") is not None
                or request.get("observation_refs") != "short"
                else "short_unexpanded_diagnostic"
            ),
            prompt_path=request.get("prompt_path"),
            mapping_sha256=request.get("observation_mapping", {}).get("mapping_sha256"),
        ),
        sources=inputs.model_dump(mode="json")["sources"],
        source_context=[c.model_dump(mode="json") for c in inputs.source_context],
        proposal=data,
        raw_model_response=response["response_text"],
        validation=validation,
        observations=observations,
        review_status=targets,
        review_annotations=annotations,
        findings=review_findings(data, validation, observations),
    )


def render_inventory(export: dict, audit: str) -> str:
    status = (
        "SOFTWARE CHECKS PASSED — SCIENTIFIC REVIEW REQUIRED"
        if export["proposal_valid"]
        else "INVALID MODEL PROPOSAL — UNAPPROVED"
    )
    # Reuse the existing robust hierarchy, exclusions, invalid records and evidence rendering.
    audit = audit.replace(
        "# Synthesis v1.2 — model proposal audit", "# Anatomical terminology inventory — proposal"
    )
    for oid, obs in export["observations"].items():
        if obs.get("short_ref"):
            audit = audit.replace(oid, obs["short_ref"])
    headings = {}
    for i, term in enumerate(records(export["proposal"].get("terms"))):
        if isinstance(term, dict):
            level = "###" if term.get("type") == "primary" else "####"
            headings[
                f"{level} {safe(term.get('text', '[missing text]'))} — "
                f"{safe(term.get('ref', '[missing ref]'))}"
            ] = i
    enriched, owner = [], None
    for line in audit.splitlines():
        enriched.append(line)
        if line in headings:
            owner = headings[line]
            decision = export["review_status"][f"/terms/{owner}"]
            enriched.extend(["", f"**Review: {decision['scientific_status']}**"])
        elif line.startswith("- **") and owner is not None:
            term = export["proposal"]["terms"][owner]
            for j, expression in enumerate(records(term.get("expressions"))):
                if isinstance(expression, dict) and line.startswith(
                    "- **" + safe(expression.get("text", "[missing text]")) + "** —"
                ):
                    decision = export["review_status"][f"/terms/{owner}/expressions/{j}"]
                    enriched.append(f"  - Review: {decision['scientific_status']}")
        elif line.startswith("## "):
            owner = None
    audit = "\n".join(enriched) + "\n"
    head, _, evidence = audit.partition("## Evidence details")
    # Detailed provenance is available in JSON; retain notes, metadata and issues in Markdown.
    _, _, tail = evidence.partition("## Review notes and nonauthoritative equivalence proposals")
    lines = [f"**{status}**", "", head]
    lines.extend(["## Review status by proposal location", ""])
    for path, decision in export["review_status"].items():
        lines.append(
            f"- {path}: {decision['scientific_status']}; "
            f"software validated: {decision['structurally_validated']}"
        )
    lines.extend(["", "## Review notes and nonauthoritative equivalence proposals", tail])
    lines.extend(
        ["", "## Export identity", "", "```json", json.dumps(export["metadata"], indent=2), "```"]
    )
    return "\n".join(lines) + "\n"


def render_review(export: dict) -> str:
    lines = [
        "# Scientific review checklist",
        "",
        "This is a model proposal, not a published dictionary.",
        "Screening flags are prompts for review, not biological findings or automatic corrections.",
        "No agreement between models counts as scientific approval.",
        "",
        "**INVALID / UNAPPROVED**"
        if not export["proposal_valid"]
        else "Software checks passed; biological interpretation remains open.",
        "",
    ]
    for item in export["findings"]:
        target = export["proposal"]
        try:
            for part in item["path"].strip("/").split("/"):
                target = target[int(part)] if isinstance(target, list) else target[part]
        except (KeyError, IndexError, TypeError, ValueError):
            target = None
        label = target.get("text", "") if isinstance(target, dict) else ""
        message = item["message"]
        for oid, observation in export["observations"].items():
            if observation.get("short_ref"):
                message = message.replace(oid, observation["short_ref"])
        lines.append(
            f"- [ ] P{item['priority']} **{safe(item['code'])}** **{safe(label)}** "
            f"{safe(item['path'])}: {safe(message)}"
        )
    lines.extend(
        [
            "",
            "## Model and evidence identity",
            "",
            "```json",
            json.dumps(export["metadata"], indent=2),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def export_job(job: Path, destination: Path, annotations: dict | None = None) -> dict:
    if destination.resolve().is_relative_to(job.parent.resolve()):
        raise ValueError("Exports must be outside the immutable synthesis run")
    export = build_export(job, annotations)
    inputs = read_inputs(job.parent / "inputs.json")
    request = parse_strict_json((job / "request.json").read_text())
    response = parse_strict_json((job / "response.json").read_text())
    audit = render_report(
        inputs,
        response,
        export["validation"],
        request,
        include_raw_json=not export["validation"]["schema_valid"],
    )
    destination.mkdir(parents=True, exist_ok=False)
    save(destination / "terminology_inventory.json", export)
    for name, content in [
        ("terminology_inventory.md", render_inventory(export, audit)),
        ("scientific_review.md", render_review(export)),
    ]:
        with (destination / name).open("x", encoding="utf-8") as handle:
            handle.write(content)
    return export


def write_disagreements(destination: Path, exports: list[dict]) -> None:
    """Compare exact observed wording for review only, retaining every independent proposal."""
    lines = [
        "# Independent proposal differences",
        "",
        "Differences are review signals, not consensus or evidence of error.",
        "No proposals are merged. Different meanings may legitimately share wording.",
        "",
    ]
    if len({e["metadata"]["input_sha256"] for e in exports}) > 1:
        lines.append("Inputs differ: proposals are not controlled comparisons. Review separately.")
    else:
        by_text = {}
        for i, export in enumerate(exports):
            terms = records(export["proposal"].get("terms"))
            names = {str(t.get("ref")): t.get("text") for t in terms if isinstance(t, dict)}
            for j, term in enumerate(terms):
                if not isinstance(term, dict):
                    continue
                label = str(term.get("text", ""))
                signature = (
                    term.get("type"),
                    tuple(
                        sorted(str(names.get(str(r), r)) for r in records(term.get("primary_refs")))
                    ),
                )
                by_text.setdefault(label, {}).setdefault(i, []).append((signature, f"/terms/{j}"))
                for k, expression in enumerate(records(term.get("expressions"))):
                    if isinstance(expression, dict):
                        by_text.setdefault(str(expression.get("text", "")), {}).setdefault(
                            i, []
                        ).append((("contextual", label), f"/terms/{j}/expressions/{k}"))
            for j, decision in enumerate(
                records(export["proposal"].get("observation_dispositions"))
            ):
                if isinstance(decision, dict) and decision.get("status") != "mapped":
                    evidence = export["observations"].get(str(decision.get("observation_id")), {})
                    if evidence:
                        by_text.setdefault(evidence["matched_text"], {}).setdefault(i, []).append(
                            ((decision.get("status"),), f"/observation_dispositions/{j}")
                        )
        for text, views in sorted(by_text.items()):
            signatures = {repr(sorted(str(sig) for sig, _ in rows)) for rows in views.values()}
            if len(signatures) > 1 or len(views) != len(exports):
                lines.append(
                    f"- [ ] **{safe(text)}** — classification, attachment or coverage differs:"
                )
                for i, export in enumerate(exports):
                    lines.append(
                        f"  - Proposal {i:03d} ({safe(export['metadata']['model'])}): "
                        + safe(views.get(i, "not represented"))
                    )
    with (destination / "proposal_differences.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
