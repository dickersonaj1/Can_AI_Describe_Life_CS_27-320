"""Independent version 2 synthesis CLI. --replay never makes an API request."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from feature_dictionary.synthesis_core.inference import evaluate, request_synthesis, write_json
from feature_dictionary.synthesis_core.ingest import read_outputs

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROMPT_PATH = PROJECT_DIR / "prompts/synthesis.txt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=PROJECT_DIR / "extractor_outputs")
    parser.add_argument(
        "--output", type=Path, default=PROJECT_DIR / "synthesis_outputs/dictionary.json"
    )
    parser.add_argument(
        "--model", help="OpenAI model; defaults to first OpenAI model in settings.json"
    )
    parser.add_argument("--max-output-tokens", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--batch-input-chars", type=int, default=18000)
    parser.add_argument("--review-block-size", type=int, default=12)
    parser.add_argument(
        "--relationship-coverage", choices=["lightweight", "comprehensive"], default="lightweight"
    )
    parser.add_argument("--run-dir", type=Path, help="New staged run archive directory")
    parser.add_argument("--resume", type=Path, help="Resume a staged run using frozen settings")
    parser.add_argument(
        "--replay-run", type=Path, help="Reconstruct a staged run without API access"
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Allow a new attempt for failed or unknown-outcome jobs",
    )
    parser.add_argument(
        "--single-request", action="store_true", help="Use the legacy v2 request path"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--overwrite", action="store_true", help="Archive prior dictionary before replacing"
    )
    parser.add_argument(
        "--replay", type=Path, help="Revalidate an archived response entirely offline"
    )
    parser.add_argument("--candidate", type=Path, help="Edited JSON for --replay or --correct-job")
    parser.add_argument(
        "--correct-job", type=Path, help="Offline correction: archived attempt directory"
    )
    parser.add_argument("--correction-reason", help="Required explanation of a manual correction")
    parser.add_argument(
        "--approve-correction",
        action="store_true",
        help="Explicitly record manual approval of the supplied correction",
    )
    args = parser.parse_args(argv)
    archive_dir = None
    try:
        if args.correct_job:
            if not args.candidate or not args.correction_reason or not args.approve_correction:
                raise ValueError(
                    "--correct-job requires --candidate, --correction-reason "
                    "and --approve-correction"
                )
            if (
                args.replay
                or args.resume
                or args.replay_run
                or args.run_dir
                or args.single_request
                or args.retry_failed
                or args.dry_run
                or args.overwrite
            ):
                raise ValueError("--correct-job is a standalone offline approval command")
            from feature_dictionary.synthesis_core.corrections import approve_job

            artifact, path = approve_job(args.correct_job, args.candidate, args.correction_reason)
            print(f"Correction artifact: {path}")
            for issue in artifact["validation"]["issues"]:
                print(f"{issue['code']} at {issue['path']}: {issue['message']}")
            print(
                "Correction accepted; no API request made."
                if artifact["accepted"]
                else "Correction rejected; original response and errors preserved."
            )
            return 0 if artifact["accepted"] else 2
        if args.correction_reason or args.approve_correction:
            raise ValueError("Correction approval flags require --correct-job")
        if args.max_output_tokens <= 0:
            raise ValueError("--max-output-tokens must be positive")
        if args.replay and (args.resume or args.replay_run or args.run_dir):
            raise ValueError("Legacy --replay cannot be combined with staged run options")
        if args.single_request and (args.resume or args.replay_run or args.run_dir):
            raise ValueError("--single-request cannot be combined with staged run options")
        if not args.replay and not args.single_request:
            from feature_dictionary.synthesis_core.staged_cli import run

            return run(args, PROJECT_DIR)
        if args.candidate and not args.replay:
            raise ValueError("--candidate requires --replay")
        if args.replay:
            archive = json.loads(args.replay.read_text(encoding="utf-8"))
            if not isinstance(archive, dict):
                raise ValueError("response archive must contain a JSON object")
            if args.candidate:
                archive["candidate_override"] = args.candidate.read_text(encoding="utf-8")
        else:
            bundle = read_outputs(args.input_dir)
            print(
                f"Loaded {len(bundle.sources)} outputs and {len(bundle.observations)} observations."
            )
            for issue in bundle.issues:
                print(f"{issue.code}: {issue.message}", file=sys.stderr)
        if args.dry_run:
            print("Dry run: no API request or output files written.")
            return 0
        if args.output.exists() and not args.overwrite:
            raise ValueError(f"output exists: {args.output}; use another --output or --overwrite")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:12]
        archive_dir = args.output.parent / "archives" / f"{args.output.stem}_{stamp}"
        if args.replay:
            archive["replayed_from"] = str(args.replay.resolve())
            write_json(archive_dir / "response.json", archive)
        else:
            model = args.model
            if not model:
                settings = json.loads((PROJECT_DIR / "settings.json").read_text())
                model = next(
                    (
                        m["model"]
                        for m in settings.get("models", [])
                        if isinstance(m, dict) and m.get("provider") == "openai"
                    ),
                    None,
                )
            if not model:
                raise ValueError("specify an OpenAI synthesis model with --model")
            from dotenv import load_dotenv
            from openai import OpenAI

            load_dotenv(PROJECT_DIR / ".env")
            print(f"Requesting synthesis from {model}... Archive: {archive_dir}", flush=True)
            with OpenAI(timeout=900, max_retries=0) as client:
                archive = request_synthesis(
                    client,
                    model=model,
                    bundle=bundle,
                    prompt=PROMPT_PATH.read_text(encoding="utf-8"),
                    max_output_tokens=args.max_output_tokens,
                    archive_dir=archive_dir,
                )
        result, report = evaluate(archive)
        write_json(archive_dir / "validation.json", report)
        print(f"Validation report: {archive_dir / 'validation.json'}")
        if result is None:
            for issue in report["issues"]:
                if issue["severity"] == "error":
                    print(
                        f"{issue['code']} at {issue['path']}: {issue['message']}", file=sys.stderr
                    )
            print(f"Response retained: {archive_dir / 'response.json'}", file=sys.stderr)
            return 2
        write_json(archive_dir / "dictionary.json", result)
        if args.output.exists():
            # Keep exact bytes of the previous experiment even with explicit overwrite.
            with (archive_dir / "previous_output.bin").open("xb") as handle:
                handle.write(args.output.read_bytes())
        temporary = archive_dir / "publication.json"
        write_json(temporary, result)
        if args.overwrite:
            os.replace(temporary, args.output)
        else:
            # Exclusive creation prevents a concurrent run overwriting an experiment.
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(temporary.read_text(encoding="utf-8"))
        print(f"Saved {len(result['terms'])} proposed terms to {args.output}")
        return 0
    except KeyboardInterrupt:
        print(f"Synthesis interrupted. Archive: {archive_dir}", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"synthesis failed ({type(exc).__name__}): {exc}; archive: {archive_dir}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
