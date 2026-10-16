"""Thin extraction-to-independent-synthesis workflow and offline review exports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from feature_dictionary import cli as extraction_cli
from feature_dictionary import modular_synthesis
from feature_dictionary.cli import _positive_integer
from feature_dictionary.settings import SettingsError, load_settings
from feature_dictionary.synthesis_core.inventory_execution import missing_credentials, save
from feature_dictionary.synthesis_core.inventory_ingest import freeze_extractions
from feature_dictionary.synthesis_core.review_exports import export_job, write_disagreements

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=Path, default=[])
    parser.add_argument(
        "--reuse-extraction",
        action="append",
        type=Path,
        default=[],
        help="Accepted archives, reused without extraction calls; repeatable",
    )
    parser.add_argument(
        "--render-job",
        action="append",
        type=Path,
        default=[],
        help="Offline export of an archived v1.2 job; repeat for independent proposals",
    )
    parser.add_argument(
        "--review-annotations",
        type=Path,
        help="Optional separately confirmed scientific decisions for one --render-job",
    )
    parser.add_argument(
        "--reference-fixture",
        type=Path,
        help="Optional provisional semantic expectations; never biological approval",
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="Fresh workflow/export directory"
    )
    parser.add_argument("--settings", default=str(ROOT / "settings.json"))
    parser.add_argument("--extractor-models")
    parser.add_argument("--synthesis-models")
    parser.add_argument("--extraction-tokens", type=_positive_integer)
    parser.add_argument("--synthesis-tokens", type=_positive_integer)
    parser.add_argument("--ollama-think", choices=["true", "false", "default"])
    parser.add_argument(
        "--ollama-output-format",
        choices=["candidate-schema", "default"],
        default="candidate-schema",
    )
    parser.add_argument(
        "--anthropic-output-format",
        choices=["candidate-schema", "default"],
        default="candidate-schema",
    )
    parser.add_argument(
        "--extraction-prompt", type=Path, default=ROOT / "prompts/extraction_v3_1_4.txt"
    )
    parser.add_argument(
        "--synthesis-prompt", type=Path, default=ROOT / "prompts/synthesis_inventory_v1_2_2.txt"
    )
    parser.add_argument("--context-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    reference = None

    def evaluate_exports(exports, destinations):
        if reference is not None:
            from feature_dictionary.synthesis_core.inventory_evaluation import evaluate_reference

            for export, destination in zip(exports, destinations, strict=True):
                save(
                    destination / "semantic_evaluation.json", evaluate_reference(export, reference)
                )

    try:
        if args.reference_fixture:
            from feature_dictionary.extraction_v3 import parse_strict_json

            reference = parse_strict_json(args.reference_fixture.read_text())
            if (
                not isinstance(reference, dict)
                or reference.get("format_version") != "anatomical-reference-1.0"
                or reference.get("advisor_approved") is not False
                or not isinstance(reference.get("expectations"), list)
            ):
                raise ValueError("Expected a provisional anatomical-reference-1.0 fixture")
        if args.output_dir.exists():
            raise ValueError(
                "Choose a fresh output directory; workflow stages are never silently rerun"
            )
        if args.render_job:
            if args.source or args.reuse_extraction or args.dry_run:
                raise ValueError("Offline rendering cannot be combined with extraction or dry-run")
            if args.review_annotations and len(args.render_job) != 1:
                raise ValueError("Annotations require exactly one archived proposal")
            # Preflight all jobs before reserving an export destination.
            from feature_dictionary.extraction_v3 import parse_strict_json
            from feature_dictionary.synthesis_core.review_exports import build_export

            annotations = (
                parse_strict_json(args.review_annotations.read_text())
                if args.review_annotations
                else None
            )
            for job in args.render_job:
                build_export(job, annotations)
                if args.output_dir.resolve().is_relative_to(job.parent.resolve()):
                    raise ValueError(
                        "Choose an export directory outside the immutable synthesis run"
                    )
            args.output_dir.mkdir(parents=True, exist_ok=False)
            exports = [
                export_job(job, args.output_dir / f"proposal_{i:03d}", annotations)
                for i, job in enumerate(args.render_job)
            ]
            evaluate_exports(
                exports, [args.output_dir / f"proposal_{i:03d}" for i in range(len(exports))]
            )
            write_disagreements(args.output_dir, exports)
            print(str(args.output_dir))
            return 0
        if args.review_annotations:
            raise ValueError("Review annotations apply only to offline --render-job")
        if not (args.source or args.reuse_extraction) or not args.synthesis_models:
            raise ValueError("Supply --source and/or --reuse-extraction, and --synthesis-models")
        if args.source and not args.extractor_models:
            raise ValueError("New source extraction requires explicit --extractor-models")
        if len({p.resolve() for p in args.source}) != len(args.source):
            raise ValueError("Duplicate source selection")
        synthesis_overrides = {"models": args.synthesis_models}
        if args.synthesis_tokens:
            synthesis_overrides["max_output_tokens"] = args.synthesis_tokens
        synthesis_settings = load_settings(args.settings, overrides=synthesis_overrides)
        args.synthesis_prompt.read_text(encoding="utf-8")
        if args.reuse_extraction:
            freeze_extractions(args.reuse_extraction)
        extraction_commands = []
        for i, source in enumerate(args.source):
            command = [
                "--settings",
                args.settings,
                "--models",
                args.extractor_models,
                "--input",
                str(source.resolve()),
                "--extraction-format",
                "v3",
                "--v3-candidate-version",
                "3.1",
                "--prompt-file",
                str(args.extraction_prompt.resolve()),
                "--output-dir",
                str((args.output_dir / f"extraction_{i:03d}").resolve()),
                "--log-dir",
                str((args.output_dir / f"extraction_logs_{i:03d}").resolve()),
                "--ollama-output-format",
                args.ollama_output_format,
                "--anthropic-output-format",
                args.anthropic_output_format,
            ]
            if args.extraction_tokens:
                command += ["--max-output-tokens", str(args.extraction_tokens)]
            if args.ollama_think:
                command += ["--ollama-think", args.ollama_think]
            # Existing dry-run validates config/prompt/source without clients or files.
            if extraction_cli.main([*command, "--dry-run"]) != 0:
                raise ValueError(f"Extraction preflight failed for {source}")
            extraction_commands.append(command)
        paths = [
            *args.reuse_extraction,
            *[args.output_dir / f"extraction_{i:03d}" for i in range(len(args.source))],
        ]
        synthesis_command = [
            "--settings",
            args.settings,
            "--models",
            args.synthesis_models,
            "--proposal-version",
            "1.2",
            "--observation-refs",
            "short",
            "--prompt-file",
            str(args.synthesis_prompt.resolve()),
            "--run-dir",
            str(args.output_dir / "synthesis"),
        ]
        for path in paths:
            synthesis_command += ["--extraction-output", str(path)]
        if args.synthesis_tokens:
            synthesis_command += ["--max-output-tokens", str(args.synthesis_tokens)]
        if args.ollama_think:
            synthesis_command += ["--ollama-think", args.ollama_think]
        if args.context_file:
            synthesis_command += ["--context-file", str(args.context_file)]
        plan = dict(
            format_version="inventory-workflow-1.0",
            extraction_commands=extraction_commands,
            synthesis_command=synthesis_command,
            reused_archives=[str(p.resolve()) for p in args.reuse_extraction],
            scientific_approval=False,
            compiler_executed=False,
        )
        if args.dry_run:
            if not args.source and modular_synthesis.main([*synthesis_command, "--dry-run"]) != 0:
                raise ValueError("Synthesis preflight failed")
            print(
                json.dumps(
                    {
                        **plan,
                        "dry_run": True,
                        "synthesis_input_pending_extraction": bool(args.source),
                    },
                    indent=2,
                )
            )
            return 0
        # Fail before any generation if a later cloud stage lacks credentials.
        from dotenv import load_dotenv

        load_dotenv()
        models = list(synthesis_settings.settings.models)
        if args.source:
            models.extend(
                load_settings(
                    args.settings, overrides={"models": args.extractor_models}
                ).settings.models
            )
        missing = missing_credentials(models)
        if missing:
            raise ValueError("Missing credentials: " + ", ".join(missing))
        args.output_dir.mkdir(parents=True, exist_ok=False)
        save(args.output_dir / "workflow.json", plan)
        for i, command in enumerate(extraction_commands):
            code = extraction_cli.main(command)
            save(args.output_dir / f"extraction_{i:03d}_status.json", {"exit_code": code})
            if code != 0:
                print(
                    "Extraction stopped; archives retained. "
                    "Reuse accepted archives explicitly in a fresh workflow.",
                    file=sys.stderr,
                )
                return code
        # Strict ingestion rejects incomplete/unaccepted evidence; nothing is silently salvaged.
        freeze_extractions(paths)
        code = modular_synthesis.main(synthesis_command)
        save(args.output_dir / "synthesis_status.json", {"exit_code": code})
        jobs = sorted((args.output_dir / "synthesis").glob("job_*/response.json"))
        exports = [export_job(p.parent, args.output_dir / "review" / p.parent.name) for p in jobs]
        if exports:
            evaluate_exports(exports, [args.output_dir / "review" / p.parent.name for p in jobs])
            write_disagreements(args.output_dir / "review", exports)
        return code
    except (OSError, ValueError, SettingsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
