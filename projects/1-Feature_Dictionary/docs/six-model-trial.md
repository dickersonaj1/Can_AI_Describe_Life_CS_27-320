# Preparing the first six-model extraction trial

This preparation changes model selection and adds a prompt revision. It does not
run the experiment, change the extraction-3.1 data contract, or change evidence
checking. All results still require terminology-quality review by researchers.

## Selecting models reliably

`--models` previously assigned every unrecognized name to Ollama, even when that
same model had a cloud provider in settings. It now resolves against the configured
provider/model pairs before considering known model identifiers. Unknown names
produce an error instead of an unintended local request.

Use explicit selections for a reproducible trial:

| Selection | Provider | Model identity |
| --- | --- | --- |
| `ollama:qwen3:8b` | Ollama | `qwen3:8b` |
| `ollama:deepseek-r1:8b` | Ollama | `deepseek-r1:8b` |
| `ollama:llama3.1:8b` | Ollama | `llama3.1:8b` |
| `openai:gpt-5.4-nano` | OpenAI | `gpt-5.4-nano` |
| `anthropic:claude-sonnet-4-5-20250929` | Anthropic | `claude-sonnet-4-5-20250929` |
| `gemini:gemini-3.8-flash` | Gemini | `gemini-3.8-flash` |

These are the project's existing model identifiers, not a claim that each provider
currently offers access to them. Selection does not contact a model catalog.

The `model_aliases` object in `settings.json` is now the configurable source for
the six short names:

| Alias | Expanded selection |
| --- | --- |
| `qwen` | `ollama:qwen3:8b` |
| `deepseek` | `ollama:deepseek-r1:8b` |
| `llama` | `ollama:llama3.1:8b` |
| `gpt` | `openai:gpt-5.4-nano` |
| `claude` | `anthropic:claude-sonnet-4-5-20250929` |
| `gemini` | `gemini:gemini-3.8-flash` |

Each alias stores separate `provider` and `model` fields. Versions can be changed
in configuration without changing runners. Alias definitions are direct identities;
they cannot refer recursively to other aliases. Aliases do not enable additional
models when `--models` is omitted. Existing default selection remains unchanged.

The legacy `provider=model` form remains supported. Bare configured IDs and the
three local names above also work. Older settings files without `model_aliases`
retain the existing cloud compatibility aliases.
A bare provider name selects its unique configured model. If none is configured
for a cloud provider, its existing compatibility default is used. Multiple
configured choices require qualification. An explicitly configured provider-named
alias such as `gemini` chooses its defined identity. An alias colliding with a
different native model name is ambiguous and requires qualification. Unknown or
ambiguous bare names and duplicate provider/model pairs are errors.
Other local model names can be configured or selected explicitly with `ollama:`.

Do not shorten identifiers into `openai.4-nano` or `gemini.8-flash`. Unless those
strings are actual configured model IDs, they are unknown. The separate provider
and full native model identity must be preserved. Omitting `--models` still uses
the original configured list without changing its order.

Output indices follow selection order. Execution remains grouped by provider as
before. Identical labels from different providers remain distinct selections and
receive distinct indexed filenames. Repeating the same provider/model pair in one
CLI selection is rejected; use separate runs for intentional replicates.

## Prompt revision 3.1.2

Select `prompts/extraction_v3_1_2.txt` explicitly. Previous prompt files and the
default prompt selection are unchanged. The output contract remains extraction-3.1.

The new instructions retain anatomical head nouns and meaningful embedded
expressions, while distinguishing technical vocabulary from generic narration.
In the smoke-test contexts, `scale rows` remains relevant but standalone `rows`
does not; `prominent` is a generic description rather than an established technical
state. `number` used as an ordinary verb, `were counted`, and `is visible` are also
excluded. These are contextual examples, not a global banned-word list.

The examples now omit generic standalone `rows`. They use compact evidence phrases
such as `dorsal scales` and `scale rows`. Instructions ask for the shortest meaningful
terminology-bearing expression that preserves necessary embedded context, with
exact quotations, capitalization, and original grammatical form.

## Preview without model requests

From the project folder:

```sh
.venv/bin/python extractor.py \
  --extraction-format v3 \
  --v3-candidate-version 3.1 \
  --prompt-file prompts/extraction_v3_1_2.txt \
  --models qwen,deepseek,llama,gpt,claude,gemini \
  --ollama-think false \
  --input tests/fixtures/extraction_v31_smoke.txt \
  --output-dir extractor_outputs/v31_six_model_aliases \
  --log-dir extractor_logs/v31_six_model_aliases \
  --dry-run
```

This prints model routing, prompt identity, limits, and destinations. It does not
verify installed models, credentials, remote model access, or model quality. It
creates no experiment artifacts. Keep the preview flag until the trial is reviewed.

## Checks still needed before a live trial

The installed Ollama Python client supports the `think` request parameter. The
current flag applies to all selected local models, not just Qwen. Qwen's earlier
reasoning-only failure motivates requesting it off, but server/model support for
the other local models has not been verified by this preparation. An unsupported
explicit mode produces an error rather than an automatic retry. Cloud providers
never receive this flag. Local model installation and server availability also
remain unverified because this preparation makes no live requests.

Cloud configuration uses `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and either
`GOOGLE_API_KEY` or `GEMINI_API_KEY`. The installed Google SDK accepts both and
prioritizes `GOOGLE_API_KEY`. Key presence does not establish validity, billing
availability, or model permissions. Never include credential values in research
reports or experiment artifacts.

## Developer reference

`settings.parse_model_selection()` resolves CLI selections against the original
settings list and validated `model_aliases` before `load_settings()` applies the
override. `MODEL_ALIASES` remains alongside that resolver as a compatibility
fallback for older settings. It is not a second resolver. `cli.MODEL_ALIASES` and `cli._parse_models` remain
available as compatibility exports. The CLI passes the selector string through
to settings so provider information is not lost early.

`tests/test_model_selection.py` covers qualified and legacy syntax, configured
identities, ambiguity, duplicates, cloud/local isolation, and mixed execution with
stable indices and archives. `tests/test_extraction_prompt_v312.py` checks grounded
JSON examples and contextual guidance. These offline tests cannot prove that a
live model follows the new quality instructions. Provider runners, quotation
validation, schemas, synthesis, and historical experiment artifacts are unchanged.

`tests/test_model_aliases.py` verifies configurable versions, all six aliases,
local/cloud/mixed selection, native metadata, duplicate identities, ambiguity,
invalid definitions, and compatibility with older settings and explicit syntax.
