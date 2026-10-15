# Provisional modular synthesis contract

This milestone defines how extracted vocabulary can be proposed and organized.
The proposal runner can freeze accepted extraction outputs and request independent
model proposals. It does not merge concepts, assign final term identifiers, or
compile a dictionary. The existing v2 synthesis commands,
experiments, and replay paths remain independent and unchanged.

An extraction observation is a vocabulary claim with its exact quotations and
possible source locations. A synthesis proposal suggests how those observations
might fit together. An inventory is the resulting organizational record. Passing
software validation establishes consistency and textual support, not scientific
verification. Even an inventory's proposed classification can need human review.

## Four separate artifacts

| Artifact | Version | Purpose |
| --- | --- | --- |
| Inputs | `synthesis-input-1.0` | Complete accepted extraction-3.1 document snapshots, raw answer strings, and observation references |
| Model proposal | `synthesis-proposal-1.0` | One independent model's local references, proposed classifications/links, rationales, dispositions, and pending equivalence suggestions |
| Inventory | `synthesis-1.0` | Three collections referencing supporting observation IDs |
| Audit sidecar | `synthesis-review-1.0` | Disposition of every observation, preserved proposals, model-reference-to-final-ID origins, and review notes |

The fixture files in `tests/fixtures/synthesis_v1/` demonstrate all four. They are
synthetic offline examples, not historical experiments or biologically verified
results. Their labels and provenance identify them as fixtures. Original-file
archive paths are illustrative references; the contract validator does not read
them or claim the referenced files are present.

The input keeps each complete extraction evidence document, including exact
source text, quotations, all location candidates, annotation suggestions,
extractor/provider identity, extraction run identity, and prompt fingerprints.
Each observation ID refers to a source snapshot and its zero-based entry index.
Every extraction entry must have exactly one such reference. Nothing is dropped
because synthesis cannot classify it. Raw source text and archived answer strings
are not normalized or rewritten.

The audit sidecar gives each observation exactly one disposition: mapped,
excluded, or unresolved. Mapped observations list all inventory records citing
them. Excluded or unresolved observations require reasons, cannot support an
inventory record at this stage, and retain their complete evidence in the input.
A standalone descriptor that fits none of the three collections can remain
unresolved rather than being forced into an anatomical noun entry.

## The three collections

- `anatomical_nouns`: proposed independent anatomical entries, with reciprocal
  `compound_ids` links.
- `compound_terms`: meaningful observed expressions, with one or more `parent_ids`
  and zero or more reusable `subterm_ids`.
- `subterms`: supporting modifiers, descriptors, or nouns, including standalone
  morphological descriptors without a compound. They are not automatically independent dictionary entries.

A record includes its exact `text`, `observation_ids`, and `review_status`.
Subterm types are `morphological_descriptor`, `anatomical_modifier`,
`supporting_noun`, or `unresolved`. A compound also has `relationship_status` and
an optional `relationship_note`. Multiple parents require a justification note.
These parent links are proposed organizational anchors, not assertions of
biological part-of or subtype relationships. Their precise interpretation needs
agreement before model integration.

The current milestone conservatively requires record text to equal at least one
cited extracted expression. It does not synthesize a canonical spelling, normalize
case, invent terminology, or create synonyms. Multiple records may share text:
identical labels can represent different senses. Validation reports a warning
for review and never merges them. Equivalence suggestions stay explicitly
`pending_review` within preserved model proposals.

`reviewed` requires a note and describes human review of that classification or
link; it is not biological verification. This initial contract does not implement
a reviewer-authentication or approval workflow.

## Deterministic validation

The validators check the original v3.1 quotations, locations, and supplied-text
hash using the existing extraction validator. They reject unsuccessful extraction
completion, modified evidence, missing/duplicate observation references,
duplicate IDs, unknown references, wrong collection targets, unsupported record
wording, missing compound parents, and inconsistent reciprocal
links or dispositions. They check proposal-origin references without turning
proposals into final inventories.

