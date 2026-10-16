# Feature Dictionary — extraction → synthesis → review

**New team members:** start with the [user manual](docs/USER_MANUAL.md) and
[GitHub handoff notes](docs/GITHUB_HANDOFF.md). The existing synthetic fixture is
a complete, no-cost example; it needs no credentials, Ollama server, or private
experiment archives. From this project directory after installation:

```sh
python -m feature_dictionary.modular_synthesis --replay-job tests/fixtures/synthesis_v12_run/job_000
python -m feature_dictionary.inventory_workflow --render-job tests/fixtures/synthesis_v12_run/job_000 --output-dir review_outputs/first_offline_01 --reference-fixture tests/fixtures/reference/acanthophis_inventory_v1.json
```

Choose a fresh export destination on repeat runs. The research baseline uses explicit
extraction v3.1.4 / synthesis v1.2.4 prompts; defaults and historical examples below
remain unchanged. See the handoff notes for the proposed Git file list and verified
dependency constraints.

Use **`python -m feature_dictionary.inventory_workflow`** as the primary entry point.
It coordinates extraction, independent synthesis proposals, validation, and review exports.
Results require scientific review; this workflow does not compile a final dictionary.

Run commands from the Feature Dictionary project root after following the manual’s
installation and guarded sample-default-input steps. Use the activated environment’s `python`.
Always choose a fresh output directory. Cloud execution may incur charges; the execution
commands below require approval before running.

### Preview (no model calls or output files)

```sh
python -m feature_dictionary.inventory_workflow \
  --source tests/fixtures/acanthophis_antarcticus_real.txt \
  --extractor-models qwen,gemini --synthesis-models claude \
  --extraction-prompt prompts/extraction_v3_1_4.txt \
  --synthesis-prompt prompts/synthesis_inventory_v1_2_4.txt \
  --ollama-think false --extraction-tokens 8192 --synthesis-tokens 16384 \
  --output-dir workflow_outputs/demo_01 --dry-run
```

### Full execution (after approval)

Run the preview command above with `--dry-run` removed. It uses extraction prompt
`extraction_v3_1_4.txt`, synthesis prompt `synthesis_inventory_v1_2_4.txt`, extraction
contract 3.1, synthesis contract 1.2, and short observation references. Explicit model
choices are required; aliases resolve through `settings.json`.

### Reuse accepted extraction (local archive example; preview first)

These historical extraction directories are excluded from Git. Obtain the complete
archive bundle separately or substitute accepted extraction from your own run.

```sh
python -m feature_dictionary.inventory_workflow \
  --reuse-extraction extractor_outputs/v314_gemini_8192_01 \
  --reuse-extraction extractor_outputs/v314_qwen_ctx16384_01 \
  --synthesis-models claude --synthesis-tokens 16384 \
  --synthesis-prompt prompts/synthesis_inventory_v1_2_4.txt \
  --output-dir workflow_outputs/reuse_demo_01 --dry-run
```

After approval, remove `--dry-run` to generate synthesis only. Failed or interrupted
runs remain intact; there is no automatic retry or in-place workflow resume.

### Export a historical Claude proposal (separate archive required)

```sh
python -m feature_dictionary.inventory_workflow \
  --render-job synthesis_outputs/acanthophis_v12_short_claude_01/job_000 \
  --reference-fixture tests/fixtures/reference/acanthophis_inventory_v1.json \
  --output-dir review_outputs/meeting_demo_01
```

The example above requires a separately supplied local archive; use the synthetic
fixture at the top of this README for the fresh-clone offline exercise.

Open `proposal_000/terminology_inventory.md`, `scientific_review.md`, and
`semantic_evaluation.json` in that destination. JSON exports retain the evidence and
provenance. Reference expectations are provisional, not advisor approval. Term-label,
owner, and primary-association comparisons ignore case; evidence checks remain exact.
Existing exports are historical snapshots and are not updated automatically.

See [workflow details](docs/inventory-workflow.md) and the short
[controlled model-comparison procedure](docs/model-comparison.md).
Preserve all experiment archives, prompts, schemas, fixtures, tests, and examples in place.

---

## Extraction-only and compatibility reference

The following reference documents the underlying extractor and older entry points.
`extractor.py`, `python -m feature_dictionary`, and the installed `feature-dictionary`
command run extraction only. Their defaults differ from the combined workflow:
`settings.json` selects extraction v2 and a cloud model in the handoff snapshot.
The numbered installation and command examples below are compatibility reference;
new users should follow the manual for platform-specific installation, the ignored
default-input workaround, and explicit current research prompt selections. Older synthesis
entry points remain available for their original contracts and archive replay.

