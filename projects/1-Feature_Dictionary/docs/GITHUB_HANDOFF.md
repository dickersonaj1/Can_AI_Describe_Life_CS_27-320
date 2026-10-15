# GitHub handoff preparation — 15 October 2026

This is a minimal packaging/documentation cleanup of the working research tool,
not a pipeline refactor. Production code, model settings, prompts, schemas,
fixtures, and meaningful historical experiment records remain unchanged. No model
requests, Git staging, commits, or pushes were performed during preparation.

## Scope of this report

This dated report preserves the earlier packaging preparation and its verification
results. Its counts, file sizes, preservation claims, and Git-state observations
are snapshots of that work, not newly rerun checks after documentation edits.
The proposed manifest remains a proposal; this report does not establish that a
commit or push has occurred.

The current modular research baseline explicitly selects extraction **v3.1.4**
(extraction-3.1) and synthesis **v1.2.4** (synthesis-1.2). It keeps independent
proposals for review. Start with the [manual](USER_MANUAL.md); use the
[comparison guide](model-comparison.md) for controlled experiments. The
[architecture](architecture.md), [decisions](decisions-and-limitations.md), and
[reproducibility](testing-and-reproducibility.md) guides preserve legacy staged
synthesis details from October 12.

## Start with the offline example

Install from the project directory as described in the [user manual](USER_MANUAL.md).
The handoff includes `tests/fixtures/synthesis_v12_run/`: an 11-observation,
self-contained frozen input plus saved request, response, and validation. Its
provider is explicitly `offline` and its model is `fixture`. This is a synthetic
software example, not a new live biological result.

After installation, these commands require no API keys, private data, Ollama,
or ignored default input file:

```sh
python -m feature_dictionary.modular_synthesis --replay-job tests/fixtures/synthesis_v12_run/job_000
python -m feature_dictionary.inventory_workflow --render-job tests/fixtures/synthesis_v12_run/job_000 --output-dir review_outputs/first_offline_01 --reference-fixture tests/fixtures/reference/acanthophis_inventory_v1.json
```

Use a new export destination when repeating. Expected files are
`proposal_000/terminology_inventory.md`, `terminology_inventory.json`,
`scientific_review.md`, and `semantic_evaluation.json`, plus the root
`proposal_differences.md`. Validation should pass; scientific verification remains
false. Semantic expectations are provisional.

Other operations that load shared settings still need its configured
`species_database.txt`. This ignored research input is deliberately not shipped.
The guarded sample-copy step in the manual supplies an existing fixture locally
without changing configuration or overwriting an existing research source.

## Actual cleanup and dependency checks

Removed only these audited disposable items:

- `tests/250k` and `tests/ALL_SNAKES!!!.txt`: zero-byte local placeholders. Only
  documentation/ignore mentions were found, with no execution/test dependency.
- `examples/synthesis_batched/run/reconstructions/20261009_215247_3517aae78268/`:
  its three files (`dictionary.json`, `validation.json`, `run_summary.json`) were
  byte-identical to the corresponding retained files in `examples/synthesis_batched/`.
  Exact path searches through source, tests, documentation, and archived text/JSON
  found only the removal-candidate mention in the earlier audit. No operational or
  provenance reference was found. The original fixture run/checkpoints remain.
- Existing `.pytest_cache/`, `.ruff_cache/`, and `__pycache__/` under
  `feature_dictionary/`, `feature_dictionary/runners/`,
  `feature_dictionary/synthesis_core/`, and `tests/`.
- `.DS_Store` at project root and in `extractor_outputs/`, `feature_dictionary/`,
  `review_outputs/`, `synthesis_outputs/`, and
  `review_outputs/acanthophis_claude_short_review_01/`.

**Preserved despite being byte-identical:**
`examples/synthesis_batched/run/reconstructions/20261009_215549_0375b8e33e7d/`.
The expanded provenance check found a direct `run_summary` reference in
`synthesis_outputs/batched_offline_example_test.json.run.json`. That dependency
was missed by the earlier narrower audit. Neither the directory nor the provenance
file was edited. The generated reconstruction remains local and ignored; it is
not required by the proposed offline Git example. Any later removal requires a
separate decision about that historical provenance, not silent relinking.

The empty `feature_dictionary/runners/_init_.py` remains: package-marker cleanup
would be a separate code decision. The active virtual environment, private `.env`,
run locks/receipts, original input/prompt snapshots, and all non-disposable live
success/failure records remain in place. No test module was removed.

