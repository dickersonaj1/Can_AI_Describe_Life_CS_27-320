# Extraction v3: evidence contracts, pipeline integration, and v3.1

This page describes the first two implementation stages. V3 records candidate biological
terminology and its exact wording in a supplied text. It does not decide what the
terminology means biologically or how concepts are related.

V3 is available through an explicit extraction-format option. V2 Markdown remains
the default. All six model selections use their existing runners, with shared
evidence checking and output writing. Synthesis ingestion is still a separate,
unimplemented third stage. Historical Markdown outputs and synthesis archives
remain unchanged.

## What vocabulary is in scope?

Candidates may include structures, positional terms, compound expressions,
characteristics, character states, shorthand, abbreviations, acronyms, historical
expressions, spelling variants, and terminology in any language. Candidates are
not restricted to nouns or English grammar.

For example, `scales`, `dorsal`, `dorsals`, `dorsal scales`, `keeling`, and `keeled`
can all be candidates when those exact expressions occur. Shorter expressions
embedded in a longer expression can have their own evidence records.

Extraction must not generate missing expansions, translations, parent terms, or
biological relationships. If both `MBSR` and `midbody scale rows` occur, preserve
both expressions separately. Their equivalence remains a synthesis question.

Entire comparative statements should not become vocabulary entries. However,
checking exact quotations cannot establish whether a phrase is suitable
terminology. A grounded clause can pass these checks while remaining a poor
extraction. That requires separate prompt instructions and biological review.

## Two records with different responsibilities

The default **model candidate** contains `format_version: "extraction-3.1"` and `entries`.
Each entry contains:

| Field | Meaning |
| --- | --- |
| `matched_text` | Exact quotation supporting the vocabulary candidate |
| `source_phrase` | Exact contiguous expression containing that quotation |
| `proposed_annotations` | Optional, unverified language and form suggestions |

The **program-derived document** adds input and run metadata. Python derives
`term` from exact `matched_text` and `evidence_type` from whether the match occupies
the entire quoted phrase (`complete`) or part of it (`embedded`). Only grounded
records from successfully completed responses are published as accepted documents.
Invalid records remain in validation reports for review; a derived lexical label
does not make an unsupported quotation valid.

V3.1 retains the saved `model_term` key with value `null`: no separate model label
was requested. This avoids inventing a claim about an independently supplied name.
The raw response is retained exactly. The accepted document identifies itself as
`extraction-3.1`; all other evidence fields retain their existing meanings.

Historical v3.0 still requires model-generated `term` and `evidence_type`. Its
original label is retained in `model_term`, and incorrect evidence types still
produce errors. Its published schemas and archived responses are unchanged.

Input metadata includes the original path, original-file fingerprint and archive
reference, exact supplied text and its fingerprint, and whether input was truncated.
A fingerprint, or hash, helps detect changed content. Original file bytes and the
text supplied to a model need not be identical, so both identities are recorded.

Run metadata includes the provider, model, run ID, prompt version and fingerprints,
and provider completion status and reason. The program, not the model, supplies
these fields.

## Exact quotations and possible locations

Python finds exact occurrences of the source phrase, then finds the matched text
inside each occurrence. It retains every possible pair of positions:

| Location status | Meaning |
| --- | --- |
| `resolved` | Exactly one pair of positions matches |
| `ambiguous` | Multiple pairs match; all are retained for review |
| `unmatched` | No pair matches; evidence checking fails and the candidate remains in the report |

An ambiguous claim does not prove that the model independently identified every
occurrence. Repeating the same quotation claim does not disambiguate it. Duplicate
claims are reported as errors; overlapping but different vocabulary is allowed.

Positions count Unicode code points, using Python string indexing. They begin at
zero and exclude the final position. They are not byte offsets or counts of visible
letters: a visible letter can contain more than one code point.

No case folding, accent removal, punctuation substitution, newline conversion, or
Unicode normalization is performed. Visually identical but differently encoded
quotations may therefore fail exact matching. No English-only boundary rules are
used to reject multilingual expressions.

### Corrected multilingual example

In `praeocular; préoculaire`, `praeocular` occupies `[0, 10)` and `préoculaire`
occupies **`[12, 23)`**. The latter corrects the earlier design example's offset.

