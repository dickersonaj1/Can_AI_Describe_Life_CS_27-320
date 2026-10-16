# Feature Dictionary user manual

For the VCU Life Sciences and Computer Science teams, including new research assistants and testing engineers.

Reviewed against the local software on **15 October 2026**. The working research baselines are **extraction prompt v3.1.4**, **extraction-3.1 JSON**, **synthesis prompt v1.2.4**, and **synthesis-1.2 proposals**. These are explicit experiment choices, not all of the program defaults.

For the subsequent cleanup, explicit staging plan, and optional verified-environment
constraints, see [GitHub handoff notes](GITHUB_HANDOFF.md). The audit in section 14
records the earlier inspection; the handoff notes record what was actually removed
or preserved. No production behavior or default was changed during preparation.

**Start here:** complete installation, run the offline exercise in section 7, then preview an experiment. Commands labeled **LIVE** contact a model and can incur charges. Nothing in the offline exercise requires a model or an API key.

**Handoff snapshot (15 October 2026):** at the initial manual review, much of the current software, prompts, fixtures, and documentation was still untracked in Git. A clone of the currently committed repository may not contain them. The subsequent [handoff report](GITHUB_HANDOFF.md) records a proposed 161-file set and clean-copy verification; it does not establish that those files have been committed or published. Confirm receipt of that set before onboarding. The default `species_database.txt` and live experiment directories are also intentionally excluded from Git. Installation below explains how to supply a harmless sample default input without overwriting an existing file.

## Contents

