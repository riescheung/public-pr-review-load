#!/usr/bin/env python3
"""Compare one Codex reference review with local Ollama inference.

Planning is offline and read-only. --execute makes model calls and records
separate, validated reviews through the existing score_harness CLI.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from review_contract import FULL, OUTPUT, PILOT, REPOSITORY, ROOT, VERSION
from review_queue import read_json, review_case
from score_harness import make_packet


def reviewer_id(role, model):
    suffix = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")[:40]
    if not suffix:
        raise ValueError("Model ID must include letters or numbers")
    return f"{role}-{suffix}"


def run_path(root, index, role, model):
    return root / "runs" / f"{index:02}" / f"{reviewer_id(role, model)}.json"


def check_existing(path, packet, index, role, model):
    if not path.exists():
        return False
    record = json.loads(path.read_text())
    expected = {
        "version": VERSION,
        "repository": REPOSITORY,
        "index": index,
        "reviewer_id": reviewer_id(role, model),
        "model_id": model,
        "diff_sha256": packet["diff_sha256"],
        "instructions_sha256": packet["instructions_sha256"],
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError(f"Stale or mismatched review; inspect rather than overwrite: {path}")
    return True


def command(scope, index, role, model):
    adapter = "codex_review_adapter.py" if role == "teacher" else "ollama_review_adapter.py"
    return [
        sys.executable, str(ROOT / "scripts" / "score_harness.py"), "run",
        "--scope", scope, "--index", str(index), "--one-pass",
        "--model-id", model, "--reviewer-id", reviewer_id(role, model),
        "--model-command", sys.executable, str(ROOT / "scripts" / adapter),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--index", type=int, required=True, help="One 1-based group index")
    parser.add_argument("--teacher-model", required=True,
                        help="Exact Codex SDK model ID; check account availability before executing")
    parser.add_argument("--ollama-model", default="qwen3.5:9b")
    parser.add_argument("--execute", action="store_true",
                        help="Explicitly allow paid teacher and local Ollama model calls")
    args = parser.parse_args()

    source = PILOT if args.scope == "pilot" else FULL
    output = OUTPUT if args.scope == "pilot" else FULL / "harness"
    selection = json.loads((source / "selection.json").read_text())
    if not 1 <= args.index <= len(selection):
        parser.error("index outside selected groups")
    group = selection[args.index - 1]
    packet = make_packet(group, diff_dir=source / "diffs")
    if packet["abstention_reason"]:
        parser.error(f"Group cannot be reviewed: {packet['abstention_reason']}")
    print(f"Group {args.index}: {len(packet['chunks'])} complete diff chunks; "
          f"{len(packet['chunks']) if len(packet['chunks']) == 1 else len(packet['chunks']) + 1} "
          "calls per reviewer at most.")
    pending = []
    for role, model in (("teacher", args.teacher_model), ("student", args.ollama_model)):
        try:
            path = run_path(output, args.index, role, model)
            exists = check_existing(path, packet, args.index, role, model)
        except ValueError as error:
            parser.error(str(error))
        print(f"{role}: {model} -> {path} ({'already recorded' if exists else 'pending'})")
        if not exists:
            pending.append((role, model))
    if not args.execute:
        print("Plan only. No model calls, downloads, or report changes.")
        return
    if any(role == "teacher" for role, _ in pending) and not os.environ.get("CURSOR_API_KEY"):
        parser.error("CURSOR_API_KEY is required for Codex model calls")
    for role, model in pending:
        env = os.environ.copy()
        env["WEAVE_REVIEW_MODEL"] = model
        subprocess.run(command(args.scope, args.index, role, model),
                       cwd=ROOT, env=env, check=True)
    case = review_case(args.index, group, output / "runs",
                       packet["instructions_sha256"])
    print(f"Review flags: {', '.join(case['flags']) or 'none'}; "
          "a teacher vote is not ground truth or a live score.")


if __name__ == "__main__":
    main()