```json
{
  "format_version": "extraction-3.1",
  "entries": [
    {
      "matched_text": "préoculaire",
      "source_phrase": "préoculaire",
      "proposed_annotations": {"language": "fr", "forms": []}
    }
  ]
}
```

For `anterior dorsal scales`, matches include `anterior` at `[0, 8)`, `dorsal`
at `[9, 15)`, `scales` at `[16, 22)`, `dorsal scales` at `[9, 22)`, and the entire
expression at `[0, 22)`. The shared source phrase has span `[0, 22)`. Only the
entire-expression entry is `complete` relative to that phrase.

For `Scales keeled. Scales keeled.`, a quotation of `keeled` alone produces two
possible match spans: `[7, 13)` and `[22, 28)`. Neither is automatically selected.

## Suggestions are not verified facts

Optional annotations conventionally have `language` (a proposed language tag or
null) and `forms` (a list). Recognized forms are `abbreviation`, `acronym`,
`shorthand`, `historical_expression`, and `spelling_variant`.

Annotation correctness is not a condition of textual grounding. Malformed or
unknown suggestions are retained with warnings. A plausible-looking but incorrect
language tag cannot be identified reliably by deterministic text matching. No
annotation is used to invent an expansion, translation, or relationship.

In historical v3.0, if a model labels an exact quotation of `colouration` as `coloration`, the derived
entry uses `term: "colouration"`, retains `model_term: "coloration"`, and records
`MODEL_LABEL_DIFFERS_FROM_QUOTE`. If the model also quotes `coloration`, which is
absent, the evidence fails. There is no spelling repair of quotations.

V3.1 removes that redundant label from the candidate entirely. A quotation of
`coloration` still fails if only `colouration` occurs. No spelling repair, Unicode
normalization, or case correction has been introduced.

## Evidence validity and completion are separate

A report's `evidence_valid` property means that its deterministic checks found no
errors. It may still contain ambiguity or annotation warnings. It does not prove
biological accuracy, extraction completeness, or a successfully completed model
request. A syntactically complete answer from an incomplete provider response must
still retain its incomplete provider status.

Malformed JSON, duplicate JSON keys, nonfinite numbers, unsupported versions,
unexpected entry fields, unmatched quotations, duplicate claims, and contradictory
evidence types produce errors. Invalid JSON is not repaired or partially accepted.
Its original response remains available in the report. Structurally invalid
candidate documents produce field paths and errors, rather than accepted entries.
Contradictory model evidence types remain a v3.0 error; v3.1 does not request that
field and rejects it as an unexpected field if the model supplies it.

## Using v3 with a local model

The new option is `--extraction-format v3`. Omitting it keeps v2 Markdown behavior.
For example, from the project folder with the virtual environment activated:

```sh
python extractor.py --extraction-format v3 --models qwen3:8b --input "Test Data/short.txt" --output-dir extractor_outputs/v3_ollama_smoke --log-dir extractor_logs/v3_ollama_smoke --dry-run
```

This preview makes no provider requests and writes no experiment files. To run
the local model, start Ollama, ensure that the selected model is installed, and
remove `--dry-run`. Replace the model identifier with an installed Qwen, DeepSeek,
or Llama identifier as needed. Use fresh output directories for each experiment;
existing artifacts cause an error rather than being overwritten.

The example input is almost 10,000 bytes, so a much smaller, manually prepared
text is preferable for a first smoke test. The configured output-token limit
may be too small for comprehensive v3 extraction. Adjust it
explicitly in a separate experimental settings file if needed; this implementation
does not silently change research settings.

V3 automatically uses the separate `prompts/extraction_v3_1.txt`. Existing v2 prompt
settings remain available when selecting v2. A `v3_prompt_file` setting can select
another v3 prompt. An explicit `--prompt-file` overrides the prompt for the selected
format; custom v3 prompts must request the v3 candidate contract.

The settings key `v3_candidate_version` defaults to `"3.1"`. Use
`--v3-candidate-version 3.0` to select the frozen v3.0 candidate rules and default
`prompts/extraction_v3.txt`. The flag does not edit settings. Custom prompts are
still honored, but their requested contract must match the selected version.
Live responses declaring a different version fail with `CANDIDATE_VERSION_MISMATCH`;
they are archived rather than silently converted or accepted.

### Repeating the Qwen smoke test

