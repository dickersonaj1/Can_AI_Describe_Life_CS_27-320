# Version 2 synthesis

Synthesis reads extraction artifacts independently of extraction and clustering. No extraction
code or settings were changed. One model proposes concepts and relationships; Python validates
and assigns final IDs. Model agreement is provenance, never biological verification.

## Commands

Activate the existing virtual environment from the project folder:

```bash
source .venv/bin/activate
```

Inspect a selected batch without an API request or any output writes:

```bash
python -m feature_dictionary.synthesis --input-dir extractor_outputs/test_20261009_191953 --dry-run
```

Generate a new dictionary (multiple paid requests, staged synthesis by default):

```bash
python -m feature_dictionary.synthesis --input-dir extractor_outputs/test_20261009_191953 --output synthesis_outputs/dictionary_v2.json
```

The first OpenAI model in `settings.json` is the default; `--model MODEL_ID` overrides it.
The existing project `.env` supplies the key. The output cap defaults to 6,000 tokens **per job** and can
be changed with `--max-output-tokens`. Automatic SDK retries are disabled.
Use `--single-request` for the legacy one-request path; its editable prompt remains
`prompts/synthesis.txt`. Existing `--replay response.json` and `--candidate` commands
continue to use that legacy archive format.
Inputs are discovered recursively, so selecting `extractor_outputs` includes saved run
subfolders and legacy answers. Select the desired subtree deliberately. Historical answers
already overwritten by extraction cannot be reconstructed.

The legacy `--single-request` path writes this exclusive archive directory:

```text
archives/dictionary_v2_<timestamp>_<unique-suffix>/
    request.json       # Full original input snapshot and exact API request, before calling API
    response.json      # Full returned response, or error/interruption details
    validation.json    # All schema and semantic validation issues, once evaluated
    dictionary.json    # Only present for a valid proposal
```

Archived inputs include exact source bytes in base64, hashes, source metadata, and all parsed
observations. Source byte copies are not sent to the model; observations and metadata are.
Invalid JSON, refusal payloads, incomplete responses, API errors, and interrupts are retained.
An API error or interruption is reported immediately; replay its response archive to generate
its deterministic validation report. An interruption before a response arrives cannot preserve
an unreceived response; the request and available error state are archived.

Replay a response without any API calls, API keys, or current extraction files:

```bash
python -m feature_dictionary.synthesis --replay examples/synthesis_v2/response.json --output synthesis_outputs/offline_example.json
```

For a failed run, inspect its `validation.json` and copy/edit the proposal JSON from
`response.json`'s `output_text` into a separate file. Then validate the correction offline:

```bash
python -m feature_dictionary.synthesis --replay PATH/response.json --candidate PATH/corrected_candidate.json --output synthesis_outputs/corrected_v2.json
```

An edited candidate is a separate archived artifact with an `OFFLINE_EDIT` warning. The original
response is never modified. Offline evaluation uses the stored observations, not today’s files
or prompt. It runs the current validator, so future validator changes can intentionally alter
validation results; schema versions are checked and v1 archives are rejected explicitly.

Existing published output is protected by default. `--overwrite` first saves its exact bytes as
`previous_output.bin` in the new archive. Existing extraction files and older archives are never
modified. Raw response archives are diagnostic artifacts, not validated dictionaries.
Exit codes: 0 success, 1 API/unexpected failure, 2 configuration/validation error, 130 interruption.

## Modules

- `feature_dictionary/synthesis.py`: CLI, archive selection and publication.
- `feature_dictionary/synthesis_core/schema.py`: typed input, candidate and output contracts.
- `feature_dictionary/synthesis_core/ingest.py`: lossless source snapshots and observation parsing.
- `feature_dictionary/synthesis_core/inference.py`: model request archival and offline evaluation.
- `feature_dictionary/synthesis_core/validation.py`: deterministic checks and final ID assignment.
- `feature_dictionary/synthesis_core/batching.py`: deterministic planning, archived jobs,
  cross-batch reconciliation, coverage scheduling, resume and offline reconstruction.