## Historical extraction reference

Send one chunk of text (`species_database.txt`) plus a configurable prompt to local Ollama
models (including Qwen, DeepSeek and Llama) and cloud models (GPT, Claude and Gemini).
One pipeline renders the prompt, dispatches requests, and writes answers and metrics.

```
species_database.txt ─┐
                      ├─► prompt ─► llama3.1:8b ─► extractor_outputs/0_llama3.1-8b.md
settings.json ────────┘             qwen3:8b    ─► extractor_outputs/1_qwen3-8b.md
                                    gemma3:12b  ─► extractor_outputs/2_gemma3-12b.md
                                                   extractor_logs/0_llama3.1-8b_09_18.md
                                                   extractor_logs/summary_09_18.md
```

Everything the run does is driven by `settings.json`: the prompt, the list of models, the
Ollama options, the output folders and the execution mode. Local model requests go to the
configured Ollama server; cloud requests send the rendered prompt to the selected provider.
Cloud clients use `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` (or
`GOOGLE_API_KEY`); `.env` is loaded at CLI startup.

---

## 1. Requirements

| Requirement | Notes |
| --- | --- |
| Python | 3.12+ declared; handoff verified on 3.14.3 (see manual) |
| Ollama | Required only for local models; running via `ollama serve` or the desktop app |
| Models | Local models must be pulled; cloud models require provider credentials/access |
| Packages | Install dependencies from `pyproject.toml`, including the cloud SDKs |

Check what you already have:

```powershell
ollama list
```

---

## 2. Install

From this folder (`projects/1-Feature_Dictionary`):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

`.venv/` is already git-ignored. You can also run the tool with any interpreter that has
the dependencies from `pyproject.toml` available — the package is importable straight from this directory.

---

## 3. Extraction-only command examples

```powershell
# 1. Show exactly what would run (no provider requests)
python extractor.py --dry-run

# 2. LIVE: smoke test one installed local model
python extractor.py --models llama3.1:8b

# 3. Run every model listed in settings.json
python extractor.py

# 4. Compare two specific models instead
python extractor.py --models llama3.1:8b,qwen3:8b

# 5. Run on a small excerpt of the database (see section 7 for why this matters)
python extractor.py --input species_database.excerpt.txt --models llama3.1:8b
```

`--models llama3.1:8b` overrides the `models` list for that single run only and is the fastest
way to check that the prompt, the input file and the output/log folders all behave as
expected. `settings.json` is still read for the prompt, options and paths.

Equivalent entry points: `python -m feature_dictionary` and the installed
`feature-dictionary` console script.

### Command line options

| Flag | Effect |
| --- | --- |
| `--settings PATH` | Use a different settings file (default: `settings.json` next to this project) |
| `--input PATH` | Override `input_file` (useful for testing with a small excerpt) |
| `--models a,b,c` | Override the model list for this run |
| `--prompt-file PATH` | Use a prompt file instead of the inline `prompt` |
| `--output-dir PATH` / `--log-dir PATH` | Override the output / log folders |
| `--dry-run` | Print the resolved configuration, target file names and a prompt preview |
| `--log-level LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` (diagnostics go to stderr) |

Exit codes: `0` every model succeeded, `1` at least one model failed or was skipped,
`2` the settings or the Ollama connection were unusable, `130` the run was interrupted with
`Ctrl+C` (partial results are still saved — see section 8).

---

### Selecting local and cloud models together

```sh
# No-cost preview of all six model families; local identifiers are examples.
python extractor.py --models qwen3:8b,deepseek-r1:8b,llama3.1:8b,gpt,claude,gemini --dry-run
```

Use `provider:model` for an explicit choice, such as `ollama:qwen3:8b` or
`openai:gpt-5.4-nano`. Legacy `provider=model` still works. Bare configured model
IDs retain their configured provider. Known cloud IDs and the local shorthand
`qwen3:8b`, `deepseek-r1:8b`, and `llama3.1:8b` also work without configuration.
For another local model, configure it or qualify it with `ollama:`; unknown bare
names no longer silently select Ollama.

