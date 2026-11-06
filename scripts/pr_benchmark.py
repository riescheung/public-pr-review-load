#!/usr/bin/env python3
"""Prepare a blind benchmark, run installed Qwen, record humans and evaluate."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import urlopen

from benchmark_data import (
    BENCHMARK, MANIFEST, case_packet, digest, export_packets, load_manifest, load_records,
    prepare, timestamp, validate_audit, validate_label, validate_review, write_new,
)
from benchmark_metrics import compare, metrics
from import_ollama_mlx import file_sha256
from review_contract import ROOT
from score_harness import run_review


ADAPTER = ROOT / "scripts" / "ollama_review_adapter.py"
HARNESS_SHA256 = hashlib.sha256((ROOT / "scripts" / "score_harness.py").read_bytes()).hexdigest()
MLX_ADAPTER = ROOT / "scripts" / "mlx_review_adapter.py"


def installed_model(name):
    with urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
        models = json.load(response)["models"]
    with urlopen("http://127.0.0.1:11434/api/version", timeout=10) as response:
        version = json.load(response)["version"]
    for model in models:
        if model["name"] == name:
            return {
                "name": name, "digest": model["digest"], "ollama_version": version,
                "adapter_sha256": hashlib.sha256(ADAPTER.read_bytes()).hexdigest(),
            }
    raise ValueError(f"{name} is not installed; no model download was attempted")


def installed_mlx_model(base, adapter=None):
    receipt_path = base / "conversion_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    for filename, expected in receipt["output_files"].items():
        if file_sha256(base / filename) != expected:
            raise ValueError(f"MLX base changed: {filename}")
    identity = {
        "name": "mlx-qwen3.5-9b", "base_ollama_digest": receipt["ollama_model_digest"],
        "base_receipt_sha256": file_sha256(receipt_path),
        "implementation_sha256": digest({
            path.name: file_sha256(path)
            for path in (MLX_ADAPTER, ROOT / "scripts" / "mlx_qwen_loader.py",
                         ROOT / "scripts" / "local_review_protocol.py",
                         ROOT / "scripts" / "mlx_json_decoder.py",
                         ROOT / "scripts" / "mlx_review_schema.py")
        }),
        "contract_attempts": 3,
        "structured_decoding": "schema-hunk-quote-v1",
        "runtime_environment": {
            name: os.environ.get(name) for name in (
                "AGX_RELAX_CDM_CTXSTORE_TIMEOUT", "MLX_MAX_OPS_PER_BUFFER",
                "MLX_MAX_MB_PER_BUFFER",
            )
        },
        "experimental_ai_labels": False,
        "versions": {name: importlib.metadata.version(name)
                     for name in ("mlx", "mlx-lm", "transformers", "outlines-core")},
    }
    if adapter is not None:
        result = json.loads((adapter / "result.json").read_text())
        if (result.get("completed") is not True
                or result["base_ollama_digest"] != receipt["ollama_model_digest"]
                or file_sha256(adapter / "adapters.safetensors") != result["adapter_sha256"]):
            raise ValueError("Incomplete, changed or mismatched MLX adapter")
        identity.update(
            name="mlx-qwen3.5-9b+experimental-lora",
            adapter_sha256=result["adapter_sha256"],
            adapter_config_sha256=file_sha256(adapter / "adapter_config.json"),
            experiment_sha256=file_sha256(adapter / "result.json"),
            experimental_ai_labels=result.get("human_gold") is not True,
        )
    return {**identity, "digest": digest(identity)}


def run_cases(manifest, run_id, model, split, limit, max_chunks, mlx_model=None, mlx_adapter=None):
    if mlx_model is None:
        identity = installed_model(model)
        command = ["/usr/bin/env", f"WEAVE_REVIEW_MODEL={model}", sys.executable, str(ADAPTER)]
    else:
        identity = installed_mlx_model(mlx_model, mlx_adapter)
        command = [
            "/usr/bin/env", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1",
            f"WEAVE_MLX_BASE={mlx_model.resolve()}",
            f"WEAVE_MLX_ADAPTER={mlx_adapter.resolve() if mlx_adapter else ''}",
            sys.executable, str(MLX_ADAPTER),
        ]
    spec = {
        "manifest_sha256": manifest["sha256"], "model": identity,
        "harness_sha256": HARNESS_SHA256,
        "protocol": "one-pass-single; observations-then-decision-for-multi",
        "max_chunks": max_chunks, "timeout_per_call": 360,
    }
    directory = BENCHMARK / "runs" / run_id
    spec_path = directory / "spec.json"
    if spec_path.exists():
        if json.loads(spec_path.read_text()) != spec:
            raise ValueError("Run/model/protocol changed; use a new run ID")
    else:
        write_new(spec_path, spec)
    attempted = 0
    for case in manifest["cases"]:
        path = directory / "predictions" / f"{case['id']}.json"
        if case["split"] != split or path.exists():
            continue
        if attempted >= limit:
            break
        packet = case_packet(case)
        print(f"{case['id']} starting ({len(packet['chunks'])} chunks)", flush=True)
        record = {
            "manifest_sha256": manifest["sha256"], "case_id": case["id"],
            "packet_sha256": case["packet_sha256"], "spec_sha256": digest(spec),
            "created_at": timestamp(),
        }
        if len(packet["chunks"]) > max_chunks:
            record.update(status="deferred", reason="Explicit chunk budget exceeded")
        else:
            attempted += 1
            try:
                review = run_review(
                    packet, command,
                    spec["model"]["digest"], one_pass=True, timeout=360,
                )
                validate_review(review, packet)
                record.update(status="preflight" if packet["abstention_reason"] else "ok",
                              review=review)
            except (ValueError, subprocess.SubprocessError) as error:
                record.update(status="error", error=str(error)[-1200:])
        write_new(path, record)
        print(f"{case['id']} {record['status']}", flush=True)


def predictions(manifest, run_id):
    directory = BENCHMARK / "runs" / run_id
    spec = json.loads((directory / "spec.json").read_text())
    if spec["manifest_sha256"] != manifest["sha256"]:
        raise ValueError("Stale run specification")
    records = load_records(directory / "predictions", manifest)
    cases = {case["id"]: case for case in manifest["cases"]}
    for identifier, record in records.items():
        case = cases[identifier]
        if (record["spec_sha256"] != digest(spec)
                or record["packet_sha256"] != case["packet_sha256"]):
            raise ValueError("Prediction provenance changed")
        if record["status"] not in ("ok", "preflight", "error", "deferred"):
            raise ValueError("Unknown prediction state")
        if record["status"] in ("ok", "preflight"):
            validate_review(record["review"], case_packet(case))
    return records


def evaluation_identity(spec):
    model = spec["model"]
    return {
        "base_model_sha256": model.get("base_ollama_digest", model["digest"]),
        "evaluation_protocol_sha256": digest({
            "harness": spec.get("harness_sha256"), "protocol": spec["protocol"],
            "max_chunks": spec["max_chunks"], "timeout_per_call": spec["timeout_per_call"],
            "runtime": "mlx" if "base_ollama_digest" in model else "ollama",
            "implementation": model.get("implementation_sha256", model.get("adapter_sha256")),
            "versions": model.get("versions", model.get("ollama_version")),
            "contract_attempts": model.get("contract_attempts", 1),
            **{key: model[key] for key in ("structured_decoding", "runtime_environment")
               if key in model},
        }),
    }


def evaluate(manifest, run_id, split):
    labels = load_records(BENCHMARK / "labels", manifest)
    runs = predictions(manifest, run_id)
    audits = load_records(BENCHMARK / "runs" / run_id / "audits", manifest)
    for identifier, answer in labels.items():
        case = next(c for c in manifest["cases"] if c["id"] == identifier)
        validate_label(answer, case_packet(case))
    for identifier, audit in audits.items():
        validate_audit(audit)
        if audit.get("prediction_sha256") != digest(runs.get(identifier)):
            raise ValueError("Semantic audit is not for this exact prediction")
    cases = [c for c in manifest["cases"] if c["split"] == split]
    spec = json.loads((BENCHMARK / "runs" / run_id / "spec.json").read_text())
    return {
        "manifest_sha256": manifest["sha256"], "run": run_id, "split": split,
        "harness_sha256": spec.get("harness_sha256"),
        "experimental_ai_labels": spec["model"].get("experimental_ai_labels", False),
        **evaluation_identity(spec),
        "case_ids": [c["id"] for c in cases], **metrics(cases, runs, labels, audits),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "export", "run", "label", "audit", "evaluate", "compare"))
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--development", type=int, default=40)
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--mlx-model", type=Path, help="Verified local MLX text-weight conversion")
    parser.add_argument("--mlx-adapter", type=Path, help="Completed experimental adapter directory")
    parser.add_argument("--run", help="Immutable run name, e.g. qwen-base-v2")
    parser.add_argument("--baseline-run", help="Frozen baseline run for paired test comparison")
    parser.add_argument("--split", choices=("development", "test", "calibration"), default="development")
    parser.add_argument("--unlock-test", action="store_true",
                        help="Explicitly open the locked final test; never tune against its results")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--case", help="Opaque case ID from the manifest")
    parser.add_argument("--answer", type=Path, help="Human JSON label or evidence audit")
    parser.add_argument("--output", type=Path, help="New file for an evaluation report")
    args = parser.parse_args()
    if args.mlx_adapter and not args.mlx_model:
        parser.error("--mlx-adapter requires --mlx-model")
    if args.action == "prepare":
        manifest = prepare(args.count, args.development)
        print(f"Frozen {len(manifest['cases'])} cases: {MANIFEST}")
        return
    manifest = load_manifest()
    if args.action in ("run", "evaluate", "audit", "compare"):
        if not args.run or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.run):
            parser.error("Supply a safe --run identifier")
    if (args.action in ("run", "evaluate", "compare")
            and (args.split == "test" or args.action == "compare") and not args.unlock_test):
        parser.error("The untouched test requires --unlock-test")
    if args.action == "export":
        export_packets(manifest)
        print(BENCHMARK / "packets")
    elif args.action == "compare":
        if not args.baseline_run or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.baseline_run):
            parser.error("Supply a safe --baseline-run")
        result = compare(evaluate(manifest, args.baseline_run, "test"),
                         evaluate(manifest, args.run, "test"))
        if args.output:
            write_new(args.output, result)
        print(json.dumps(result, indent=2))
    elif args.action == "run":
        if args.limit < 1 or args.max_chunks < 1:
            parser.error("Use a positive, explicit inference budget")
        run_cases(manifest, args.run, args.model, args.split, args.limit, args.max_chunks,
                  args.mlx_model, args.mlx_adapter)
    elif args.action in ("label", "audit"):
        case = next((c for c in manifest["cases"] if c["id"] == args.case), None)
        if case is None or not args.answer:
            parser.error("Supply a valid --case and --answer")
        answer = json.loads(args.answer.read_text())
        if args.action == "label":
            validate_label(answer, case_packet(case))
            destination = BENCHMARK / "labels" / f"{case['id']}.json"
            answer = {**answer, "source": "human_adjudicated"}
        else:
            validate_audit(answer)
            record = predictions(manifest, args.run).get(case["id"])
            if not record or record["status"] != "ok":
                parser.error("Audit requires a completed model prediction")
            answer = {**answer, "prediction_sha256": digest(record)}
            destination = BENCHMARK / "runs" / args.run / "audits" / f"{case['id']}.json"
        write_new(destination, {
            **answer, "manifest_sha256": manifest["sha256"], "case_id": case["id"],
            "created_at": timestamp(),
        })
        print(destination)
    else:
        result = evaluate(manifest, args.run, args.split)
        if args.output:
            write_new(args.output, result)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