- `feature_dictionary/synthesis_core/staged_cli.py`: staged command orchestration and publication.
- `prompts/synthesis.txt`: editable biological inference instructions.

There is no clustering dependency, extraction invocation, graph database or plugin abstraction.
The selected input folder is the integration boundary with extraction.

## Schema

Machine-readable schemas are in `schemas/feature_dictionary_v2.schema.json` (published output)
and `schemas/synthesis_candidate_v2.schema.json` (model proposal / offline edited candidate).
They are generated from the Pydantic definitions, which are the source of truth. JSON Schema
checks field shapes; the Python validator additionally checks references and cross-record rules.

```text
schema_version: "2.0"
status: "proposed_requires_review"
synthesis_run: model, response_id, prompt_sha256
sources[]: id, output_path, model, extraction_run_id, prompt_fingerprint,
           sha256, raw_bytes_b64, metadata[]
observations[]: id, source_id, line, raw_text, category, observed_terms[],
                synonym_claims[], homonym_claims[]
terms[]: id, kind, characteristic_type, sense_note, scope_note, expressions[], notes
relationships[]: subject_id, predicate, object_id, status, basis,
                 observation_ids[], rationale
observation_dispositions[]: observation_id, status, term_ids[], reason
issues[]: severity, code, path, message
review_notes[]
```

`kind` is `structure`, `characteristic`, `character_state`, or `unresolved`.
A characteristic can have `characteristic_type` `measurement` or `qualitative`; otherwise null.
A character state remains in the same concept registry, connected through `state_of`.

Expressions contain `text`, `role`, nullable `language`, nullable `expansion`, and
`observation_ids`. Roles are `preferred`, `synonym`, `spelling_variant`, `grammatical_variant`,
`acronym`, and `translation`. Every concept has exactly one preferred expression. Original
observed spelling is retained; comparison keys normalize Unicode, case and whitespace only.
An acronym expansion must occur in its cited observations. Translations must also be observed;
no outside terminology is invented. Language and synonym judgments remain model proposals.

Identical labels do not trigger merging. Distinct senses/scopes have separate concept IDs and
`sense_note`/`scope_note`. Shared expressions generate review warnings. Exact duplicate
label/kind/sense/scope combinations are rejected for explicit resolution; Python does not guess
whether they are biologically equivalent. Homonym claims remain in immutable observations.

Read relations as SUBJECT PREDICATE OBJECT:

| Predicate | Allowed endpoints | Example |
| --- | --- | --- |
| `part_of` | structure -> structure | head scales part_of head |
| `subtype_of` | structure -> structure or characteristic -> characteristic | head scales subtype_of scales |
| `describes` | characteristic -> structure | eye diameter describes eye |
| `state_of` | character_state -> characteristic | keeled state_of keeling |

A concept can participate in multiple relationships without duplication. Each containment or
subtype hierarchy is checked separately for cycles. There is no stored universal root list:
root concepts depend on the selected predicate. All relationships have `status: proposed` and
`basis: model_inference`; there is deliberately no AI-generated verified status.

Every observation has exactly one disposition: mapped, excluded, or unresolved. Mapped entries
must retain all observed term/synonym expressions and point to every concept citing them.
Excluded/unresolved entries require reasons and cannot simultaneously be cited by a concept.
This preserves ambiguous and malformed source entries without placeholder concepts.

## Safeguards and limits

Validation collects structured errors instead of stopping at the first one. Checks include
unique IDs, nonempty concepts, one preferred expression, supported terminology and expansions,
known references, complete observation dispositions, consistent evidence/mapping, compatible
relationship endpoints, duplicate edges, self-relations, and cycles. Source bytes are re-parsed
to detect changed observations, metadata, IDs or input warnings in replay archives.

Observation references prove where terminology was claimed, not that the original species
source supports a biological relationship. Source model names and prompt/run identifiers are
preserved separately. Voting across models never upgrades an inference to verification.