The `model_aliases` object in `settings.json` defines short selections using separate
provider/model fields. The project defines `gpt`, `claude`, `gemini`, `qwen`,
`deepseek`, and `llama`. For example:

```json
"model_aliases": {
  "qwen": {"provider": "ollama", "model": "qwen3:8b"},
  "gpt": {"provider": "openai", "model": "gpt-5.4-nano"}
}
```

Edit an alias's model ID here to select another version; provider runners do not
need changes. Alias values must be direct provider/model objects, not strings or
references to other aliases. Aliases do not add models to the default `models`
list. Select all six with `--models qwen,deepseek,llama,gpt,claude,gemini`.
They expand before execution; filenames, logs, and raw metadata retain full native
model identities. Existing `gpt`, `claude`, and `gemini` defaults remain available
for older settings files without alias definitions.

A provider name (`openai`,
`anthropic`, `gemini`, or `ollama`) selects its unique configured model. Multiple
configured choices require an explicit model. If no model is configured for a cloud
provider, the existing compatibility-alias model is used. `ollama` alone requires
a unique configured local model. Unknown/ambiguous selections and repeated
provider/model identities are errors; the same model label under different providers
remains distinct. An explicit configured alias such as `gemini` selects its defined
identity even when that provider has multiple configured models. If an alias also
names a different configured/known native model, selection is ambiguous and requires
qualification. Omitting `--models` preserves the configured list and order.

Do not abbreviate native IDs into strings such as `openai.4-nano` or
`gemini.8-flash`; these are recognized only if they are actual configured model IDs.
Settings support legacy local strings and objects such as
`{"provider": "openai", "model": "gpt-5.4-nano"}`. Supported provider IDs are `ollama`,
`openai`, `anthropic`, and `gemini`. Output indices follow selection order even though
execution remains grouped by provider. The index prevents collisions between identical
labels or filename slugs. Cloud-only runs do not create or probe an Ollama client.
Explicit qualification assigns a provider; it does not check a remote model catalog.
Model availability and account access still need verification during an authorized run.

`max_output_tokens` is the shared output cap. Ollama receives `num_predict` (an explicit
`options.num_predict` takes precedence); OpenAI receives `max_output_tokens`; Anthropic
receives `max_tokens`; Gemini receives `config.max_output_tokens`. If unset, OpenAI and
Gemini use provider defaults, Anthropic uses the application's 4,096-token fallback,
and Ollama retains its own default. Provider model limits still apply. Ollama options
such as `temperature`, `seed`, and `num_ctx` are **not** applied to cloud models.

The current experimental setting of **1,200 remains unchanged**. Given the observed
truncation, a reasonable next experiment would start at **4,096 tokens for development**
and **8,192 for term-heavy inputs**, then use completion reasons and measured token counts
to adjust. These are starting points, not guarantees. Reasoning models may consume output
budget on reasoning. For local runs, increasing output allowance also requires enough
`num_ctx` for both the input and output; check the dry run first.

All runners return `GenerationOutcome` with text, metrics, and a completion status.
Partial, blocked, and empty responses do not count as successes; their received text and
provider completion reason are retained. Legacy exception labels remain `error` for
Ollama and `failed` for cloud failures. Prompt path, filename-derived version, template
SHA-256, and rendered-prompt fingerprint appear in metadata and logs. Provider and effective
output cap are also recorded. Markdown bodies and filenames retain the existing format
for synthesis ingestion. Cloud requests are non-streaming; a user interrupt cannot save
text that the SDK has not yet returned.

### Protecting experimental outputs

Extraction refuses existing answer filenames before contacting any provider. When
`log_append` is false, existing destination logs and summaries are also refused.
The error exits with code `2`; use a fresh `--output-dir` and, when needed, `--log-dir`.
No overwrite flag or automatic filename suffix is introduced. Existing filenames and
synthesis ingestion remain compatible. Non-conflicting targets may share a directory,
and `log_append: true` continues to append logs as before.

New run IDs combine an ISO timestamp with a UUID. Each destination directory records a
permanent `.extraction_runs/<run-id-sha256>.json` reservation receipt; reusing a recorded
ID fails even if no answer was written. Receipts indicate reservation, not successful
completion. Markdown ingestion ignores these JSON files.

A temporary `.extraction.lock` in each destination rejects concurrent runs sharing that
directory. Normal exit removes only locks owned by the current run. A process crash may
leave a lock: use fresh directories, or inspect the lock and verify that its process is
no longer active before manually removing it. Existing locks are never automatically
removed. Exclusive file creation provides a final safeguard against late collisions.
Dry runs remain read-only previews and do not reserve destinations.

