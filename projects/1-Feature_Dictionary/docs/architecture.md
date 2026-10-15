# Understanding the Feature Dictionary project

## Workflow scope and navigation

This guide preserves the **October 12, 2026** implementation, including legacy
staged synthesis. References to “current” behavior, defaults, tests, and deferred
features describe that checkpoint; do not assume its resume or correction behavior
applies to modular jobs.

For the current research baseline—extraction prompt **v3.1.4** and synthesis prompt
**v1.2.4**—start with the [user manual](USER_MANUAL.md),
[model-comparison guide](model-comparison.md), and [handoff report](GITHUB_HANDOFF.md).
See the [modular synthesis reference](modular-synthesis-v1-2.md) and
[connected workflow reference](inventory-workflow.md) for technical details.

This project is being developed jointly with VCU Life Sciences. It helps the Life
Sciences and Computer Science teams turn written descriptions of snakes into a
proposed dictionary of morphology: the observable structures and characteristics
of organisms.

The software helps researchers organize terminology. It does not decide that a
biological interpretation is scientifically correct. Its results remain proposals
for review, even when all automated checks pass.

This guide describes the implementation inspected on October 12, 2026. It begins
with the research purpose. The developer section contains the software map.

## Start with the research question

A snake description might mention **head scales**, **dorsal scales**, and scales
that are **keeled**. Different descriptions or AI models may use different words
for related ideas. They may also use the same word with different meanings.

The project preserves the wording that was found, compares interpretations, and
records proposed relationships. This allows a researcher to ask both “What concept
does this name?” and “Where did this interpretation come from?”

The following examples explain the intended distinctions. They are not a report
that these biological relationships have been independently verified.

| Example | What it helps describe |
| --- | --- |
| Dorsal scales | An anatomical structure |
| Keeling | A characteristic that may describe scales |
| Keeled | A state of that characteristic |

## Two separate stages

**Extraction** means finding candidate terminology in the supplied descriptions.
The selected AI models receive the text and instructions and return lists of
terms. These lists are saved before synthesis begins.

**Synthesis** means comparing and organizing those saved lists into a single
proposed dictionary. It can consolidate expressions for the same concept while
preserving distinctions, uncertainty, and the original records.

```mermaid
flowchart LR
    A[Written snake descriptions] --> B[AI lists candidate terms]
    B --> C[Save each model's answer]
    C --> D[Compare and organize the saved answers]
    D --> E[Check consistency and references]
    E --> F[Proposed dictionary for scientific review]
```

Saving answers between the stages matters. Researchers can examine an extraction
without synthesizing it. They can also reconstruct synthesis from saved material
without asking the extraction models again.

There is no clustering stage in this project's current implementation. Clustering
would mean automatically grouping items by a similarity measure. The current
cross-batch concept comparisons are part of synthesis, not a separate clustering
program.

## What the components contribute

| Component | Research purpose |
| --- | --- |
| Input descriptions | Supply the text being studied |
| Settings | Record which models, instructions, limits, and destinations are selected |
| Extraction instructions | Tell the AI what terminology to look for and how to present it |
| Model connections | Deliver the same prepared text to the selected models |
| Saved answers and run logs | Preserve returned text and information about the experiment |
| Observation records | Keep the individual lines from saved answers available for inspection |
| Synthesis batches | Make a large comparison task manageable without trimming observations |
| Concept reconciliation | Compare candidate concepts across batches before deciding which to combine |
| Relationship review | Propose connections between concepts, including concepts from different batches |
| Automated checks | Reject inconsistent records and broken references |
| Correction records | Keep a separate, explained edit alongside the original AI answer |

An **observation** has a specific meaning here: a record parsed from an AI
extraction answer. It is not a direct observation of a snake or specimen.

## What can be trusted about the result?

The software checks whether records obey its rules. For example, a relationship
cannot refer to a concept that is missing from the dictionary. A concept must have
one preferred expression, and its terminology must be supported by the cited
extraction observations.

These checks establish internal consistency and traceability. They do not establish
that “dorsals” and “dorsal scales” mean the same thing in every source context.
That interpretation may require examination of the original description and
review by a domain specialist.

Agreement among multiple AI models is information about the models' answers.
It is not independent biological verification.

## Reading guide

- [Extraction](extraction.md): how descriptions become saved term lists.
- [Data records and their meaning](data-contracts.md): how concepts, wording,
  relationships, and uncertainty are represented.
- [Testing and reproducibility](testing-and-reproducibility.md): what can be
  reconstructed, what tests establish, and how corrections are preserved.
- [Decisions and limitations](decisions-and-limitations.md): implemented choices,
  remaining uncertainties, and work that is not yet implemented.

The existing [synthesis guide](../SYNTHESIS.md) contains command-line workflows.
The [checkpoint](../CHECKPOINT.md) records the earlier tested state; it is a
historical record rather than an automatically updated status page.

