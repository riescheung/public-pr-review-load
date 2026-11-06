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
from contribution_estimates import archive_publication, json_snapshot, publish, reserved, validate_publication
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


def retained_publication_runs(publication):
    selected = {row["run"] for row in publication["reviews"].values()
                if row["source"] == "publication"}
    return [run for run in publication["models"] if run in selected]


def require_safe_power(minimum_battery=20):
    if sys.platform == "darwin":
        power = subprocess.run(
            ["/usr/bin/pmset", "-g", "batt"], capture_output=True, text=True, check=True,
        ).stdout
        battery = re.search(r"(\d+)%", power)
        if battery and int(battery.group(1)) <= minimum_battery:
            raise RuntimeError(
                f"Battery at {battery.group(1)}%; GPU safety floor is {minimum_battery}%. "
                "Allow the battery to charge before resuming."
            )
        if not battery and "AC Power" not in power:
            raise RuntimeError("Cannot read macOS battery state; GPU work was paused")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run", default="qwen-contributions-v1")
    parser.add_argument("--adapter", type=Path, default=ADAPTER,
                        help="Existing completed same-base adapter; verified before inference")
    parser.add_argument("--previous-run", action="append",
                        help="Retain an earlier run on the same manifest; defaults to published runs")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--only-case", action="append", help="Restrict a diagnostic run to a case ID")
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name)
           for name in [args.run, *(args.previous_run or [])]):
        parser.error("Use a safe, explicit run name")
    benchmark = load_manifest()
    catalog_path, report_path = FULL / "selection.json", ROOT / "data" / "report.json"
    catalog, catalog_hash = json_snapshot(catalog_path)
    hashes = catalog_hash, file_sha256(report_path)
    if args.action == "prepare":
        manifest = prepare(catalog, benchmark, *hashes)
        write_new(args.manifest, manifest)
        archive_publication(manifest)
        print(f"Prepared {len(manifest['cases'])} cached groups; reserved test families excluded.")
        return
    manifest = load_manifest(args.manifest)
    if args.only_case and set(args.only_case) - {case["id"] for case in manifest["cases"]}:
        parser.error("--only-case must name a case in the supplied manifest")
    validate_publication(manifest, benchmark, catalog, *hashes)
    if not args.execute:
        print(f"Plan: {len(manifest['cases'])} eligible cached groups, "
              f"at most {args.limit} new attempts using {args.adapter.name}. No model calls.")
        return
    if not 1 <= args.limit <= 100 or not 1 <= args.max_chunks <= 8:
        parser.error("Use a finite batch: --limit 1..100 and --max-chunks 1..8")
    require_safe_power()
    archive_publication(manifest)
    if not args.worker:
        command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
        if sys.platform == "darwin":
            command = ["/usr/bin/caffeinate", "-s", "-i", *command]
        env = {**os.environ, "AGX_RELAX_CDM_CTXSTORE_TIMEOUT": "1",
               "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        process = subprocess.Popen(command, env=env, start_new_session=True)
        try:
            while process.poll() is None:
                require_safe_power()
                time.sleep(10)
        except (RuntimeError, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGTERM)
            process.wait()
            raise
        raise SystemExit(process.returncode)
    try:
        run_cases(manifest, args.run, "qwen3.5:9b", "publication", args.limit,
                  args.max_chunks, BASE, args.adapter, args.only_case)
    finally:
        # Publish completed records even if a later case fails or the batch ends.
        spec = ROOT / "data" / "benchmark" / "runs" / args.run / "spec.json"
        if spec.exists():
            publication = ROOT / "data" / "contribution_estimates.json"
            previous = args.previous_run
            if previous is None and publication.exists():
                previous = retained_publication_runs(json.loads(publication.read_text()))
            runs = list(dict.fromkeys([*(previous or []), args.run]))
            publish(benchmark, ["qwen-base-v2", "mlx-distilled-v4"],
                    publication, manifest, runs)


if __name__ == "__main__":
    main()
