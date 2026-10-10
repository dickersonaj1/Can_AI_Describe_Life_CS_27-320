"""Staged synthesis integration tests. Fake clients only; never paid API calls."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from feature_dictionary import synthesis as cli
from feature_dictionary.synthesis_core import batching as b
from feature_dictionary.synthesis_core.ingest import read_outputs
from feature_dictionary.synthesis_core.schema import Dictionary, DictionaryProposal


def inputs(tmp_path, entries=None):
    folder = tmp_path / "inputs"
    folder.mkdir()
    entries = entries or ["head", "head scales", "scales", "scales", "keeling", "keeled"]
    for i, label in enumerate(entries):
        sense = "skull" if label == "homonym-A" else "plant" if label == "homonym-B" else None
        label = "crown" if sense else label
        (folder / f"{i:02}.md").write_text(
            f"<!--\nmodel: fake-{i}\nstatus: success\n-->\n## Primary terms\n"
            f"* **{label}** - synonyms: - homonyms:\n" + (f"sense {sense}\n" if sense else "")
        )
    return read_outputs(folder)


def local_candidate(payload):
    terms, dispositions = [], []
    grouped = {}
    for o in payload["observations"]:
        if o["category"] != "term_entry":
            dispositions.append(
                dict(
                    observation_id=o["id"],
                    status="unresolved",
                    term_refs=[],
                    reason="Preserved fixture context",
                )
            )
            continue
        label = o["observed_terms"][0]
        sense = (
            "Sense A"
            if label == "crown" and int(o["id"][1:]) <= 2
            else "Sense B"
            if label == "crown"
            else None
        )
        identity = (label, sense)
        if identity not in grouped:
            ref = f"c{len(terms)}"
            term = dict(
                ref=ref,
                kind={"keeling": "characteristic", "keeled": "character_state"}.get(
                    label, "structure"
                ),
                characteristic_type=None,
                sense_note=sense,
                scope_note=None,
                notes="",
                expressions=[],
            )
            terms.append(term)
            grouped[identity] = term
        term = grouped[identity]
        for j, word in enumerate(o["observed_terms"]):
            existing = next((e for e in term["expressions"] if e["text"] == word), None)
            if existing:
                existing["observation_ids"].append(o["id"])
            else:
                term["expressions"].append(
                    dict(
                        text=word,
                        role="preferred" if j == 0 else "synonym",
                        language=None,
                        expansion=None,
                        observation_ids=[o["id"]],
                    )
                )
        dispositions.append(
            dict(observation_id=o["id"], status="mapped", term_refs=[term["ref"]], reason=None)
        )
    return dict(
        terms=terms, relationships=[], observation_dispositions=dispositions, review_notes=[]
    )


def answer(request):
    payload = json.loads(request["input"])
    stage = request["text"]["format"]["name"].removeprefix("synthesis_")
    if stage == "local":
        return local_candidate(payload)
    cards = {c["ref"]: c for c in payload["concepts"]}
    if stage == "reconcile":
        decisions = []
        for left, right in payload["comparisons"]:
            a, z = cards[left], cards[right]
            if a["expressions"][0]["text"] == z["expressions"][0]["text"]:
                decisions.append(
                    dict(
                        left=left,
                        right=right,
                        action="merge" if a["sense_note"] == z["sense_note"] else "keep_separate",
                        rationale="Synthetic explicit sense comparison",
                        left_sense=a["sense_note"],
                        right_sense=z["sense_note"],
                    )
                )
        return dict(decisions=decisions)
    relationships = []
    for left, right in payload["comparisons"]:
        a, z = cards[left], cards[right]
        labels = a["expressions"][0]["text"], z["expressions"][0]["text"]
        predicate = {
            ("head scales", "head"): "part_of",
            ("head scales", "scales"): "subtype_of",
            ("keeling", "scales"): "describes",
            ("keeled", "keeling"): "state_of",
        }.get(labels)
        if predicate:
            relationships.append(
                dict(
                    subject_ref=left,
                    predicate=predicate,
                    object_ref=right,
                    observation_ids=a["expressions"][0]["observation_ids"],
                    rationale="Synthetic cross-batch inference, unverified",
                )
            )
    return dict(relationships=relationships)


class FakeClient:
    def __init__(self, hook=None):
        self.calls = []
        self.hook = hook
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.calls.append(request)
        if self.hook:
            response = self.hook(request, len(self.calls))
            if response is not None:
                return response
        return response_for(answer(request))


def response_for(data, status="completed", reason=None):
    text = json.dumps(data)
    response = dict(
        status=status,
        id="fake-response",
        usage=dict(input_tokens=10, output_tokens=20),
        incomplete_details=dict(reason=reason) if reason else None,
    )
    return SimpleNamespace(output_text=text, model_dump=lambda **kw: response)


def new_run(tmp_path, bundle=None, **kwargs):
    bundle = bundle or inputs(tmp_path)
    config = b.plan(
        bundle, model="fake", batch_size=1, block_size=2, coverage="comprehensive", **kwargs
    )
    root = tmp_path / "run"
    b.create_run(root, bundle, config)
    return root, bundle


def test_cross_batch_duplicates_relationships_multiple_parents_and_replay(tmp_path):
    root, bundle = new_run(tmp_path)
    client = FakeClient()
    result, validation, summary = b.execute(root, client=client)
    assert validation["valid"], validation
    Dictionary.model_validate_json(json.dumps(result))
    assert len(result["terms"]) == 5
    scales = next(t for t in result["terms"] if t["expressions"][0]["text"] == "scales")
    assert len(scales["expressions"][0]["observation_ids"]) == 2
    assert len(result["relationships"]) == 4
    assert all(
        r["status"] == "proposed" and r["basis"] == "model_inference"
        for r in result["relationships"]
    )
    assert result["observations"] == bundle.model_dump(mode="json")["observations"]
    assert (
        summary["reviewed_relationship_comparisons"]
        == summary["compatible_relationship_comparisons"]
    )
    assert len(list(root.rglob("request.json"))) == len(client.calls)
    before = len(client.calls)
    assert b.execute(root, client=client) == (result, validation, summary)
    assert len(client.calls) == before
    # Offline reconstruction needs neither original extraction files nor an API key.
    for path in (tmp_path / "inputs").glob("*.md"):
        path.write_text("changed current input")
    assert b.execute(root) == (result, validation, summary)


def test_homonyms_preserved_across_batches(tmp_path):
    root, _ = new_run(tmp_path, inputs(tmp_path, ["homonym-A", "homonym-B"]))
    result, validation, _ = b.execute(root, client=FakeClient())
    assert validation["valid"], validation
    assert len(result["terms"]) == 2
    assert len({t["sense_note"] for t in result["terms"]}) == 2
    assert "AMBIGUOUS_LABEL" in {i["code"] for i in validation["issues"]}


def test_incomplete_local_splits_and_does_not_repeat_parent_or_children(tmp_path):
    bundle = inputs(tmp_path)
    root = tmp_path / "run"
    b.create_run(
        root,
        bundle,
        b.plan(bundle, model="fake", batch_size=30, block_size=2, coverage="comprehensive"),
    )

    def truncate(request, number):
        if number == 1:
            return response_for({}, "incomplete", "max_output_tokens")

    client = FakeClient(truncate)
    result, validation, summary = b.execute(root, client=client)
    assert validation["valid"]
    calls = len(client.calls)
    assert b.execute(root, client=client)[0] == result
    assert len(client.calls) == calls
    assert b.execute(root)[0] == result
    assert summary["usage_all_archived_attempts"]["output_tokens"] == calls * 20
    failed = [
        b.load(p)
        for p in root.rglob("response.json")
        if b.load(p)["response"]["status"] == "incomplete"
    ]
    assert len(failed) == 1


@pytest.mark.parametrize("exception", [KeyboardInterrupt(), RuntimeError("network failure")])
def test_interrupt_resume_reuses_successful_jobs_and_requires_explicit_retry(tmp_path, exception):
    root, _ = new_run(tmp_path)

    def interrupt(request, number):
        if number == 2:
            raise exception

    client = FakeClient(interrupt)
    with pytest.raises(type(exception)):
        b.execute(root, client=client)
    successful = client.calls[0]
    retry = FakeClient()
    with pytest.raises(b.JobFailure):
        b.execute(root, client=retry)
    assert not retry.calls
    result, validation, _ = b.execute(root, client=retry, retry_failed=True)
    assert validation["valid"]
    assert successful not in retry.calls
    assert b.execute(root)[0] == result
    assert len(list(root.rglob("attempt_0002"))) == 1


def test_unknown_outcome_never_silently_resubmits(tmp_path):
    root, _ = new_run(tmp_path)

    def crash(request, number):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        b.execute(root, client=FakeClient(crash))
    # Simulate hard process loss after request save but before response save.
    response = next(root.rglob("response.json"))
    response.rename(response.with_name("interrupted_response.json"))
    client = FakeClient()
    with pytest.raises(b.JobFailure, match="unknown"):
        b.execute(root, client=client)
    assert not client.calls
    assert b.execute(root, client=client, retry_failed=True)[1]["valid"]


def test_invalid_response_reproducible_offline_without_repeated_requests(tmp_path):
    root, _ = new_run(tmp_path)
    client = FakeClient(lambda request, n: response_for({"wrong": True}))
    with pytest.raises(b.JobFailure):
        b.execute(root, client=client)
    response_path = next(root.rglob("response.json"))
    original = response_path.read_bytes()
    with pytest.raises(b.JobFailure):
        b.execute(root)
    assert response_path.read_bytes() == original
    assert not b.load(next(root.rglob("validation.json")))["valid"]
    assert len(client.calls) == 1


def test_coverage_modes_are_recorded_and_comprehensive_exposes_nonlexical_pairs(tmp_path):
    bundle = inputs(tmp_path)
    summaries = []
    for mode in ("lightweight", "comprehensive"):
        root = tmp_path / mode
        b.create_run(
            root, bundle, b.plan(bundle, model="fake", batch_size=1, coverage=mode, block_size=2)
        )
        result, validation, summary = b.execute(root, client=FakeClient())
        assert validation["valid"]
        assert summary["coverage_mode"] == mode
        summaries.append(summary)
        if mode == "lightweight":
            assert any("unexamined" in note for note in result["review_notes"])
    assert (
        summaries[0]["reviewed_relationship_comparisons"]
        < summaries[1]["reviewed_relationship_comparisons"]
    )


def test_master_integrity_and_batch_ownership_not_weakened(tmp_path):
    root, _ = new_run(tmp_path)
    raw = b.load(root / "inputs.json")
    raw["observations"][0]["raw_text"] = "forged"
    (root / "inputs.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="INTEGRITY"):
        b.execute(root, client=FakeClient())


def test_plan_deterministic_and_configurable(tmp_path):
    bundle = inputs(tmp_path)
    first = b.plan(bundle, model="fake", batch_size=2)
    assert first == b.plan(bundle, model="fake", batch_size=2)
    assert all(len(batch) <= 2 for batch in first["batches"])
    assert sorted(o["id"] for batch in first["batches"] for o in batch) == sorted(
        first["aliases"].values()
    )
    assert all(len(o["id"]) < 5 for batch in first["batches"] for o in batch)
    with pytest.raises(ValueError):
        b.plan(bundle, model="fake", batch_size=0)


def test_cli_dry_run_and_staged_replay_without_client_or_input_access(tmp_path, monkeypatch):
    root, _ = new_run(tmp_path)
    assert (
        cli.main(["--input-dir", str(tmp_path / "inputs"), "--dry-run", "--batch-size", "2"]) == 0
    )
    b.execute(root, client=FakeClient())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from feature_dictionary.synthesis_core import staged_cli

    monkeypatch.setattr(staged_cli, "read_outputs", lambda *_: pytest.fail("must use snapshot"))
    output = tmp_path / "offline.json"
    assert cli.main(["--replay-run", str(root), "--output", str(output)]) == 0
    assert Dictionary.model_validate_json(output.read_text())
    assert cli.main(["--replay-run", str(root), "--output", str(output)]) == 2


def test_transitive_merge_conflict_requires_explicit_group_agreement(tmp_path):
    root, _ = new_run(tmp_path, inputs(tmp_path, ["scales", "scales", "scales"]))

    def chain(request, n):
        if request["text"]["format"]["name"] == "synthesis_reconcile":
            result = answer(request)
            result["decisions"] = [
                d for d in result["decisions"] if (d["left"], d["right"]) != ("b1:c0", "b3:c0")
            ]
            return response_for(result)

    with pytest.raises(ValueError, match="INCOMPLETE_EQUIVALENCE_GROUP"):
        b.execute(root, client=FakeClient(chain))


def test_global_cycles_detected_even_when_each_review_job_is_acyclic(tmp_path):
    root, _ = new_run(tmp_path, inputs(tmp_path, ["head", "scales"]))

    def cycle(request, n):
        if request["text"]["format"]["name"] == "synthesis_relationships":
            payload = json.loads(request["input"])
            # Make each one-edge job acyclic; global union must fail.
            left, right = payload["comparisons"][0]
            card = next(c for c in payload["concepts"] if c["ref"] == left)
            return response_for(
                dict(
                    relationships=[
                        dict(
                            subject_ref=left,
                            predicate="part_of",
                            object_ref=right,
                            observation_ids=card["expressions"][0]["observation_ids"],
                            rationale="Synthetic cycle",
                        )
                    ]
                )
            )

    # One term/block ensures the two directions live in separate requests.
    config = b.load(root / "plan.json")
    config["block_size"] = 1
    (root / "plan.json").write_text(json.dumps(config))
    (root / "manifest.json").write_text(
        json.dumps(dict(version=b.VERSION, plan_sha256=b.fingerprint(config)))
    )
    result, validation, _ = b.execute(root, client=FakeClient(cycle))
    assert result is None
    assert "HIERARCHY_CYCLE" in {i["code"] for i in validation["issues"]}


def test_merge_collapsed_relationship_is_not_silently_dropped():
    data = local_candidate(
        dict(
            observations=[
                dict(id="o1", category="term_entry", observed_terms=["scales"]),
                dict(id="o2", category="term_entry", observed_terms=["head"]),
            ]
        )
    )
    data["relationships"] = [
        dict(
            subject_ref="c0",
            object_ref="c1",
            predicate="part_of",
            observation_ids=["o1"],
            rationale="x",
        )
    ]
    proposal = DictionaryProposal.model_validate_json(json.dumps(data))
    decision = b.Decision(
        left="c0", right="c1", action="merge", rationale="x", left_sense=None, right_sense=None
    )
    with pytest.raises(ValueError, match="MERGE_COLLAPSED_EDGE"):
        b.reconcile(proposal, [decision])


def test_review_payload_budget_splits_pairs(tmp_path):
    root, bundle = new_run(tmp_path)
    data = local_candidate(
        dict(
            observations=[
                dict(id=f"o{i}", category="term_entry", observed_terms=[f"term {i}"])
                for i in range(1, 5)
            ]
        )
    )
    proposal = DictionaryProposal.model_validate_json(json.dumps(data))
    inverse = {f"o{i + 1}": o.id for i, o in enumerate(bundle.observations)}
    for term in proposal.terms:
        for e in term.expressions:
            e.observation_ids = [inverse[x] for x in e.observation_ids]
    config = b.load(root / "plan.json")
    config.update(block_size=4, max_input_chars=1100)
    jobs = list(b.bounded_reviews(proposal.terms, bundle, config, lambda s, t: s.ref < t.ref))
    assert len(jobs) > 1
    assert sum(len(pairs) for pairs, _ in jobs) == 6
    assert all(len(json.dumps(payload)) <= 1100 for _, payload in jobs)


def test_cross_batch_different_labels_reconciled_as_synonyms(tmp_path):
    root, _ = new_run(tmp_path, inputs(tmp_path, ["belly", "ventrum"]))

    def synonyms(request, number):
        if request["text"]["format"]["name"] == "synthesis_reconcile":
            left, right = json.loads(request["input"])["comparisons"][0]
            return response_for(
                dict(
                    decisions=[
                        dict(
                            left=left,
                            right=right,
                            action="merge",
                            rationale="Synthetic synonym claim, requires review",
                            left_sense=None,
                            right_sense=None,
                        )
                    ]
                )
            )

    result, validation, summary = b.execute(root, client=FakeClient(synonyms))
    assert validation["valid"]
    assert len(result["terms"]) == 1
    assert {e["text"] for e in result["terms"][0]["expressions"]} == {"belly", "ventrum"}
    assert {e["role"] for e in result["terms"][0]["expressions"]} == {"preferred", "synonym"}
    assert len(set(summary["candidate_to_final_id"].values())) == 1


def test_ambiguous_identical_labels_remain_unresolved_separate_concepts(tmp_path):
    root, _ = new_run(tmp_path, inputs(tmp_path, ["scales", "scales"]))

    def ambiguous(request, number):
        if request["text"]["format"]["name"] == "synthesis_reconcile":
            result = answer(request)
            for d in result["decisions"]:
                d["action"] = "unresolved"
                d["rationale"] = "Insufficient biological context"
            return response_for(result)

    result, validation, _ = b.execute(root, client=FakeClient(ambiguous))
    assert validation["valid"]
    assert len(result["terms"]) == 2
    assert all("Unresolved identity" in t["sense_note"] for t in result["terms"])
    assert len(result["observation_dispositions"]) == 2


@pytest.mark.parametrize("stage", ["reconcile", "relationships"])
def test_incomplete_review_subdivides_and_replays_without_new_requests(tmp_path, stage):
    root, _ = new_run(tmp_path)
    interrupted = []

    def truncate(request, number):
        if request["text"]["format"]["name"] == f"synthesis_{stage}" and not interrupted:
            pairs = json.loads(request["input"])["comparisons"]
            if len(pairs) > 1:
                interrupted.append(True)
                return response_for({}, "incomplete", "max_output_tokens")

    client = FakeClient(truncate)
    result, validation, summary = b.execute(root, client=client)
    assert interrupted and validation["valid"]
    calls = len(client.calls)
    assert b.execute(root, client=client)[0] == result
    assert len(client.calls) == calls
    assert b.execute(root) == (result, validation, summary)


def test_offline_reconstruction_does_not_mutate_run_archive(tmp_path):
    root, _ = new_run(tmp_path)
    b.execute(root, client=FakeClient())
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert b.execute(root)[1]["valid"]
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_local_citations_cannot_escape_owned_batch(tmp_path):
    root, _ = new_run(tmp_path)

    def escaped(request, number):
        if number == 1:
            candidate = answer(request)
            candidate["terms"][0]["expressions"][0]["observation_ids"] = ["o6"]
            return response_for(candidate)

    with pytest.raises(b.JobFailure):
        b.execute(root, client=FakeClient(escaped))
    validation = b.load(next(root.rglob("validation.json")))
    assert "BATCH_OWNERSHIP" in {i["code"] for i in validation["issues"]}


def test_concurrent_live_resume_does_not_issue_duplicate_requests(tmp_path):
    import fcntl

    root, _ = new_run(tmp_path)
    client = FakeClient()
    with (root / "run.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(b.JobFailure, match="RUN_BUSY"):
            b.execute(root, client=client)
    assert not client.calls


def test_saved_success_before_validation_report_is_recovered_without_api(tmp_path):
    root, _ = new_run(tmp_path)
    expected = b.execute(root, client=FakeClient())[0]
    validation = next(root.rglob("validation.json"))
    validation.rename(validation.with_name("earlier_validation.json"))
    client = FakeClient()
    assert b.execute(root, client=client)[0] == expected
    assert not client.calls
    assert validation.exists()


def test_saved_staged_example_reconstructs_exactly_offline():
    from pathlib import Path

    folder = Path(__file__).resolve().parents[1] / "examples/synthesis_batched"
    result, validation, summary = b.execute(folder / "run")
    assert validation["valid"]
    assert result == b.load(folder / "dictionary.json")
    assert validation == b.load(folder / "validation.json")
    # JSON serializes comparison tuples as arrays; normalize before comparison.
    assert json.loads(json.dumps(summary)) == b.load(folder / "run_summary.json")


def test_single_oversized_observation_stops_before_any_api_request(tmp_path):
    bundle = inputs(tmp_path)
    with pytest.raises(ValueError, match="OVERSIZED_OBSERVATION"):
        b.plan(bundle, model="fake", max_input_chars=10)
