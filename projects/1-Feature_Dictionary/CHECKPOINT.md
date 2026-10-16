# Test-bench checkpoint — 2026-10-12

This checkpoint records the local, offline-tested code state before prompt revision and
architecture documentation. It is not a Git snapshot or a claim of biological verification.
No provider requests, synthesis replay/resume, or historical archive modifications were made.

## Output safety

- Existing answer destinations are refused before provider initialization (exit code 2).
  With `log_append: false`, existing destination logs and summaries are also refused.
- Fail-fast was chosen over automatic suffixes: filenames and ingestion stay compatible,
  and a changed experiment is not silently mixed into an old directory. Choose fresh
  `--output-dir` / `--log-dir` paths for repeated experiments. Non-conflicting targets
  may share directories; `log_append: true` retains its previous append behavior.
- Run IDs now contain a microsecond ISO timestamp and UUID. Historical IDs remain intact;
  ingestion treats both formats as opaque strings. New `.extraction_runs/<sha256>.json`
  receipts prevent identity reuse within either destination directory, including runs
  that failed before producing answers. Receipts indicate reservation, not completion.
- Exclusive `.extraction.lock` files reject concurrent runs sharing either directory.
  Normal exit releases owned locks; existing locks are not removed automatically.
  Exclusive file creation also refuses files appearing after preflight.
- Dry runs remain read-only and do not reserve destinations. Crashes may leave locks;
  inspect them and confirm no owner is active before manual removal, or use fresh paths.

## Module map

| Modules | Responsibility |
| --- | --- |
| `extractor.py`, `__main__.py`, `cli.py` | Entry points, model selection, orchestration, provider-client ownership |
| `settings.py`, `context.py`, `budget.py` | Validated configuration, prompt rendering/identity, Ollama budget estimates |
| `runner.py` | Shared outcome/result/metric types plus local Ollama execution and loop detection |
| `runners/cloud_runner.py`, `anthropic_runner.py`, `gemini_runner.py` | OpenAI, Anthropic, and Gemini request/response handling |
| `writers.py`, `naming.py` | Output reservation, Markdown output/logging, stable indexed filenames |
| `synthesis.py`, `synthesis_core/`, `schemas/` | Separate synthesis CLI, ingestion, inference, staged batching/reconciliation/review, corrections and deterministic validation |
| `tests/` | Mocked integration and deterministic unit tests |

Provider IDs: `ollama`, `openai`, `anthropic`, `gemini`. Qwen, DeepSeek and Llama use
explicit local model identifiers through Ollama. `gpt`, `claude`, and `gemini` retain
the existing cloud aliases. Six-model mocked tests cover shared prompts, dispatch,
indexed filenames, metadata, and unchanged synthesis ingestion. Live model availability,
credentials, endpoint compatibility, and biological accuracy were not tested.

## Effective configuration

These are the checked-in settings, not all class-level defaults:

| Setting | Effective value |
| --- | --- |
| Selected model | `openai:gpt-5.4-nano` |
| Input / prompt | `species_database.txt` / `prompts/extraction_v2.txt` |
| Output / logs | `extractor_outputs` / `extractor_logs` |
| Output cap / timeout | 1,200 tokens / 900 seconds |
| Concurrency | 1; provider groups run Ollama, OpenAI, Anthropic, Gemini |
| Ollama options | temperature 0.2, seed 42, num_ctx 6,144; effective num_predict 1,200 |
| Input cap / context guard | No character cap; fail-on-overrun enabled for runs selecting Ollama |
| Stream / keep alive / loop guard | Ollama only: true / 5 minutes / true, 25 repeats |
| Logging | Metadata and summaries enabled; logs append; thinking output disabled |

`max_output_tokens` maps to Ollama `num_predict`, OpenAI `max_output_tokens`, Anthropic
`max_tokens`, and Gemini `config.max_output_tokens`. An explicit `options.num_predict`
overrides it only for Ollama. The class-level shared cap default is null: OpenAI/Gemini
then use provider defaults, Anthropic uses the application fallback of 4,096, and
Ollama retains its default. Configured timeouts are seconds for OpenAI/Anthropic and
converted to milliseconds for Gemini. Cloud requests remain non-streaming and sequential;
Ollama sampling/context/loop/keep-alive settings do not apply to clouds. Cloud-only runs
neither create an Ollama client nor enforce its budget. Host resolution is explicit
`host`, then `OLLAMA_HOST`, then `http://127.0.0.1:11434`.