## 4. Settings reference (`settings.json`)

| Key | Default | Meaning |
| --- | --- | --- |
| `host` | `null` | Ollama base URL. When `null`, `$OLLAMA_HOST` is used, then `http://127.0.0.1:11434` |
| `input_file` | `species_database.txt` | The text chunk that is embedded into the prompt |
| `prompt` | — | Inline prompt; should contain `{species_database}` |
| `prompt_file` | `null` | Path to a prompt file; set **either** this or `prompt`, never both |
| `models` | — | Local strings or provider/model objects; `{i}` follows selection order |
| `options` | `{}` | Passed straight to Ollama (`temperature`, `num_ctx`, `seed`, `num_predict`, …) |
| `output_dir` | `extractor_outputs` | Where answers are written |
| `log_dir` | `extractor_logs` | Where per-model logs and the summary are written |
| `index_base` | `0` | First `{i}`. Set to `1` to number models from one |
| `log_date_format` | `%m_%d` | Date stamp in log file names (`MM_DD`) |
| `log_append` | `true` | Same-day re-runs append a new `## Run` block instead of overwriting |
| `stream` | `false` | Ollama only: stream tokens while a model is generating |
| `keep_alive` | `"5m"` | How long Ollama keeps a model in memory after the request |
| `request_timeout_seconds` | `900` | Per-request timeout |
| `max_concurrency` | `1` | Ollama group only: `>1` uses a thread pool; clouds stay sequential |
| `include_thinking` | `false` | Append the reasoning trace of thinking models to the answer file |
| `output_metadata_header` | `true` | Write the `<!-- model, run id, fingerprint … -->` comment block |
| `continue_on_error` | `true` | Keep going when a model is missing or fails |
| `write_run_summary` | `true` | Also write `{log_dir}/summary_MM_DD.md` |
| `prompt_placeholder` | `{species_database}` | The token replaced by the input text |
| `max_input_characters` | `null` | Optional cap on how much of the input is embedded |
| `fail_on_context_overrun` | `false` | Refuse when the Ollama input budget is exceeded; cloud-only runs bypass this |
| `max_output_tokens` | `null` | Shared cloud/local output cap; explicit Ollama `num_predict` overrides it locally |
| `loop_guard` | `false` | Stop a model that has locked into repeating the same lines |
| `loop_guard_repeats` | `25` | How often one line may repeat inside a 200-line window before the guard fires |

The `settings.json` in this repository turns on three of these —
`"fail_on_context_overrun": true`, `"max_output_tokens": 1200` and `"loop_guard": true` — because
the historical input exceeded local context windows (section 7) and a runaway
model once had to be killed by hand (section 8).

Relative paths are resolved against the folder that contains `settings.json`; `~` is expanded,
so `"output_dir": "~/extractor_outputs"` also works. Unknown keys are rejected on purpose, so a
typo fails loudly instead of being silently ignored.

### Customising the prompt

Edit the inline `prompt` string, or point `prompt_file` at a Markdown/text file for longer
prompts:

```json
{
  "prompt_file": "prompts/feature_extraction.md",
  "models": ["llama3.1:8b"]
}
```

The placeholder `{species_database}` is replaced with the contents of `input_file`. If the
placeholder is missing, the input text is appended after the prompt instead, so the data can
never be lost silently. Plain `str.replace` semantics are used, so literal `{` / `}` characters
in your prompt are safe.

---

## 5. What gets written, and where

| Artefact | Path | Contents |
| --- | --- | --- |
| Answer | `extractor_outputs/{i}_<model_name>.md` | Metadata comment block + the model's answer |
| Log | `extractor_logs/{i}_<model_name>_MM_DD.md` | Timing and token table for that model |
| Summary | `extractor_logs/summary_MM_DD.md` | One row per model, for comparing them |

`{i}` is the **0-based index of the model in the `models` list** (`index_base` changes the
starting number), `MM_DD` is the run date, and `<model_name>` is the model identifier with
`:` replaced by `-` because Windows does not allow `:` in file names:

| Model identifier | Answer file | Log file |
| --- | --- | --- |
| `llama3.1:8b` | `0_llama3.1-8b.md` | `0_llama3.1-8b_09_18.md` |
| `qwen3:8b` | `1_qwen3-8b.md` | `1_qwen3-8b_09_18.md` |
| `gemma3:12b` | `2_gemma3-12b.md` | `2_gemma3-12b_09_18.md` |