The supplied fixture reproduces the five short sentences from the first live
experiment, including `Dorsals`, `keeled`, `MBSR`, and `préoculaire`:

```sh
.venv/bin/python extractor.py --extraction-format v3 --models qwen3:8b --ollama-think false --input tests/fixtures/extraction_v31_smoke.txt --output-dir extractor_outputs/v31_smoke --log-dir extractor_logs/v31_smoke --dry-run
```

Remove `--dry-run` for a local model request, and use fresh directories for each
repeat. The fixture's expected terms in tests are illustrative review expectations,
not scientifically verified labels or evidence of a model's completeness. Offline
tests construct quotations manually; they do not ask a model to extract them.

Cloud-only selections remain independent of Ollama availability and its context
budget. Only Ollama selections require a running local server. No live model run
was used to validate this integration.

## Saved artifacts and unsuccessful responses

Each v3 model has two always-written artifacts once a result or failure is recorded:

- `{index}_{model}.raw.json`: exact returned response and reasoning strings, provider
  completion status, error information, and provenance.
- `{index}_{model}.validation.json`: evidence records, warnings/errors, and separate
  `evidence_valid` and `accepted` flags.

A third artifact, `{index}_{model}.json`, is written only when the provider completed
successfully and deterministic evidence validation passed. Acceptance establishes
textual support, not scientific verification. Ambiguity warnings do not prevent
acceptance; unmatched quotations do. Unmatched and incomplete candidates remain
available in the report and raw archive for review.

Raw and validation archives record the selected `candidate_format_version`
independently of their archive-envelope version. Accepted documents use the selected
candidate version (`extraction-3.0` or `extraction-3.1`). The raw archive is saved
before parsing the model's candidate JSON. It preserves
returned text, including whitespace and empty strings, using reversible JSON
escapes. It is not a full provider SDK or HTTP response archive: the shared runners
expose text, reasoning, metrics, and completion status rather than those envelopes.
Content not exposed by a runner cannot be reconstructed from this archive.

An actual empty response has `response_available: true`. A failure before any
response is available has `response_available: false` and explicit error details.
Partial Ollama streaming text is captured even when the stream disconnects. Cloud
runners do not expose partial text if their nonstreaming request raises before
returning an outcome; such failures are recorded without fabricating a response.

Original input bytes and the exact rendered prompt are archived once per run under
`.extraction_runs/` in the output directory, before provider construction. Their
names use a fingerprint of the run ID, and artifacts reference their locations.
The exact supplied text is retained separately, including any deliberate input cap.

Reservation checks cover all model artifacts, input/prompt snapshots, and run IDs.
Exclusive file creation also prevents overwriting a file that appears after the
initial checks. Failed experiments must use a new directory on retry. A process
stopped during validation may leave only its raw archive; that archive remains
available for offline checking.

## Developer reference: contract and integration interfaces

`feature_dictionary/extraction_v3.py` owns the contract and validation functions.
It imports no model runners, makes no network requests, and performs no file I/O.

- `CandidateResponse` and `ExtractionDocument` retain the v3.0 contracts.
- `CandidateResponseV31` and `ExtractionDocumentV31` define the v3.1 contracts.
- `validate_response(raw_response, supplied_text)` parses strict JSON, resolves
  quotations, and returns an `EvidenceReport` retaining the exact response string.
  It dispatches by the response's declared version. Optional `expected_version`
  pins live requests to their planned version without changing archived rules.
- `resolve_location(...)` enumerates exact, contained span pairs.
- `validate_document(document, raw_response)` reconstructs entries and checks their
  equality and the supplied-text fingerprint, rather than trusting saved positions.

The schema files in `schemas/` mirror these Python contracts. JSON Schema checks
structure; the functions above enforce evidence semantics. Annotation fields are
intentionally permissive so uncertain suggestions cannot invalidate grounded text.

```python
from feature_dictionary.extraction_v3 import validate_response

report = validate_response(raw_response, supplied_text)
print(report.evidence_valid)
for issue in report.issues:
    print(issue.severity, issue.code, issue.path, issue.message)
```

The validator itself does no file I/O. Shared pipeline responsibilities are:

- `settings.py`: `extraction_format` defaults to `v2`; `v3_prompt_file` is optional.
  `v3_candidate_version` defaults to `3.1`. `resolve_prompt_path()` selects the
  effective version-specific prompt.
