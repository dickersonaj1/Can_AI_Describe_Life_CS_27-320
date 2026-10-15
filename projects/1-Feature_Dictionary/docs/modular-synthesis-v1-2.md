# Modular synthesis v1.2: anatomical index and proposal audit

V1.2 changes what the model proposes. It does not compile a dictionary, assign
stable term IDs, reconcile meanings, or scientifically verify a classification.
Earlier prompts, contracts, experiments, and the default v1.0 runner remain usable.
Select the new contract explicitly with `--proposal-version 1.2`; that selects
`prompts/synthesis_inventory_v1_2.txt` unless `--prompt-file` is supplied.

## Indexed concepts and local descriptions

The new proposal has one `terms` collection. A record is either a `primary`
(independent anatomical structure or region) or a `compound` (a distinct
anatomical structure/region named by several words). Each has a temporary `ref`,
exact observed `text`, supporting `observation_ids`, classification `rationale`,
`primary_refs`, and an `expressions` array. Primaries leave `primary_refs` empty.
Compounds cite one or more associated primaries; these are dictionary display
anchors, not anatomical containment assertions. No reverse link list is stored.

For example, `tail tip` may be an indexed compound associated with `tail`.
`tail spine` can be stored once and associated with both `tail` and `spine` if
those independent terms and associations are justified. Every word need not be
an indexed primary. Displaying one compound beneath two primaries does not create
two compound records.

`anal entire` is a contextual expression under `anal`, rather than a separate
indexed anatomical structure. A hypothetical `curved tail tip` would be local to
`tail tip`, but is never generated without actual extracted wording. Expressions
contain only text, observation IDs, and a concise attachment rationale. They have
no IDs, no global subterm inventory, and no cross-record subterm links. Reusing a
modifier in several local expressions does not imply global semantic identity.
An indexed term may have no local expressions.

The classification depends on anatomical meaning in source context, not word
count or a noun/adjective rule. `Total length` is a property, and a coloration
pattern does not automatically name an anatomical structure. Unsupported or
ambiguous classifications and attachments remain unresolved. Standalone
properties without a confident anatomical attachment remain auditable unresolved
observations in this version; they are not forced into an indexed term.

All observed text, case variants, source locations, and observation IDs are
preserved. Indexed labels and expressions must exactly match cited extraction
expressions. Equivalence proposals remain separate, nonauthoritative, and
`pending_review`. They reference temporary indexed term refs using the existing
`record_refs` field. There is no canonical renaming feature or automatic merge.

Every observation needs one mapped/excluded/unresolved disposition. A mapped
observation lists every indexed term citing it directly or through an expression.
Excluded and unresolved decisions require reasons and cannot be cited by a term.
Missing decisions fail validation and appear as unresolved in the audit report;
the renderer does not change the raw proposal or manufacture an accepted decision.

## Offline audit reports

Every new v1.2 job gets `report.md`, including invalid or incomplete jobs when a
response archive is available. It is clearly labeled an **unvalidated model
proposal, not a compiled dictionary**, even when software checks pass.

The report sorts primaries and associated compounds alphabetically for display,
without changing observed text. It shows local expressions, evidence IDs, compact
extracted phrases and observation IDs, concise rationales, and validation
markers. Detailed source phrases, all location candidates, and extractor/run
provenance appear once in a separate evidence section. Ambiguous locations retain
visible warning indicators in the main hierarchy. Shared compounds may appear beneath several primaries but
are stored and counted once. Separate sections retain orphan compounds, malformed
records, exclusions, unresolved/missing decisions, review notes, metadata, counts,
and validation issues. Counts describe audit records, not species frequencies.
The complete raw-proposal appendix is optional and omitted by default. Add
`--include-raw-json` to an offline `--render-report` command to include it. Invalid
records and validation issues remain visible without the appendix; full raw data
still resides in the immutable response archive. Shared compounds are explicitly
labeled as stored once and displayed under several primaries. Ordinary punctuation
is left readable while untrusted HTML, links, and inline markup remain escaped.

Reports can also be rendered from a saved job without a provider call:

```bash
python -m feature_dictionary.modular_synthesis \
  --render-report tests/fixtures/synthesis_v12_run/job_000 \
  --report-output /tmp/synthesis_v12_review_01.md
```

To include raw JSON, add `--include-raw-json` and choose another new destination.
This option applies to offline report rendering; automatic new-job reports use
the concise default.

The destination must be new and outside the saved run. Repeated renders require
another destination; existing files are never overwritten. The report uses the
archived frozen inputs, original response, and saved validation report. Rendering
is not model execution, compilation, or a new scientific assessment. Historical
v1.0/v1.1 proposals are not silently reinterpreted as v1.2.

The repository includes a rendered synthetic example at
`examples/synthesis_v12_sample.md`. The synthetic job fixture uses invented
example source text for contract testing; it is not a historical research result.

## Commands

Offline tests and formatting checks:

```bash
python -m pytest
ruff check .
ruff format --check .
```

