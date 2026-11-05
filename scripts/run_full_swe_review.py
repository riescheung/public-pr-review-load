#!/usr/bin/env python3
"""Resume validated SWE-2 CLI reviews across the cached full snapshot."""

import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys

from build_review_status import main as refresh_status
from devin_cli_env import cli_environment
from review_contract import FULL, REPOSITORY, ROOT, VERSION
from review_queue import read_json, save_queue
from score_harness import make_packet, run_review


REVIEWER_ID = "swe2-cli-v1"
RUNS = FULL / "harness" / "runs"
ADAPTER = ROOT / "scripts" / "devin_swe_review_adapter.py"


def preflight(model_id):
    if not model_id or "swe-2" not in model_id.lower():
        raise ValueError("Supply the exact SWE-2 ID shown by `devin models list`")
    result = subprocess.run(
        ["devin", "models", "list"], capture_output=True, text=True,
        timeout=30, check=False, env=cli_environment(),
    )
    if result.returncode:
        raise ValueError(
            f"Devin CLI cannot list models: {result.stderr.strip() or result.stdout.strip()}"
        )
    if not re.search(r"(?<![\w.-])" + re.escape(model_id) + r"(?![\w.-])",
                     result.stdout, re.IGNORECASE):
        raise ValueError(f"{model_id} was not found in the signed-in Devin model catalog")


def review_one(index, group, model_id, run_root=RUNS):
    destination = run_root / f"{index:02}" / f"{REVIEWER_ID}.json"
    packet = make_packet(group, diff_dir=FULL / "diffs")
    if packet["abstention_reason"]:
        return "missing_diff"
    if destination.exists():
        old = json.loads(destination.read_text())
        expected = {
            "version": VERSION, "repository": REPOSITORY,
            "index": index, "reviewer_id": REVIEWER_ID, "model_id": model_id,
            "instructions_sha256": packet["instructions_sha256"],
            "diff_sha256": packet["diff_sha256"],
        }
        if any(old.get(key) != value for key, value in expected.items()):
            raise ValueError(f"Stale or mismatched review; do not overwrite {destination}")
        return "already_reviewed"
    command = [sys.executable, str(ADAPTER)]
    # The adapter is called separately for each complete chunk; model identity is
    # explicitly supplied rather than inherited from a mutable CLI default.
    old_model = os.environ.get("WEAVE_REVIEW_MODEL")
    os.environ["WEAVE_REVIEW_MODEL"] = model_id
    try:
        review = run_review(packet, command, model_id, one_pass=True)
    finally:
        if old_model is None:
            os.environ.pop("WEAVE_REVIEW_MODEL", None)
        else:
            os.environ["WEAVE_REVIEW_MODEL"] = old_model
    record = {
        "version": VERSION, "index": index, "repository": REPOSITORY,
        "reviewer_id": REVIEWER_ID, "model_id": model_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instructions_sha256": packet["instructions_sha256"],
        "diff_sha256": packet["diff_sha256"], "review": review,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as output:
        output.write(json.dumps(record, indent=2) + "\n")
    return "reviewed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True,
                        help="Exact SWE-2 ID from the signed-in Devin CLI model catalog")
    parser.add_argument("--index", type=int, help="Review only one 1-based group index")
    parser.add_argument("--limit", type=int,
                        help="Maximum new group attempts; 0 means all remaining")
    parser.add_argument("--execute", action="store_true",
                        help="Start real local Devin CLI model sessions")
    args = parser.parse_args()
    selection = json.loads((FULL / "selection.json").read_text())
    if args.index is not None and not 1 <= args.index <= len(selection):
        parser.error("index outside full snapshot")
    if args.limit is not None and args.limit < 0:
        parser.error("limit must be nonnegative")
    indexes = [args.index] if args.index else range(1, len(selection) + 1)
    available = sum(
        set(selection[i - 1]["diff_sha256"]) == set(map(str, selection[i - 1]["prs"]))
        for i in indexes
    )
    print(f"{available}/{len(indexes)} groups have cached diff hashes; "
          f"{len(indexes) - available} await the public diff fetch.")
    if not args.execute:
        print("Plan only; no SWE-2 model sessions or scores were produced.")
        return
    if args.limit is None:
        parser.error("--execute requires --limit N (or --limit 0 for all remaining)")
    try:
        preflight(args.model_id)
    except (ValueError, FileNotFoundError, subprocess.TimeoutExpired) as error:
        parser.error(str(error))
    results = {"reviewed": 0, "already_reviewed": 0, "missing_diff": 0, "failed": 0}
    attempted = 0
    for index in indexes:
        group = selection[index - 1]
        destination = RUNS / f"{index:02}" / f"{REVIEWER_ID}.json"
        ready = set(group["diff_sha256"]) == set(map(str, group["prs"]))
        if not destination.exists() and not ready:
            results["missing_diff"] += 1
            continue
        if not destination.exists() and (args.limit == 0 or attempted < args.limit):
            attempted += 1
        elif not destination.exists():
            break
        try:
            state = review_one(index, group, args.model_id)
            results[state] += 1
            if state == "reviewed":
                print(f"{index}/{len(selection)} reviewed PRs {group['prs']}", flush=True)
        except ValueError as error:
            if "Stale or mismatched review" in str(error):
                raise
            results["failed"] += 1
            print(f"Group {index} failed; no score saved: {error}", file=sys.stderr, flush=True)
            if results["failed"] >= 3:
                print("Stopping after three failures; inspect the adapter or model access.",
                      file=sys.stderr)
                break
        if results["reviewed"] and results["reviewed"] % 25 == 0:
            save_queue(selection, RUNS, read_json(FULL / "calibration.json", []),
                       FULL / "harness" / "review_queue.json")
            refresh_status()
    save_queue(selection, RUNS, read_json(FULL / "calibration.json", []),
               FULL / "harness" / "review_queue.json")
    refresh_status()
    print(f"Run finished or paused: {results}. Dashboard scores were not changed.")


if __name__ == "__main__":
    main()