The exact identifier is recorded inside both files, so nothing is lost by the slug. A model
that fails or is not installed still gets a log file (status `error` / `skipped`, with the
reason under **Notes**) but no answer file. With `log_append: true`, a second run on the same
day adds another `## Run` block to the existing log instead of replacing it.

A run that does not finish on its own still produces artefacts: the header of the answer file,
the `Status` row of the log and the status column of the summary all carry `interrupted` (you
pressed `Ctrl+C`) or `loop_detected` (the loop guard stopped the model), with a note explaining
why the answer is incomplete.

### Answer file

```markdown
<!--
model: llama3.1:8b
model_index: 0
status: success
run_id: 2026-09-18T14:03:11-05:00
input_file: species_database.excerpt.txt
input_characters_used: 26,384
input_characters_total: 26,384
input_truncated: no
prompt_characters: 27,100
prompt_fingerprint: 8f2c1a4d91b7e0c3
generated_at: 2026-09-18T14:03:52-05:00
-->

## Primary terms

* **ventrals** - synonyms: `ventral scales`, `ventralia` - homonyms: None
* **subcaudals** - synonyms: `subcaudal scales` - homonyms: None
```

### Log file

```markdown
# Extraction log — llama3.1:8b

## Run 2026-09-18T14:03:11-05:00

| Field | Value |
| --- | --- |
| Status | success |
| Wall-clock time | 41.23 s |
| Ollama total duration | 40.98 s |
| Model load duration | 310.0 ms |
| Prompt tokens | 812 |
| Prompt eval rate | 96.44 tok/s |
| Generated tokens | 350 |
| Generation rate | 10.55 tok/s |
| Total tokens | 1,162 |
| Done reason | stop |
| Interrupted | no |
| Loop detected | no |
| Output file | `extractor_outputs/0_llama3.1-8b.md` |

### Notes

No errors.
```

---

## 6. What the numbers mean

| Field | Source |
| --- | --- |
| `Wall-clock time` | Measured by this tool around the request — what the user actually waits |
| `Ollama total duration` | Ollama's own `total_duration` (load + prompt + generation) |
| `Model load duration` | Time spent loading weights into memory (`load_duration`) |
| `Prompt tokens` / `Prompt eval rate` | `prompt_eval_count` and `prompt_eval_duration` (how fast the input was read) |
| `Generated tokens` / `Generation rate` | `eval_count` and `eval_duration` (how fast the answer was written) |
| `Total tokens` | Prompt tokens + generated tokens |
| `Done reason` | `stop` (finished naturally) or `length` (hit the token limit) |
| `Prompt fingerprint` | Short SHA-256 of the rendered prompt, to prove two runs used the same input |
| `Ollama options` | The exact options sent, after `max_output_tokens` is merged in |
| `Interrupted` / `Loop detected` | Whether the user stopped the model, the loop guard did, or neither |
| `Estimated generated tokens` | Falls back to ~4 characters per token when Ollama never reported counts |
| `Data budget` / `Input fits budget` | How much input fits next to the instructions and the output cap |

Every figure is per model and per request, so the tables are directly comparable across models
as long as the runs are sequential (see section 8). A row with `interrupted` or `loop_detected`
has no Ollama token counts — the final stream chunk never arrived — so those numbers are labelled
as estimates.

---

## 7. Large inputs: only the *tail* of the prompt reaches the model

A local model only sees `num_ctx` tokens. Ollama does **not** error when a prompt is longer than
that — it keeps the tail and silently drops the beginning. Verified against a running server with
a 70,367-character prompt and `num_ctx: 512`, marking the head and the tail of the prompt:

| Marker | Position in the prompt | Reached the model |
| --- | --- | --- |
| `ALPHA-111` | head | **no** |
| `BETA-222` | tail | yes (`prompt_eval_count: 258`) |

That is what a previous run against `species_database.txt` (635,907 characters ≈ 158,914 tokens)
hit with `num_ctx: 8192`:

* instructions: 164 tokens, always safe — this prompt puts `{species_database}` *before* the task
  block, so the tail-truncation keeps the task and drops data instead
* data that actually reached the model: ~7,996 tokens = **5.0 % of the file** (the last ~75 lines)

