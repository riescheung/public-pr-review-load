#!/usr/bin/env python3
"""Continue finite, resumable publication cohorts with the guarded scalar worker."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

from benchmark_data import BENCHMARK, digest, load_manifest, timestamp
from contribution_estimates import json_snapshot, validate_publication
from pr_benchmark import file_sha256
from review_artifacts import write_bytes, write_receipt
from review_contract import FULL, ROOT
from run_contribution_reviews import require_safe_power
from run_mlx_batch_reviews import (
    BASE, REFERENCE_ADAPTER, native_identity, pending_publication_cases, publish_completed,
)


def cohort_finished(directory):
    spec = directory / "spec.json"
    if not spec.exists():
        return False
    selected = json.loads(spec.read_text())["selected_case_ids"]
    return all((directory / "predictions" / f"{identifier}.json").exists()
               for identifier in selected)


def run_cohort(command):
    child = subprocess.Popen(command, start_new_session=True)
    try:
        return subprocess.CompletedProcess(command, child.wait())
    except BaseException:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait()
        raise


def stop_requested(_signal, _frame):
    raise KeyboardInterrupt


def wait_for_power(resuming=False):
    while True:
        try:
            require_safe_power(34 if resuming else 20)
            return
        except RuntimeError as error:
            print(f"Paused: {error} Resuming automatically at 35% or higher.", flush=True)
            resuming = True
            time.sleep(60)


def deploy_checkpoint():
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], check=True)
    for command in (["npm", "test"], ["npm", "run", "build"]):
        subprocess.run(command, check=True)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], text=True,
    ).strip()
    if branch != "main":
        raise ValueError("Automatic publication requires the approved main branch")
    paths = ["data/contribution_estimates.json", "data/ai_review/selection.json",
             "public/review-evidence"]
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths])
    if changed.returncode not in (0, 1):
        changed.check_returncode()
    if changed.returncode == 1:
        publication = json.loads((ROOT / paths[0]).read_text())
        subprocess.run(["git", "add", "--", "public/review-evidence"], check=True)
        subprocess.run([
            "git", "-c", "commit.gpgsign=false", "commit", "--only", "-m",
            f"Publish {publication['overall']['scored']} Qwen estimates", "--", *paths,
        ], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--cohort-size", type=int, default=20)
    parser.add_argument("--max-cohorts", type=int, default=1000)
    parser.add_argument("--deploy", action="store_true",
                        help="Test, build and push generated data directly to main per cohort")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,54}", args.run_prefix)
            or not 1 <= args.cohort_size <= 100 or not 1 <= args.max_cohorts <= 1000):
        parser.error("Use a safe prefix and finite cohort and case budgets")
    if not args.execute:
        print("Plan only: finite scalar cohorts; no inference, downloads or pushes.")
        return
    os.chdir(ROOT)
    benchmark, manifest = load_manifest(), load_manifest(args.manifest)
    catalog, catalog_hash = json_snapshot(FULL / "selection.json")
    validate_publication(manifest, benchmark, catalog, catalog_hash,
                         file_sha256(ROOT / "data" / "report.json"))
    model = native_identity(BASE, REFERENCE_ADAPTER, 1, 32)
    directory = FULL / "harness" / "rollouts" / args.run_prefix
    receipt = {
        "manifest_sha256": manifest["sha256"], "model_sha256": model["digest"],
        "controller_sha256": file_sha256(Path(__file__)),
        "cohort_size": args.cohort_size, "max_cohorts": args.max_cohorts,
        "deploy": args.deploy,
    }
    receipt_path = directory / "control.json"
    if receipt_path.exists():
        if json.loads(receipt_path.read_text()) != receipt:
            raise ValueError("Frozen rollout changed; choose a new prefix")
    else:
        write_receipt(receipt_path, receipt)
        write_bytes(directory / "controller.py", Path(__file__).read_bytes())
    for number in range(1, args.max_cohorts + 1):
        run = f"{args.run_prefix}-{number:04d}"
        completed = directory / f"{number:04d}.json"
        if completed.exists():
            continue
        publication = json.loads((ROOT / "data" / "contribution_estimates.json").read_text())
        spec_path = BENCHMARK / "runs" / run / "spec.json"
        if not spec_path.exists() and not pending_publication_cases(
                manifest["cases"], publication, model["digest"]):
            print("All cached eligible groups have been attempted under this protocol.", flush=True)
            return
        command = [
            sys.executable, str(ROOT / "scripts" / "run_mlx_batch_reviews.py"),
            "--manifest", str(args.manifest.resolve()), "--run", run,
            "--limit", str(args.cohort_size), "--batch-size", "1", "--execute",
        ]
        while True:
            wait_for_power()
            result = run_cohort(command)
            if result.returncode == 0:
                break
            try:
                require_safe_power()
            except RuntimeError:
                if spec_path.exists():
                    publish_completed(SimpleNamespace(split="publication", run=run),
                                      benchmark, manifest,
                                      ROOT / "data" / "contribution_estimates.json")
                    if args.deploy:
                        deploy_checkpoint()
                wait_for_power(resuming=True)
            else:
                result.check_returncode()
        if not cohort_finished(spec_path.parent):
            raise RuntimeError("Worker exited without completing its frozen cohort")
        if args.deploy:
            deploy_checkpoint()
        write_receipt(completed, {"run": run, "finished_at": timestamp(),
                                  "control_sha256": digest(receipt)})
    print("Explicit cohort budget reached; completed work is preserved.", flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_requested)
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped. Completed receipts are preserved.", flush=True)
