# Controlled model comparisons

Use fresh destinations for every trial and replicate. Keep all raw responses,
failures, validation reports, and source archives. Never edit a historical prompt
or answer. Preview each command with `--dry-run`; generation requires approval.
Aliases below use existing project configuration, not verified provider availability.

## Compare extraction models independently

Run extraction only on one fixed source with one fixed prompt and contract:

```sh
python extractor.py \
  --input tests/fixtures/acanthophis_antarcticus_real.txt \
  --extraction-format v3 --v3-candidate-version 3.1 \
  --prompt-file prompts/extraction_v3_1_4.txt \
  --models qwen,gemini --ollama-think false \
  --ollama-output-format candidate-schema --anthropic-output-format candidate-schema \
  --max-output-tokens 8192 \
  --output-dir extractor_outputs/comparison_extraction_01 \
  --log-dir extractor_logs/comparison_extraction_01 --dry-run
```

Remove `--dry-run` only after approval. Compare evidence acceptance, completion,
missed vocabulary, unsupported candidates, and advisor-assessed relevance. Do not
use downstream synthesis differences to score extraction alone.

## Current synthesis baseline: v1.2.4

For a portable preview after installation and the manual’s sample-default-input
step, use the handoff’s 11-observation synthetic frozen input:

```sh
python -m feature_dictionary.modular_synthesis \
  --settings settings.json --inputs tests/fixtures/synthesis_v12_run/inputs.json \
  --models claude --proposal-version 1.2 --observation-refs short \
  --prompt-file prompts/synthesis_inventory_v1_2_4.txt \
  --max-output-tokens 16384 \
  --run-dir synthesis_outputs/comparison_v124_fixture_01 --dry-run
```

This previews a new v1.2.4 experiment; replaying the saved fixture response instead
checks that archived proposal and does not rerun it under v1.2.4. The synthetic
input is a software exercise, not the 130-observation biological research baseline.
For controlled model comparisons, repeat with the same frozen input and prompt,
explicit model selections, and fresh destinations. Keep small-input and full-input
trials separate. See the [manual](USER_MANUAL.md) for setup and review exports.

## Historical synthesis comparison example: v1.2.2

The command below preserves the earlier v1.2.2 procedure and local extraction paths.
These archives are excluded from Git and must be supplied separately. It is not
the current v1.2.4 baseline. For a new baseline trial on those accepted extractions,
select `prompts/synthesis_inventory_v1_2_4.txt` explicitly and choose a fresh output
path; preserve the historical experiment unchanged.

Freeze the same accepted extraction selection for every synthesis model:

```sh
python -m feature_dictionary.inventory_workflow \
  --reuse-extraction extractor_outputs/v314_gemini_8192_01 \
  --reuse-extraction extractor_outputs/v314_qwen_ctx16384_01 \
  --synthesis-models claude,gemini \
  --synthesis-prompt prompts/synthesis_inventory_v1_2_2.txt \
  --synthesis-tokens 16384 \
  --reference-fixture tests/fixtures/reference/acanthophis_inventory_v1.json \
  --output-dir workflow_outputs/comparison_synthesis_01 --dry-run
```

After approval, remove `--dry-run`. Each model receives the same frozen input and
prompt, independently. Compare per-job review exports and `review/proposal_differences.md`.
Confirm matching input and rendered-prompt fingerprints before interpreting differences.
Inspect classifications, attachments, exclusions, unresolved observations, and exact
evidence separately from structural validity. The reference is provisional; matching
it does not establish biological correctness.

## Minimum experiment record

Keep one short record alongside each new experiment, excluding credential values:

- Trial ID, date, stage, replicate number, hypothesis, and reference/reviewer version.
- Exact command and resolved provider/model IDs; local model digest when available.
- Source bytes/fingerprint, accepted extraction paths, frozen input fingerprint,
  prompt version/template fingerprint, and rendered-prompt fingerprint.
- Contract/schema versions, settings snapshot, temperature, requested seed, context
  limit, output-token budget, thinking mode, schema constraints, timeout, concurrency,
  and any provider settings that were unsupported or omitted.
- Code revision plus a patch/snapshot of uncommitted code and dependency versions.
- Completion/error status, validation findings, returned token usage and duration,
  archive/export paths, and separate scientific review findings.

Use the archived fields where available; mark missing metadata as unavailable.
Provider constraints and seed support differ, so document differences rather than
claiming identical decoding. A fixed seed does not guarantee repeatable generation.
Keep failed trials in the comparison denominator and report the number of replicates.
Change only one prompt revision at a time while holding model/input/settings fixed;
then compare models under the selected revision. Preserve prior revisions.
Comparisons with different extraction inputs are end-to-end experiments, not controlled
synthesis-model comparisons. Reusing paths matters because source IDs include paths.

For local synthesis, preflight the frozen input against the configured context limit.
This workflow has no `--num-ctx` flag; select a separately saved settings file with
an adequate `options.num_ctx`, and record that file with the experiment.