## Explicit proposed staging set

[github-staging-paths.txt](github-staging-paths.txt) lists every proposed path,
one per line, relative to this project directory. It includes existing tracked
files as well as the essential currently untracked implementation, to capture a
complete working handoff. It does not stage itself automatically.

The list covers:

- All production Python modules and extraction entry point, including modular
  synthesis, evidence replay, review exports, and legacy compatibility modules.
- All 31 test modules, shared test configuration, and all 13 fixture files.
- All 16 prompt versions and all 11 schemas, including historical versions.
- The user manual, handoff notes, existing technical documentation, README,
  SYNTHESIS guide, and historical CHECKPOINT.
- `settings.json`, `pyproject.toml`, `.gitignore`, and the optional verified
  dependency constraints.
- The original synthetic v2/batched examples used by regression tests and both
  existing synthetic v1.2 Markdown samples.

Before staging, review the exact list and working changes. From this project
directory, the future explicit staging command is:

```sh
git add --pathspec-from-file=docs/github-staging-paths.txt
git diff --cached --stat
```

These are instructions for a later authorized staging step. They were not run.
Do not substitute `git add .`, change the working directory for this command, or
assume that ignored local research archives will be included. Review any later
new files before adding them to the manifest.

### Intentionally outside the staging proposal

- Generated `extractor_outputs/`, `extractor_logs/`, `synthesis_outputs/`,
  `review_outputs/`, and `workflow_outputs/`, including all meaningful failures.
  They remain on disk; no archival reorganization was performed.
- Generated reconstruction exports and `examples/synthesis_batched/run/run.lock`.
  Ignore rules prevent accidental staging; existing local files are preserved.
- `Test Data/`, `species_database.txt`, `.env`, environments, caches, credentials,
  and OS metadata.
- `Can AI Describe Every Reptile_ Project Plan - 09:11:2026.pdf` and
  `examples/acanthophis_inventory_review_v1/`: preserved, untracked, and withheld
  from this minimal plan pending a source-sharing decision. Neither is needed
  to run tests or the small offline workflow. They are deliberately not hidden
  by blanket ignore rules for PDFs or curated examples.

The 130-observation research baseline is still available locally, but is not a
fresh-clone dependency. Deliver that complete bundle separately if Amro needs to
reproduce the real six-model analysis. Preserve its frozen input, extraction
sidecars/hidden snapshots, source archives, model requests/responses, failures,
reference mapping, settings/code records, and comparison reports together.

## Dependency installation recommendation

`pyproject.toml` remains authoritative and unchanged. The new
[constraints-verified-py314.txt](../constraints-verified-py314.txt) pins the **40
installed packages in the runtime/test dependency closure** for the verified
macOS/Python 3.14.3 environment. It excludes unrelated installed tools, the local
editable project, and pip. No package was upgraded, installed, or removed here.

To target those versions in a fresh Python 3.14 environment:

```sh
python -m pip install -c constraints-verified-py314.txt -e ".[dev]"
python -m pip check
```

This is an optional constraint snapshot, not a complete cross-platform lockfile.
It does not pin downloads by hash, wheel artifacts, isolated build dependencies,
or additional platform-specific requirements. In particular, `hatchling` is the
unchanged build backend and is not installed in the current runtime environment;
a fresh editable installation must obtain it in its isolated build environment.
Windows/other Python versions need a separately verified resolution. Do not claim
that a macOS dependency snapshot certifies those platforms.

Keep editable installation from a full checkout: prompts/settings live outside
the Python package, so a normal wheel is not yet a verified self-contained product.
A build-backend pin, hashed lockfile, Windows acceptance run, or package-data change
should be separate, reviewed work rather than part of this minimal cleanup.

## Verification

Preparation verifies both the working tree and a clean source tree assembled from
only the exact staging manifest, with no `.env`, virtual environment, live archives,
private dataset, or ignored `species_database.txt` copied into it. Tests in that
clean tree use the already-installed verified dependency environment; this checks
file completeness and import isolation, not a new dependency download/install.

Commands checked include the full offline test suite, Ruff lint/formatting,
synthetic replay and review export, and the documented settings-input workaround.
The source-tree check also confirms package imports resolve inside the clean
copy rather than falling back to the original editable checkout. Credential and
machine-path scans report file locations/counts rather than secret values.

