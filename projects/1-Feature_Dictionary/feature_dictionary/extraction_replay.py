"""Read-only offline evidence reconstruction from v3 raw archives, without model clients."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .extraction_v3 import (
    ExtractionInput,
    ExtractionRun,
    Issue,
    parse_strict_json,
    validate_response,
)


def replay_archive(path: Path) -> dict[str, Any]:
    """Use the archive's original text, completion state, and candidate version.

    Early v3.0 archives have no expected-version metadata; their raw response's
    declared version selects the validator. No prompt or current settings are read.
    Original file/archive references are not inspected; this is evidence replay.
    """
    archive = parse_strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(archive, dict) or archive.get("format_version") != "extraction-raw-3.0":
        raise ValueError("Expected a v3 raw-response archive, not a candidate or validation report")
    source = ExtractionInput.model_validate(archive["input"])
    run = ExtractionRun.model_validate(archive["run"])
    text = archive["response_text"]
    available = archive["response_available"]
    version = archive.get("candidate_format_version")
    if not isinstance(text, str) or not isinstance(available, bool):
        raise ValueError("Archive must contain response_text and a boolean response_available")
    if version not in (None, "extraction-3.0", "extraction-3.1"):
        raise ValueError(f"Unsupported archived candidate version: {version!r}")
    report = validate_response(text, source.supplied_text, expected_version=version)
    if source.supplied_text_sha256 != report.supplied_text_sha256:
        report.issues.append(
            Issue(
                severity="error",
                code="INPUT_HASH_MISMATCH",
                path="/input/supplied_text_sha256",
                message="Fingerprint differs from exact supplied text.",
            )
        )
    return {
        **report.model_dump(),
        "evidence_valid": report.evidence_valid,
        "completion_status": run.completion_status,
        "completion_reason": run.completion_reason,
        "accepted": available and run.completion_status == "success" and report.evidence_valid,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Saved *.raw.json extraction archive")
    args = parser.parse_args(argv)
    try:
        result = replay_archive(args.archive)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
