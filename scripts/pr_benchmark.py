#!/usr/bin/env python3
"""Prepare a blind benchmark, run installed Qwen, record humans and evaluate."""

import argparse
import hashlib
import json
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
from review_contract import ROOT
from score_harness import run_review


ADAPTER = ROOT / "scripts" / "ollama_review_adapter.py"
HARNESS_SHA256 = hashlib.sha256((ROOT / "scripts" / "score_harness.py").read_bytes()).hexdigest()


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


def run_cases(manifest, run_id, model, split, limit, max_chunks):
    spec = {
        "manifest_sha256": manifest["sha256"], "model": installed_model(model),
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
                    packet,
                    ["/usr/bin/env", f"WEAVE_REVIEW_MODEL={model}",
                     sys.executable, str(ADAPTER)],
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
    return {
        "manifest_sha256": manifest["sha256"], "run": run_id, "split": split,
        "harness_sha256": json.loads(
            (BENCHMARK / "runs" / run_id / "spec.json").read_text()
        ).get("harness_sha256"),
        "case_ids": [c["id"] for c in cases], **metrics(cases, runs, labels, audits),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "export", "run", "label", "audit", "evaluate", "compare"))
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--development", type=int, default=40)
    parser.add_argument("--model", default="qwen3.5:9b")
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
        run_cases(manifest, args.run, args.model, args.split, args.limit, args.max_chunks)
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