Source IDs are content-addressed using the relative path and original bytes; observation IDs
also include the line. Adding unrelated files does not renumber existing records. Final concept
IDs are assigned by Python from the validated concept content, not model handles. They are
reproducible for unchanged content, not permanent IDs across later edits, splits or merges.
Selecting a different input root can change relative paths and thus source IDs.

The legacy inference path is one pass; the default staged path is described below. Truncated
or malformed extraction outputs are preserved and warned about, but missing content cannot be
recovered. The ingestion warning for a missing Homonyms section is a heuristic, not an API stop
reason. No biological ground-truth verification, automatic v1 migration, or cross-run concept
registry has been added.

## Offline example and tests

`examples/synthesis_v2/` contains explicitly synthetic extraction input, candidate, raw-response
fixture, validated dictionary and validation report. No paid API call created this example. It
includes structures, a characteristic, a state, a shared subterm with multiple parents, and an
acronym. The fixture model name is `synthetic-fixture`, not a real extraction model.

```bash
python -m pytest tests/test_synthesis.py
python -m pytest
```

Tests use fake clients, including failed, incomplete and invalid responses. They exercise
immutability, provenance, homonyms, multiple parents, model agreement without verification,
validation coverage, offline corrections, overwrite backups and deterministic replay.


## Staged synthesis and resume

New live runs use staged synthesis by default. The published dictionary remains exactly the
v2 schema above: no downstream consumer must adopt a new term collection. A companion
`dictionary.json.run.json` points to the run archive and a versioned reconstruction summary.
For staged output, `synthesis_run.response_id` is null because several responses contribute;
`prompt_sha256` fingerprints all three stage prompts. Individual response IDs, exact prompts,
request schemas, responses and usage remain in the run archive. The summary maps original
candidate references to final term IDs and records explicit completed comparisons.

1. Freeze `inputs.json` and a deterministic `plan.json`, bound by hashes in `manifest.json`.
2. Synthesize owned observation batches, defaulting to 30 observations. Grouping by normalized
   label improves locality without asserting equivalence. Each observation has exactly one
   owner; the complete source-byte integrity check still runs during batch validation.
3. Compare all same-kind candidate pairs in bounded catalog blocks. Model decisions explicitly
   merge, keep separate, or preserve uncertainty. Omitted pairs mean no merge proposed, not
   biological verification. Different concept kinds cannot be merged. A merged component needs
   explicit pairwise merge agreement, rather than an unchecked transitive chain. Conflicting
   senses/scopes and collapsed relationship edges block assembly instead of disappearing.
4. Review relationships using reconciled concepts. Retain and remap all accepted local edges.
5. Assemble in Python and run the complete existing validator, including global cycle checks.
   Only then assign final term IDs and publish a dictionary.

All stage prompts and schemas are frozen into the plan; staged prompt definitions currently
live in `batching.py`. Resume uses those frozen settings, regardless of later CLI budget or
coverage flags. Start a new run to change the experiment configuration. Future changes to
validators can intentionally change replay acceptance; retain the code revision/environment
with a research experiment. A new API run is not guaranteed to reproduce archived judgments.

```text
run/
  inputs.json                         # Original bytes, sources, immutable observations
  plan.json                           # Batches, aliases, prompts, schemas, settings
  manifest.json                       # Plan fingerprint / planner version
  jobs/<stage>/<request-hash>/attempt_0001/
    request.json                      # Exact API kwargs + input snapshot fingerprint
    response.json                     # Raw returned object/text or error
    validation.json                   # Deterministic acceptance report
  checkpoints/<stage>/<request-hash>.json
  assembly_reports/                   # Global reconciliation errors, if any
  reconstructions/<unique-id>/
    dictionary.json                   # Valid results only
    validation.json
    run_summary.json                  # Coverage, jobs, ID mappings, total archived usage
```

Archive attempts are exclusive and never overwritten. Successful responses are revalidated
and reused without a new request. If a process stopped after saving a response, resume can
finish validation locally. A saved unsuccessful/unknown-outcome request blocks retry by
default; `--retry-failed` explicitly allows another attempt. An unknown outcome may have
already incurred a charge. Incomplete responses with `max_output_tokens` are preserved and
subdivided automatically: observations for local jobs, comparison lists for review jobs.
A single observation/comparison that still exhausts the budget stops with an explicit error.
No incomplete JSON is salvaged as an accepted result.