- `context.py`: `RunContext` retains the original input-byte snapshot. V3 renders
  the supplied text without the legacy renderer's whitespace trimming.
- `writers.py`: `reserve_run()` covers every v3 target; `archive_v3_input()` saves
  the captured bytes and prompt; `write_v3_output()` archives before validating.
- `cli.py`: `_write_outcome()` routes shared runner outcomes to the selected writer.
  Provider success with invalid evidence becomes pipeline status `invalid_output`;
  the original provider status remains recorded in the raw/validation artifacts.
  `_failure_result()` records no-response failures without inventing model text.

The offline `validate_document()` helper checks supplied text and recomputed
evidence. It does not inspect archive paths on disk. Input-byte fingerprints at
extraction time are calculated from the same captured bytes that are archived.

No provider runners, v2 output names, configured token limits, or historical
synthesis fields changed. Version-aware synthesis ingestion without changing the
v2 dictionary contract remains stage three; do not pass v3 output folders to the
current Markdown-only synthesis ingestion command.

### Offline replay of historical v3.0 and current v3.1

```sh
.venv/bin/python -m feature_dictionary.extraction_replay extractor_outputs/v3_live_no_thinking/0_qwen3-8b.raw.json
```

This command reads the archive's supplied text, original completion state, and
candidate-version metadata. Early v3.0 archives lack the new metadata, so their
response's declared `extraction-3.0` version selects the original rules. Current
settings and prompts are not consulted. It prints reconstructed validation to
the terminal without changing any experiment files or making model requests.

Exit code 0 means accepted evidence from a successful response; 1 means a
reproduced validation/completion failure; 2 means the archive could not be loaded.
The original no-thinking experiment therefore still reports its four
`EVIDENCE_TYPE_MISMATCH` errors and one `UNMATCHED_EVIDENCE` error. Replay does not
upgrade or correct it. Supplied-text fingerprints are checked; original-file
archive references are not independently inspected by this evidence-only command.

## Developer reference: controlling local Ollama thinking

The installed Ollama Python client inspected for this change is version 0.6.2.
Its `Client.generate()` supports a top-level `think` parameter. This is separate
from Ollama generation `options` and from `include_thinking`, which controls
whether reasoning is shown in legacy Markdown answers.

Use the top-level settings key `ollama_think`:

| Value | Request behavior |
| --- | --- |
| omitted or `null` | Omit `think`; retain the model/server's existing default |
| `false` | Send `think=False` |
| `true` | Send `think=True` |

The command-line equivalent is `--ollama-think false`, `true`, or `default`.
`default` explicitly overrides a configured value back to omission. Settings
require actual JSON booleans or null, rather than strings such as `"false"`.

For a Qwen3 v3 rerun, reuse the input from the earlier smoke test and choose fresh
destinations:

```sh
python extractor.py --extraction-format v3 --models qwen3:8b --ollama-think false --input /tmp/feature_dictionary_v3_smoke.txt --output-dir extractor_outputs/v3_smoke_no_thinking --log-dir extractor_logs/v3_smoke_no_thinking --dry-run
```

Remove `--dry-run` to make the local request, after checking the preview. This
change does not alter the output-token budget, timeout, prompt, or validation.

The setting applies to all Ollama selections in that invocation. It is never sent
to OpenAI, Anthropic, or Gemini. Leave it unspecified for models that do not
support thinking; if an explicit mode is rejected, the error is recorded without
silently retrying or changing the experiment. No extra capability requests are made.

The requested mode is visible in previews, console reporting, model logs, run
summaries, and new local v2 metadata headers. V3 raw/validation artifacts also
record the exact nullable boolean as `ollama_think` and a readable
`ollama_thinking_request` label. Thinking selection does not change evidence rules
for either candidate version.
Thinking settings do not alter the prompt fingerprint, so both must be retained
when comparing experiments.

These records describe the parameter actually sent (or omitted), not independent
proof that a particular server/model honored it. Returned reasoning is still
archived even when thinking was requested off. The client behavior is covered by
mocked tests; no model request was used to test this change.

## Optional local JSON constraints and prompt v3.1.3

Ollama can constrain new responses to the existing extraction-3.1 candidate
schema. This helps prevent conversational wrappers and code fences. It does not
establish that a quotation occurs in the source, that a term is biologically
meaningful, or that extraction is complete. Python still performs strict JSON
parsing and exact, case-sensitive Unicode quotation checking.