So the tool computes a **data budget** — `num_ctx`, minus the instruction tokens, minus
`max_output_tokens` — and either warns or refuses:

```text
data budget     : 26,384 characters (input fits: no)      <- python extractor.py --dry-run
```

With `"num_ctx": 8192` and `"max_output_tokens": 1200` that budget is roughly **26,000 characters
≈ 60 records**, which is the size this prompt is designed for. `settings.json` ships with
`"fail_on_context_overrun": true`, so a plain `python extractor.py` against the full 636 KB file
now stops with a clear error instead of quietly feeding the model 5 % of it.

### Building an excerpt

`--input` accepts any file, so cut one line-aware excerpt (this never splits a record, whose lines
can reach ~4 KB) and run against that:

```powershell
python -c "import itertools,pathlib; lines=pathlib.Path('species_database.txt').read_text(encoding='utf-8').splitlines(keepends=True); sizes=list(itertools.accumulate(map(len,lines))); over=[i for i,s in enumerate(sizes) if s>26000]; cut=max(over[0] if over else len(lines),1); pathlib.Path('species_database.excerpt.txt').write_text(''.join(lines[:cut]),encoding='utf-8'); print(cut,'lines /',sum(map(len,lines[:cut])),'characters')"
python extractor.py --input species_database.excerpt.txt --models llama3.1:8b
```

Alternatives to an excerpt: cap the embedded text with `"max_input_characters": 26000` (the log
then reports `Input truncated: yes`), or raise `num_ctx` under `options` — but the KV cache needs
VRAM too and this laptop has about 8 GB in total.

> **Not implemented yet:** automatic per-record chunking with a merge pass. That is the next step
> if you want all 1,497 lines covered by a single command.

---

## 8. Execution model: sequential by default (`max_concurrency`)

Execution is grouped: Ollama first, then OpenAI, Anthropic, and Gemini. Within each group,
selection order is preserved. Cloud jobs remain sequential. `max_concurrency` in
`settings.json` controls the Ollama group only:

* `1` (default) — one request at a time, implemented with a plain loop. No GPU contention, so
  every measurement in section 6 is trustworthy and comparable between models.
* `>1` — the same jobs are dispatched through a thread pool. Wall-clock for the whole run can
  drop when several small models fit in memory at once, but the request timings now include the
  contention, so treat them as indicative only. Streaming output is suppressed in this mode
  (the console would interleave), and the run mode is recorded in every log file.

Why sequential is the right default here:

1. **VRAM is the binding constraint.** This machine has an AMD Radeon RX 6700S (~8 GB VRAM),
   while the six pulled models total ~37 GB of weights. Exactly one 8B-class model can be
   resident at a time; `gemma3:12b` (8.1 GB) already spills into system RAM. A second
   concurrent model would evict the first or push it onto the CPU, slowing both down.
2. **Fair comparisons.** Each model gets the whole GPU, so `Generation rate` reflects the model,
   not the scheduler.
3. **Load-duration details.** The first request to a model includes its `load_duration`; a later
   request to a model that is still resident reports almost none. `keep_alive` (default `"5m"`)
   decides how long that stays true. Every log records `load_duration`, `keep_alive` and the run
   mode so the numbers can be reproduced and interpreted.
4. **Failure isolation.** A model that runs out of memory or errors only affects its own row;
   `continue_on_error: true` keeps the remaining models running.
5. **`keep_alive` trade-off.** `"5m"` reuses a warm model for the next model in a list — but with
   only 8 GB of VRAM, switching models usually means a reload anyway. Use `0` to unload
   immediately (lowest memory pressure, slowest run) or a long value like `"30m"` when you re-run
   only one model repeatedly.

Ollama decides how many requests a single model may serve in parallel
(`OLLAMA_NUM_PARALLEL`, auto-defaulted from available memory); this tool never changes that
setting.

### Interrupting a run (`Ctrl+C`)

`Ctrl+C` now stops cleanly instead of raising a traceback:

1. the in-flight request is cancelled (closing the stream also stops generation server-side);
2. whatever the model had already produced is written to `extractor_outputs/{i}_<model>.md` with
   `status: interrupted`, plus a log whose token counts are marked as estimates;
3. every model that never started gets a log with `skipped: not run: the run was interrupted by
   the user`, so the summary still accounts for the whole run;
4. the summary is written and the process exits with code **130**.