Canonical SHA-256 fingerprints bind proposals/inventories to the exact input
snapshot, and the sidecar to its exact inventory. A fingerprint is a repeatable
content identifier, not proof of authenticity. Encoding is UTF-8 JSON with sorted
keys, compact separators, and unescaped Unicode; list order remains significant.
The validator returns the existing `Issue` structure: severity, code, path, message.
Malformed artifact shapes are rejected by Pydantic before these semantic checks.

Input evidence validation cannot authenticate extractor identities or confirm the
original input-file bytes from paths alone. A later ingestion step must check
those archive files and provenance. Preserved location ambiguities remain warnings.
These checks do not evaluate whether a biological classification or relationship
is justified. A model proposal can pass every check and still need scientific review.

## Developer references

- `feature_dictionary/synthesis_core/inventory_schema.py`: strict, versioned
  contracts; reuses the historical `FrozenModel` base without changing it.
- `feature_dictionary/synthesis_core/inventory_validation.py`:
  `validate_inputs`, `validate_inventory_proposal`, `validate_inventory`, and
  `artifact_sha256`. These functions perform no filesystem or network operations.
- `schemas/synthesis_{input,proposal,inventory,review}_v1.schema.json`: exported
  schemas, checked against the Python contracts by offline tests.
- `tests/test_synthesis_inventory_v1.py`: fixture round trips and deterministic
  failures, multi-parent/shared-subterm support, and preservation of shared labels.

Load JSON artifacts using each contract's `model_validate_json()` method; JSON
arrays become tuples in the frozen record containers. Then validate the inventory
with its input and sidecar together:

```python
issues = validate_inventory(inventory, inputs, review)
valid = not any(issue.severity == "error" for issue in issues)
```

Freezing the synthesis containers prevents attribute reassignment; it is not deep
immutability of the nested existing extraction document classes. Integrity is
rechecked from raw answers and bindings at validation time. Consumers should
preserve snapshots rather than mutate those nested objects.

## Decisions before integration

The collection boundary needs biological review: an anatomical shorthand such as
`anal` may function differently from a conventional noun, and a structure such as
`spine` can be both an independent entry and a supporting noun. Decide how such
roles and homonyms should coexist, without losing observations.

Anatomical parents are organizational anchors for dictionary presentation, not
containment relationships. Standalone descriptors now fit the subterm collection;
other unresolved classifications remain explicit dispositions.
The reciprocal noun/compound lists duplicate information, but follow the requested
example and are checked for exact consistency.

Model references and final IDs are separate fields and namespaces in the example.
The deterministic final-ID algorithm is intentionally deferred to the compiler
milestone; this module neither assigns IDs nor requires model references to become
final IDs. Decide ID stability across spelling changes, reviewed senses, and
reordered inputs before implementing it.

No definitions, species classifications, frequency counts, biological facts,
reconciliation, or automatic semantic merging are introduced.

## Independent model proposal runner

`python -m feature_dictionary.modular_synthesis` is a separate entry point.
The extraction CLI and historical `feature_dictionary.synthesis` commands are
unchanged. Synthesis model selection is explicit and independent of the models
that created the source observations. It reuses `settings.json` aliases and the
existing provider/model resolver, rather than introducing another registry.

Start with a no-cost preview of the synthetic input fixture:

```bash
python -m feature_dictionary.modular_synthesis \
  --inputs tests/fixtures/synthesis_v1/inputs.json \
  --models qwen,deepseek,llama,gpt,claude,gemini \
  --num-ctx 32768 --max-output-tokens 8192 \
  --run-dir synthesis_outputs/modular_preview_01 --dry-run
```

A dry run validates inputs, resolves identities, prepares schemas, and checks the
Ollama context estimate. It creates no directories and contacts no providers,
including model-list/version endpoints. It does not require cloud credentials.
Use fresh run directories: the runner refuses existing directories.