## Developer reference: project layout

Paths in developer references are relative to the project root. Repeated generated
files are shown as patterns; their original names and contents remain unchanged.

```text
1-Feature_Dictionary/
├── extractor.py
├── settings.json
├── pyproject.toml
├── .gitignore
├── .env                         Local credentials; not documentation input
├── README.md
├── SYNTHESIS.md
├── CHECKPOINT.md
├── Can AI Describe Every Reptile_ Project Plan - 09:11:2026.pdf
├── species_database.txt
├── Test Data/
│   ├── short.txt
│   ├── mid.txt
│   ├── long.txt
│   └── 250k characters.txt
├── prompts/
│   ├── Initial Promt.txt
│   ├── extraction_v2.txt
│   └── synthesis.txt
├── feature_dictionary/
│   ├── __init__.py
│   ├── __main__.py
│   ├── settings.py
│   ├── context.py
│   ├── budget.py
│   ├── cli.py
│   ├── runner.py
│   ├── naming.py
│   ├── writers.py
│   ├── synthesis.py
│   ├── runners/
│   │   ├── _init_.py
│   │   ├── cloud_runner.py
│   │   ├── anthropic_runner.py
│   │   └── gemini_runner.py
│   └── synthesis_core/
│       ├── __init__.py
│       ├── ingest.py
│       ├── schema.py
│       ├── inference.py
│       ├── validation.py
│       ├── batching.py
│       ├── corrections.py
│       └── staged_cli.py
├── schemas/
│   ├── synthesis_candidate_v2.schema.json
│   └── feature_dictionary_v2.schema.json
├── docs/                        The five guides in this documentation set
├── tests/
│   ├── conftest.py
│   ├── test_settings.py
│   ├── test_context.py
│   ├── test_naming.py
│   ├── test_runner.py
│   ├── test_writers.py
│   ├── test_cli.py
│   ├── test_cloud_extraction.py
│   ├── test_extraction_pipeline.py
│   ├── test_extraction_safety.py
│   ├── test_synthesis.py
│   ├── test_synthesis_batching.py
│   ├── test_synthesis_corrections.py
│   ├── 250k
│   └── ALL_SNAKES!!!.txt
├── examples/
│   ├── synthesis_v2/            Saved synthetic example and legacy archives
│   └── synthesis_batched/       Saved synthetic staged run and reconstruction
├── extractor_outputs/          Historical Markdown answers, including run folders
├── extractor_logs/             Historical model logs and summaries
└── synthesis_outputs/
    ├── archives/               Legacy request/response archives
    ├── mid_batched_test/       Frozen live experiment and its correction artifacts
    └── *.json                  Offline example dictionaries and provenance sidecar
```

The local environment and caches also include `.venv/`, `.pytest_cache/`,
`.ruff_cache/`, `__pycache__/`, and macOS `.DS_Store` files. They are not pipeline
components. Some experiment inputs and outputs are excluded by `.gitignore`.

## Developer reference: module responsibilities

| Module | Implementation responsibility |
| --- | --- |
| `extractor.py`, `__main__.py` | Call `cli.main()`; the installed `feature-dictionary` command has the same entry point |
| `__init__.py` | Exposes selected settings helpers and the package version |
| `settings.py` | `load_settings()`, `resolve_settings()`, `read_prompt()`, `render_prompt()` |
| `context.py`, `budget.py` | `RunContext`, prompt identity, copied run options, and Ollama budget estimates |
| `cli.py` | Model selection, orchestration, client ownership, persistence coordination, reporting, exit codes |
| `runner.py` | Shared extraction result types, Ollama communication, streaming, repetition and interruption handling |
| `runners/*.py` | Provider-specific cloud communication and response-status interpretation |
| `writers.py`, `naming.py` | Reservations, exclusive creation, metadata, Markdown output/logs, indexed filenames |
| `synthesis.py` | Synthesis mode selection and legacy single-request/replay path |
| `synthesis_core/staged_cli.py` | Staged planning, execution/resume/replay, reconstruction and publication |
| `synthesis_core/ingest.py` | Source snapshots, line parsing, conservative normalization |
| `synthesis_core/schema.py` | Authoritative runtime data contracts |
| `synthesis_core/inference.py` | Legacy request archiving/evaluation and shared exclusive JSON writer |
| `synthesis_core/validation.py` | Integrity and semantic consistency checks; final ID assignment |
| `synthesis_core/batching.py` | Frozen plans, jobs, subdivision, reconciliation, relationship review, assembly |
| `synthesis_core/corrections.py` | Offline edit registration, bindings, revalidation and reuse |

The extraction-to-synthesis interface is saved Markdown. Neither stage calls the
other stage's runners. Synthesis can read a model default from `settings.json`,
but otherwise uses its own command-line configuration and frozen run plan.
