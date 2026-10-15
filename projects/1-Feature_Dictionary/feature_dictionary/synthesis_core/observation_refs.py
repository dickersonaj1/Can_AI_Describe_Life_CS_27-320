"""Lossless run-local evidence aliases; never match evidence by wording."""

from __future__ import annotations

import copy
import hashlib
import json

from .inventory_schema import SynthesisInputs
from .inventory_validation import artifact_sha256


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def create_mapping(inputs: SynthesisInputs) -> dict:
    entries = [
        {"short_ref": f"O{i:03d}", "observation_id": obs.id}
        for i, obs in enumerate(inputs.observations, 1)
    ]
    if len({e["observation_id"] for e in entries}) != len(entries):
        raise ValueError("Observation aliases require unique original IDs")
    payload = {
        "format_version": "observation-refs-1.0",
        "input_sha256": artifact_sha256(inputs),
        "entries": entries,
    }
    return {**payload, "mapping_sha256": fingerprint(payload)}


def verify_mapping(mapping: dict, inputs: SynthesisInputs) -> None:
    if mapping != create_mapping(inputs):
        raise ValueError("Observation mapping differs from frozen input order or fingerprint")


def model_input(inputs: SynthesisInputs, mapping: dict) -> dict:
    verify_mapping(mapping, inputs)
    view = inputs.model_dump(mode="json")
    sources = {s.id: s.document for s in inputs.sources}
    view["observations"] = [
        {
            "id": entry["short_ref"],
            "matched_text": sources[obs.source_id].entries[obs.entry_index].matched_text,
            "source_id": obs.source_id,
            "entry_index": obs.entry_index,
        }
        for obs, entry in zip(inputs.observations, mapping["entries"], strict=True)
    ]
    return view


def expand_proposal(value: dict, mapping: dict, inputs: SynthesisInputs) -> dict:
    """Translate only evidence fields. Unknown/mixed references are errors, never guessed."""
    verify_mapping(mapping, inputs)
    lookup = {e["short_ref"]: e["observation_id"] for e in mapping["entries"]}

    def expand(ref):
        if not isinstance(ref, str) or ref not in lookup:
            raise ValueError(f"Unknown short observation reference: {ref!r}")
        return lookup[ref]

    result = copy.deepcopy(value)
    for term in result.get("terms", []):
        term["observation_ids"] = [expand(r) for r in term["observation_ids"]]
        for expression in term.get("expressions", []):
            expression["observation_ids"] = [expand(r) for r in expression["observation_ids"]]
    for decision in result.get("observation_dispositions", []):
        decision["observation_id"] = expand(decision["observation_id"])
    for equivalence in result.get("equivalence_proposals", []):
        equivalence["observation_ids"] = [expand(r) for r in equivalence["observation_ids"]]
    return result
