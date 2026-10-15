# Implemented decisions and remaining limitations

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

This guide separates choices already implemented from ideas still under
discussion. It also records research uncertainty plainly. It describes the
implementation inspected on October 12, 2026; it is not a promise that every
future experiment will behave identically.

## Why preserve the original wording?

Snake descriptions can contain informative compounds, historical spellings, and
abbreviations. Replacing them too early with a modern or broader name could erase
what the original material actually said.

**Implemented:** synthesis preserves saved extraction answers and their observation
records. Proposed concepts cite observed expressions. Unknown or questionable
records can remain unresolved instead of being deleted.

**Tradeoff:** this conservative rule can preserve awkward phrases as well as useful
terms. The current model may promote a descriptive sentence to a preferred expression.
Passing automated checks does not make that a good biological dictionary entry.

## Why keep concepts separate from their expressions?

“Dorsals” and “dorsal scales” may name the same concept in context. Conversely, the
same expression may carry distinct meanings. Neither shared words nor identical
spelling settles the biological question.

**Implemented:** concepts can have several observed expressions. Distinct senses
can remain separate, with explanatory notes. Cross-batch merging requires explicit
compatible decisions rather than automatic label matching or model majority vote.

**Tradeoff:** uncertainty can leave separate records that later need expert review.
The software cannot independently determine whether a model's proposed synonymy
is scientifically sound.

## Why use one collection of typed concepts?

Readers need to distinguish an anatomical structure, its characteristic, and a
state of that characteristic without losing how they are connected.

**Implemented:** structures, characteristics, character states, and unresolved
concepts share one collection, with a category on each record. A concept can have
multiple relationships without being copied for each parent.

**Tradeoff:** an incorrect category can prevent an otherwise plausible relationship
from passing the checks. The model must either classify the concept consistently
or preserve uncertainty; the program does not silently change categories to make
an answer pass.

## Why distinguish AI proposals from verification?

A model can suggest that “keeled” is a state of “keeling,” or that a characteristic
describes dorsal scales. These suggestions may be useful starting points. They
still require appropriate biological context and review.

**Implemented:** final relationships remain proposed model interpretations. The
dictionary is marked as requiring review. Citations document the terminology's
origin; agreement among models does not turn a relationship into verified biology.

**Not implemented:** an in-program process for recording a relationship as
scientifically verified. There is also no numerical confidence score. Expert
review and uncertainty are represented through current notes, outcomes, and
warnings, not a complete scientific approval system.

## Why save small synthesis jobs separately?

Large answers can be cut short. Repeating an entire experiment to recover one
failed portion can waste time and money.

**Implemented:** synthesis divides work into batches, saves each request and
answer, reuses valid work, and can split tasks that exhaust their output allowance.
It then compares concepts and relationships across batches. An offline
reconstruction uses saved responses without another model request.

**Tradeoff:** comparisons between many concepts can still be numerous. Comprehensive
relationship coverage increases scheduled work, not guaranteed scientific accuracy.
The text-size estimates are approximate and do not guarantee that every request
fits every model's allowance.

## Why refuse conflicting extraction outputs?

A repeated experiment should not quietly replace an earlier answer.

**Implemented:** conflicting answer destinations are refused. Existing logs are
also refused when configured for replacement; append-enabled logs keep their
previous behavior. Temporary directory reservations and exclusive file creation
provide additional protection. Run IDs include a timestamp and random identifier.

**Tradeoff:** repeated experiments need fresh output paths or non-conflicting
targets. A hard crash can leave a protected partial file or reservation. The
software does not automatically delete those records or decide that their owner
has stopped.

## Why save corrections separately?

A useful repair should not hide the AI's original mistake. For example, removing
an unsupported relationship should leave both the original claim and the reason
for its removal available to reviewers.

**Implemented:** corrections are separate records linked to original requests,
responses, inputs, and plans. They require a reason, explicit approval flags, and
successful checking before reuse. They retain an offline-edit warning in the
assembled result.

**Limitation:** approval flags are not attributable approval evidence. The current
batch 3 correction is registered and internally consistent, but its record does
not establish who authorized registration after an earlier instruction withheld
it. That distinction is documented in
[testing and reproducibility](testing-and-reproducibility.md).

## Research questions still open

| Question | What is currently known |
| --- | --- |
| How reliably are meaningful snake morphology terms extracted? | The tests check software handling, not extraction accuracy against an expert reference set. |
| How should long comparative phrases be handled? | They are preserved. Unresolved outcomes are possible, but general phrase decomposition is not implemented. |
| How accurate are synonyms, homonyms, languages, and acronym assignments? | They remain model proposals supported by recorded wording, not independently verified classifications. |
| Does comprehensive review find every biological relationship? | It schedules all type-compatible pairs; AI omissions, wrong categories, and missing source context can still hide relationships. |
| Does a valid file represent a complete dictionary? | No. It can preserve unresolved records and incomplete extraction sources. |
| Can the same live request reproduce exactly the same answer? | Not guaranteed. Reconstructing saved responses is different from requesting new ones. |

The original species descriptions and biological publications need their own
research record. Synthesis archives preserve extraction answers, which may omit
context needed to evaluate a proposed relationship.

## Deferred work, not current features

The following items have been discussed or identified but are not implemented as
part of this documentation checkpoint:

- Revised prompts to reduce full descriptive phrases, duplicate expressions, and
  incorrectly typed relationships.
- The proposed three-model synthesis architecture. Extraction supports six model
  families; current synthesis requests use OpenAI rather than all extraction providers.
- A separate clustering stage within this project.
- A biological verification workflow and attributable approval records.
- Extraction archives and request reuse comparable to staged synthesis.
- Fully consistent cancellation, cloud streaming, and provider-specific experiment controls.
- A locked dependency installation that recreates the same software versions.

These items require separate design and research decisions. Listing them here
does not authorize implementation or change the frozen experiment.

## Developer reference: technical debt

| Area | Current detail |
| --- | --- |
| Prompt paths | Active extraction uses `prompts/extraction_v2.txt`. Staged synthesis freezes three constants from `batching.py`; legacy single-request synthesis uses `prompts/synthesis.txt`. Their instruction detail differs. |
| Extraction configuration | `settings.json` still sets `max_output_tokens: 1200`; proposed larger starting allowances were not applied. Shared output cap does not imply shared sampling controls. |
| Failure control | `continue_on_error: false` does not consistently stop all provider failures. Legacy exception labels remain `error` versus `failed`. |
| Cancellation | Cloud requests are non-streaming. Thread cancellation and partial-result retention are not uniform at every interruption point. |
| Packaging | `runners/_init_.py` is misspelled; imports currently rely on namespace-package behavior. Some package descriptions still describe a local-only extractor. |
| Portability | Synthesis live execution and correction registration use `fcntl`, which requires a Windows portability review. |
| Identity | Source IDs depend on path and bytes. Term IDs depend on concept content, citations and notes; they are not experiment-independent ontology IDs. |
| Integrity and approval | Hashes detect content changes against recorded bindings; they do not authenticate an approver or establish scientific validity. |
| Resume/replay | Inputs/prompts are frozen, but current Python validation and assembly code are used. Dependency versions are recorded, not locked. |
| Archives | Extraction saves answer text/metrics, not the full provider response envelope. Legacy single-response and staged synthesis archives remain separate compatibility paths. |
| Coverage | Concept reconciliation can approach quadratic pair counts. Lightweight relationship review uses shared words; comprehensive review uses permitted type combinations. |

The underlying code, prompts, settings, and experimental archives were not changed
to address these items during documentation creation. The existing checkpoint
remains the record of the previously tested implementation.
