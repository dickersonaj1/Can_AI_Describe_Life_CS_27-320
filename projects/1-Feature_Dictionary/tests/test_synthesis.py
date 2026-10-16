"""Deterministic v2 contracts and offline replay. No live clients or paid API calls."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from feature_dictionary import synthesis as cli
from feature_dictionary.synthesis_core import inference as inf
from feature_dictionary.synthesis_core.ingest import normalize, read_outputs
from feature_dictionary.synthesis_core.schema import Dictionary, DictionaryProposal, InputBundle
from feature_dictionary.synthesis_core.validation import validate_proposal

TEXT = """<!--
model: synthetic-fixture
status: success
input_characters_used: 123
-->
## Primary terms
* **scales** - synonyms: `scale` - homonyms:
* **keeling** - synonyms: - homonyms:
* **keeled** - synonyms: - homonyms:
* **head** - synonyms: - homonyms:
* **head scales** - synonyms: `head-scales` - homonyms:
* **midbody scale rows** - synonyms: `MBSR` - homonyms:
## Homonyms
None found
"""


def project(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "fixture.md").write_text(TEXT, encoding="utf-8")
    return read_outputs(folder)


def candidate(bundle):
    terms, dispositions = [], []
    for obs in bundle.observations:
        if obs.category != "term_entry":
            dispositions.append(
                dict(
                    observation_id=obs.id,
                    status="unresolved",
                    term_refs=[],
                    reason="Retained section boilerplate",
                )
            )
            continue
        index = len(terms)
        ref = f"c{index}"
        kind = {1: "characteristic", 2: "character_state"}.get(index, "structure")
        expressions = [
            dict(
                text=w,
                role="preferred" if j == 0 else "grammatical_variant",
                language=None,
                expansion=None,
                observation_ids=[obs.id],
            )
            for j, w in enumerate(obs.observed_terms)
        ]
        if index == 5:
            expressions[1].update(role="acronym", expansion="midbody scale rows")
        terms.append(
            dict(
                ref=ref,
                kind=kind,
                characteristic_type=None,
                sense_note=None,
                scope_note=None,
                expressions=expressions,
                notes="",
            )
        )
        dispositions.append(
            dict(observation_id=obs.id, status="mapped", term_refs=[ref], reason=None)
        )
    relationships = []
    for subject, predicate, obj in [
        ("c1", "describes", "c0"),
        ("c2", "state_of", "c1"),
        ("c4", "part_of", "c3"),
        ("c4", "subtype_of", "c0"),
    ]:
        evidence = terms[int(subject[1:])]["expressions"][0]["observation_ids"]
        relationships.append(
            dict(
                subject_ref=subject,
                predicate=predicate,
                object_ref=obj,
                observation_ids=evidence,
                rationale="Synthetic example proposal",
            )
        )
    return dict(
        terms=terms,
        relationships=relationships,
        observation_dispositions=dispositions,
        review_notes=[],
    )


def archive(bundle, data=None, status="completed"):
    return dict(
        artifact_version="2.0",
        inputs=bundle.model_dump(mode="json"),
        request=dict(model="synthetic-fixture", instructions="Offline fixture"),
        response=dict(status=status, id="fixture-response"),
        output_text=json.dumps(data if data is not None else candidate(bundle)),
        error=None,
        candidate_override=None,
    )


def codes(report):
    return {issue["code"] for issue in report["issues"]}


def test_valid_output_has_typed_concepts_multiple_parents_and_no_verification(tmp_path):
    bundle = project(tmp_path)
    result, report = inf.evaluate(archive(bundle))
    assert report["valid"]
    Dictionary.model_validate_json(json.dumps(result))
    assert result["observations"] == bundle.model_dump(mode="json")["observations"]
    assert result["status"] == "proposed_requires_review"
    assert {r["basis"] for r in result["relationships"]} == {"model_inference"}
    assert {r["status"] for r in result["relationships"]} == {"proposed"}
    shared = next(t for t in result["terms"] if t["expressions"][0]["text"] == "head scales")
    assert sum(r["subject_id"] == shared["id"] for r in result["relationships"]) == 2


def test_observations_are_deeply_immutable_and_original_bytes_retained(tmp_path):
    bundle = project(tmp_path)
    with pytest.raises(ValidationError):
        bundle.observations[0].raw_text = "changed"
    with pytest.raises(TypeError):
        bundle.observations[0].observed_terms[0] = "changed"
    with pytest.raises(ValidationError):
        bundle.sources[0].metadata[0].value = "changed"
    assert base64.b64decode(bundle.sources[0].raw_bytes_b64) == TEXT.encode()


def test_recursive_discovery_and_stable_ids_when_another_file_is_added(tmp_path):
    first = project(tmp_path)
    nested = tmp_path / "inputs" / "another-run"
    nested.mkdir()
    (nested / "answer.md").write_text(TEXT.replace("synthetic-fixture", "second-model"))
    second = read_outputs(tmp_path / "inputs")
    assert len(second.sources) == 2
    assert set(o.id for o in first.observations) <= set(o.id for o in second.observations)


def test_invalid_extractions_and_unparsed_content_are_not_dropped(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    raw = b"<!--\nstatus: failed\ninput_characters_used: 0\n-->\nUnexpected answer\xff"
    (folder / "bad.md").write_bytes(raw)
    bundle = read_outputs(folder)
    assert base64.b64decode(bundle.sources[0].raw_bytes_b64) == raw
    assert len(bundle.observations) == 1
    assert bundle.observations[0].category == "unparsed"
    assert {"ZERO_INPUT", "NO_PARSED_TERMS", "EXTRACTION_UNSUCCESSFUL"} <= {
        i.code for i in bundle.issues
    }


def test_homonym_section_preserves_each_claim_and_line(tmp_path):
    bundle = project(tmp_path)
    path = tmp_path / "inputs" / "fixture.md"
    path.write_text(TEXT.replace("None found", "* **spines** - homonyms: `sense A`; `sense B`"))
    changed = read_outputs(path.parent)
    obs = changed.observations[-1]
    assert obs.category == "homonym_claim"
    assert obs.homonym_claims == ("sense A", "sense B")
    assert obs.raw_text.endswith("`sense B`")
    assert bundle != changed


@pytest.mark.parametrize(
    "damage,expected",
    [
        ("unknown_term", "UNKNOWN_TERM_REFERENCE"),
        ("unknown_observation", "UNKNOWN_OBSERVATION"),
        ("invented", "UNSUPPORTED_EXPRESSION"),
        ("lost_variant", "LOST_TERMINOLOGY"),
        ("wrong_direction", "RELATIONSHIP_TYPE_MISMATCH"),
        ("placeholder", "PLACEHOLDER_EXPRESSION"),
        ("empty_term", "PLACEHOLDER_TERM"),
        ("duplicate_concept", "DUPLICATE_CONCEPT"),
        ("duplicate_id", "DUPLICATE_OR_EMPTY_ID"),
        ("duplicate_alias", "DUPLICATE_EXPRESSION"),
        ("redundant_alias", "REDUNDANT_ALIAS"),
        ("missing_disposition", "MISSING_DISPOSITION"),
        ("duplicate_disposition", "DUPLICATE_DISPOSITION"),
        ("unexplained_exclusion", "MISSING_DISPOSITION_REASON"),
        ("conflicting_exclusion", "DISPOSITION_CONFLICT"),
        ("missing_evidence", "MISSING_EVIDENCE"),
        ("duplicate_edge", "DUPLICATE_RELATIONSHIP"),
        ("self_edge", "SELF_RELATIONSHIP"),
        ("cycle", "HIERARCHY_CYCLE"),
        ("unrelated_evidence", "UNRELATED_RELATIONSHIP_EVIDENCE"),
        ("invented_expansion", "UNSUPPORTED_EXPANSION"),
        ("verified", "CANDIDATE_SCHEMA"),
    ],
)
def test_invalid_proposals_produce_clear_errors(tmp_path, damage, expected):
    bundle = project(tmp_path)
    data = candidate(bundle)
    if damage == "unknown_term":
        data["relationships"][0]["object_ref"] = "missing"
    elif damage == "unknown_observation":
        data["terms"][0]["expressions"][0]["observation_ids"] = ["missing"]
    elif damage == "invented":
        data["terms"][0]["expressions"][0]["text"] = "invented"
    elif damage == "lost_variant":
        data["terms"][0]["expressions"].pop()
    elif damage == "wrong_direction":
        data["relationships"][0].update(subject_ref="c0", object_ref="c1")
    elif damage == "placeholder":
        data["terms"][0]["expressions"][0]["text"] = "TBD"
    elif damage == "empty_term":
        data["terms"][0]["expressions"] = []
    elif damage in ("duplicate_concept", "duplicate_id"):
        duplicate = json.loads(json.dumps(data["terms"][0]))
        if damage == "duplicate_concept":
            duplicate["ref"] = "another"
        data["terms"].append(duplicate)
    elif damage == "duplicate_alias":
        data["terms"][0]["expressions"].append(data["terms"][0]["expressions"][1].copy())
    elif damage == "redundant_alias":
        data["terms"][0]["expressions"][1]["text"] = "SCALES"
    elif damage == "missing_disposition":
        data["observation_dispositions"].pop(0)
    elif damage == "duplicate_disposition":
        data["observation_dispositions"].append(data["observation_dispositions"][0].copy())
    elif damage in ("unexplained_exclusion", "conflicting_exclusion"):
        data["observation_dispositions"][0].update(status="excluded", term_refs=[])
    elif damage == "missing_evidence":
        data["relationships"][0]["observation_ids"] = []
    elif damage == "duplicate_edge":
        data["relationships"].append(data["relationships"][0].copy())
    elif damage == "self_edge":
        data["relationships"][2]["object_ref"] = "c4"
    elif damage == "cycle":
        data["relationships"].append(
            dict(
                subject_ref="c0",
                predicate="subtype_of",
                object_ref="c4",
                observation_ids=[bundle.observations[0].id],
                rationale="x",
            )
        )
    elif damage == "unrelated_evidence":
        data["relationships"][0]["observation_ids"] = [bundle.observations[3].id]
    elif damage == "invented_expansion":
        data["terms"][5]["expressions"][1]["expansion"] = "invented expansion"
    elif damage == "verified":
        data["relationships"][0]["status"] = "verified"
    result, report = inf.evaluate(archive(bundle, data))
    assert result is None
    assert expected in codes(report)
    assert all(i["path"].startswith("/") for i in report["issues"])


def test_same_spelling_distinct_senses_are_preserved_not_merged(tmp_path):
    bundle = project(tmp_path)
    data = candidate(bundle)
    first = data["terms"][0]
    first["sense_note"] = "First explicitly distinguished sense"
    second = json.loads(json.dumps(first))
    second.update(ref="another", sense_note="Second uncertain sense")
    data["terms"].append(second)
    data["observation_dispositions"][0]["term_refs"].append("another")
    result, report = inf.evaluate(archive(bundle, data))
    assert report["valid"]
    assert len(result["terms"]) == 7
    assert "AMBIGUOUS_LABEL" in codes(report)
    assert len({t["id"] for t in result["terms"]}) == 7


def test_unresolved_observations_and_homonym_claims_remain_in_output(tmp_path):
    bundle = project(tmp_path)
    data = candidate(bundle)
    data["terms"].pop(5)
    data["observation_dispositions"][5].update(
        status="unresolved", term_refs=[], reason="Acronym interpretation needs review"
    )
    result, report = inf.evaluate(archive(bundle, data))
    assert report["valid"]
    assert result["observations"] == bundle.model_dump(mode="json")["observations"]
    assert result["observation_dispositions"]


def test_source_and_observation_tampering_detected(tmp_path):
    original = archive(project(tmp_path))
    original["inputs"]["observations"][0]["raw_text"] = "changed"
    _, report = inf.evaluate(original)
    assert "OBSERVATION_INTEGRITY" in codes(report)
    original["inputs"]["sources"][0]["metadata"][0]["value"] = "forged"
    _, report = inf.evaluate(original)
    assert "SOURCE_INTEGRITY" in codes(report)


def test_invalid_response_and_schema_report_all_reproducible_errors(tmp_path):
    original = archive(project(tmp_path))
    original["output_text"] = "{not json"
    result, report = inf.evaluate(original)
    assert result is None and "CANDIDATE_SCHEMA" in codes(report)
    assert inf.evaluate(original)[1] == report
    original["artifact_version"] = "1.0"
    assert "UNSUPPORTED_ARCHIVE_VERSION" in codes(inf.evaluate(original)[1])


class FakeResponse:
    def __init__(self, text, status="completed"):
        self.output_text, self.status = text, status

    def model_dump(self, **kwargs):
        return dict(
            status=self.status,
            id="fake-response",
            output=[{"text": self.output_text}],
            usage={"input_tokens": 10, "output_tokens": 10},
        )


@pytest.mark.parametrize(
    "status,text", [("incomplete", "{}"), ("completed", "not json"), ("completed", "")]
)
def test_unsuccessful_raw_response_saved_before_validation(tmp_path, status, text):
    bundle = project(tmp_path)
    client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kw: FakeResponse(text, status))
    )
    folder = tmp_path / "archive"
    saved = inf.request_synthesis(
        client,
        model="fake",
        bundle=bundle,
        prompt="prompt",
        max_output_tokens=1000,
        archive_dir=folder,
    )
    assert (folder / "request.json").exists()
    response = json.loads((folder / "response.json").read_text())
    assert response["output_text"] == text
    assert response["response"]["output"][0]["text"] == text
    assert response["inputs"] == bundle.model_dump(mode="json")
    assert not inf.evaluate(saved)[1]["valid"]


@pytest.mark.parametrize("exception", [RuntimeError("API failed"), KeyboardInterrupt()])
def test_api_failures_and_interruptions_preserve_request_and_inputs(tmp_path, exception):
    bundle = project(tmp_path)

    def fail(**kwargs):
        raise exception

    folder = tmp_path / "archive"
    with pytest.raises(type(exception)):
        inf.request_synthesis(
            SimpleNamespace(responses=SimpleNamespace(create=fail)),
            model="fake",
            bundle=bundle,
            prompt="prompt",
            max_output_tokens=1000,
            archive_dir=folder,
        )
    saved = json.loads((folder / "response.json").read_text())
    assert saved["error"]["type"] == type(exception).__name__
    assert saved["inputs"] == bundle.model_dump(mode="json")
    assert saved["response"] is None


def test_replay_and_offline_correction_never_use_api_or_current_inputs(tmp_path, monkeypatch):
    bundle = project(tmp_path)
    saved = archive(bundle)
    data = candidate(bundle)
    saved["output_text"] = "invalid JSON"
    raw = tmp_path / "response.json"
    inf.write_json(raw, saved)
    edited = tmp_path / "candidate.json"
    inf.write_json(edited, data)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "read_outputs", lambda *_: pytest.fail("Replay must not read inputs"))
    output = tmp_path / "dictionary.json"
    assert cli.main(["--replay", str(raw), "--output", str(output)]) == 2
    assert not output.exists()
    assert (
        cli.main(["--replay", str(raw), "--candidate", str(edited), "--output", str(output)]) == 0
    )
    result = json.loads(output.read_text())
    assert "OFFLINE_EDIT" in {i["code"] for i in result["issues"]}
    assert json.loads(raw.read_text()) == saved  # Original invalid response unchanged.


def test_id_resolution_is_deterministic_and_does_not_mutate_candidate(tmp_path):
    saved = archive(project(tmp_path))
    before = json.dumps(saved, sort_keys=True)
    first = inf.evaluate(saved)[0]
    second = inf.evaluate(saved)[0]
    assert first == second
    assert json.dumps(saved, sort_keys=True) == before
    assert all(t["id"].startswith("term_") for t in first["terms"])


def test_dry_run_and_overwrite_protection(tmp_path, monkeypatch):
    project(tmp_path)
    output = tmp_path / "dictionary.json"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    args = ["--input-dir", str(tmp_path / "inputs"), "--output", str(output)]
    assert cli.main([*args, "--dry-run"]) == 0
    assert not output.exists()
    output.write_text("existing experiment")
    assert cli.main(args) == 2
    assert output.read_text() == "existing experiment"


def test_explicit_overwrite_archives_exact_previous_experiment(tmp_path):
    saved = tmp_path / "response.json"
    inf.write_json(saved, archive(project(tmp_path)))
    output = tmp_path / "dictionary.json"
    old = b"prior experimental data\x00\xff"
    output.write_bytes(old)
    assert cli.main(["--replay", str(saved), "--output", str(output), "--overwrite"]) == 0
    backups = list((tmp_path / "archives").rglob("previous_output.bin"))
    assert len(backups) == 1 and backups[0].read_bytes() == old


def test_normalization_is_conservative():
    assert normalize("  SCALES  ") == "scales"
    assert normalize("head-scales") != normalize("head scales")
    assert normalize("scale") != normalize("scales")


def test_bundle_round_trip_preserves_immutable_input(tmp_path):
    bundle = project(tmp_path)
    assert InputBundle.model_validate_json(bundle.model_dump_json()) == bundle
    proposal = DictionaryProposal.model_validate_json(json.dumps(candidate(bundle)))
    assert not any(i.severity == "error" for i in validate_proposal(proposal, bundle))


def test_model_agreement_is_provenance_not_verification(tmp_path):
    project(tmp_path)
    folder = tmp_path / "inputs"
    (folder / "second.md").write_text(TEXT.replace("synthetic-fixture", "second-model"))
    bundle = read_outputs(folder)
    data = candidate(bundle)
    # Model agreement is expressed as multiple observation citations on the same concept.
    by_label = {}
    refs = {}
    for term in data["terms"]:
        label = term["expressions"][0]["text"]
        if label not in by_label:
            by_label[label] = term
        else:
            original = by_label[label]
            for dest, expression in zip(original["expressions"], term["expressions"], strict=True):
                dest["observation_ids"].extend(expression["observation_ids"])
        refs[term["ref"]] = by_label[label]["ref"]
    data["terms"] = list(by_label.values())
    for disposition in data["observation_dispositions"]:
        disposition["term_refs"] = [refs[r] for r in disposition["term_refs"]]
    result, report = inf.evaluate(archive(bundle, data))
    assert report["valid"]
    assert {source["model"] for source in result["sources"]} == {
        "synthetic-fixture",
        "second-model",
    }
    assert len(result["terms"][0]["expressions"][0]["observation_ids"]) == 2
    assert all(r["status"] == "proposed" for r in result["relationships"])
    assert all(r["basis"] == "model_inference" for r in result["relationships"])


def test_validation_reports_multiple_errors_in_one_pass(tmp_path):
    bundle = project(tmp_path)
    data = candidate(bundle)
    data["relationships"][0]["object_ref"] = "nonexistent"
    data["relationships"][0]["rationale"] = ""
    data["terms"][0]["expressions"][0]["text"] = "invented"
    _, report = inf.evaluate(archive(bundle, data))
    assert {"UNKNOWN_TERM_REFERENCE", "MISSING_RATIONALE", "UNSUPPORTED_EXPRESSION"} <= codes(
        report
    )
    assert report["error_count"] >= 3


def test_committed_schemas_and_synthetic_example_match_runtime_contracts():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    final_schema = json.loads((root / "schemas/feature_dictionary_v2.schema.json").read_text())
    candidate_schema = json.loads((root / "schemas/synthesis_candidate_v2.schema.json").read_text())
    assert final_schema == Dictionary.model_json_schema()
    assert candidate_schema == DictionaryProposal.model_json_schema()
    sample = root / "examples/synthesis_v2"
    saved = json.loads((sample / "response.json").read_text())
    result, report = inf.evaluate(saved)
    assert report["valid"]
    assert result == json.loads((sample / "dictionary.json").read_text())
    assert report == json.loads((sample / "validation.json").read_text())


def test_empty_synonym_field_never_becomes_a_homonym_label(tmp_path):
    bundle = project(tmp_path)
    assert bundle.observations[1].observed_terms == ("keeling",)
    assert bundle.observations[2].observed_terms == ("keeled",)
    assert bundle.observations[3].observed_terms == ("head",)
    assert all("- homonyms:" not in o.observed_terms for o in bundle.observations)