Dry-run the two accepted Gemini and Qwen extraction archives with Claude selected
independently as the synthesis model:

```bash
python -m feature_dictionary.modular_synthesis \
  --proposal-version 1.2 \
  --extraction-output extractor_outputs/v314_gemini_8192_01 \
  --extraction-output extractor_outputs/v314_qwen_ctx16384_01 \
  --models claude --max-output-tokens 16384 \
  --run-dir synthesis_outputs/acanthophis_v12_preview_01 --dry-run
```

These archives contain 130 observations in total. A dry run validates and freezes
them in memory and previews the request; it creates no run directory and contacts
no provider. Original extraction and archived source bytes remain unchanged.

Only after separate approval, run ONE Claude proposal using a fresh directory:

```bash
python -m feature_dictionary.modular_synthesis \
  --proposal-version 1.2 \
  --extraction-output extractor_outputs/v314_gemini_8192_01 \
  --extraction-output extractor_outputs/v314_qwen_ctx16384_01 \
  --models claude --max-output-tokens 16384 \
  --run-dir synthesis_outputs/acanthophis_v12_claude_01
```

This live command was not executed during implementation. A larger output budget
does not guarantee completion. Existing native provider adapters, archiving,
exclusive run-directory reservation, source-context handling, and offline replay
are reused. No provider runner, extraction prompt, or historical archive changed.

## Developer map and remaining uncertainty

- `inventory_v12.py`: independent strict proposal contract and evidence/reference
  validator, reusing the v1 input snapshots and issue types.
- `inventory_report.py`: deterministic renderer and exclusive new-file writer.
- `inventory_execution.py`: explicit contract selection, native request schema,
  v1.2 evaluation, and automatic reports; old archived requests still select v1.0.
- `modular_synthesis.py`: `--proposal-version`, `--render-report`, `--report-output`.
- `schemas/synthesis_proposal_v1_2.schema.json`: exported v1.2 proposal schema.
- `tests/test_synthesis_v12.py` and `tests/fixtures/synthesis_v12_run/`: offline
  semantic organization fixtures, provider mocks, and report regressions.

Deterministic checks establish exact evidence support, references, ownership,
and observation accounting. They cannot establish whether an expression names a
separate anatomical concept or whether a proposed attachment is biologically
correct. Those judgments remain model proposals requiring scientific review.
The renderer keeps duplicate or otherwise invalid records visible rather than
merging or repairing them. The input fixture and real runs remain immutable.
Compiler design, stable IDs, batching/resume, definitions, and biological
reconciliation remain outside this milestone.


## Optional short evidence references

Add `--observation-refs short` to a new `--proposal-version 1.2` run to show
observations as `O001`, `O002`, and so on. These labels follow the frozen input
array order, including separate observations with identical wording. They are
local to that run, not permanent term identifiers. Reordering or changing the
frozen input creates a different mapping. The default remains original IDs.

Short mode selects `prompts/synthesis_inventory_v1_2_1.txt` unless an explicit
prompt override is supplied. The earlier v1.2 prompt remains unchanged. Every
model receives the same view, with each short ID immediately beside its exact
extracted wording. References must support that exact expression; related wording
cannot stand in for missing evidence. Short IDs reduce copying complexity but do
not establish biological correctness or fix wrong evidence assignments.

The immutable run stores `inputs.json` unchanged, `observation_refs.json` (version
`observation-refs-1.0`), and `model_input.json`. The mapping records the original
input fingerprint and a fingerprint of its own contents. Fingerprints are SHA-256
checksums of canonical JSON (sorted object keys, compact separators, Unicode UTF-8;
array order is retained). They detect changes, not authorship. The mapping checksum
excludes its own `mapping_sha256` field.

Each request also records the mapping, view, mode, schema, and prompt fingerprint.
Raw provider envelopes and `response.json` are preserved unchanged. For a
schema-valid response with known aliases, `proposal_expanded.json` substitutes
original observation IDs only in evidence and disposition fields. A separate
`proposal_expansion.json` binds this derivation to the response text and mapping
checksums. Expansion is archived even if strict evidence validation subsequently
fails. `proposal.json` is still written only when all existing checks pass.
Unknown aliases, original hashes mixed into short mode, and incorrect capitalization
are rejected. A valid alias citing the wrong wording still fails evidence checking.

Replay verifies the archived mapping and input view, then regenerates the expansion
from the original response without contacting a provider or trusting saved derived
outputs. Use `--replay-job RUN/job_000` as before. Offline Markdown reports use the
expanded evidence references; their optional raw appendix retains the model's short
references. Neither replay nor reporting changes the archived run.

Example no-cost preparation (choose a fresh run directory):

```sh
python -m feature_dictionary.modular_synthesis \
  --proposal-version 1.2 --observation-refs short \
  --extraction-output extractor_outputs/v314_gemini_8192_01 \
  --extraction-output extractor_outputs/v314_qwen_ctx16384_01 \
  --models claude --max-output-tokens 16384 \
  --run-dir synthesis_outputs/acanthophis_v12_short_01 --dry-run
```