`--batch-size` defaults to 30. `--batch-input-chars` defaults to 18,000 serialized payload
characters; `--review-block-size` defaults to 12 concepts per catalog block. Review payloads
are further subdivided to fit the character budget. A single oversized observation/comparison
stops rather than silently trimming evidence. This is a payload estimate, not tokenizer-based
context accounting: prompts and JSON schemas add overhead. Output caps apply per request.

Relationship coverage is configurable:

| Mode | Scheduled comparisons | Intended use |
| --- | --- | --- |
| `lightweight` (default) | Type-compatible directed pairs sharing a normalized word in an expression | Development; can miss links with no lexical overlap |
| `comprehensive` | Every type-compatible directed pair of distinct reconciled concepts | Research experiments; more requests and repeated context |

Both modes retain local inferred edges. Concept reconciliation compares every same-kind pair
in both modes, so development mode reduces relationship work but does not skip global synonym
review. Comprehensive comparison cost grows quadratically with the number of concepts.
Completed comparisons are listed by job in `run_summary.json`; total compatible and reviewed
relationship counts are also recorded. Checkpoints and archived request comparison lists retain
partial progress if the run stops before a final summary. Completed coverage means concepts
were presented in a successfully validated review request, not that the model discovered every
possible biological link. Omission never means biological absence; all links remain proposed.

Compact `o1` observation aliases are used only on the wire. The immutable canonical IDs and
source metadata stay in the frozen snapshot and final dictionary; Python expands every accepted
citation. All original terminology stays in observations, even when accepted expressions are
normalized into a shared concept. Model agreement remains provenance rather than verification.

Live execution uses an OS lock on macOS/Linux to prevent concurrent resumes from issuing
duplicate requests; the OS releases it on interruption or process loss. Offline reconstruction
reads raw accepted responses rather than trusting checkpoints or cached dictionaries. It does
not create an API client, read `.env`, or read current extraction outputs. The CLI saves a new
reconstruction report; the underlying evaluation function performs no writes offline.

Costs are the sum of input/output usage across **all** archived attempts, including unsuccessful
and superseded requests. Batching can cost more in successful-request overhead; compact IDs,
local assembly and reuse reduce payload size and failed-run repetition. The dry run reports
local batches without making calls. Later job counts depend on the concepts produced and
cannot be known exactly before local synthesis.

## Try the staged pipeline safely

The small fixture has four synthetic observations in two extraction files. Its archived run
was generated by a fake client, not a paid model. It merges duplicate head-scale concepts and
retains both `head scales part_of head` and `head scales subtype_of scales`.

No-cost planning:

```bash
python -m feature_dictionary.synthesis --input-dir examples/synthesis_batched/inputs --batch-size 2 --relationship-coverage lightweight --dry-run
```

No-cost full staged reconstruction (no API key needed):

```bash
python -m feature_dictionary.synthesis --replay-run examples/synthesis_batched/run --output synthesis_outputs/batched_offline_example.json
```

Small **paid** test, before using the 220-observation dataset:

```bash
python -m feature_dictionary.synthesis --input-dir examples/synthesis_batched/inputs --batch-size 2 --relationship-coverage lightweight --max-output-tokens 6000 --model gpt-5.4-nano --run-dir synthesis_outputs/small_live_run --output synthesis_outputs/small_live_dictionary.json
```

The synthetic archived example uses four successful jobs; a live model can produce a different
number of concepts/jobs or require subdivisions. Inspect the new run's validation and summary.
To resume after stopping, use the same frozen run directory:

```bash
python -m feature_dictionary.synthesis --resume synthesis_outputs/small_live_run --output synthesis_outputs/small_live_dictionary.json
```

