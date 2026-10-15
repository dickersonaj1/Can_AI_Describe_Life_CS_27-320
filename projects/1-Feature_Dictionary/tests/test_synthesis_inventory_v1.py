"""Fixture-only provisional synthesis contracts; no model calls or compiler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from feature_dictionary.synthesis_core.inventory_schema import (
    Inventory,
    InventoryProposal,
    InventoryReview,
    SynthesisInputs,
)
from feature_dictionary.synthesis_core.inventory_validation import (
    artifact_sha256,
    validate_inputs,
    validate_inventory,
    validate_inventory_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/synthesis_v1"


def load(name, model):
    return model.model_validate_json((FIXTURES / f"{name}.json").read_text())


def case():
    return (
        load("inputs", SynthesisInputs),
        load("inventory", Inventory),
        load("review", InventoryReview),
    )


def errors(issues):
    return {i.code for i in issues if i.severity == "error"}


def rebind(inputs, inventory, review):
    # Test-only binding of deliberately edited fixtures; no production compiler.
    binding = artifact_sha256(inputs)
    inventory = inventory.model_copy(update={"input_sha256": binding})
    review = review.model_copy(
        update={
            "input_sha256": binding,
            "inventory_sha256": artifact_sha256(inventory),
            "proposals": (),
            "proposal_origins": (),
        }
    )
    return inventory, review


def test_fixture_is_valid_but_explicitly_unverified():
    inputs, inventory, review = case()
    proposal = load("proposal", InventoryProposal)
    assert not errors(validate_inputs(inputs))
    assert not errors(validate_inventory_proposal(proposal, inputs))
    assert not errors(validate_inventory(inventory, inputs, review))
    assert len(inputs.observations) == 8
    assert {d.status for d in review.observation_dispositions} == {
        "mapped",
        "excluded",
        "unresolved",
    }
    assert all(r.review_status == "proposed" for r in inventory.anatomical_nouns)
    assert all(r.relationship_status == "proposed" for r in inventory.compound_terms)
    assert {o.proposal_ref for o in review.proposal_origins}.isdisjoint(
        {o.record_id for o in review.proposal_origins}
    )


@pytest.mark.parametrize(
    "name,model,schema",
    [
        ("inputs", SynthesisInputs, "synthesis_input_v1"),
        ("proposal", InventoryProposal, "synthesis_proposal_v1"),
        ("inventory", Inventory, "synthesis_inventory_v1"),
        ("review", InventoryReview, "synthesis_review_v1"),
    ],
)
def test_exported_schema_and_json_round_trip(name, model, schema):
    artifact = load(name, model)
    assert model.model_validate_json(artifact.model_dump_json()) == artifact
    assert (
        json.loads((ROOT / "schemas" / f"{schema}.schema.json").read_text())
        == model.model_json_schema()
    )


def test_model_proposal_cannot_be_loaded_as_compiled_inventory():
    with pytest.raises(ValidationError):
        Inventory.model_validate_json((FIXTURES / "proposal.json").read_text())
    data = json.loads((FIXTURES / "inventory.json").read_text())
    data["definitions"] = []
    with pytest.raises(ValidationError):
        Inventory.model_validate_json(json.dumps(data))


def test_original_evidence_and_ambiguous_locations_are_preserved():
    inputs, _, _ = case()
    source = inputs.sources[0]
    assert source.document.entries[1].location.status == "resolved"
    assert source.document.run.model == "offline-fixture"
    assert "horn-like" in source.raw_response
    entry = source.document.entries[0]
    changed = entry.model_copy(update={"matched_text": "Anal"})
    document = source.document.model_copy(
        update={"entries": [changed, *source.document.entries[1:]]}
    )
    tampered = inputs.model_copy(
        update={"sources": (source.model_copy(update={"document": document}),)}
    )
    assert "DOCUMENT_EVIDENCE_MISMATCH" in errors(validate_inputs(tampered))


@pytest.mark.parametrize("edit", ["missing", "duplicate", "bad_source", "bad_index"])
def test_inputs_cannot_drop_duplicate_or_misreference_observations(edit):
    inputs, _, _ = case()
    records = inputs.observations
    if edit == "missing":
        records = records[:-1]
    elif edit == "duplicate":
        records = (*records, records[0])
    elif edit == "bad_source":
        records = (records[0].model_copy(update={"source_id": "missing"}), *records[1:])
    else:
        records = (records[0].model_copy(update={"entry_index": 999}), *records[1:])
    assert errors(validate_inputs(inputs.model_copy(update={"observations": records})))


def test_incomplete_extraction_cannot_enter_inputs():
    inputs, _, _ = case()
    source = inputs.sources[0]
    document = source.document.model_copy(
        update={"run": source.document.run.model_copy(update={"completion_status": "incomplete"})}
    )
    changed = inputs.model_copy(
        update={"sources": (source.model_copy(update={"document": document}),)}
    )
    assert "UNACCEPTED_EXTRACTION" in errors(validate_inputs(changed))


@pytest.mark.parametrize(
    "edit,code",
    [
        ("duplicate", "DUPLICATE_OR_EMPTY_ID"),
        ("parent", "INVALID_REFERENCE"),
        ("subterm", "INVALID_REFERENCE"),
        ("reciprocal", "RECIPROCAL_LINK_MISMATCH"),
        ("evidence", "UNKNOWN_OBSERVATION"),
        ("invented", "UNOBSERVED_EXPRESSION"),
        ("empty_parent", "MISSING_PARENT"),
    ],
)
def test_inventory_graph_and_grounding_errors(edit, code):
    inputs, inventory, review = case()
    compound = inventory.compound_terms[0]
    updates = {
        "duplicate": {"id": "t1"},
        "parent": {"parent_ids": ("s1",)},
        "subterm": {"subterm_ids": ("missing",)},
        "reciprocal": {"parent_ids": ("t2",)},
        "evidence": {"observation_ids": ("missing",)},
        "invented": {"text": "new term"},
        "empty_parent": {"parent_ids": ()},
    }
    inventory = inventory.model_copy(
        update={
            "compound_terms": (
                compound.model_copy(update=updates[edit]),
                inventory.compound_terms[1],
            )
        }
    )
    inventory, review = rebind(inputs, inventory, review)
    assert code in errors(validate_inventory(inventory, inputs, review))


@pytest.mark.parametrize(
    "edit", ["missing", "duplicate", "excluded_used", "no_reason", "wrong_mapping"]
)
def test_audit_sidecar_requires_complete_consistent_dispositions(edit):
    inputs, inventory, review = case()
    records = review.observation_dispositions
    if edit == "missing":
        records = records[:-1]
    elif edit == "duplicate":
        records = (*records, records[0])
    elif edit == "excluded_used":
        records = (
            records[0].model_copy(
                update={"status": "excluded", "record_ids": (), "reason": "exclude"}
            ),
            *records[1:],
        )
    elif edit == "no_reason":
        records = (*records[:-1], records[-1].model_copy(update={"reason": None}))
    else:
        records = (records[0].model_copy(update={"record_ids": ("t2",)}), *records[1:])
    review = review.model_copy(update={"observation_dispositions": records})
    assert errors(validate_inventory(inventory, inputs, review))


def test_sidecar_is_bound_to_exact_inventory_and_input():
    inputs, inventory, review = case()
    assert "INPUT_BINDING" in errors(
        validate_inventory(inventory.model_copy(update={"input_sha256": "0" * 64}), inputs, review)
    )
    assert "INVENTORY_BINDING" in errors(
        validate_inventory(
            inventory, inputs, review.model_copy(update={"inventory_sha256": "0" * 64})
        )
    )


def test_unknown_model_refs_are_not_treated_as_final_ids():
    inputs, inventory, review = case()
    bad = review.proposal_origins[0].model_copy(update={"proposal_ref": "t1"})
    review = review.model_copy(update={"proposal_origins": (bad, *review.proposal_origins[1:])})
    assert "INVALID_PROPOSAL_ORIGIN" in errors(validate_inventory(inventory, inputs, review))


def test_proposal_classification_and_equivalence_stay_proposals():
    inputs, _, _ = case()
    proposal = load("proposal", InventoryProposal)
    from feature_dictionary.synthesis_core.inventory_schema import EquivalenceProposal

    equivalence = EquivalenceProposal(
        record_refs=("model_anal", "model_tail"),
        observation_ids=("o1", "o4"),
        rationale="Synthetic test of review retention, not biological equivalence.",
    )
    proposal = proposal.model_copy(update={"equivalence_proposals": (equivalence,)})
    assert not errors(validate_inventory_proposal(proposal, inputs))
    assert equivalence.status == "pending_review"
    bad = proposal.records[0].model_copy(update={"parent_refs": ("model_tail",)})
    proposal = proposal.model_copy(update={"records": (bad, *proposal.records[1:])})
    assert "INVALID_LINK_OWNER" in errors(validate_inventory_proposal(proposal, inputs))


def test_shared_labels_remain_distinct_records_requiring_review():
    inputs, inventory, review = case()
    second_sense = inventory.anatomical_nouns[0].model_copy(
        update={
            "id": "t3",
            "compound_ids": (),
            "review_note": "Another proposed sense, retained for review.",
        }
    )
    inventory = inventory.model_copy(
        update={"anatomical_nouns": (*inventory.anatomical_nouns, second_sense)}
    )
    inventory, review = rebind(inputs, inventory, review)
    first = review.observation_dispositions[0].model_copy(update={"record_ids": ("t1", "t3")})
    review = review.model_copy(
        update={"observation_dispositions": (first, *review.observation_dispositions[1:])}
    )
    issues = validate_inventory(inventory, inputs, review)
    assert not errors(issues)
    assert "SHARED_LABEL_REVIEW" in {i.code for i in issues}
    assert len(inventory.anatomical_nouns) == 3


def test_multiple_parents_and_shared_subterm_with_exact_synthetic_evidence():
    from feature_dictionary.extraction_v3 import text_sha256, validate_response
    from feature_dictionary.synthesis_core.inventory_schema import ObservationReference

    inputs, _, _ = case()
    text = "head and body scales; dorsal scales; dorsal bands"
    terms = [
        "head",
        "body",
        "scales",
        "head and body scales",
        "dorsal",
        "dorsal scales",
        "bands",
        "dorsal bands",
    ]
    raw = json.dumps(
        {
            "format_version": "extraction-3.1",
            "entries": [{"matched_text": t, "source_phrase": t} for t in terms],
        }
    )
    snapshot = inputs.sources[0]
    source = snapshot.document.input.model_copy(
        update={
            "supplied_text": text,
            "supplied_text_sha256": text_sha256(text),
            "original_file_sha256": text_sha256(text),
        }
    )
    document = snapshot.document.model_copy(
        update={"input": source, "entries": validate_response(raw, text).entries}
    )
    inputs = inputs.model_copy(
        update={
            "sources": (snapshot.model_copy(update={"document": document, "raw_response": raw}),),
            "observations": tuple(
                ObservationReference(id=f"o{i + 1}", source_id="src1", entry_index=i)
                for i in range(8)
            ),
        }
    )
    binding = artifact_sha256(inputs)
    inventory = Inventory.model_validate_json(
        json.dumps(
            {
                "format_version": "synthesis-1.0",
                "input_sha256": binding,
                "anatomical_nouns": [
                    {"id": "t1", "text": "head", "observation_ids": ["o1"], "compound_ids": ["c1"]},
                    {"id": "t2", "text": "body", "observation_ids": ["o2"], "compound_ids": ["c1"]},
                    {
                        "id": "t3",
                        "text": "scales",
                        "observation_ids": ["o3"],
                        "compound_ids": ["c2"],
                    },
                    {
                        "id": "t4",
                        "text": "bands",
                        "observation_ids": ["o7"],
                        "compound_ids": ["c3"],
                    },
                ],
                "compound_terms": [
                    {
                        "id": "c1",
                        "text": "head and body scales",
                        "observation_ids": ["o4"],
                        "parent_ids": ["t1", "t2", "t3"],
                        "relationship_note": (
                            "Head/body coordination and the shared scales head are "
                            "proposed anchors, pending review."
                        ),
                        "subterm_ids": [],
                    },
                    {
                        "id": "c2",
                        "text": "dorsal scales",
                        "observation_ids": ["o6"],
                        "parent_ids": ["t3"],
                        "subterm_ids": ["s1"],
                    },
                    {
                        "id": "c3",
                        "text": "dorsal bands",
                        "observation_ids": ["o8"],
                        "parent_ids": ["t4"],
                        "subterm_ids": ["s1"],
                    },
                ],
                "subterms": [
                    {
                        "id": "s1",
                        "text": "dorsal",
                        "observation_ids": ["o5"],
                        "type": "anatomical_modifier",
                    }
                ],
            }
        )
    )
    # Keep reciprocal links explicit; no automatic repair or compiler is involved.
    noun = inventory.anatomical_nouns[2].model_copy(update={"compound_ids": ("c1", "c2")})
    inventory = inventory.model_copy(
        update={
            "anatomical_nouns": (
                *inventory.anatomical_nouns[:2],
                noun,
                inventory.anatomical_nouns[3],
            )
        }
    )
    records = [*inventory.anatomical_nouns, *inventory.compound_terms, *inventory.subterms]
    review = InventoryReview.model_validate_json(
        json.dumps(
            {
                "format_version": "synthesis-review-1.0",
                "input_sha256": binding,
                "inventory_sha256": artifact_sha256(inventory),
                "observation_dispositions": [
                    {
                        "observation_id": o.id,
                        "status": "mapped",
                        "record_ids": [r.id for r in records if o.id in r.observation_ids],
                        "reason": None,
                    }
                    for o in inputs.observations
                ],
                "proposal_origins": [],
                "proposals": [],
                "review_notes": ["Synthetic links remain unverified proposals."],
            }
        )
    )
    assert not errors(validate_inventory(inventory, inputs, review))
    assert len(inventory.compound_terms[0].parent_ids) == 3
    assert inventory.compound_terms[1].subterm_ids == inventory.compound_terms[2].subterm_ids


def test_reviewed_claims_need_explicit_accounting():
    inputs, inventory, review = case()
    noun = inventory.anatomical_nouns[0].model_copy(update={"review_status": "reviewed"})
    compound = inventory.compound_terms[0].model_copy(
        update={"subterm_ids": (), "relationship_status": "reviewed"}
    )
    inventory = inventory.model_copy(
        update={
            "anatomical_nouns": (noun, inventory.anatomical_nouns[1]),
            "compound_terms": (compound, inventory.compound_terms[1]),
        }
    )
    inventory, review = rebind(inputs, inventory, review)
    assert {"REVIEW_NOTE_REQUIRED"} <= errors(validate_inventory(inventory, inputs, review))
