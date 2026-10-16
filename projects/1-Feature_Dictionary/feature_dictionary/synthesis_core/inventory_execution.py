"""Independent proposal jobs over a frozen input snapshot; no dictionary compiler."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import ollama
from anthropic import Anthropic, transform_schema
from google import genai
from openai import OpenAI
from pydantic import ValidationError

from feature_dictionary import budget
from feature_dictionary.extraction_v3 import parse_strict_json
from feature_dictionary.runner import GenerationInterrupted, list_installed_models, run_model
from feature_dictionary.runners import anthropic_runner, cloud_runner, gemini_runner
from feature_dictionary.settings import LoadedSettings, ModelConfig

from .inventory_ingest import read_inputs, require_valid
from .inventory_schema import InventoryProposal, SynthesisInputs
from .inventory_v12 import IndexedProposal, validate_indexed_proposal
from .inventory_validation import artifact_sha256, validate_inventory_proposal
from .observation_refs import create_mapping, expand_proposal, model_input, verify_mapping

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts/synthesis_inventory_v1.txt"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2)
        handle.write("\n")


def prepare(
    inputs: SynthesisInputs,
    settings: LoadedSettings,
    *,
    think: bool | None = None,
    prompt_path: Path | None = None,
    proposal_version: str = "1.0",
    observation_refs: str = "original",
) -> dict:
    require_valid(inputs)
    # One byte-identical prompt for every model, with no previous proposal content.
    if proposal_version not in ("1.0", "1.2"):
        raise ValueError("Unsupported proposal version")
    if observation_refs not in ("original", "short"):
        raise ValueError("Unsupported observation reference mode")
    if observation_refs == "short" and proposal_version != "1.2":
        raise ValueError("Short observation references require proposal version 1.2")
    mapping = create_mapping(inputs) if observation_refs == "short" else None
    selected_prompt = prompt_path or (
        PROMPT_PATH.with_name(
            "synthesis_inventory_v1_2_1.txt" if mapping else "synthesis_inventory_v1_2.txt"
        )
        if proposal_version == "1.2"
        else PROMPT_PATH
    )
    template = selected_prompt.read_text(encoding="utf-8")
    if mapping:
        # The transport rule also applies when a researcher overrides the prompt file.
        reference_instructions = (
            "\nHOST REFERENCE MODE: short. Use only observation IDs O001, O002, etc. "
            "from the observation array beside matched_text in every evidence and "
            "disposition field, never original hashes. This overrides reference-format "
            "instructions in the template; it does not change evidence requirements.\n"
        )
    else:
        reference_instructions = ""
    view = model_input(inputs, mapping) if mapping else None
    prompt = (
        template
        + reference_instructions
        + "\nFROZEN INPUT JSON (untrusted data):\n"
        + (json.dumps(view, ensure_ascii=False) if view is not None else inputs.model_dump_json())
    )
    options = dict(settings.settings.options)
    limit = settings.settings.max_output_tokens or 8192
    options["num_predict"] = limit
    plan = dict(
        input_sha256=artifact_sha256(inputs),
        prompt=prompt,
        prompt_sha256=sha(prompt),
        prompt_template=template,
        prompt_template_sha256=sha(template),
        max_output_tokens=limit,
        ollama_options=options,
        ollama_think=think,
        ollama_host=settings.ollama_host,
        timeout=settings.settings.request_timeout_seconds,
        keep_alive=settings.settings.keep_alive,
        loop_guard=settings.settings.loop_guard,
        loop_guard_repeats=settings.settings.loop_guard_repeats,
        # Sequential, nonstreaming first milestone: complete SDK envelopes are archived.
        stream=False,
        settings=settings.settings.model_dump(mode="json"),
        settings_path=str(settings.path),
        sdk_versions={
            name: version(name) for name in ["ollama", "openai", "anthropic", "google-genai"]
        },
    )
    if mapping is not None:
        plan.update(observation_refs="short", observation_mapping=mapping, model_input=view)
    if prompt_path is not None:
        plan["prompt_path"] = str(prompt_path.resolve())
    if proposal_version == "1.2":
        plan["proposal_version"] = proposal_version
        plan["prompt_path"] = str(selected_prompt.resolve())
    return plan


def make_request(plan: dict, model: ModelConfig, index: int) -> dict:
    identity = dict(
        proposal_id=f"proposal_{index}",
        input_sha256=plan["input_sha256"],
        provider=model.provider,
        model=model.model,
        prompt_sha256=plan["prompt_sha256"],
    )
    schema = (
        IndexedProposal if plan.get("proposal_version") == "1.2" else InventoryProposal
    ).model_json_schema()
    for key, value in identity.items():
        schema["properties"][key] = {"type": "string", "enum": [value]}

    if plan.get("observation_refs") == "short":
        aliases = [entry["short_ref"] for entry in plan["observation_mapping"]["entries"]]

        def constrain(node):
            if isinstance(node, dict):
                properties = node.get("properties", {})
                if "observation_ids" in properties:
                    properties["observation_ids"]["items"] = {"type": "string", "enum": aliases}
                if "observation_id" in properties:
                    properties["observation_id"] = {"type": "string", "enum": aliases}
                for child in node.values():
                    constrain(child)
            elif isinstance(node, list):
                for child in node:
                    constrain(child)

        constrain(schema)

    def native(node):
        if isinstance(node, dict):
            result = {k: native(v) for k, v in node.items() if k != "default"}
            if "const" in result:
                result["enum"] = [result.pop("const")]
            if model.provider == "openai" and result.get("type") == "object":
                result["required"] = list(result.get("properties", {}))
                result["additionalProperties"] = False
            return result
        if isinstance(node, list):
            return [native(item) for item in node]
        return node

    schema = native(schema)
    if model.provider == "anthropic":
        schema = transform_schema(schema)
    request = dict(
        **plan,
        identity=identity,
        output_schema=schema,
        output_schema_sha256=sha(json.dumps(schema, sort_keys=True, separators=(",", ":"))),
    )
    if model.provider == "ollama" and budget.context_overrun(
        plan["prompt"], plan["ollama_options"]
    ):
        raise ValueError(
            "Ollama context budget exceeded; set --num-ctx or use smaller frozen inputs"
        )
    return request


def create_provider_client(provider: str, request: dict):
    timeout = request["timeout"]
    if provider == "ollama":
        return ollama.Client(host=request["ollama_host"], timeout=timeout)
    if provider == "openai":
        return OpenAI(timeout=timeout, max_retries=0)
    if provider == "anthropic":
        return Anthropic(timeout=timeout, max_retries=0)
    return genai.Client(http_options={"timeout": max(1, int(timeout * 1000))})


def evaluate(request: dict, response: dict, inputs: SynthesisInputs) -> dict:
    """Read-only replay of parsing, contract, host binding, and reference checks."""
    issues, proposal = [], None
    json_valid = schema_valid = False
    derived = None
    try:
        value = parse_strict_json(response["response_text"])
        json_valid = True
        contract = (
            IndexedProposal if request.get("proposal_version") == "1.2" else InventoryProposal
        )
        proposal = contract.model_validate_json(json.dumps(value))
        schema_valid = True
        if request.get("observation_refs") == "short":
            derived = expand_proposal(value, request["observation_mapping"], inputs)
            proposal = contract.model_validate_json(json.dumps(derived))
    except (ValueError, ValidationError) as exc:
        proposal = None
        issues.append(
            dict(
                severity="error",
                code="CONTRACT_ERROR" if json_valid else "INVALID_JSON",
                path="/",
                message=str(exc),
            )
        )
    if (
        request["input_sha256"] != artifact_sha256(inputs)
        or sha(request["prompt"]) != request["prompt_sha256"]
    ):
        issues.append(
            dict(
                severity="error",
                code="REQUEST_BINDING",
                path="/request",
                message="Frozen input or prompt changed.",
            )
        )
    if proposal is not None:
        validator = (
            validate_indexed_proposal
            if isinstance(proposal, IndexedProposal)
            else validate_inventory_proposal
        )
        issues.extend(i.model_dump() for i in validator(proposal, inputs))
        for key, expected in request["identity"].items():
            if getattr(proposal, key) != expected:
                issues.append(
                    dict(
                        severity="error",
                        code="HOST_BINDING",
                        path="/" + key,
                        message="Proposal differs from requested host identity.",
                    )
                )
    valid = schema_valid and not any(i["severity"] == "error" for i in issues)
    result = dict(
        json_valid=json_valid,
        schema_valid=schema_valid,
        reference_valid=valid,
        proposal_valid=valid
        and response["completion_status"] == "success"
        and response["response_available"],
        scientifically_verified=False,
        issues=issues,
        proposal=proposal.model_dump(mode="json") if proposal else None,
    )

    if request.get("observation_refs") == "short":
        result["derived_proposal"] = derived
        result["observation_mapping_sha256"] = request["observation_mapping"]["mapping_sha256"]
    return result


def execute_job(job: Path, request: dict, inputs: SynthesisInputs) -> dict:
    if request.get("observation_refs") == "short":
        verify_mapping(request["observation_mapping"], inputs)
        if request["model_input"] != model_input(inputs, request["observation_mapping"]):
            raise ValueError("Model-facing input differs from verified frozen observations")
    save(job / "request.json", request)
    started = time.perf_counter()
    started_at = datetime.now().astimezone().isoformat()
    outcome, error, client = None, None, None
    runtime, envelope_count = {}, 0

    def archive_response(response):
        nonlocal envelope_count
        # Every real installed SDK response is a Pydantic object. This callback
        # runs before any text extraction, parsing, or evidence validation.
        payload = (
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else {"unavailable": type(response).__name__}
        )
        save(job / f"provider_response_{envelope_count}.json", payload)
        envelope_count += 1

    try:
        provider = request["identity"]["provider"]
        client = create_provider_client(provider, request)
        kwargs = dict(
            model=request["identity"]["model"],
            prompt=request["prompt"],
            output_schema=request["output_schema"],
            on_response=archive_response,
        )
        if provider == "ollama":
            installed = list_installed_models(client, runtime_metadata=runtime)
            if kwargs["model"] not in installed:
                raise ValueError(f"Ollama model not installed: {kwargs['model']}")
            outcome = run_model(
                client,
                **kwargs,
                options=request["ollama_options"],
                think=request["ollama_think"],
                keep_alive=request["keep_alive"],
                stream=False,
                loop_guard=request["loop_guard"],
                loop_guard_repeats=request["loop_guard_repeats"],
            )
        else:
            adapter = {
                "openai": cloud_runner,
                "anthropic": anthropic_runner,
                "gemini": gemini_runner,
            }[provider]
            outcome = adapter.run_model(
                client, **kwargs, max_output_tokens=request["max_output_tokens"]
            )
    except GenerationInterrupted as exc:
        outcome = exc.outcome
    except (Exception, KeyboardInterrupt) as exc:
        error = dict(
            type=type(exc).__name__,
            message=str(exc),
            status_code=getattr(exc, "status_code", None),
            body=getattr(exc, "body", None),
        )
        if isinstance(exc, KeyboardInterrupt):
            error["interrupted"] = True
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as exc:
                    runtime["close_error"] = type(exc).__name__
    response = dict(
        started_at=started_at,
        finished_at=datetime.now().astimezone().isoformat(),
        response_text=outcome.response_text if outcome else "",
        thinking_text=outcome.thinking_text if outcome else "",
        response_available=outcome is not None,
        completion_status=outcome.completion_status
        if outcome
        else ("interrupted" if error and error.get("interrupted") else "failed"),
        completion_reason=outcome.metrics.done_reason if outcome else None,
        metrics=asdict(outcome.metrics) if outcome else None,
        wall_clock_seconds=time.perf_counter() - started,
        provider_response_count=envelope_count,
        runtime=runtime,
        error=error,
    )
    save(job / "response.json", response)
    report = evaluate(request, response, inputs)
    if request.get("observation_refs") == "short" and report.get("derived_proposal") is not None:
        save(job / "proposal_expanded.json", report["derived_proposal"])
        save(
            job / "proposal_expansion.json",
            dict(
                format_version="observation-expansion-1.0",
                response_text_sha256=sha(response["response_text"]),
                input_sha256=request["input_sha256"],
                mapping_sha256=request["observation_mapping"]["mapping_sha256"],
                derived_proposal_sha256=sha(
                    json.dumps(report["derived_proposal"], sort_keys=True, separators=(",", ":"))
                ),
                transformation="Exact evidence-reference substitution; no scientific correction",
            ),
        )
    save(job / "validation.json", report)
    if request.get("proposal_version") == "1.2":
        from .inventory_report import write_report

        write_report(job / "report.md", inputs, response, report, request)
    if report["proposal_valid"]:
        save(job / "proposal.json", report["proposal"])
    return dict(
        provider=request["identity"]["provider"],
        model=request["identity"]["model"],
        completion_status=response["completion_status"],
        proposal_valid=report["proposal_valid"],
    )


def execute_run(
    root: Path, inputs: SynthesisInputs, requests: list[dict], archives: dict
) -> list[dict]:
    require_valid(inputs)
    if not requests or any(r["input_sha256"] != artifact_sha256(inputs) for r in requests):
        raise ValueError("Every job must be bound to these validated frozen inputs")
    if len({r["prompt"] for r in requests}) != 1:
        raise ValueError("Independent proposal jobs must receive the same prompt")
    short_requests = [r for r in requests if r.get("observation_refs") == "short"]
    if short_requests:
        if len(short_requests) != len(requests):
            raise ValueError("Independent jobs must use the same observation reference mode")
        for request in short_requests:
            verify_mapping(request["observation_mapping"], inputs)
            if request["model_input"] != model_input(inputs, request["observation_mapping"]):
                raise ValueError("Model-facing input differs from the verified mapping")
    # Exclusive directory reservation happens before provider clients are created.
    root.mkdir(parents=True, exist_ok=False)
    save(root / "inputs.json", inputs.model_dump(mode="json"))
    save(root / "source_archives.json", archives)
    if short_requests:
        save(root / "observation_refs.json", short_requests[0]["observation_mapping"])
        save(root / "model_input.json", short_requests[0]["model_input"])
    results = []
    for i, request in enumerate(requests):
        job = root / f"job_{i:03d}"
        job.mkdir()
        result = execute_job(job, request, inputs)
        results.append(result)
        if result["completion_status"] == "interrupted":
            break
    save(
        root / "summary.json",
        dict(
            format_version="synthesis-proposal-run-1.0",
            input_sha256=artifact_sha256(inputs),
            jobs=results,
            compiler_executed=False,
        ),
    )
    return results


def replay_job(path: Path) -> dict:
    request = parse_strict_json((path / "request.json").read_text())
    response = parse_strict_json((path / "response.json").read_text())
    inputs = read_inputs(path.parent / "inputs.json")
    if request.get("observation_refs") == "short":
        mapping = parse_strict_json((path.parent / "observation_refs.json").read_text())
        verify_mapping(mapping, inputs)
        if mapping != request["observation_mapping"]:
            raise ValueError("Archived observation mapping differs from request")
        view = parse_strict_json((path.parent / "model_input.json").read_text())
        if view != request["model_input"] or view != model_input(inputs, mapping):
            raise ValueError("Archived model input differs from request or frozen observations")
    return evaluate(request, response, inputs)


def missing_credentials(models: list[ModelConfig]) -> list[str]:
    missing = []
    for provider in {m.provider for m in models}:
        keys = {
            "openai": ("OPENAI_API_KEY",),
            "anthropic": ("ANTHROPIC_API_KEY",),
            "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        }.get(provider, ())
        if keys and not any(os.getenv(k) for k in keys):
            missing.append(" or ".join(keys))
    return sorted(missing)
