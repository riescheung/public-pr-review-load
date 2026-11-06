#!/usr/bin/env python3
"""Resume bounded, local trained-Qwen scoring outside the reserved final test."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from benchmark_data import digest, load_manifest, seal, write_new
from contribution_estimates import publish, reserved, validate_publication
from import_ollama_mlx import file_sha256
from pr_benchmark import run_cases
from review_contract import FULL, ROOT
from score_harness import make_packet


DEFAULT_MANIFEST = FULL / "harness" / "contribution-manifest-v1.json"
BASE = FULL / "model" / "qwen3.5-9b-ollama"
ADAPTER = FULL / "lora" / "adapter-experimental-v6"


def prepare(catalog, benchmark, catalog_hash, report_hash):
    cases = []
    for index, group in enumerate(catalog, 1):
        if reserved(group, benchmark):
            continue
        if (set(group["diff_sha256"]) != set(map(str, group["prs"]))
                or any(not (FULL / "diffs" / f"{number}.diff").is_file()
                       for number in group["prs"])):
            continue
        packet = make_packet(group, FULL / "diffs")
        cases.append({
            "id": "E" + digest(group)[:16], "source": "full", "index": index,
            "group": group, "split": "publication", "packet_sha256": digest(packet),
        })
    return seal({
        "purpose": "Estimated contribution publication, not a benchmark evaluation",
        "benchmark_sha256": benchmark["sha256"], "catalog_sha256": catalog_hash,
        "report_sha256": report_hash, "cases": cases,
    })


def require_ac():
    if sys.platform == "darwin":
        power = subprocess.run(
            ["/usr/bin/pmset", "-g", "batt"], capture_output=True, text=True, check=True,
        ).stdout
        if "AC Power" not in power:
            raise RuntimeError("Connect AC power before starting trained-Qwen inference")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run", default="qwen-contributions-v1")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.run):
        parser.error("Use a safe, explicit run name")
    benchmark = load_manifest()
    catalog_path, report_path = FULL / "selection.json", ROOT / "data" / "report.json"
    catalog = json.loads(catalog_path.read_text())
    hashes = file_sha256(catalog_path), file_sha256(report_path)
    if args.action == "prepare":
        manifest = prepare(catalog, benchmark, *hashes)
        write_new(args.manifest, manifest)
        print(f"Prepared {len(manifest['cases'])} cached groups; reserved test families excluded.")
        return
    manifest = load_manifest(args.manifest)
    validate_publication(manifest, benchmark, catalog, *hashes)
    if not args.execute:
        print(f"Plan: {len(manifest['cases'])} eligible cached groups, "
              f"at most {args.limit} new attempts using {ADAPTER.name}. No model calls.")
        return
    if not 1 <= args.limit <= 100 or not 1 <= args.max_chunks <= 8:
        parser.error("Use a finite batch: --limit 1..100 and --max-chunks 1..8")
    require_ac()
    if not args.worker:
        command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
        if sys.platform == "darwin":
            command = ["/usr/bin/caffeinate", "-s", "-i", *command]
        env = {**os.environ, "AGX_RELAX_CDM_CTXSTORE_TIMEOUT": "1",
               "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        process = subprocess.Popen(command, env=env, start_new_session=True)
        try:
            while process.poll() is None:
                require_ac()
                time.sleep(10)
        except (RuntimeError, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGTERM)
            process.wait()
            raise
        raise SystemExit(process.returncode)
    try:
        run_cases(manifest, args.run, "qwen3.5:9b", "publication", args.limit,
                  args.max_chunks, BASE, ADAPTER)
    finally:
        # Publish completed records even if a later case fails or the batch ends.
        spec = ROOT / "data" / "benchmark" / "runs" / args.run / "spec.json"
        if spec.exists():
            publish(benchmark, ["qwen-base-v2", "mlx-distilled-v4"],
                    ROOT / "data" / "contribution_estimates.json", manifest, args.run)


if __name__ == "__main__":
    main()
