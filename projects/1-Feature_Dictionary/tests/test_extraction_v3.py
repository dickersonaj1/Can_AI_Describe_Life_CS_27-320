"""Offline evidence checks. No model clients, runner changes, or paid requests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from feature_dictionary.extraction_v3 import (
    FORMAT_VERSION,
    CandidateResponse,
    ExtractionDocument,
    Span,
    resolve_location,
    text_sha256,
    validate_document,
    validate_response,
)


def entry(term, phrase=None, **changes):
    phrase = term if phrase is None else phrase
    return dict(
        term=term,
        matched_text=term,
        source_phrase=phrase,
        evidence_type="complete" if term == phrase else "embedded",
        **changes,
    )


def response(*entries):
    return json.dumps(dict(format_version=FORMAT_VERSION, entries=entries), ensure_ascii=False)


def codes(report):
    return {issue.code for issue in report.issues}


def document(raw, text):
    return ExtractionDocument(
        format_version=FORMAT_VERSION,
        input=dict(
            source_path="fixture.txt",
            original_file_sha256=text_sha256(text),
            original_file_archive="inputs/fixture.txt",
            supplied_text=text,
            supplied_text_sha256=text_sha256(text),
            truncated=False,
        ),
        run=dict(
            run_id="offline",
            provider="openai",
            model="mock",
            prompt_version="v3",
            prompt_template_sha256="0" * 64,
            rendered_prompt_fingerprint="fixture",
            completion_status="success",
            completion_reason="stop",
        ),
        entries=validate_response(raw, text).entries,
    )


def test_nested_terms_preserve_overlapping_evidence():
    text = "anterior dorsal scales"
    terms = ["anterior", "dorsal", "scales", "dorsal scales", text]
    raw = response(*(entry(term, text) for term in terms))
    report = validate_response(raw, text)
    assert report.evidence_valid
    assert report.raw_response == raw
    assert report.supplied_text_sha256 == text_sha256(text)
    for record in report.entries:
        candidate = record.location.candidates[0]
        assert text[candidate.match_span.start : candidate.match_span.end] == record.term
        assert text[candidate.phrase_span.start : candidate.phrase_span.end] == text
    assert [e.evidence_type for e in report.entries] == ["embedded"] * 4 + ["complete"]


def test_all_possible_occurrences_remain_ambiguous():
    report = validate_response(response(entry("keeled")), "Scales keeled. Scales keeled.")
    assert report.evidence_valid
    assert codes(report) == {"AMBIGUOUS_LOCATION"}
    location = report.entries[0].location
    assert location.status == "ambiguous"
    assert [c.match_span.start for c in location.candidates] == [7, 22]


def test_matches_are_paired_with_their_own_phrase_and_context_can_disambiguate():
    text = "scales; dorsal scales; scales"
    location = resolve_location(text, "scales", "dorsal scales")
    assert location.status == "resolved"
    assert location.candidates[0].match_span == Span(start=15, end=21)
    assert resolve_location("scales scales", "scales", "scales scales").status == "ambiguous"
    assert len(resolve_location("aaa", "aa", "aa").candidates) == 2


def test_corrected_multilingual_example_offsets():
    text = "praeocular; préoculaire"
    assert len(text) == 23
    report = validate_response(response(entry("praeocular"), entry("préoculaire")), text)
    assert report.evidence_valid
    assert report.entries[1].location.candidates[0].match_span == Span(start=12, end=23)
    assert text[12:23] == "préoculaire"


@pytest.mark.parametrize("term", ["鳞片", "حراشف", "écailles", "M.B.S.R.", "A–B", "🐍"])
def test_unicode_punctuation_and_capitalization_are_preserved(term):
    report = validate_response(response(entry(term)), "🐍\r\n" + term)
    assert report.evidence_valid
    result = report.entries[0]
    assert result.term == term
    assert result.location.candidates[-1].match_span.start == 3


@pytest.mark.parametrize("quote,text", [("é", "e\u0301"), ("scales", "Scales"), ("A-B", "A–B")])
def test_no_unicode_case_or_punctuation_normalization(quote, text):
    report = validate_response(response(entry(quote)), text)
    assert not report.evidence_valid
    assert "UNMATCHED_EVIDENCE" in codes(report)
    assert report.entries[0].term == quote
    assert report.entries[0].location.status == "unmatched"


def test_normalized_model_label_is_retained_but_not_added_as_observed_vocabulary():
    candidate = entry("colouration")
    candidate["term"] = "coloration"
    report = validate_response(response(candidate), "colouration")
    assert report.evidence_valid
    assert report.entries[0].term == "colouration"
    assert report.entries[0].model_term == "coloration"
    assert codes(report) == {"MODEL_LABEL_DIFFERS_FROM_QUOTE"}
    invented_quote = validate_response(response(entry("coloration")), "colouration")
    assert not invented_quote.evidence_valid


@pytest.mark.parametrize(
    "annotations",
    [
        None,
        {},
        {"language": "fr", "forms": []},
        {"language": "wrong-language"},
        {"language": 17, "forms": "acronym"},
        {"forms": ["uncertain", 3]},
        "possibly historical",
        {"confidence": 0.2},
    ],
)
def test_annotations_never_invalidate_grounded_terminology(annotations):
    report = validate_response(
        response(entry("préoculaire", proposed_annotations=annotations)), "préoculaire"
    )
    assert report.evidence_valid
    assert report.entries[0].proposed_annotations == annotations
    assert all(issue.severity == "warning" for issue in report.issues)


def test_broad_vocabulary_and_abbreviation_are_separate_without_relationships():
    terms = [
        "scales",
        "dorsal",
        "dorsals",
        "dorsal scales",
        "keeling",
        "keeled",
        "midbody scale rows",
        "MBSR",
        "praeocular",
        "préoculaire",
        "colouration",
        "coloration",
    ]
    text = "; ".join(terms)
    report = validate_response(response(*(entry(t) for t in terms)), text)
    assert report.evidence_valid
    assert [e.term for e in report.entries] == terms
    assert "expansion" not in report.entries[-5].model_dump()


def test_grounding_does_not_claim_to_reject_descriptive_clauses():
    clause = "anterior chin-shields, which are as long as the posterior"
    report = validate_response(response(entry(clause)), clause)
    assert report.evidence_valid  # Phrase suitability requires separate biological review.


@pytest.mark.parametrize("extra", ["parent", "relationships", "expansion", "translation", "kind"])
def test_model_cannot_add_relationship_or_classification_fields(extra):
    candidate = entry("scales")
    candidate[extra] = "invented"
    report = validate_response(response(candidate), "scales")
    assert not report.evidence_valid
    assert codes(report) == {"CONTRACT_ERROR"}


@pytest.mark.parametrize(
    "raw",
    [
        '{"format_version": "extraction-3.0", "entries": [',
        '{"entries": [], "entries": []}',
        '{"entries": [], "x": NaN}',
        '{"entries": [], "x": Infinity}',
        '{"entries": [], "x": 1e999}',
        "```json\n{}\n```",
    ],
)
def test_invalid_or_incomplete_json_is_retained_exactly(raw):
    report = validate_response(raw, "scales")
    assert not report.evidence_valid
    assert report.raw_response == raw
    assert codes(report) == {"INVALID_JSON"}


@pytest.mark.parametrize("change", [{"format_version": "extraction-4.0"}, {"entries": "scales"}])
def test_contract_errors_are_explicit(change):
    value = dict(format_version=FORMAT_VERSION, entries=[])
    value.update(change)
    assert "CONTRACT_ERROR" in codes(validate_response(json.dumps(value), "scales"))


def test_whitespace_and_false_evidence_type_fail_without_trimming_quotes():
    candidate = entry("scales", "dorsal scales")
    candidate["evidence_type"] = "complete"
    assert "EVIDENCE_TYPE_MISMATCH" in codes(
        validate_response(response(candidate), "dorsal scales")
    )
    assert "EMPTY_EXPRESSION" in codes(validate_response(response(entry(" ")), " "))


def test_duplicate_claims_fail_but_different_phrase_contexts_remain_separate():
    duplicate = validate_response(response(entry("scales"), entry("scales")), "scales")
    assert "DUPLICATE_ENTRY" in codes(duplicate)
    assert len(duplicate.entries) == 2
    separate = validate_response(
        response(entry("scales", "dorsal scales"), entry("scales", "ventral scales")),
        "dorsal scales; ventral scales",
    )
    assert separate.evidence_valid


def test_empty_output_does_not_assert_completeness():
    report = validate_response(response(), "scales")
    assert report.evidence_valid
    assert codes(report) == {"NO_ENTRIES"}


def test_surrogate_input_reports_an_error():
    report = validate_response(response(entry("scales")), "\ud800")
    assert not report.evidence_valid
    assert codes(report) == {"INVALID_UNICODE"}


def test_document_revalidation_detects_tampering_and_retains_provider_status():
    raw = response(entry("scales"))
    saved = document(raw, "scales")
    saved.run.completion_status = "incomplete"
    saved.run.completion_reason = "max_output_tokens"
    assert validate_document(saved, raw).evidence_valid
    assert saved.run.completion_status == "incomplete"
    saved.entries[0].location.candidates[0].match_span.end = 99
    assert "DOCUMENT_EVIDENCE_MISMATCH" in codes(validate_document(saved, raw))
    saved.input.supplied_text_sha256 = "0" * 64
    assert "INPUT_HASH_MISMATCH" in codes(validate_document(saved, raw))


def test_span_types_are_strict():
    with pytest.raises(ValidationError):
        Span(start=True, end=1)


def test_offline_validation_is_reproducible():
    raw = response(entry("keeled"))
    assert (
        validate_response(raw, "keeled keeled").model_dump_json()
        == validate_response(raw, "keeled keeled").model_dump_json()
    )


@pytest.mark.parametrize(
    "name,contract",
    [
        ("extraction_candidate_v3.schema.json", CandidateResponse),
        ("extraction_v3.schema.json", ExtractionDocument),
    ],
)
def test_published_schemas_match_python_contract(name, contract):
    path = Path(__file__).resolve().parents[1] / "schemas" / name
    assert json.loads(path.read_text()) == contract.model_json_schema()