Add `--retry-failed` only when you want to permit another paid attempt for an archived failed
or unknown-outcome job. Successful jobs are still reused. If a dictionary was already published,
choose a new output filename or explicitly use `--overwrite`; old output and sidecar bytes
are backed up first. Staged offline corrections are supported through `--correct-job` (below); legacy correction
replay remains available for legacy response archives. Never edit raw archived responses in place.

```bash
python -m pytest tests/test_synthesis.py tests/test_synthesis_batching.py
```


## Offline corrections for individual staged jobs

Use the failed attempt's `response.json` `output_text` as the starting candidate, and save
edits into a separate JSON file. Use local observation aliases and concept refs from that
request, not final dictionary IDs. Keep original extraction observations unchanged. For a
relationship type mismatch, omitting an unsupported edge pending biological review is safer
than changing a concept type merely to satisfy the validator.

Approve and validate a correction entirely offline:

```bash
python -m feature_dictionary.synthesis \
  --correct-job RUN/jobs/local/JOB_HASH/attempt_0001 \
  --candidate corrected_candidate.json \
  --correction-reason "Omit invalid relationship claims pending biological review" \
  --approve-correction
```

`--correct-job` takes an **attempt directory**, not its response file. The run root is inferred
from that directory. This is a standalone command; do not combine it with `--resume`,
`--replay-run`, `--dry-run` or `--retry-failed`. It never creates an API client. It reconstructs
preceding accepted jobs offline to reach the selected job's existing validator, applies exactly
that validator (including batch ownership and all original integrity safeguards), then stops.
If an earlier job is still blocked, correct it first. The same command supports local,
reconciliation and relationship-review jobs, including deterministically subdivided jobs.

The reason must be nonempty, and `--approve-correction` explicitly records the user's manual
approval. Validation determines acceptance: an approved but invalid candidate is **rejected**,
saved for diagnosis, and never reused. Return code 0 means accepted; 2 means rejected or a
configuration error. No published dictionary is written by the correction command.

Each artifact is exclusively created as:

```text
RUN/jobs/STAGE/JOB_HASH/corrections/<content-hash>.json
    version: job-correction-1
    binding: attempt path, original request byte hash, original response byte hash,
             master input fingerprint, frozen plan fingerprint
    candidate_text, candidate_sha256
    reason, manually_approved: true
    accepted: true | false
    validation: structured deterministic report
```

Original request, response, failed validation report and extraction observations are never
rewritten. Exact candidate text is stored, including malformed JSON when rejected. Artifacts
have content-addressed names and exclusive creation; changes are detected during reuse.
These checks establish archive integrity, not a cryptographic identity for the person approving.
One accepted correction per job is supported. Repeating identical approval is idempotent;
conflicting approvals stop explicitly. Superseding an accepted edit is intentionally outside
this small workflow; retain it and start a separately tracked experiment if needed.

After acceptance, use the normal resume command:

```bash
python -m feature_dictionary.synthesis --resume RUN --output synthesis_outputs/resumed.json
```

The corrected job and earlier successful jobs do not make additional requests. Remaining
unfinished jobs can incur charges. Do not add `--retry-failed` for an accepted correction.
If later jobs already exist and their input context changed, their fingerprints change, so
new inference may be required for those dependent jobs; unrelated matching jobs remain reusable.

For a run with all remaining responses archived, reconstruct entirely offline:

```bash
python -m feature_dictionary.synthesis --replay-run RUN --output synthesis_outputs/replayed.json
```

An incomplete run stops at the next missing job during offline replay; it never requests it.
Every accepted edit is checked against the original request/response/input/plan hashes and
revalidated on every resume/replay. Invalidated or mismatched edits block progress even if
`--retry-failed` is present, rather than silently requesting another paid response.

The final dictionary and validation report include `OFFLINE_EDIT` warnings. The run summary
contains a `corrections` collection with artifact IDs/paths, reasons, explicit manual approval,
original request/response bindings and candidate hashes. Existing v2 dictionary fields are
unchanged. A correction remains a manual editorial decision; biological relationships still
have `status: proposed` and `basis: model_inference`. Manual approval does not verify biology.

```bash
python -m pytest tests/test_synthesis_corrections.py
```