Enable this for a v3.1 run with `--ollama-output-format candidate-schema`, or add
`"ollama_output_format": "candidate_schema"` to the settings file. The default is
`null`: no `format` parameter is sent. `--ollama-output-format default` overrides a
configured constraint and restores that behavior. Constraints require
`--extraction-format v3 --v3-candidate-version 3.1`; they do not affect cloud
requests. Historical v2/v3.0 generation and replay remain unchanged.

Select `--prompt-file prompts/extraction_v3_1_3.txt` explicitly. This new prompt
retains the extraction-3.1 contract, uses one compact demonstration, distinguishes
actual source evidence from demonstrations, and reinforces contextual exclusions
for generic reporting language. Earlier prompts and the existing default prompt
are preserved. Prompt tests check the instructions and example grounding; they
cannot establish how well a model follows those instructions.

For constrained local runs, raw archives and validation reports include
`ollama_output_constraint`: the requested mode, schema identity, canonical JSON
SHA-256 hash, and exact schema. The hash uses UTF-8 JSON with sorted keys and
compact separators. `ollama_runtime` records the installed Python client version,
server version when available, and the selected model's digest, modification
time, family, size, and quantization information when supplied by Ollama. Model
digests identify the installed artifacts more precisely than mutable model tags.
These are snapshots of reported metadata, not scientific verification.

The normal model-list request supplies model metadata. Only constrained runs add
a read-only `/api/version` request with a five-second timeout. SDK 0.6.2 has no
public version wrapper, so the runner isolates this call through the existing
SDK transport. Missing version metadata is recorded as unavailable with an error
type; it does not cause generation retries. Dry runs contact no endpoints and
therefore cannot retrieve runtime metadata. Logs and summaries display the
constraint, schema hash, and available runtime information. Raw response strings
and thinking strings remain unchanged; no JSON extraction or output repair occurs.

### Separate local smoke tests

Run from the project directory with the virtual environment activated and Ollama
running. These commands execute models; append `--dry-run` to preview without
contacting Ollama. Each uses a distinct output directory. Existing outputs cause
a collision error; use a new directory for subsequent experiments.

```bash
python extractor.py --extraction-format v3 --v3-candidate-version 3.1 \
  --prompt-file prompts/extraction_v3_1_3.txt \
  --ollama-output-format candidate-schema --models qwen --ollama-think false \
  --input tests/fixtures/extraction_v31_smoke.txt \
  --output-dir extractor_outputs/v313_qwen_schema_01 \
  --log-dir extractor_logs/v313_qwen_schema_01

python extractor.py --extraction-format v3 --v3-candidate-version 3.1 \
  --prompt-file prompts/extraction_v3_1_3.txt \
  --ollama-output-format candidate-schema --models llama --ollama-think default \
  --input tests/fixtures/extraction_v31_smoke.txt \
  --output-dir extractor_outputs/v313_llama_schema_01 \
  --log-dir extractor_logs/v313_llama_schema_01

python extractor.py --extraction-format v3 --v3-candidate-version 3.1 \
  --prompt-file prompts/extraction_v3_1_3.txt \
  --ollama-output-format candidate-schema --models deepseek --ollama-think true \
  --input tests/fixtures/extraction_v31_smoke.txt \
  --output-dir extractor_outputs/v313_deepseek_schema_01 \
  --log-dir extractor_logs/v313_deepseek_schema_01
```

Qwen's prior run respected `think=false`. Llama does not need reasoning enabled.
For DeepSeek, `think=true` requests separate reasoning and answer fields rather
than attempting to suppress reasoning. Its previous `think=false` run leaked
reasoning into response text under Ollama 0.40.3. Schema-plus-thinking behavior
has not yet been verified live. Thinking still consumes generation tokens and
can exhaust the limit before producing a complete answer. No automatic endpoint
switch, thinking-mode fallback, or retry is performed. If any model emits
wrappers, tags, unsupported quotations, or incomplete JSON, its original response
remains archived and is rejected by the existing checks.

## Optional Claude native JSON output

Claude Sonnet 4.5 supports native JSON-schema output. The installed Anthropic SDK
1.9.0 exposes it through `messages.create(output_config={"format": ...})`. Our
historical runner omitted this parameter, so a normal completed request could
still return Markdown-fenced JSON. Strict parsing correctly rejects those fences.

