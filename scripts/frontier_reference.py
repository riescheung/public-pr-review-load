#!/usr/bin/env python3
"""Collect estimated frontier references for development, never the final test."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from benchmark_data import (
    BENCHMARK, case_packet, digest, load_manifest, load_records, timestamp,
    validate_review, write_new,
)
from benchmark_metrics import metrics
from devin_cli_env import cli_environment
from import_ollama_mlx import file_sha256
from pr_benchmark import predictions
from review_contract import ROOT
from score_harness import run_review


ADAPTER = ROOT / "scripts" / "frontier_review_adapter.py"


def model_identity(model):
    result = subprocess.run(
        ["devin", "models", "list"], env=cli_environment(), capture_output=True,
        text=True, timeout=30, check=False,
    )
    if result.returncode or not re.search(
        r"(?m)^\s+" + re.escape(model) + r"\s", result.stdout,
    ):
        raise ValueError(f"Exact model unavailable in signed-in CLI catalog: {model}")
    version = subprocess.run(
        ["devin", "--version"], env=cli_environment(), capture_output=True,
        text=True, timeout=30, check=True,
    ).stdout.strip()
    return {"model_id": model, "cli_version": version}


def reference_records(manifest, directory):
    spec = json.loads((directory / "spec.json").read_text())
    if spec["manifest_sha256"] != manifest["sha256"] or spec["split"] != "development":
        raise ValueError("References must belong to this development benchmark")
    records = load_records(directory / "predictions", manifest)
    cases = {case["id"]: case for case in manifest["cases"]}
    for identifier, record in records.items():
        case = cases[identifier]
        if (case["split"] != "development" or record.get("spec_sha256") != digest(spec)
                or record.get("packet_sha256") != case["packet_sha256"]
                or record.get("source") != "frontier_model_reference"
                or record.get("human_gold") is not False
                or record["status"] not in ("ok", "preflight", "error", "deferred", "running")):
            raise ValueError("Stale, foreign or mislabeled frontier reference")
        if record["status"] in ("ok", "preflight"):
            validate_review(record["review"], case_packet(case))
    return records


def run_references(manifest, directory, model, limit, max_chunks, case_ids=None):
    development = {case["id"] for case in manifest["cases"] if case["split"] == "development"}
    if case_ids and not set(case_ids).issubset(development):
        raise ValueError("Only development case IDs may be assigned to reference workers")
    spec = {
        "manifest_sha256": manifest["sha256"], "split": "development",
        "teacher": model_identity(model), "human_gold": False,
        "meaning": "Frontier-model estimates, not independently verified truth",
        "max_chunks": max_chunks, "timeout_per_call": 360,
        "implementation_sha256": {
            name: file_sha256(ROOT / "scripts" / name) for name in (
                "frontier_review_adapter.py", "local_review_protocol.py", "score_harness.py",
            )
        },
    }
    path = directory / "spec.json"
    if path.exists():
        if json.loads(path.read_text()) != spec:
            raise ValueError("Reference model or protocol changed; use a new reference ID")
        reference_records(manifest, directory)
    else:
        write_new(path, spec)
    command = ["/usr/bin/env", f"WEAVE_REFERENCE_MODEL={model}", sys.executable, str(ADAPTER)]
    assigned = []
    for case in manifest["cases"]:
        if case["split"] != "development" or (case_ids and case["id"] not in case_ids):
            continue
        path = directory / "predictions" / f"{case['id']}.json"
        if path.exists():
            continue
        if len(assigned) >= limit:
            break
        record = {
            "manifest_sha256": manifest["sha256"], "case_id": case["id"],
            "packet_sha256": case["packet_sha256"], "spec_sha256": digest(spec),
            "source": "frontier_model_reference", "human_gold": False,
            "created_at": timestamp(),
        }
        # Reserve this worker's finite assignment before any paid calls. Other
        # workers skip these files; an interrupted assignment stays visible.
        try:
            write_new(path, {**record, "status": "running"})
        except FileExistsError:
            continue
        assigned.append((case, path, record))
    for case, path, record in assigned:
        packet = case_packet(case)
        print(f"{case['id']} frontier review ({len(packet['chunks'])} chunks)", flush=True)
        if len(packet["chunks"]) > max_chunks:
            record.update(status="deferred", error="Explicit chunk budget exceeded")
        else:
            try:
                review = run_review(packet, command, model, one_pass=True, timeout=360)
                validate_review(review, packet)
                record.update(status="preflight" if packet["abstention_reason"] else "ok",
                              review=review)
            except (ValueError, subprocess.SubprocessError) as error:
                record.update(status="error", error=str(error)[-1200:])
        with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False) as target:
            json.dump(record, target, indent=2)
            temporary = Path(target.name)
        temporary.replace(path)
        print(f"{case['id']} {record['status']}", flush=True)


def agreement(manifest, directory, run):
    references = reference_records(manifest, directory)
    labels = {identifier: {"score": record["review"]["score"]}
              for identifier, record in references.items() if record["status"] == "ok"}
    cases = [case for case in manifest["cases"] if case["split"] == "development"]
    return {
        "purpose": "Estimated frontier-reference agreement, not human accuracy",
        "human_gold": False, "promoted": False, "run": run,
        "teacher": json.loads((directory / "spec.json").read_text())["teacher"],
        "manifest_sha256": manifest["sha256"],
        "reference_spec_sha256": file_sha256(directory / "spec.json"),
        "reference_labels": len(labels),
        "reference_errors": sum(r["status"] == "error" for r in references.values()),
        "reference_preflight": sum(r["status"] == "preflight" for r in references.values()),
        "reference_running": sum(r["status"] == "running" for r in references.values()),
        "metrics_against_frontier_estimates": metrics(cases, predictions(manifest, run), labels, {}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "evaluate"))
    parser.add_argument("--reference", required=True)
    parser.add_argument("--model", default="gpt-6-1-sol-high")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--case", action="append", help="Assign an explicit development case; repeatable")
    parser.add_argument("--run", help="Qwen run to evaluate against estimated references")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.reference):
        parser.error("Supply a safe reference ID")
    manifest = load_manifest()
    directory = BENCHMARK / "references" / args.reference
    if args.action == "run":
        if not args.execute or not 1 <= args.limit <= 40 or not 1 <= args.max_chunks <= 16:
            parser.error("Use --execute and a finite budget: --limit 1..40 --max-chunks 1..16")
        run_references(manifest, directory, args.model, args.limit, args.max_chunks, args.case)
    else:
        if not args.run or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.run):
            parser.error("Supply a safe Qwen --run ID")
        result = agreement(manifest, directory, args.run)
        if args.output:
            write_new(args.output, result)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