Fill the gaps afterwards by re-running just the missing model, e.g.
`python extractor.py --input species_database.excerpt.txt --models qwen3:8b`. A second `Ctrl+C`
during that saving step aborts immediately.

### Loop guard

A small model asked to enumerate a large corpus can lock into repeating the same lines forever:
Ollama keeps generating by discarding the oldest context, so the only real limit is your patience.
With `"loop_guard": true`, generation is stopped as soon as one line has repeated
`loop_guard_repeats` times inside the last 200 lines (default 25). The model is recorded as
`loop_detected`, its partial answer and log are kept, and the remaining models still run. Lines
shorter than 8 characters are ignored, so a legitimate run of short rows cannot trip it. Pair it
with `max_output_tokens`, which caps `num_predict`, so a model can never generate unbounded output.

---

## 9. Tests and lint

```powershell
.venv\Scripts\python -m pytest          # mocked tests; no provider requests
python -m ruff check .                  # matches the repository lint workflow
python -m ruff format --check .
```

The suite covers settings validation, prompt rendering and truncation, filename slugs, metric
capture (streaming included), error wrapping, the repeat detector and loop guard, interrupt
handling, the data-budget maths and every Markdown artefact. `test_cli.py` drives `main()` end to
end with a fake client and asserts the exit codes (`0`, `1`, `2`, `130`). It never contacts
Ollama.

---

## 10. Project layout

```
projects/1-Feature_Dictionary/
├── extractor.py                  entry point: python extractor.py [--models ...]
├── settings.json                 prompt, models, options, folders, execution mode
├── species_database.txt          the text chunk sent to the models
├── pyproject.toml                dependencies, ruff and pytest configuration
├── feature_dictionary/
│   ├── cli.py                    argument parsing, preflight checks, sequential/threaded run
│   ├── settings.py               settings.json loading, validation, path/prompt resolution
│   ├── context.py                one immutable RunContext per run (run id, prompt, counters)
│   ├── budget.py                 rough token estimation and context-overrun detection
│   ├── runner.py                 Ollama client, per-model execution, metric capture
│   ├── writers.py                answer files, per-model logs, run summary
│   └── naming.py                 file names, model slugs, number formatting
├── tests/                        pytest suite (no server required)
├── extractor_outputs/            ← generated answers   (git-ignored)
└── extractor_logs/               ← generated logs       (git-ignored)
```

---

## 11. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `cannot reach the Ollama server at http://127.0.0.1:11434` | Start Ollama (`ollama serve`, or the desktop app), or set `host` / `$OLLAMA_HOST` |
| `model is not installed locally; run ollama pull <model> first` | Pull it, or remove it from `models`. The attempt is still logged with status `skipped` |
| `ReadTimeout` / `httpx.ReadTimeout` in a log's Notes | Raise `request_timeout_seconds` (big or slow models) |
| `invalid settings in settings.json` | Unknown keys are rejected on purpose — the traceback names the offending field |
| `input file not found` | Paths are relative to `settings.json`; check `input_file` or pass `--input` |
| Answer file is empty | Some thinking models return reasoning separately — set `"include_thinking": true` and check `Thinking characters` in the log |
| `Done reason: length` | The answer hit the token limit; raise `num_predict` or lower the ask |
| Log file already has content | Expected: same-day runs append a new `## Run` block (`log_append: true`) |
| `Only part of the database seems to be used` | Context overrun — section 7 explains the tail-only behaviour |
| `error: the input is ... but only about ... fit alongside the instructions` | `fail_on_context_overrun` is on: run an excerpt with `--input`, or raise `num_ctx` (section 7) |
| Answer/log shows `status: interrupted` | You pressed `Ctrl+C`; the partial answer was saved. Re-run the remaining models with `--models` |
| Answer/log shows `status: loop_detected` | The loop guard stopped a model that kept repeating lines. Raise `loop_guard_repeats`, disable `loop_guard`, or improve the prompt |
| A model never stops and its answer repeats | Set `max_output_tokens`, enable `loop_guard`, raise `repeat_penalty`, and give the prompt a bullet limit |
| Console output is silent while a model works | Set `"stream": true` (sequential mode only) |

### Known limitations

* The whole input chunk is sent as a single prompt; there is no per-record chunking yet.
* `max_concurrency > 1` still writes logs in index order, but the console cannot show per-model
  streaming.
* Token counts come from Ollama; the prompt-size estimate used for the context warning is a
  rough 4-characters-per-token approximation.