To prepare real accepted v3.1 documents, replace `--inputs` with one or more
`--extraction-output` arguments. Each can name a published evidence JSON document
or a directory containing accepted evidence documents:

```bash
python -m feature_dictionary.modular_synthesis \
  --extraction-output PATH_TO_ACCEPTED_EXTRACTION_DIRECTORY \
  --models gpt,claude,gemini --max-output-tokens 8192 \
  --run-dir synthesis_outputs/modular_real_01 --dry-run
```

Remove `--dry-run` only when ready to execute models. There have been no live
model requests during implementation. Explicit `provider:model`, legacy
`provider=model`, configured native IDs, and aliases use the existing resolver.
Unknown, duplicate, or ambiguous selections fail before requests. Cloud
credentials are checked by environment-variable name; their values are never
written to configuration archives.

Extraction-directory ingestion requires matching published v3.1 evidence, raw
response, and accepted validation artifacts. It verifies evidence and metadata,
the archived original input bytes, their relationship to supplied text, and the
archived rendered prompt when recorded. Rejected runs are not salvaged. Full
original artifact bytes are retained in `source_archives.json` as base64, alongside
frozen `inputs.json`. Base64 is an encoding for preserving bytes, not encryption.
A prebuilt `--inputs` file is validated and copied as a snapshot; this path cannot
authenticate original files referenced elsewhere. Treat it as a trusted prepared
bundle. No word-based deduplication is performed.

All selected models receive the same prompt and input snapshot, without seeing
other synthesis proposals. Per-model native schemas bind the host-assigned
proposal identity, provider/model, input fingerprint, and prompt fingerprint.
These are proposal identities, not final term IDs. The prompt is separately
versioned at `prompts/synthesis_inventory_v1.txt`.

The implementation calls existing provider adapters. Optional schema/capture
arguments were added without changing their extraction defaults. Native output
constraints use Ollama `format`, OpenAI `text.format`, Anthropic
`output_config.format`, and Gemini JSON MIME type plus `response_json_schema`.
OpenAI requires all schema object fields to be present; nullable values and empty
arrays represent unused optional fields. Anthropic's SDK transforms unsupported
constraints into descriptions; unchanged Python validation remains authoritative.
The exact transmitted schema and hash are recorded per job. Support for a newly
selected model or account may still fail at the provider; no unconstrained fallback
or model substitution is performed.

The first runner is sequential and nonstreaming across all providers. Each job
archives its request/configuration, full returned SDK envelope before text
validation, exact answer/reasoning strings, completion state, timing/token metrics,
and validation report. SDK versions are recorded. Available Ollama model/server
metadata is also captured. Raw SDK usage metadata retains counters that the shared
metrics interface may not expose, such as provider-specific reasoning usage.
The runner adds no application retries; OpenAI/Anthropic SDK retries are disabled
for this new entry point. Google SDK retry defaults are not overridden. There is
no resume implementation or automatic reuse across separate run directories yet.

`proposal.json` is written only for a completed, structurally consistent proposal.
It remains a model proposal, never a final inventory. `validation.json` separately
reports JSON parsing, contract shape, reference/input consistency, and completion
eligibility. `scientifically_verified` is always false. Raw failures, refusals,
invalid JSON, invalid references, and interrupted jobs remain archived. Ordinary
job failures allow other independent jobs to proceed; an interruption stops the
run before the next model. Requests interrupted before receiving a provider
response cannot preserve content the provider never returned.

Revalidate a saved job offline without changing its files or making a request:

```bash
python -m feature_dictionary.modular_synthesis \
  --replay-job synthesis_outputs/modular_real_01/job_000
```

The input snapshot remains at the run root; preserve the entire run directory for
replay. There is no final compiler, deterministic final term-ID assignment,
reconciliation, biological approval workflow, batching, or definitions stage.
Large inputs may exceed a model's context or output budget; the Ollama estimate
blocks known overruns, while cloud providers report their own limits. Larger local
context settings can require more memory. Thinking mode is independent of JSON
constraints: use `--ollama-think true|false|default` for the selected local group,
or separate runs for models needing different settings. Omitted thinking follows
configuration; `default` omits the request field. DeepSeek's previous behavior
still warrants a separate smoke test.