For new v3.1 experiments, opt in using
`--anthropic-output-format candidate-schema`, or configure
`"anthropic_output_format": "candidate_schema"`. The default is `null`; the CLI
value `default` restores omission. No prompt, default model, historical archive,
other provider request, or validation rule changes. The mode requires v3 with
candidate version 3.1. Provider errors do not trigger an application fallback to
unconstrained output or another model.

Anthropic cannot enforce the complete original schema directly. Its native
schema subset does not support `minLength`, and SDK 1.9.0's transformer rejects
the unrestricted optional `proposed_annotations` field. The request therefore
uses a documented projection derived from the original candidate contract:

- Nonempty-string constraints move into descriptions through the SDK's public
  `transform_schema` helper. Python still enforces them as before.
- The format-version constant becomes a single-value enum so the SDK preserves
  its native constraint.
- Optional annotations may be omitted, null, or a closed object with optional
  `language` (string or null) and `forms` (array of strings). Their scientific
  correctness remains unverified. This limits what the new generation mode
  requests; it does not tighten validation of old or unexpected annotations.

The original extraction-3.1 contract stays unchanged and remains authoritative.
The application continues to use `messages.create`, rather than an SDK parsing
helper, so responses are archived before our existing strict parser runs. It
never strips fences, extracts JSON substrings, or repairs evidence. A native
format constraint does not make an unsupported quotation acceptable, guarantee
complete terminology discovery, or make a refused/truncated response successful.

Raw archives and validation reports record `anthropic_output_constraint`,
including mode, request parameter, projection identity, exact sent schema, its
canonical JSON SHA-256 hash, original contract hash, SDK version, and adaptations.
Logs, summaries, and dry-run previews also identify the requested constraint and
schema hash. Existing model identity and completion metadata remain intact.
No beta header or SDK upgrade is required for the documented native mode.
See [Anthropic structured-output documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

With the virtual environment activated, this command starts a new Claude trial:

```bash
python extractor.py --extraction-format v3 --v3-candidate-version 3.1 \
  --prompt-file prompts/extraction_v3_1_3.txt \
  --anthropic-output-format candidate-schema --models claude \
  --input tests/fixtures/extraction_v31_smoke.txt \
  --output-dir extractor_outputs/v313_claude_schema_01 \
  --log-dir extractor_logs/v313_claude_schema_01
```

Append `--dry-run` to preview without an API request. Use fresh directories for
subsequent trials; collision protection remains active. Native request wiring
and failure handling are tested offline. Account availability and actual model
behavior require a separately authorized live trial.

## Override the output-token budget for one run

Use `--max-output-tokens N` to override the configured generation budget without
editing settings. `N` must be a positive integer. For example,
`--max-output-tokens 8192` sends 8192 through each provider's existing interface:
Ollama `options.num_predict`, OpenAI `max_output_tokens`, Anthropic `max_tokens`,
and Gemini `config.max_output_tokens`.

An explicit flag also overrides a configured Ollama `options.num_predict`.
Without the flag, existing settings precedence and provider defaults are
unchanged. Effective per-provider limits are recorded in logs and run summaries,
v2 output metadata, and v3 raw/validation archives. Output budgets do not alter
the candidate/evidence schemas or quotation checks.

Provider/model upper limits vary; this option does not guess a universal maximum
or silently clamp the requested value. Provider rejections retain their error
messages in the existing failure reports. Local runs retain the existing context
budget checks: a larger output allocation may require a larger `options.num_ctx`
or a smaller input. Cloud-only runs are not limited by Ollama's context setting.

To repeat the real-description Gemini experiment with a larger budget:

```bash
python extractor.py --extraction-format v3 --v3-candidate-version 3.1 \
  --prompt-file prompts/extraction_v3_1_4.txt --models gemini \
  --max-output-tokens 8192 \
  --input tests/fixtures/acanthophis_antarcticus_real.txt \
  --output-dir extractor_outputs/v314_gemini_8192_01 \
  --log-dir extractor_logs/v314_gemini_8192_01
```

Append `--dry-run` for a preview with no provider requests. Repeated experiments
require fresh directories; collision protection stays active. A higher budget
does not guarantee completion or evidence validity.