1. [Introduction](#1-introduction)
2. [Pipeline overview](#2-pipeline-overview)
3. [System requirements](#3-system-requirements)
4. [macOS installation](#4-macos-installation)
5. [Windows installation](#5-windows-installation)
6. [Model configuration](#6-model-configuration)
7. [First experiment tutorial](#7-first-experiment-tutorial)
8. [Advanced usage](#8-advanced-usage)
9. [Understanding the results](#9-understanding-the-results)
10. [Troubleshooting](#10-troubleshooting)
11. [Experiment management](#11-experiment-management)
12. [Scientific limitations](#12-scientific-limitations)
13. [Developer reference and verification](#13-developer-reference-and-verification)
14. [Repository audit and proposed cleanup](#14-read-only-repository-audit-and-proposed-cleanup)

## 1. Introduction

The Feature Dictionary software helps researchers discover and organize biological terminology in natural-history descriptions. It supports the broader effort to digitize specimen information by preserving a connection between candidate vocabulary and the original text.

Extraction looks for anatomical structures and regions, positional terms, compounds, morphological characteristics, character states, abbreviations, shorthand, historical spellings, and non-English terminology. From `anterior dorsal scales`, useful observed expressions may include `scales`, `dorsal`, `dorsal scales`, and `anterior dorsal scales`. The software checks exact quotations; a researcher decides which expressions are scientifically useful.

Synthesis organizes accepted extracted vocabulary into proposed anatomical entries and local descriptive expressions. For example, `tail spine` may be an indexed compound associated with both `tail` and `spine`. `anal entire` may be a local expression under `anal`. Those associations are model suggestions requiring review.

The output includes machine-readable JSON files and readable Markdown reports. **JSON** is a structured text format with named fields and lists. **Markdown** is ordinary text with simple formatting such as headings and bullet lists; it can be read in a text editor or rendered in GitHub.

The current modular workflow does not compile a final dictionary, assign final stable concept IDs, generate definitions, analyze species characteristics or frequency, or automatically verify biological claims. Independent model proposals are kept separate. Agreement among models is not scientific verification.

## 2. Pipeline overview

```text
Original species description
        |
        v
Extraction model(s): candidate vocabulary and exact quotations
        |
        v
Python checks: valid JSON, exact wording, possible source locations
        |
        +-- Rejected or incomplete output --> preserve response and error report
        |
        v
Accepted extraction records --> frozen observations and provenance
        |
        v
Independent synthesis model(s): proposed anatomical organization
        |
        v
Python checks: format, evidence, references, observation accounting
        |
        v
Readable inventory + scientific review checklist
        |
        v
Life Sciences review: judge relevance, meaning, and proposed associations
```

**Python** is the programming language used by the project. Its checks are deterministic: given the same saved input and software, they apply the same rules without consulting a model. A **schema** describes the allowed fields and record shapes. Passing a schema does not establish that a term is anatomically appropriate.

A **frozen input** is a saved snapshot that later model runs can reuse unchanged. **Provenance** records where information came from: source text, extraction model, prompt identity, observations, and run metadata. A **fingerprint**, often called a SHA-256 hash, is a calculated identifier for content. Matching fingerprints help check that experiments used identical content; they do not establish scientific truth or guarantee identical model answers.

A successful provider request, parseable JSON, valid evidence, and correct biological classification are separate outcomes. Report them separately, including when a request returns successfully but the proposal fails validation.

## 3. System requirements

### Software and platform status

- The project declares **Python 3.12 or newer** in `pyproject.toml`. The reviewed environment ran Python **3.14.3**. Other Python versions were not verified in this handoff.
- Git is needed to obtain and update a working copy. Run the project from that copy, using the editable installation below. A standalone installed wheel is not a verified distribution: prompts and settings live outside the Python package.
- macOS is the platform tested here. Linux was not tested in this review. Windows instructions are supplied below but have not been executed on Windows.
- Dependencies are `ollama`, `openai`, `anthropic`, `google-genai`, `python-dotenv`, and `pydantic`. Development tools are `pytest` and `ruff`. Install them from `pyproject.toml`; there is no `requirements.txt` or dependency lockfile.
- Installation needs internet access to download software and Python packages. Cloud generation needs internet access, a provider account, model access, and billing or credit. An **API** is the provider's service interface that this software uses; an API key grants account access. This is separate from any consumer chat subscription.
- Offline validation, replay, and report generation require neither provider credentials nor a running Ollama server once dependencies and artifacts are available.

### Local models and hardware

Ollama is optional for cloud-only experiments. It is an additional local service that runs downloaded model files; installing its Python package alone does not install the server or models.

Consult the current [Ollama macOS requirements](https://docs.ollama.com/macos) or [Ollama Windows requirements](https://docs.ollama.com/windows). At review time, these specify macOS 14 or newer, or Windows 10 22H2 or newer. Their GPU and driver requirements may change.

Small fixtures and offline tests do not need model-sized memory. Local generation needs memory for model weights, the input context, and generated output. A context is the text a model can consider in one request. Longer contexts increase memory and processing time.

A 16 GB Mac ran small extraction tests, but all three local models timed out on the 130-observation synthesis input. Each attempt processed the full input and then generated until the 900-second request timeout. Do not treat 16 GB as recommended hardware for that workload. For large local experiments, plan a higher-memory machine or suitable GPU workstation and benchmark a small input first. No specific larger memory size has been certified sufficient by this review.

Allow space for the virtual environment, model downloads, and growing experiment archives. Ollama model storage can be many gigabytes. The reviewed research artifacts were only about 18 MB excluding the environment and caches, but repeated runs store complete inputs and can grow substantially. Keep failed attempts too.

## 4. macOS installation

Use Terminal. Commands in this section are for macOS; do not copy Windows activation commands here.

### Install prerequisites and obtain the project

Install Python from [python.org](https://www.python.org/downloads/) and Git through your institution's approved method. Check that the Python command reports at least 3.12:

```sh
python3 --version
git --version
```

Choose a parent directory for your checkout, then run:

```sh
git clone https://github.com/dickersonaj1/Can_AI_Describe_Life_CS_27-320.git
cd Can_AI_Describe_Life_CS_27-320/projects/1-Feature_Dictionary
```

Repository access may require GitHub authentication. If the directory already exists, use that checkout rather than cloning over it. Confirm the maintainer has supplied the current handoff files, especially `feature_dictionary/modular_synthesis.py`, `prompts/synthesis_inventory_v1_2_4.txt`, and `tests/fixtures/synthesis_v12_run/`.

Create a **virtual environment**, a project-specific Python installation that keeps dependencies separate:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip check
```

The editable install uses the source files in this checkout. Keep the whole project together. To return in a later terminal session, navigate to this project and run `source .venv/bin/activate` again. `python -c "import sys; print(sys.executable)"` should identify this project's `.venv`.

### Supply the default input on a fresh clone

`settings.json` points to the ignored `species_database.txt`. Synthesis settings loading also checks that this file exists, even when synthesis uses a separate frozen input. On a new clone only, supply the existing sample if the default is missing:

```sh
if [ ! -e species_database.txt ]; then cp tests/fixtures/acanthophis_antarcticus_real.txt species_database.txt; fi
```

This is a local convenience copy, not a replacement for the research database. Later commands explicitly select their actual input. Never replace an existing research source merely to satisfy setup.

### Configure only the cloud keys you need

For a Claude experiment, set `ANTHROPIC_API_KEY` in your current terminal session. The equivalent names are `OPENAI_API_KEY` and `GOOGLE_API_KEY` (or `GEMINI_API_KEY`). For example, replacing the placeholder with your own key:

```sh
export ANTHROPIC_API_KEY="your-own-key"
```

Do not put real keys in shared commands, screenshots, reports, or Git. Typed assignments may remain in shell history. Alternatively, create a private local `.env` file in the project using a text editor, containing only the keys you need:

```dotenv
ANTHROPIC_API_KEY=your-own-key
```

`.env` is ignored by Git and loaded by live execution. Existing terminal environment values take precedence over values loaded from `.env`. Key presence does not establish valid billing or model permissions. Offline exercises need no key.

### Optional: install Ollama

Follow the [official macOS installation guide](https://docs.ollama.com/macos), open the Ollama application, and confirm its command is available. These commands check the server or download models; they do not perform extraction:

```sh
ollama --version
ollama list
ollama pull qwen3:8b
```

Download `deepseek-r1:8b` and `llama3.1:8b` separately only if needed. Downloads can be large. If the desktop application is not running a server, `ollama serve` can start one in another terminal; do not start a second server on an occupied port.

### Verify installation without generation

```sh
python extractor.py --help
python -m feature_dictionary.modular_synthesis --help
python -m feature_dictionary.inventory_workflow --help
python -m pytest -p no:cacheprovider
python -m ruff check --no-cache .
```

Continue with the offline exercise in section 7.

## 5. Windows installation

**Platform status: instructions reviewed against the code and upstream installation documentation, but not run on Windows.** Current extraction and modular synthesis do not use the Unix-only lock used by legacy batched synthesis. This is not a claim that the complete test suite or every workflow is Windows-compatible.

Use PowerShell. Install Python 3.12 or newer, Git for Windows, and optionally the [official Ollama Windows application](https://docs.ollama.com/windows). Open a new PowerShell window after installation so updated command paths take effect.

```powershell
py --version
git --version
git clone https://github.com/dickersonaj1/Can_AI_Describe_Life_CS_27-320.git
Set-Location "Can_AI_Describe_Life_CS_27-320/projects/1-Feature_Dictionary"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip check
```

If `py` is unavailable but `python --version` is correct, use `python -m venv .venv`. If PowerShell blocks activation, you can use `.\.venv\Scripts\python.exe` in place of `python` in every command; activation is optional. An approved alternative is `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`, which changes only the current PowerShell process. Follow institutional policy. See [Python's virtual-environment documentation](https://docs.python.org/3/library/venv.html).

Enable UTF-8 for the current session because some archived JSON readers use the platform's default text encoding:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if (-not (Test-Path "species_database.txt")) { Copy-Item "tests/fixtures/acanthophis_antarcticus_real.txt" "species_database.txt" }
```

Set cloud credentials for this session, or use the ignored local `.env` file described above:

```powershell
$env:ANTHROPIC_API_KEY = "your-own-key"
```

For other providers use `$env:OPENAI_API_KEY`, `$env:GOOGLE_API_KEY`, or `$env:GEMINI_API_KEY`. Do not share key values. Avoid defining both Google names unnecessarily; the installed Google client prioritizes `GOOGLE_API_KEY`.

After starting Ollama from the Start menu, `ollama --version`, `ollama list`, and `ollama pull qwen3:8b` work in PowerShell too. The local server normally listens on port 11434. No download or inference is required for the offline exercise.

All later `python ...` examples are single-line commands and can be pasted into either terminal after setup. Forward slashes in project-relative paths are intentional. Quote paths containing spaces. Do not copy a macOS backslash line continuation into PowerShell.

### Windows-specific uncertainties

- Legacy `feature_dictionary.synthesis` batching/resume and correction registration import `fcntl`, a Unix-only file-locking module. Do not use those operations on native Windows. They are separate from the current modular workflow; an appropriate Unix environment is needed for that legacy behavior.
- Some tests exercise symbolic links and may require Windows Developer Mode or additional permissions. The full suite also includes the Unix-lock tests. Full Windows test success has not been demonstrated.
- Unicode decoding, non-ASCII file paths, interruption handling, and installed provider SDK behavior need a Windows acceptance test. UTF-8 settings reduce one risk but do not establish compatibility.
- Long generated paths may encounter Windows path-length restrictions. Use a short checkout location if needed. Model filename colons are sanitized by the existing naming code.

For an initial offline check, run section 7 and this focused subset, recording any failure rather than weakening validation:

```powershell
python -m pytest tests/test_extraction_v31.py tests/test_synthesis_v12.py tests/test_report_presentation.py tests/test_synthesis_observation_refs.py -p no:cacheprovider
```

## 6. Model configuration

### Current selectors

`settings.json` separates the provider from the exact model name. A **provider** is the local service or company handling the request. The six configured aliases at this review are:

| Alias | Provider | Exact model ID | Explicit selector |
| --- | --- | --- | --- |
| `gpt` | OpenAI | `gpt-5.4-nano` | `openai:gpt-5.4-nano` |
| `claude` | Anthropic | `claude-sonnet-4-5-20250929` | `anthropic:claude-sonnet-4-5-20250929` |
| `gemini` | Gemini | `gemini-3.8-flash` | `gemini:gemini-3.8-flash` |
| `qwen` | Ollama | `qwen3:8b` | `ollama:qwen3:8b` |
| `deepseek` | Ollama | `deepseek-r1:8b` | `ollama:deepseek-r1:8b` |
| `llama` | Ollama | `llama3.1:8b` | `ollama:llama3.1:8b` |

These are configured identifiers, not a guarantee of current remote availability, access, or local installation. Change versions through configuration only as a new recorded experiment; do not silently replace the baseline models.

Aliases are direct entries in `model_aliases`, for example:

```json
"claude": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"}
```

This fragment belongs inside `model_aliases`; it is not a complete settings file. Keep configuration JSON valid: double quotes, no comments, no trailing commas. Unknown settings keys are rejected.

Use `--models qwen,gemini,claude` for mixed selection. Exact known IDs and legacy `provider=model` syntax also work. Unknown or ambiguous bare selectors, and duplicate provider/model pairs, are errors. To select a new local model explicitly, use `ollama:its-exact-model-name`. Shortened names such as `openai.4-nano` are not supported aliases.

Extraction without `--models` uses the `models` list, currently only GPT; alias definitions do not enable all six. Modular synthesis requires its own `--models` selection. The connected workflow uses independent `--extractor-models` and `--synthesis-models` flags.

### Defaults versus experimental baselines

| Item | Current behavior unless explicitly overridden |
| --- | --- |
| Extraction format | v2 Markdown |
| v2 extraction prompt | `prompts/extraction_v2.txt` |
| Opt-in v3 candidate contract | extraction-3.1 |
| Opt-in v3 prompt | `prompts/extraction_v3_1.txt`, not v3.1.4 |
| Modular proposal version | 1.0 |
| Modular 1.2 prompt, original references | `prompts/synthesis_inventory_v1_2.txt` |
| Modular 1.2 prompt, short references | `prompts/synthesis_inventory_v1_2_1.txt` |
| Connected workflow prompts | Extraction v3.1.4, synthesis v1.2.2 |
| Shared configured output limit | 4,096 tokens |
| Configured Ollama context | 16,384 tokens |
| Request timeout | 900 seconds |
| Configured Ollama controls | temperature 0.2; requested seed 42; keep-alive 5 minutes; loop guard 25 repeats |
| Extraction concurrency/streaming | one at a time by default; streaming requested for Ollama |
| Modular synthesis | sequential, nonstreaming, independent proposals |

Use explicit prompt and format flags from this manual to select v3.1.4/v1.2.4. A prompt revision is distinct from a JSON contract version: v3.1.4 still produces extraction-3.1, and v1.2.4 still produces synthesis-1.2.

### Token budgets and provider differences

A **token** is a unit of model input or generation; it is not the same as a word or character. The exact count depends on the provider's tokenizer. Output limits may include internal reasoning, not just visible JSON.

`--max-output-tokens N` requires a positive integer and overrides the shared setting, including a previously configured Ollama `num_predict`. Without that flag, an explicit `options.num_predict` takes precedence for local extraction only. With the current settings, the effective default is 4,096.

| Provider | Output-limit parameter | Structured output in extraction | Current modular synthesis |
| --- | --- | --- | --- |
| Ollama | `options.num_predict` | Opt in with `--ollama-output-format candidate-schema` | Proposal schema supplied automatically |
| OpenAI | `max_output_tokens` | Prompt requests JSON; this extraction path supplies no native schema | Strict proposal schema supplied |
| Anthropic | `max_tokens` | Opt in with `--anthropic-output-format candidate-schema` | Native proposal schema supplied |
| Gemini | `config.max_output_tokens` | Prompt requests JSON; this extraction path supplies no native schema | JSON MIME type and proposal schema supplied |

A provider may reject an unsupported model, schema, or budget. The program reports the error; it does not clamp the budget or repair the response. Native constraints help formatting but do not verify biology or exact evidence.

Ollama-specific context, seed, sampling, thinking, and keep-alive settings do not become equivalent cloud controls. Cloud-only extraction avoids Ollama availability and context checks. Mixed extraction still requires Ollama and obeys its budget guard. Extraction groups execution by provider, although artifact indices follow selection order. Modular synthesis executes its selected jobs in order.

`--ollama-think false` explicitly requests disabled thinking; `true` requests enabled thinking; `default` omits the parameter. Support depends on the local model/server. An unsupported setting is not silently retried. Thinking-mode requests do not authorize stripping `<think>` text or other material from responses.

Extraction has no `--num-ctx` flag; use a separately named settings copy for a future approved context change. Modular synthesis does have `--num-ctx N`. The workflow wrapper does not expose that flag. Local budget checks are rough character-based estimates, not exact tokenizer guarantees.

Budget planning should consider actual completion reasons, returned usage, and full provider envelopes when available. In the six-model synthesis comparison, Gemini used almost its entire 16,384-token allowance on thinking, while the local attempts timed out despite their input fitting in context. Repeating such settings blindly is not a useful benchmark.

## 7. First experiment tutorial

The first exercise is entirely offline and establishes that the installation can validate and display a saved proposal. The second previews a real source experiment; live execution is a separate decision.

Run all commands from `projects/1-Feature_Dictionary` with the environment active. Each destination below must be new. Change `_01` to `_02` when repeating an export or experiment. Dry-run commands create no destination.

### A. Validate the saved synthetic proposal at no cost

A **fixture** is a small saved example used for repeatable tests. This example contains 11 synthetic observations and a synthesis-1.2 proposal. It is not a new live model result or the 130-observation research baseline.

```sh
python -m feature_dictionary.modular_synthesis --replay-job tests/fixtures/synthesis_v12_run/job_000
```

The program reads frozen inputs, the saved request and response, and prints validation JSON. Expect `json_valid`, `schema_valid`, and `proposal_valid` to be true, and `scientifically_verified` to remain false. The successful exit code is 0. Existing archives are not rewritten.

Generate readable exports in a fresh location:

```sh
python -m feature_dictionary.inventory_workflow --render-job tests/fixtures/synthesis_v12_run/job_000 --output-dir review_outputs/first_offline_01 --reference-fixture tests/fixtures/reference/acanthophis_inventory_v1.json
```

Open these files in your editor or Markdown viewer:

```text
review_outputs/first_offline_01/
  proposal_000/
    terminology_inventory.md
    terminology_inventory.json
    scientific_review.md
    semantic_evaluation.json
  proposal_differences.md
```

The inventory displays primaries, associated compounds, local expressions, exact evidence, exclusions, and unresolved observations. The scientific review file lists questions for human review. The optional semantic evaluation compares a limited provisional reference; entries absent from the fixture are reported as not observed. It is not an approval certificate.

You now have a software-validated saved proposal and reviewable output without a model call.

### B. Preview a real description with a known-working provider configuration

The sample `tests/fixtures/acanthophis_antarcticus_real.txt` contains a 1,976-character description of *Acanthophis antarcticus*. Claude's tested configuration is useful for a first live workflow, but no model response is guaranteed to pass validation.

Preview extraction and synthesis together:

```sh
python -m feature_dictionary.inventory_workflow --source tests/fixtures/acanthophis_antarcticus_real.txt --extractor-models claude --synthesis-models claude --extraction-prompt prompts/extraction_v3_1_4.txt --synthesis-prompt prompts/synthesis_inventory_v1_2_4.txt --extraction-tokens 8192 --synthesis-tokens 16384 --output-dir review_outputs/first_real_01 --dry-run
```

This verifies extraction settings and prints the planned commands. It does not verify credentials, remote model availability, or future model output. It cannot freeze or budget-check synthesis observations that have not yet been extracted; the plan says `synthesis_input_pending_extraction: true`.

The wrapper requests native Claude extraction output constraints, then uses the synthesis proposal schema. Neither prompt defaults nor `settings.json` are changed.

### C. LIVE: run only after the experiment and cost are approved

The following can make **two paid requests**: one extraction and, only if extraction succeeds, one synthesis request. It was not executed during preparation of this manual.

```sh
python -m feature_dictionary.inventory_workflow --source tests/fixtures/acanthophis_antarcticus_real.txt --extractor-models claude --synthesis-models claude --extraction-prompt prompts/extraction_v3_1_4.txt --synthesis-prompt prompts/synthesis_inventory_v1_2_4.txt --extraction-tokens 8192 --synthesis-tokens 16384 --output-dir review_outputs/first_real_01
```

Expected layout, if all stages reach completion:

```text
review_outputs/first_real_01/
  workflow.json
  extraction_000/                 raw/validation files and accepted extraction JSON
  extraction_logs_000/            timing and token logs
  extraction_000_status.json
  synthesis/
    inputs.json                  unchanged frozen source/observation snapshot
    source_archives.json         original extraction archive content
    observation_refs.json        short-to-original reference map
    model_input.json              model-facing observations
    summary.json
    job_000/
      request.json
      provider_response_0.json   when a provider envelope was returned
      response.json
      validation.json
      proposal_expanded.json     parsed short references expanded to original IDs
      proposal_expansion.json    mapping/transformation provenance
      report.md
      proposal.json              only when the proposal passed validation
  synthesis_status.json
  review/
    job_000/                     inventory, scientific review, optional evaluation
    proposal_differences.md
```

If extraction is rejected or incomplete, its response and report remain and synthesis stops. If synthesis is invalid, the wrapper can still produce diagnostic exports prominently labeled invalid/unapproved. Inspect `validation.json` rather than assuming an exported report is valid. If interrupted or failed, retain the directory; do not rerun into it. There is no automatic modular resume or retry.

The live workflow above omits `--reference-fixture`, so it does not create `semantic_evaluation.json`. Add that flag with the reference path from exercise A if a provisional comparison is appropriate.

## 8. Advanced usage

### Run extraction independently

This preview selects all six aliases, preserves exact quotations, and requests schema-constrained output for the local models and Claude:

```sh
python extractor.py --settings settings.json --extraction-format v3 --v3-candidate-version 3.1 --prompt-file prompts/extraction_v3_1_4.txt --models qwen,deepseek,llama,gpt,claude,gemini --input tests/fixtures/acanthophis_antarcticus_real.txt --max-output-tokens 8192 --ollama-think false --ollama-output-format candidate-schema --anthropic-output-format candidate-schema --output-dir extractor_outputs/handoff_preview_01 --log-dir extractor_logs/handoff_preview_01 --dry-run
```

This is only a routing/configuration preview, not a recommended first six-model live workload. It does not check installations or credentials. For a small local extraction test, select only `qwen`, replace the source with `tests/fixtures/extraction_v31_smoke.txt`, and use fresh directories. Removing `--dry-run` starts generation; cloud selections can incur charges.

Extraction v3 writes, for each model, `INDEX_MODEL.raw.json` and `INDEX_MODEL.validation.json`. Only an accepted result also gets `INDEX_MODEL.json`. Ollama colons become hyphens, for example `0_qwen3-8b.json`. Input bytes, the rendered prompt, and reservation receipts are preserved under the hidden `.extraction_runs/` directory. Copy hidden directories with the archive too.

Raw extraction archives preserve the returned response and thinking strings, source/input metadata, completion state, and constraints. They are not full cloud SDK envelopes. Timing and token counts are in extraction logs; modular synthesis additionally saves returned SDK envelopes.

Historical v2 Markdown remains available with `--extraction-format v2` and its own prompt. V3.0 candidate replay retains its own rules; new v3 runs can explicitly select `--v3-candidate-version 3.0`. Do not mix the v3.1.4 prompt with that older contract. Current modular ingestion accepts validated extraction-3.1 records, not v2 Markdown.

### Revalidate extraction without generation

After an actual extraction created this archive, run:

```sh
python -m feature_dictionary.extraction_replay extractor_outputs/your_trial/0_qwen3-8b.raw.json
```

Replace the illustrative path with a real `.raw.json` file. The command uses archived source text, completion status, and candidate version, prints a report, and never calls a model or modifies the archive. Exit 0 means accepted, 1 means rejected/incomplete, and 2 means the archive could not be processed.

### Combine accepted extraction outputs

You can select accepted document files or directories. Ingestion checks their `.raw.json` and `.validation.json` sidecars and original input-byte archive. Do not copy just the accepted JSON.

This preview uses two historical archives present on the maintainer's machine; they are not currently distributed by a normal clone:

```sh
python -m feature_dictionary.modular_synthesis --settings settings.json --extraction-output extractor_outputs/v314_gemini_8192_01 --extraction-output extractor_outputs/v314_qwen_ctx16384_01 --models claude --proposal-version 1.2 --observation-refs short --prompt-file prompts/synthesis_inventory_v1_2_4.txt --max-output-tokens 16384 --run-dir synthesis_outputs/reused_extraction_preview_01 --dry-run
```

Replace those paths with your own complete accepted archives when necessary. Directory ingestion inspects top-level JSON documents; it is not a recursive search through every experiment. Avoid directories containing unrelated JSON. Rejected documents are not silently salvaged. Repeating the same extraction selection is an error.

Freezing extraction records preserves every accepted observation independently, even if several have identical wording. The frozen source and observation IDs currently depend partly on the original absolute extraction path. Moving archives and freezing them again can change IDs and the resulting fingerprint. For controlled synthesis comparisons, reuse the already-frozen `inputs.json` instead.

### Reuse an identical frozen input

A portable offline preview using the distributed synthetic input is:

```sh
python -m feature_dictionary.modular_synthesis --settings settings.json --inputs tests/fixtures/synthesis_v12_run/inputs.json --models claude --proposal-version 1.2 --observation-refs short --prompt-file prompts/synthesis_inventory_v1_2_4.txt --max-output-tokens 16384 --run-dir synthesis_outputs/handoff_synthetic_preview_01 --dry-run
```

For the established 130-observation research baseline, substitute `synthesis_outputs/acanthophis_v124_claude_01/inputs.json` after obtaining that full archive from the maintainer. Its input fingerprint is:

```text
96cbfa8d2f8a7c7dc7027ddeb8b8ac3dcdc224f3c290880462329bcc64950f1e
```

A dry run should report 130 observations and that exact fingerprint. Reuse the archived mapping and observation order; do not sort, normalize, or edit observations. The archive's old source paths are provenance, not instructions to create those paths on your computer.

`--inputs` preserves frozen content, but `source_archives.json` for the new run records the frozen input path rather than recopies all original extraction archive bytes. Retain the original baseline bundle too. Identical inputs and prompts do not imply identical provider schema transformations, tokenization, sampling, or results.

### Choose independent synthesis models and local budgets

Supply a comma-separated `--models` selection in the preceding command. Each selected model receives the same frozen content and no other model's proposal. Use a new run directory per experiment. Local jobs need a suitable `--num-ctx`; changing it is an experimental choice that should be recorded and previewed.

The approved six-model comparison used local `--num-ctx 40960 --max-output-tokens 6144`, with `--ollama-think false` for Qwen and DeepSeek. All local requests timed out on the tested 16 GB Mac. These values document the experiment; they are not a recommendation to repeat it unchanged. This milestone has no modular batching, compiler, or in-place resume.

### Replay synthesis or render a saved report

For a saved job, substitute its actual path:

```sh
python -m feature_dictionary.modular_synthesis --replay-job synthesis_outputs/your_trial/job_000
```

This recomputes validation offline using the saved input, request, response, and reference mapping. It returns 0 for a valid proposal, 1 for an invalid one, and 2 for an input/configuration error. It does not request a new response or register a correction.

To create only a readable report from the synthetic example:

```sh
python -m feature_dictionary.modular_synthesis --render-report tests/fixtures/synthesis_v12_run/job_000 --report-output review_outputs/synthetic_audit_01.md
```

Use `--include-raw-json` to add the full appendix explicitly. The default is a concise hierarchy plus evidence details. Render outside the immutable source run, and select a destination that does not exist.

For inventory, scientific review, and provisional evaluation exports, use the `inventory_workflow --render-job` command from section 7. Repeat `--render-job` with other jobs to create separate independent exports and `proposal_differences.md`. Invalid exports can be useful diagnostics, but are never validated dictionaries. The raw response is always retained unchanged.

### Scientific annotations and model comparisons

Review statuses initially require human scientific review. The exporter can accept a separate `--review-annotations` JSON file for one `--render-job`. It must explicitly bind decisions to the exact input and proposal fingerprints and identify the reviewer, date, and confirmation. It cannot approve an invalid proposal. See [the workflow guide](inventory-workflow.md) and [the annotation tests](../tests/test_inventory_workflow.py) before constructing annotations; do not edit the original model response to manufacture approval.

`--reference-fixture tests/fixtures/reference/acanthophis_inventory_v1.json` adds a provisional semantic evaluation. It checks a small selection of expected roles/attachments and evidence, not all biological correctness. Some comparison matching ignores label case for review; the underlying evidence validator remains case-sensitive and never rewrites the proposal.

Compare models using identical frozen inputs, prompt text, schema version, and reference expectations. Report provider-specific controls separately. The default disagreement report is not a consensus vote or automatic merge. Differing input fingerprints are marked as uncontrolled comparisons.

The earlier [legacy synthesis guide](../SYNTHESIS.md) documents v2 dictionaries, batching, reconciliation, resume, and corrections. Those features belong to the separate historical path, not modular synthesis-1.2. Do not apply legacy correction/resume commands to modular proposals.

## 9. Understanding the results

### Anatomical organization

A **primary** is a proposed independent anatomical structure or region, such as `tail`. An **indexed compound** identifies a distinct anatomical structure or region in several words, such as `tail spine`. Compounds have organizational links to primary entries; these are not anatomical-containment claims.

A **contextual expression** describes its owner, for example `anal entire` under `anal`, or `laterally compressed` under `tail` when the source supports that attachment. These expressions are local arrays, with no global subterm IDs. A modifier can occur under multiple entries without being merged into a global concept.

A multiword positional phrase such as `distal portion` is not automatically an indexed structure. Pigmentation expressions such as `dark cross-bands`, and measurements such as `Total length`, need scope review rather than automatic promotion to anatomy. Exact evidence checking cannot decide those classifications.

Compounds are stored once and may be displayed under several primaries. Temporary proposal references connect the records. Their values are not final dictionary identifiers, and their numbering has no biological meaning.

### Observation accounting and exact wording

Every frozen observation must have one **disposition**, a recorded decision:

- **Mapped:** cited by an indexed term or one of its local expressions. Its owner references must match all actual citations.
- **Excluded:** judged outside the proposed inventory, with a reason. It remains in the frozen input and review material.
- **Unresolved:** classification or attachment needs review. No owner or evidence is invented.

A missing decision is an error; the report leaves it visibly unresolved rather than treating silence as exclusion. Two models extracting the same text create two observations, not two independent biological confirmations.

Short IDs such as `O001` are run-local aliases for original observation IDs. The map is one-to-one, ordered, archived, and fingerprinted. `response.json` keeps the original model output; `proposal_expanded.json` is a separate derived view with original IDs restored. Unknown references are not guessed or repaired.

In extraction-3.1, Python derives `term` from `matched_text` and derives complete/embedded evidence type. A **complete** expression equals its chosen source phrase; **embedded** is a smaller expression within that phrase. These labels describe textual evidence, not whether a biological concept is complete.

Positions use zero-based Python Unicode character offsets with an exclusive end: start 0/end 5 selects the first five characters. They are not UTF-8 byte offsets. Multiple identical occurrences remain **ambiguous**, with all valid candidates preserved; Python does not silently select one. Case, accents, spelling, and punctuation must match exactly. Language/form annotations are optional model suggestions and do not establish translation, abbreviation expansion, or synonymy.

### Validation and scientific judgment

Common errors include `INVALID_JSON`, `UNOBSERVED_EXPRESSION`, `INVALID_REFERENCE`, `MISSING_PRIMARY`, `DISPOSITION_MISMATCH`, and `MISSING_DISPOSITION`. Their paths identify the affected record, such as `/terms/3/expressions/0`. Errors block proposal acceptance; warnings such as `AMBIGUOUS_LOCATION` preserve uncertainty without necessarily blocking acceptance.

JSON wrapped in Markdown fences is invalid under strict parsing. The software does not strip fences, extract a JSON substring, change capitalization, or accept an unsupported quotation to make a run pass.

Evidence matching for a synthesis label requires exact equality with at least one cited observation's `matched_text`. Related source wording alone is insufficient. This check does not certify that every additional citation is direct evidence, that the expression belongs to its proposed owner, or that an equivalence is scientifically justified. Inspect the quotations and rationales during review.

Equivalence suggestions remain pending review, not automatic canonical naming or merges. A software-valid proposal still needs Life Sciences review of indexed anatomy, contextual ownership, exclusions, and uncertainty.

## 10. Troubleshooting

| Problem | What to check or do |
| --- | --- |
| `python` missing or wrong version | Activate the project environment. On macOS use `python3` to create it; on Windows use `py` or the verified Python executable. Check `sys.executable`. |
| Import/dependency error | From the project directory run `python -m pip install -e ".[dev]"`, then `python -m pip check`. There is no requirements file. Fresh package resolution is not locked. |
| Missing `species_database.txt` before synthesis | Complete the guarded sample-copy step in installation; synthesis still loads and validates the shared settings input path. |
| Missing API key | Configure the correct provider variable in this session or private `.env`. Check the variable name, never print the value. Modular execution lists missing credential names before creating jobs. |
| HTTP authentication, access, or billing failure | Inspect the preserved error type/status and account permissions. Key presence is not proof of access. Do not publish sensitive response details. Any retry is a new explicit experiment. |
| Unknown/ambiguous model selector | Use a configured alias or full `provider:model` identifier. Do not abbreviate versions. Duplicate aliases selecting the same identity are rejected. |
| Ollama connection refused | Start its application or server, confirm `ollama list`, and check `host` or `OLLAMA_HOST`. Cloud-only extraction does not need Ollama. |
| Local model not installed | Compare `ollama list` with the exact configured ID; download the needed model intentionally. Alias resolution does not install it. |
| Insufficient memory or very slow generation | Use a small fixture first, close competing workloads, and record hardware/context. Large local synthesis timed out on the tested 16 GB Mac. Do not interpret timeout as a classification result. |
| Local context-budget error | Preview settings. Extraction uses `options.num_ctx`; modular synthesis supports `--num-ctx`. Smaller frozen input or a separately approved context change may be needed. The estimate is approximate. |
| Incomplete/MAX_TOKENS/length | Preserve the attempt. Inspect completion reason and reasoning usage; little visible JSON can still exhaust the generation budget. Change budgets only as a new recorded experiment. |
| ReadTimeout with empty response | No model text may have returned. Empty-response JSON failure is secondary to the transport/time limit. Server progress is not a recoverable complete response or accurate final usage record. |
| JSON contains fences, commentary, or `<think>` | Keep the raw output. Use supported native schema modes for future experiments. No output-stripping workaround is applied; `think=false` support varies. |
| Exact evidence rejected | Compare capitalization, spelling, Unicode, punctuation, and the quotation boundary with archived source text. Never normalize evidence to force acceptance. |
| Proposal reference/disposition error | Use the error path and exact observation IDs. Account for all citations and decisions. Replay checks correctness; it does not fix the model output. |
| Existing destination or reservation lock | Choose fresh output/log/run/export paths. A dry run does not reserve or guarantee availability. After a crash, inspect ownership before any manual lock cleanup; do not delete a lock from an active run. |
| New clone lacks documented files or examples | Confirm the current untracked handoff files and selected research archives were explicitly included by the maintainer. Ignored live runs do not arrive through a normal clone. |
| Windows Unicode/path/locking failure | Use UTF-8 mode and short paths; record the exact failure. Legacy Unix-lock operations are not native-Windows compatible. Do not weaken evidence checks. |

Extraction exits 0 when all selected runs succeed, 1 for model/acceptance failures, 2 for configuration/output/connection errors, and 130 for handled interruption. Modular synthesis similarly uses 0 for valid proposals, 1 for invalid results, 2 for input/configuration errors, and 130 for handled interruption. The connected workflow may report 2 for an orchestration failure; inspect its stage status files and archives for the actual cause.

## 11. Experiment management

### Use clear, fresh names

Use names that identify source, stage, prompt, model, and replicate, for example `acanthophis_v124_claude_rep02`. Keep extraction output and logs together by using the same experiment name in their separate parent directories. Select fresh paths for every attempt, including failures.

Extraction protects output filenames, raw/validation artifacts, source/prompt snapshots, and run-ID receipts. Existing model outputs are refused. Nonconflicting extraction filenames can technically share a directory, and configured logs can append; isolated directories are clearer for research. Modular runs, workflow destinations, and exports require fresh destinations. Hard crashes can leave partial protected artifacts; there is no automatic paid retry or modular resume.

### Record controls before generation

Preserve the exact command, code snapshot, dependency versions, prompt file/version, full provider/model IDs, source text, input fingerprint, schema version, reference map, budgets, thinking request, context, timeout, and hardware. Record unsupported or unavailable settings rather than pretending providers share all controls.

Keep raw responses, errors, validation, timing, returned token usage, and separate scientific findings. For modular cloud synthesis, consult `provider_response_0.json` for usage fields missing from shared metrics. In particular Gemini's candidate-token count excludes its separately reported thought-token count. Report unavailable local usage as unavailable, not zero.

For repeated synthesis comparisons, reuse the same frozen `inputs.json`, preserve observation order, and verify the fingerprint before generation. Source-path-dependent IDs mean rebuilding a freeze elsewhere can change the comparison input. Seed requests do not guarantee identical output. Provider model aliases and services can change; keep local model digests and returned metadata when available.

### Preserve complete archive bundles

Keep the following together:

- Extraction directory, including accepted JSON, raw/report sidecars, hidden input/prompt archives and receipts; matching extraction logs.
- Synthesis run root, all jobs, frozen input, source-archive content, short-reference map, requests, SDK responses, errors, and derived-proposal provenance.
- Review exports, separate human annotations, reference fixture, comparison report, and relevant code/settings/dependency snapshot.

Use approved research storage for bulk archives, with a manifest recording checksums and how to retrieve them. Verify an offline replay from a copied bundle before considering external archival complete. Do not delete failure records or cherry-pick only successful model output. Repository cleanup does not authorize discarding scientific data.

Currently `.gitignore` excludes extraction outputs/logs, synthesis outputs, private environment files, caches, and local datasets. `review_outputs/` and a future `workflow_outputs/` are not ignored. Review generated files deliberately before any future staging; this manual does not change ignore rules or authorize publishing source material.

For GitHub, retain compact synthetic fixtures, all compatibility-critical schemas/prompts/tests, and selected reproducible baseline bundles with permission to share their sources. The existing real review example is not a substitute for a complete replayable request/input/response bundle. Do not copy a virtual environment to Amro; recreate it from declared dependencies.

### Current benchmark status

The 130-observation input combines 66 Gemini and 64 Qwen extraction observations. In the v1.2.4 synthesis comparison, Claude's archived baseline passed software validation, GPT returned complete JSON with 30 bookkeeping/structural errors, Gemini exhausted its generation budget, and all three local models timed out after approximately 900 seconds. No retries or output repairs were performed.

Only complete proposals can be assessed for classification. Claude matched nine applicable provisional reference roles; GPT matched six in a diagnostic evaluation of its invalid proposal. These small-reference results are not comprehensive biological accuracy scores. Preserve model errors, schema/evidence errors, and resource failures as separate outcome categories.

The older `CHECKPOINT.md` is a historical report, not current configuration. It also records an unresolved authorization question about a legacy batch-3 correction: a saved manually-approved flag is not proof of who approved it. Do not silently reinterpret that legacy experiment or its correction history during the handoff.

## 12. Scientific limitations

Exact source grounding answers, “Does the quoted wording occur here?” It does not answer, “Is this useful biological vocabulary?” or “Is this its correct anatomical owner?” Models can omit relevant embedded terms, extract generic language, mistake properties for structures, or attach a valid descriptor to the wrong term.

Synthesis can organize only accepted observations. A missing or rejected extraction expression cannot be invented during synthesis. Exclusion does not erase an observation, but an inappropriate exclusion can still lose useful vocabulary from the displayed index. Review exclusions as carefully as proposed entries.

Historical spelling, case, multilingual vocabulary, abbreviations, and homonyms require care. Identical spelling does not guarantee identical meaning; different spelling does not prove different meaning. Equivalence remains a proposal. The current system does not automatically supply missing translations, expansions, or canonical names.

Shared source text and model training can produce correlated answers. More model agreement does not substitute for biological verification. The semantic reference fixture is explicitly provisional and not advisor-approved; it must not become an unquestioned scoring authority.

Comparisons must report model/version, hardware, context, output cap, internal reasoning, timeout, schema constraints, and input differences. Failure on a constrained computer is not evidence of inferior biological reasoning. One run per model is a reliability observation, not a statistically established ranking.

Final decisions need scientific review against the original description and appropriate domain knowledge. Even individually reviewed records do not turn the entire proposal into a scientifically verified compiled dictionary.

## 13. Developer reference and verification

### Component responsibilities

| Files | Purpose |
| --- | --- |
| `extractor.py`, `feature_dictionary/__main__.py`, `cli.py` | Extraction entry points and orchestration; `cli.main()` loads settings, previews, reserves outputs, dispatches providers, and reports results. |
| `settings.py`, `context.py`, `budget.py` | Resolve models and paths, render/identify prompts, assemble run context, and estimate local budgets. `parse_model_selection()` is the existing shared selector. |
| `runner.py`, `runners/cloud_runner.py`, `anthropic_runner.py`, `gemini_runner.py` | Local and cloud communication through shared outcome/metric structures. `cloud_runner.py` is specifically the OpenAI adapter. |
| `naming.py`, `writers.py` | Compatible indexed names, reservation and no-overwrite checks, source/raw archives, evidence documents, logs, and summaries. |
| `extraction_v3.py`, `extraction_replay.py` | Versioned quotation contracts, strict JSON, deterministic location/evidence checks, and offline replay. |
| `modular_synthesis.py`, `synthesis_core/inventory_execution.py` | Independent proposal CLI, frozen-input request planning, native schema requests, response archiving, evaluation, and replay. No compiler. |
| `synthesis_core/inventory_ingest.py`, `inventory_schema.py`, `inventory_validation.py`, `inventory_v12.py`, `observation_refs.py` | Freeze accepted extraction-3.1 evidence, preserve older contracts, validate inputs/proposals, and manage lossless short references. |
| `synthesis_core/inventory_report.py`, `review_exports.py`, `inventory_evaluation.py` | Readable hierarchy, scientific review views, separate annotations, independent-proposal differences, and provisional semantic checks. |
| `inventory_workflow.py` | Thin connection between existing extraction, modular synthesis, and offline exports; separate model selections, no new inference architecture. |
| `synthesis.py`, `synthesis_core/ingest.py`, `schema.py`, `validation.py`, `inference.py`, `batching.py`, `staged_cli.py`, `corrections.py` | Historical Markdown-to-v2 dictionary and staged synthesis infrastructure. Retain for reproducibility; separate from the modular path. |
| `prompts/`, `schemas/`, `tests/fixtures/`, `examples/` | Versioned instructions/contracts, minimal repeatable inputs and archived examples. Old versions still protect historical replay. |

### Tests to retain

The test suite protects software reliability, not model vocabulary quality. It uses fixtures, mocked providers, and local SDK serialization; it does not intentionally generate model responses.

- Exact quotation, Unicode, offsets, ambiguity, derived fields, and legacy versions: `test_extraction_v3.py`, `test_extraction_v31.py`, and prompt tests.
- Six-model routing, aliases, provider forwarding, limits, completion, interruption and archival: model selection/alias tests, extraction pipeline/cloud tests, structured-output/thinking tests, and `test_output_token_cli.py`.
- Output collisions, late file races, symlinks, reservations and run IDs: `test_extraction_safety.py`, writer/naming tests, and v3 pipeline tests.
- Frozen provenance, role/link ownership, evidence, dispositions, equivalence, short maps and replay: modular synthesis, inventory, v1.2, observation-reference and context tests.
- Human-readable output, invalid diagnostic visibility, review approval binding, provisional semantics and independent differences: report presentation and inventory workflow tests.
- Historical dictionary validation, batching, incomplete responses, resume, correction binding and offline reconstruction: `test_synthesis.py`, `test_synthesis_batching.py`, and `test_synthesis_corrections.py`.

Tests for old prompts and validators are compatibility safeguards, not automatically obsolete development clutter. The review did not identify a test module safe to remove wholesale. Grouping documentation is preferable to weakening invariants.

### Verification on 15 October 2026

Executed on macOS with Python 3.14.3:

```sh
python -m pytest -p no:cacheprovider
python -m ruff check --no-cache .
python -m ruff format --check .
python -m pip check
```

Results: **734 tests passed**; Ruff lint passed; Ruff formatting checks passed; dependency consistency check passed. One Google SDK/Python deprecation warning remains. This is not a clean-room installation test or a Windows result.

The installed key versions were Ollama client 0.6.2, OpenAI 3.20.0, Anthropic 1.9.0, Google GenAI 2.25.0, Pydantic 2.13.5, pytest 9.1.1, and Ruff 0.16.8. Record dependency versions for each research environment; they are not locked by the project.

CLI help was checked for extraction, extraction replay, modular synthesis, the connected workflow, and historical synthesis. Offline checks exercised synthetic proposal replay, concise Markdown rendering, review exports with provisional evaluation, a six-model extraction preview, a v1.2.4 frozen-input synthesis preview, and the connected workflow preview. Historical extraction and research proposal replay were also checked without generation. A missing-default-input simulation and a relocated copy of the synthetic archive were checked outside the repository.

Installation commands, dependency downloads, GitHub access, Windows execution, Ollama downloads, and live/cloud generation were not executed for this documentation task. The live tutorial is an explicitly labeled operation, not a claimed new experiment. Default prompts, production code, schemas, model configuration, and historical archives were not changed.

### Further reading

- [Extraction v3 contracts and operation](extraction-v3.md)
- [Modular synthesis v1.2](modular-synthesis-v1-2.md)
- [Connected workflow and review annotations](inventory-workflow.md)
- [Controlled comparison considerations](model-comparison.md)
- [Historical architecture overview](architecture.md)
- [Historical synthesis CLI guide](../SYNTHESIS.md)

Some older guides describe earlier milestones or defaults. For this research baseline, use the explicit prompt/contract selections above and actual CLI help. The architecture, decisions, and reproducibility guides preserve the October 12 staged-synthesis checkpoint. Use this manual for the current modular workflow.

## 14. Read-only repository audit and proposed cleanup

**Historical audit:** this appendix preserves the inspection before handoff preparation.
The [handoff report](GITHUB_HANDOFF.md) supersedes its cleanup and ignore-rule
recommendations where it records completed work; counts and unchanged-file claims
below belong to that earlier pass. They are not a new verification of this edited
documentation set.

This appendix records handoff recommendations, not authorization to delete, move, stage, or publish anything. Paths below are relative to `projects/1-Feature_Dictionary`. The only file created in this documentation pass was this manual; 650 pre-existing non-cache/environment files were checked for unchanged contents.

### A. Essential — keep

Keep the production package, entry points, `pyproject.toml`, `settings.json`, active prompts, all historical contracts needed for replay, and corresponding tests/fixtures. There are 35 Python source files and 31 test modules. Older synthesis code remains operational compatibility infrastructure, not an abandoned prototype. No separate obsolete debugging scripts were found in the project.

Keep `tests/fixtures/synthesis_v12_run/`, `tests/fixtures/synthesis_v1/`, both sample source text fixtures, and the provisional reference. Keep `examples/synthesis_v2/` and the original `examples/synthesis_batched/` inputs/run/dictionary/validation/summary: tests replay those artifacts directly. Do not delete them to simplify the folder tree.

### B. Useful — keep or consolidate after approval

| Exact paths | Recommendation and dependency check |
| --- | --- |
| `README.md`; `SYNTHESIS.md`; `docs/architecture.md`; `docs/data-contracts.md`; `docs/decisions-and-limitations.md`; `docs/extraction.md`; `docs/testing-and-reproducibility.md` | Keep historical explanations. Later make the README a shorter entry point and label legacy sections clearly. Some content describes v2 rather than current modular synthesis; a default-input-size statement in README no longer describes the present local file. Internal Markdown links checked here resolve. No other documentation was edited. |
| `docs/extraction-v3.md`; `docs/modular-synthesis-v1.md`; `docs/modular-synthesis-v1-2.md`; `docs/inventory-workflow.md`; `docs/model-comparison.md`; `docs/six-model-trial.md` | Keep technical detail, but consolidate operating instructions around this manual. Several defaults/examples intentionally select older prompt versions; do not reinterpret those as current baseline instructions. |
| `CHECKPOINT.md` | Retain as a dated historical checkpoint. Its 258-test count, 1,200-token cap, and earlier context settings are not current defaults. Preserve its correction-authorization caveat. |
| `prompts/Initial Promt.txt` and all earlier extraction/synthesis prompt versions | Keep or archive with their experiments. The initial prompt is inactive, but documentation references it and historical requests may depend on its text. Old prompt tests protect reproducibility. Do not overwrite versions. |
| `examples/synthesis_v12_sample.md`; `examples/synthesis_v12_readable_sample.md` | Candidate for later consolidation to one readable showcase. The modular-v1.2 guide still references the older sample; fix that reference only with approval before removing it. Neither is required by production execution. |
| `examples/acanthophis_inventory_review_v1/`; `examples/synthesis_v2/archives/parser_regression_response.json` | Useful real review and historical failure examples. No active code/test lookup of the parser-regression filename was found, but the original failure is useful provenance. Retain or archive deliberately, rather than delete as scratch output. |
| `feature_dictionary/runners/_init_.py` | Empty, misspelled package-marker file. No execution import targets it; a historical execution manifest records its hash and older documentation notes it. Treat namespace/package cleanup as a separate small code decision, with an installation check, rather than removing it during documentation work. |

Tests import helper functions from other test modules, including `test_cli.py`, `test_cloud_extraction.py`, `test_extraction_v3_pipeline.py`, and `test_modular_synthesis_runner.py`. Deleting a seemingly old module can therefore break other tests. If helper organization becomes troublesome, a later small consolidation can move genuinely shared fixtures without dropping assertions. No such change is needed for this handoff.

### C. Obsolete/disposable — removal candidates requiring approval

| Exact paths | Reason and dependencies |
| --- | --- |
| `tests/250k`; `tests/ALL_SNAKES!!!.txt` | Both are zero-byte ignored local placeholders, not Python tests or actual experiment records. Searches found only ignore/documentation references, no code/test dependency. Update historical layout notes if removing these names. |
| `examples/synthesis_batched/run/reconstructions/20261009_215247_3517aae78268/`; `examples/synthesis_batched/run/reconstructions/20261009_215549_0375b8e33e7d/` | Each contains only dictionary, validation, and run-summary JSON byte-identical to the retained original example files. No named code/test/document dependency was found. Keep the original example run and its checkpoints/jobs. These duplicate offline replay exports can be regenerated without generation. |
| `.pytest_cache/`; `.ruff_cache/` | Recreated tool caches, excluded from Git; no research evidence. Tests and lint do not require their existing content. |
| `feature_dictionary/__pycache__/`; `feature_dictionary/runners/__pycache__/`; `feature_dictionary/synthesis_core/__pycache__/`; `tests/__pycache__/` | Recreated Python bytecode, excluded from Git; source and tests remain authoritative. |
| `.DS_Store`; `extractor_outputs/.DS_Store`; `feature_dictionary/.DS_Store`; `review_outputs/.DS_Store`; `synthesis_outputs/.DS_Store`; `review_outputs/acanthophis_claude_short_review_01/.DS_Store` | macOS folder-view metadata; no code/test/evidence dependency. The parent repository already ignores these names. |

Do not classify the active `.venv/` as scientific evidence or ship it in Git; recreate it for installation. It is still needed by the current local working environment. Preserve `.env` privately. Preserve run receipts, hidden input/prompt archives, and lock files; a lock's mere presence does not prove it is stale.

### D. Experimental archives — preserve with a retrieval plan

The bulk local roots are `extractor_outputs/` (about 1.10 MB), `extractor_logs/` (0.22 MB), `synthesis_outputs/` (11.99 MB), and `review_outputs/` (2.55 MB), measured in decimal units. These are modest today; the issue is reviewability and distribution, not an immediate file-size emergency. `Test Data/` is local research input, not disposable clutter. Confirm source-sharing permission before publishing specimen descriptions or project-plan material.

Keep a compact reproducible GitHub example set in the existing `examples/` and `tests/fixtures/` layout. Prefer one valid complete baseline bundle and representative failures, with their command/settings/version records. Preserve the complete six-model comparison, including failures, in approved research storage if not shipping it in GitHub.

Protect these exact current baseline dependencies together:

- `extractor_outputs/v314_gemini_8192_01/` and its matching `extractor_logs/v314_gemini_8192_01/`.
- `extractor_outputs/v314_qwen_ctx16384_01/` and its matching `extractor_logs/v314_qwen_ctx16384_01/`.
- `synthesis_outputs/acanthophis_v124_claude_01/`, including frozen input and source archives.
- `synthesis_outputs/acanthophis_v124_gpt_01/`, `synthesis_outputs/acanthophis_v124_gemini_01/`, `synthesis_outputs/acanthophis_v124_qwen_01/`, `synthesis_outputs/acanthophis_v124_deepseek_01/`, and `synthesis_outputs/acanthophis_v124_llama_01/`.
- `review_outputs/acanthophis_v124_claude_01/` and `review_outputs/acanthophis_v124_six_model_comparison_01/`.

Earlier controlled trials and legacy archives, including `synthesis_outputs/mid_batched_test/`, remain research records. No blanket removal is recommended. External archival should preserve original paths in provenance, include a checksum/retrieval manifest, and pass a copied-bundle offline replay before any later approved move.

### GitHub readiness findings at the original audit

1. **Supply the current implementation.** At audit time, 71 project files were tracked and 152 nonignored files were untracked, including this new manual. Many current modules, fixtures, schemas, and prompts were absent from the tracked set. Review their inclusion explicitly before a later authorized commit; this task made no commit.
2. **Resolve the ignored default input.** `species_database.txt` is excluded by the parent repository. A new clone cannot load the current shared settings without supplying it, even for some synthesis commands. The guarded sample-copy workaround above was tested. Discuss a default-fixture/configuration improvement separately; no default was changed.
3. **Choose the research archive delivery method.** Live extraction/synthesis roots are ignored, so a clone lacks the 130-observation baseline. Review exports and `workflow_outputs/` are not ignored and can be accidentally staged. Propose explicit ignore rules plus selected curated examples; do not ignore all `examples/` or fixtures. `.env`, environments, caches, and OS metadata are already covered by project/parent rules. A targeted credential-pattern scan found potential key material only in ignored, untracked `.env`; no values were displayed. This is not a complete secret-history/security audit.
4. **Record a tested dependency environment.** `pyproject.toml` declares dependencies but has no lockfile, and some provider SDKs have no lower bound. The current environment is consistent, but a future fresh resolution may differ. Native Anthropic support also depends on SDK functionality. Prompt/settings files outside the package mean an ordinary wheel should not be advertised as self-contained. Keep the editable checkout installation until packaging is tested.
5. **Finish portability and navigation checks.** Windows needs an actual acceptance test, particularly Unicode, symlinks, interrupted requests, and legacy Unix locks. The reviewed production code/settings/documentation did not contain `/Users/` or `/home/` paths, but archived inputs/requests contain original machine paths. Frozen replay preserves them; refreezing relocated extraction can change IDs. Obtain approval before consolidating existing documentation or changing ignore rules.

The recommended GitHub structure is the current one: entry point and configuration at project root, production modules in `feature_dictionary/`, versioned `prompts/` and `schemas/`, tests and compact fixtures in `tests/`, curated reproducible material in `examples/`, and operating guidance in `docs/`. No production reorganization or architectural redesign is needed for the handoff.