The 1,200-token experimental cap is unchanged. Proposed next-experiment starting points
remain 4,096 for development and 8,192 for term-heavy inputs, checked against completion
reasons, usage and model/context limits. No prompt revisions were applied.

## Verification and reproducibility

- Full suite: **258 passed**, including 14 new output-safety tests; one existing Google
  SDK/Python 3.14 deprecation warning.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: 41 Python files already formatted.
- Regression coverage includes existing outputs/logs, occupied directory paths, dangling
  symlinks, shared-directory locks, forced run-ID reuse, fixed-time distinct identities,
  cleanup on exceptions, read-only dry runs, and a post-preflight file collision.
- Local runtime: Python 3.14.3; ollama 0.6.2; openai 3.20.0; anthropic 1.9.0;
  google-genai 2.25.0; pydantic 2.13.5; pytest 9.1.1; ruff 0.16.8.
- Settings SHA-256: `213452c4905ef8f69c3d79701e8201c4bca3b4571327b9aaa91c4cb3730e0d78`.
- Loaded extraction template SHA-256: `64fa0f5423667035135d9f247f6f92633b94e1d56d30ea1db444fd4b9fa44b61`.
- Code/configuration checkpoint SHA-256: `06d8c4b35fecf60e141c0e265d904b82d9577108896be11569cb8b092c168daf` (45 files).
  Computed over sorted relative POSIX paths, each UTF-8 path + NUL + file bytes + NUL;
  scope: `feature_dictionary/**/*.py`, `tests/**/*.py`, `schemas/*.json`, `prompts/*.txt`,
  `extractor.py`, `settings.json`, `pyproject.toml`, `README.md`, `SYNTHESIS.md`.
  This report and experimental archives are excluded.

## Synthesis experiment status (read-only inspection)

`mid_batched_test` contains three extraction sources and 220 immutable observations.
Its frozen plan uses GPT-5.4 Nano, batches of 30 (eight batches), lightweight relationship
coverage, and a 6,000-token output cap per job. Only local batches 1 and 2 have checkpoints;
no reconciliation/review checkpoints, final dictionary, or final run summary are present.
The existing `run.lock` file was left untouched; its presence alone does not prove that
an experiment is currently running.

- Batch 1 archived validation passed. Batch 2's original response failed two relationship
  checks; its correction is registered as accepted/manually approved and has a checkpoint.
- Batch 3's original response still has seven errors. Its proposed candidate's saved
  offline report has zero errors and five warnings (two source-completeness warnings,
  shared `dorsals` expression, and two unresolved concept kinds).
- **Approval discrepancy:** both `batch2_correction_proposed.json` and
  `batch3_correction_proposed.json` match registered immutable correction artifacts marked
  `accepted: true` and `manually_approved: true`. No unregistered proposal remains among
  these two files. However, the earlier batch-3 instruction authorized creating/validating
  the candidate while explicitly withholding registration. The on-disk flag cannot establish
  who authorized a later registration. Treat that authorization as unconfirmed until
  clarified. No batch-3 checkpoint shows consumption yet; resume is designed to reuse
  accepted corrections after revalidation. Nothing was approved or registered in this pass.
- The earlier monolithic live archive retains the incomplete 16,000-token response:
  35,431 input tokens, reason `max_output_tokens`. Offline examples are fixtures, not
  evidence that the live experiment reached final assembly.

## Remaining limitations

- Dependency versions are recorded here but not locked by a reproducible installer file.
- The 1,200-token cap, prompt-quality failures, biological ambiguity and incomplete source
  outputs remain unresolved; validation success does not establish biological correctness.
- Cloud response archives currently retain extracted text/metrics rather than the full SDK
  envelope; extraction lacks synthesis-style resumable paid-request replay.
- Provider grouping and cloud sequential execution remain; sampling controls differ.
  `continue_on_error: false` does not consistently stop all provider failures, and legacy
  exception labels remain `error` (Ollama) versus `failed` (cloud).
- Concurrent thread cancellation and partial-result retention at every interrupt point
  are not fully uniform. Non-streaming cloud interruption cannot recover unreturned text.
- Destination locks coordinate this pipeline, not arbitrary external tools. Hard crashes
  can leave locks or partial files, which remain protected rather than automatically cleaned.
- Run-ID collision detection is scoped to recorded destination directories; UUIDs supply
  uniqueness across otherwise independent directories. Earlier runs have no retroactive
  reservation receipts. Historical outputs and IDs were not migrated.