## Experimental prompt v1.1 and source-grounded context

The first live Claude fixture proposal placed a subterm link on an anatomical
noun and introduced unsupported fin-related interpretations. The original
`prompts/synthesis_inventory_v1.txt` and its default selection are unchanged.
Select the new `prompts/synthesis_inventory_v1_1.txt` with `--prompt-file`.

The revised prompt explicitly reserves `parent_refs` and `subterm_refs` for
compound records. Anatomical nouns and subterms must leave both arrays empty.
The existing validator still rejects violations; the runner performs no repair.
Rationales should briefly explain observed wording and organizational decisions,
not define organs, infer morphology, or expand ambiguous shorthand. Missing
organism context is a reason to retain uncertainty, not assume an anatomical sense.

`SynthesisInputs` now permits optional `source_context`. Each quote specifies
`source_id`, `quoted_text`, `start`, and `end`. Positions are zero-based Python
Unicode character offsets with the end excluded. Each quote must match the exact
range in that source's preserved `document.input.supplied_text`. Unknown sources,
wrong case, incorrect ranges, invented wording, and duplicate context records
are rejected. These checks establish quotation grounding, not taxonomic truth.

The current extraction document contract has no dedicated organism/taxonomy
metadata field. The runner therefore does not guess one from filenames, model
identities, or anatomical vocabulary. When an organism label already occurs in
preserved source wording (for example an explicit specimen header), quote that
label as context. Metadata outside the preserved source text is not imported as
an unchecked taxonomic assertion. Supporting an authoritative external metadata
field would require a separate provenance design; it is not added in this milestone.
Context applies only to its source document, not every input source or every term.

Context can be embedded in a prepared input bundle or supplied using
`--context-file FILE.json`, containing an array such as:

```json
[
  {
    "source_id": "src1",
    "quoted_text": "Acanthophis antarcticus",
    "start": 10,
    "end": 32
  }
]
```

Those example positions refer only to the new synthetic contextual fixture's
source header. They are invalid for the original context-free fixture. Attaching
context leaves all existing observation IDs, source quotations, locations, and
provenance unchanged. The added context becomes part of frozen `inputs.json`,
the shared model prompt, and the input fingerprint. It is revalidated during
replay, without consulting the original context file. Repeated context records
are rejected rather than silently merged.

Empty context is omitted during serialization to preserve historical input
fingerprints and prompt bytes. Existing v1.0 bundles, archived proposals, and
fixture artifacts remain usable. `tests/fixtures/synthesis_v1/contextual_inputs.json`
is a separate synthetic example with an explicit organism header and recomputed
locations; it does not alter the original eight-observation fixture. The adjacent
`source_context.json` demonstrates the external context-file format; do not append
it to a bundle that already contains the same context.

Preview the new prompt on the original, context-free eight-observation fixture:

```bash
python -m feature_dictionary.modular_synthesis \
  --inputs tests/fixtures/synthesis_v1/inputs.json \
  --prompt-file prompts/synthesis_inventory_v1_1.txt \
  --models claude --max-output-tokens 8192 \
  --run-dir synthesis_outputs/claude_synthesis_v11_preview_01 --dry-run
```

A subsequent live test (not executed during development):

```bash
python -m feature_dictionary.modular_synthesis \
  --inputs tests/fixtures/synthesis_v1/inputs.json \
  --prompt-file prompts/synthesis_inventory_v1_1.txt \
  --models claude --max-output-tokens 8192 \
  --run-dir synthesis_outputs/claude_synthesis_v11_test_01
```

To test explicit organism context instead, use `contextual_inputs.json` and a
fresh run directory. Both cases remain independent model proposals requiring
review. The compiler and final-ID assignment remain unimplemented.
