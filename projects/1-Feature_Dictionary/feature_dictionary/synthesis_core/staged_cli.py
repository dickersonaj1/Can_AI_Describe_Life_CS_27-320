"""Staged CLI orchestration; legacy single-response replay remains in synthesis.py."""

from __future__ import annotations

import json
import os
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .batching import create_run, execute, plan, read_run
from .inference import write_json
from .ingest import read_outputs


def run(args, project_dir: Path):
    if args.candidate:
        raise ValueError("--candidate applies only to legacy --replay response.json")
    if args.resume and args.replay_run:
        raise ValueError("Choose --resume or --replay-run")
    if args.retry_failed and not args.resume:
        raise ValueError("--retry-failed requires --resume")
    root = args.resume or args.replay_run
    if root:
        bundle, config = read_run(root)
        if args.model and args.model != config["model"]:
            raise ValueError("Resume uses the archived model; start a new run to change settings")
        print("Using frozen run settings; batch/coverage/budget flags do not change resumed runs.")
    else:
        if args.run_dir and args.run_dir.exists():
            raise ValueError("Run directory exists; use --resume or a new --run-dir")
        bundle = read_outputs(args.input_dir)
        model = args.model
        if not model:
            settings = json.loads((project_dir / "settings.json").read_text())
            model = next(
                (
                    m["model"]
                    for m in settings.get("models", [])
                    if isinstance(m, dict) and m.get("provider") == "openai"
                ),
                None,
            )
        if not model:
            raise ValueError("Specify --model")
        config = plan(
            bundle,
            model=model,
            batch_size=args.batch_size,
            coverage=args.relationship_coverage,
            block_size=args.review_block_size,
            max_input_chars=args.batch_input_chars,
            max_output_tokens=args.max_output_tokens,
        )
    print(f"Loaded {len(bundle.sources)} outputs and {len(bundle.observations)} observations.")
    print(
        f"Local batches: {len(config['batches'])}; batch size: {config['batch_size']}; "
        f"relationship coverage: {config['coverage']}; "
        f"output cap/job: {config['max_output_tokens']}"
    )
    for index, batch in enumerate(config["batches"], 1):
        print(
            f"  Batch {index}: {len(batch)} observations; "
            f"{len(json.dumps(batch))} payload characters"
        )
    print(
        "Reconciliation/review job counts depend on local concepts. "
        "Character budgets are estimates,"
    )
    print("not guaranteed token limits; schema and instructions add request overhead.")
    if args.dry_run:
        print("Dry run: no API request or output files written.")
        return 0
    if args.output.exists() and not args.overwrite:
        raise ValueError(f"output exists: {args.output}; use another --output or --overwrite")
    sidecar = args.output.with_name(args.output.name + ".run.json")
    if sidecar.exists() and not args.overwrite:
        raise ValueError(f"provenance sidecar exists: {sidecar}; choose another --output")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:12]
    if root is None:
        root = args.run_dir or args.output.parent / "archives" / f"{args.output.stem}_{stamp}"
        create_run(root, bundle, config)
    print(f"Run archive: {root}", flush=True)
    if args.replay_run:
        context = nullcontext(None)
    else:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv(project_dir / ".env")
        context = OpenAI(timeout=900, max_retries=0)
    with context as client:
        result, validation, summary = execute(root, client=client, retry_failed=args.retry_failed)
    # Never overwrite earlier reconstruction reports or experimental dictionaries.
    reconstruction = root / "reconstructions" / stamp
    write_json(reconstruction / "validation.json", validation)
    write_json(reconstruction / "run_summary.json", summary)
    print(f"Run summary: {reconstruction / 'run_summary.json'}")
    if result is None:
        for issue in validation["issues"]:
            if issue["severity"] == "error":
                print(f"{issue['code']} at {issue['path']}: {issue['message']}")
        return 2
    write_json(reconstruction / "dictionary.json", result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        (reconstruction / "previous_output.bin").write_bytes(args.output.read_bytes())
    if sidecar.exists():
        (reconstruction / "previous_sidecar.bin").write_bytes(sidecar.read_bytes())
    if args.overwrite:
        temporary = args.output.parent / f".{args.output.name}.{uuid4().hex}.tmp"
        write_json(temporary, result)
        os.replace(temporary, args.output)
    else:
        write_json(args.output, result)
    provenance = dict(
        run_archive=str(root.resolve()),
        run_summary=str((reconstruction / "run_summary.json").resolve()),
        dictionary_sha256=summary["dictionary_sha256"],
        coverage_mode=config["coverage"],
    )
    if args.overwrite:
        temporary_sidecar = reconstruction / "publication_sidecar.json"
        write_json(temporary_sidecar, provenance)
        os.replace(temporary_sidecar, sidecar)
    else:
        write_json(sidecar, provenance)
    print(f"Saved {len(result['terms'])} proposed terms to {args.output}")
    return 0