Detailed outcomes and staging counts are recorded at the end of this document
after verification. No live availability, billing, local inference, or Windows
execution is implied by offline success.

## Remaining decisions and portability

The minimal source/test/offline-example handoff does not require publishing real
experiment archives or the project-plan PDF. Decide their sharing permissions
and delivery location separately. The referenced duplicate is preserved until
its provenance can be handled explicitly.

Windows acceptance remains unverified. Legacy batching/correction operations use
Unix-only `fcntl`; symlink tests may need Windows privileges; UTF-8/default-decoding
and interruption behavior need actual Windows checks. The manual documents these
limits. Historical fixture metadata may contain old paths without requiring
those files locally; do not rewrite fingerprints merely to cosmetically remove
provenance. Distinguish such inert text from a genuine runtime dependency.

## Verified results and final inventory

| Proposed group | Files | Currently untracked |
| --- | ---: | ---: |
| Production Python | 35 | 14 |
| Tests, shared configuration, and fixtures | 45 | 36 |
| Prompts | 16 | 13 |
| Schemas | 11 | 9 |
| Documentation and staging manifest | 14 | 14 |
| Synthetic compatibility examples | 32 | 2 |
| Root entry/configuration/dependency/documentation files | 8 | 2 |
| **Total** | **161** | **90** |

The root files are `.gitignore`, `README.md`, `SYNTHESIS.md`, `CHECKPOINT.md`,
`extractor.py`, `pyproject.toml`, `settings.json`, and
`constraints-verified-py314.txt`. Total proposed content is approximately **1.29 MB**;
no proposed file exceeds 1 MB. The largest is the user manual (about 69 KB).

- **Working tree:** 734 tests passed; Ruff lint and formatting passed; installed
  dependency consistency passed. One existing Google SDK/Python deprecation
  warning remains.
- **Clean proposed file set:** 733 tests passed, one expected skip, and Ruff lint
  and formatting passed. The skipped test reads the optional ignored research
  archive `extractor_outputs/v3_live_no_thinking/`; no required fixture is missing.
- **Fresh-clone test correction:** the first clean run exposed six alias-test
  failures because `test_project_aliases_resolve_to_full_identities_without_enabling_extra_models`
  loaded the ignored default input. Only that test was adjusted to use the existing
  `extraction_v31_smoke.txt` fixture, including its default-model assertion.
  Assertions were retained; no production loading behavior or default changed.
  The complete clean suite then passed without `species_database.txt`.
- **Offline example:** replay passed with `proposal_valid=true` and scientific
  verification false. All five documented review/export files were generated in
  the disposable clean copy with cloud credential variables unset, no `.env`, no
  Ollama, and no private/default source file. No model call was made.
- **Manual settings workaround:** after the no-default-input checks, the existing
  specimen fixture was copied only into the disposable tree as instructed by the
  manual. A v1.2.4 short-reference synthesis dry run then passed with 11 observations
  and created no run directory. No research data or repository setting changed.
- **File checks:** manifest paths exist, are explicit relative regular files, and
  are not ignored. Required source imports resolve inside the clean copy. Relative
  documentation links are checked against that proposed tree. Targeted scans found
  no credential-shaped values or concrete machine-specific paths in proposed
  files. This is not a full credential-history/security audit.
- **Preservation:** hashes confirmed all 530 protected source/prompt/schema/config
  and meaningful experiment-archive files retained their original content. The
  only changed existing files are `.gitignore`, `README.md`, `docs/USER_MANUAL.md`,
  and `tests/test_model_aliases.py`; new files are this handoff note, its explicit
  staging manifest, and the optional constraint snapshot.
- **Git state:** the actual index remains unchanged. No staging, commit, push,
  historical archive move, paid request, or local generation was performed.
  The explicit staging command was checked with `--dry-run` against a temporary
  copy of the index; it identified 108 changed/new paths and left the real index
  byte-identical. An ordinary dry run could not create the parent repository's
  index lock within this task's filesystem permissions, so no permission
  expansion or real-index write was needed.

The clean-copy test used the existing verified SDK environment and a temporary
source tree, not a fresh Git clone plus downloaded dependency installation.
Internet installation/build-backend resolution and native Windows acceptance
remain untested. None of these limits is hidden by changing tests, validators,
production defaults, or historical experiment records.
