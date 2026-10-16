"""Independent synthesis-1.0 proposal CLI; never compiles a final dictionary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from feature_dictionary.cli import _positive_integer
from feature_dictionary.settings import SettingsError, load_settings
from feature_dictionary.synthesis_core.inventory_execution import (
    execute_run,
    make_request,
    missing_credentials,
    prepare,
    replay_job,
)
from feature_dictionary.synthesis_core.inventory_ingest import (
    freeze_extractions,
    read_inputs,
    with_source_context,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default="settings.json")
    parser.add_argument(
        "--models", help="Independent synthesis model aliases or provider:model selectors"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--inputs", type=Path, help="Frozen synthesis-input-1.0 JSON")
    source.add_argument(
        "--extraction-output",
        action="append",
        type=Path,
        help="Accepted v3.1 document or directory; repeat to combine extractor runs",
    )
    source.add_argument("--replay-job", type=Path, help="Read-only offline proposal revalidation")
    source.add_argument("--render-report", type=Path, help="Render a saved v1.2 job offline")
    parser.add_argument(
        "--report-output", type=Path, help="New Markdown destination; never overwritten"
    )
    parser.add_argument(
        "--include-raw-json",
        action="store_true",
        help="Include the raw appendix with --render-report; omitted by default",
    )
    parser.add_argument("--proposal-version", choices=["1.0", "1.2"], default="1.0")
    parser.add_argument(
        "--observation-refs",
        choices=["original", "short"],
        default="original",
        help="Opt-in run-local O001 evidence aliases for synthesis-1.2",
    )
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument(
        "--prompt-file", type=Path, help="Versioned synthesis prompt; omitted preserves v1.0"
    )
    parser.add_argument(
        "--context-file",
        type=Path,
        help="Optional exact source-context quotes with source IDs and character ranges",
    )
    parser.add_argument("--max-output-tokens", type=_positive_integer)
    parser.add_argument(
        "--num-ctx", type=_positive_integer, help="Ollama context override for this proposal run"
    )
    parser.add_argument("--ollama-think", choices=["true", "false", "default"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.include_raw_json and not args.render_report:
        parser.error("--include-raw-json requires --render-report")
    try:
        if args.render_report:
            if not args.report_output:
                parser.error("--render-report requires --report-output")
            from feature_dictionary.extraction_v3 import parse_strict_json
            from feature_dictionary.synthesis_core.inventory_report import write_report

            job = args.render_report
            request = parse_strict_json((job / "request.json").read_text())
            if request.get("proposal_version") != "1.2":
                raise ValueError(
                    "Markdown audit requires synthesis-1.2; no historical migration is inferred"
                )
            if args.report_output.resolve().is_relative_to(job.parent.resolve()):
                raise ValueError("Choose a report destination outside the immutable saved run")
            response = parse_strict_json((job / "response.json").read_text())
            validation = (
                replay_job(job)
                if request.get("observation_refs") == "short"
                else parse_strict_json((job / "validation.json").read_text())
            )
            write_report(
                args.report_output,
                read_inputs(job.parent / "inputs.json"),
                response,
                validation,
                request,
                include_raw_json=args.include_raw_json,
            )
            print(str(args.report_output))
            return 0
        if args.replay_job:
            result = replay_job(args.replay_job)
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0 if result["proposal_valid"] else 1
        if not args.models or not args.run_dir or not (args.inputs or args.extraction_output):
            parser.error("select --models, --run-dir, and --inputs or --extraction-output")
        overrides = {"models": args.models}
        if args.max_output_tokens is not None:
            overrides["max_output_tokens"] = args.max_output_tokens
        loaded = load_settings(args.settings, overrides=overrides)
        if args.num_ctx is not None:
            loaded.settings.options["num_ctx"] = args.num_ctx
        if args.inputs:
            inputs, archives = (
                read_inputs(args.inputs),
                {"frozen_input_path": str(args.inputs.resolve())},
            )
        else:
            inputs, archives = freeze_extractions(args.extraction_output)
        if args.context_file:
            inputs = with_source_context(inputs, args.context_file)
        think = (
            loaded.settings.ollama_think
            if args.ollama_think is None
            else {"true": True, "false": False, "default": None}[args.ollama_think]
        )
        plan = prepare(
            inputs,
            loaded,
            think=think,
            prompt_path=args.prompt_file,
            proposal_version=args.proposal_version,
            observation_refs=args.observation_refs,
        )
        requests = [make_request(plan, model, i) for i, model in enumerate(loaded.settings.models)]
        if args.run_dir.exists():
            raise ValueError("Run directory already exists; choose a fresh directory")
        if args.dry_run:
            print(
                json.dumps(
                    dict(
                        dry_run=True,
                        input_sha256=plan["input_sha256"],
                        observations=len(inputs.observations),
                        observation_refs=args.observation_refs,
                        models=[r["identity"] for r in requests],
                        max_output_tokens=plan["max_output_tokens"],
                        prompt_sha256=plan["prompt_sha256"],
                        run_dir=str(args.run_dir),
                        compiler_executed=False,
                    ),
                    indent=2,
                )
            )
            return 0
        load_dotenv()
        missing = missing_credentials(loaded.settings.models)
        if missing:
            raise ValueError("Missing credentials: " + ", ".join(missing))
        results = execute_run(args.run_dir, inputs, requests, archives)
        print(json.dumps(results, indent=2))
        if any(r["completion_status"] == "interrupted" for r in results):
            return 130
        return 0 if all(r["proposal_valid"] for r in results) else 1
    except (OSError, ValueError, SettingsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
