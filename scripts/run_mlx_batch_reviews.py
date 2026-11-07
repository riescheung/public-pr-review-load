#!/usr/bin/env python3
"""Run bounded, resumable Qwen reviews through one native-batched MLX worker."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from benchmark_data import BENCHMARK, case_packet, digest, load_manifest, timestamp, validate_review
from contribution_estimates import archive_publication, json_snapshot, publish, validate_publication
from import_ollama_mlx import file_sha256
from mlx_batch_client import verify_files
from pr_benchmark import HARNESS_SHA256, installed_mlx_model
from review_contract import FULL, ROOT
from review_artifacts import write_bytes, write_receipt
from run_contribution_reviews import require_safe_power, retained_publication_runs
from score_harness import run_review


BASE = FULL / "model" / "qwen3.5-9b-ollama"
REFERENCE_ADAPTER = FULL / "lora" / "adapter-reference-v4"
MAX_NEW_TOKENS = 2048
MODEL_MEMORY_GIB = 24


def native_identity(base, adapter, batch_size, max_chunks):
    parent = installed_mlx_model(base, adapter)
    files = {name: file_sha256(ROOT / "scripts" / name) for name in (
        "mlx_review_adapter.py", "mlx_qwen_loader.py", "local_review_protocol.py",
        "mlx_json_decoder.py", "mlx_review_schema.py", "score_harness.py",
        "review_contract.py", "benchmark_data.py", "contribution_estimates.py",
        "mlx_batch_client.py", "mlx_batch_server.py", "mlx_prose_penalty.py",
        "run_mlx_batch_reviews.py", "review_artifacts.py",
    )}
    model = {k: v for k, v in parent.items() if k != "digest"}
    model.update(
        name=parent["name"] + ("+persistent-scalar" if batch_size == 1 else "+native-batch"),
        implementation_sha256=digest(files),
        native_batch={
            "batch_size": batch_size, "prefill_batch_size": min(4, batch_size),
            "engine": "mlx-generate" if batch_size == 1 else "mlx-continuous-batch",
            "prefill_step_size": 1024, "max_tokens": MAX_NEW_TOKENS,
            "repetition_penalty": 1.15, "repetition_context_size": 256,
            "repetition_scope": "descriptive-json-strings-only",
            "max_chunks": max_chunks, "memory_limit_bytes": MODEL_MEMORY_GIB * 1024 ** 3,
            "parent_identity": parent, "files": files,
        },
    )
    return {**model, "digest": digest(model)}


def archive_runtime(model):
    directory = FULL / "harness" / "runtime-sources" / model["digest"]
    for name, expected in model["native_batch"]["files"].items():
        source = ROOT / "scripts" / name
        if file_sha256(source) != expected:
            raise ValueError(f"Frozen model runtime changed: {name}")
        path = directory / name
        if not path.exists():
            write_bytes(path, source.read_bytes())
        if file_sha256(path) != expected:
            raise ValueError(f"Runtime source archive changed: {name}")


def publish_completed(args, benchmark, manifest, publication_path):
    if args.split != "publication":
        return
    publication = json.loads(publication_path.read_text()) if publication_path.exists() else {}
    previous = retained_publication_runs(publication) if publication else []
    runs = [*dict.fromkeys(run for run in previous if run != args.run), args.run]
    publish(benchmark, ["qwen-base-v2", "mlx-distilled-v4"],
            publication_path, manifest, runs)


def pending_publication_cases(cases, publication, model_digest):
    return [case for case in cases if not (
        (row := publication.get("reviews", {}).get(case["group"]["id"]))
        and (row["status"] in ("ok", "abstained", "preflight")
             or publication["models"][row["run"]]["digest"] == model_digest)
    )]


def run_worker(args, benchmark, manifest, model):
    directory = BENCHMARK / "runs" / args.run
    spec_path = directory / "spec.json"
    publication_path = ROOT / "data" / "contribution_estimates.json"
    publication = json.loads(publication_path.read_text()) if publication_path.exists() else {}
    cases = [case for case in manifest["cases"] if case["split"] == args.split]
    if args.only_case:
        selected = set(args.only_case)
        if selected - {case["id"] for case in cases}:
            raise ValueError("Selected cases must belong to the requested split")
    elif spec_path.exists():
        selected = set(json.loads(spec_path.read_text())["selected_case_ids"])
    else:
        if args.split == "publication":
            cases = pending_publication_cases(cases, publication, model["digest"])
        selected = {case["id"] for case in cases[:args.limit]}
    cases = [case for case in cases if case["id"] in selected]
    if len(cases) > args.limit:
        raise ValueError("The selected subset exceeds this explicit batch budget")
    spec = {
        "manifest_sha256": manifest["sha256"], "model": model,
        "harness_sha256": HARNESS_SHA256,
        "protocol": "one-pass-single; observations-then-decision-for-multi",
        "max_chunks": args.max_chunks, "timeout_per_call": 360,
        "selected_case_ids": sorted(selected),
    }
    if spec_path.exists():
        if json.loads(spec_path.read_text()) != spec:
            raise ValueError("Model, manifest or protocol changed; use a new run ID")
    else:
        write_receipt(spec_path, spec)
    pending = [case for case in cases
               if not (directory / "predictions" / f"{case['id']}.json").exists()]
    print(f"{args.run}: {len(pending)} pending of {len(cases)} selected cases", flush=True)
    if not pending:
        publish_completed(args, benchmark, manifest, publication_path)
        return
    with tempfile.TemporaryDirectory(prefix="qwen-batch-", dir="/tmp") as temporary:
        socket_path = Path(temporary) / "model.sock"
        command = [sys.executable, str(ROOT / "scripts" / "mlx_batch_server.py"),
                   "--spec", str(spec_path), "--socket", str(socket_path),
                   "--base", str(args.base), "--raw-dir", str(directory / "raw")]
        if args.adapter is not None:
            command.extend(["--adapter", str(args.adapter)])
        with (directory / "worker.log").open("a") as log:
            server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 120
                while not socket_path.exists():
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Local worker failed to start; inspect worker.log")
                    time.sleep(0.1)
                client = ["/usr/bin/env", f"WEAVE_BATCH_SOCKET={socket_path}",
                          f"WEAVE_BATCH_SPEC={spec_path}", f"WEAVE_BATCH_MODEL={model['digest']}",
                          sys.executable, str(ROOT / "scripts" / "mlx_batch_client.py")]

                def review_case(case):
                    verify_files(model["native_batch"]["files"])
                    packet = case_packet(case)
                    record = {
                        "manifest_sha256": manifest["sha256"], "case_id": case["id"],
                        "packet_sha256": case["packet_sha256"], "spec_sha256": digest(spec),
                        "created_at": timestamp(),
                    }
                    if len(packet["chunks"]) > args.max_chunks:
                        record.update(status="deferred", reason="Explicit chunk budget exceeded")
                    else:
                        try:
                            review = run_review(packet, client, model["digest"],
                                                one_pass=True, timeout=360)
                            validate_review(review, packet)
                            record.update(status="preflight" if packet["abstention_reason"] else "ok",
                                          review=review)
                        except (ValueError, subprocess.SubprocessError) as error:
                            record.update(status="error", error=str(error)[-1200:])
                    write_receipt(directory / "predictions" / f"{case['id']}.json", record)
                    print(f"{case['id']} {record['status']}", flush=True)

                with ThreadPoolExecutor(max_workers=args.batch_size) as pool:
                    for _ in pool.map(review_case, pending):
                        if server.poll() is not None:
                            raise RuntimeError("Local worker exited; completed receipts are retained")
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    verify_files(model["native_batch"]["files"])
    publish_completed(args, benchmark, manifest, publication_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--base", type=Path, default=BASE)
    adapters = parser.add_mutually_exclusive_group()
    adapters.add_argument("--adapter", type=Path, default=REFERENCE_ADAPTER)
    adapters.add_argument("--base-only", action="store_true")
    parser.add_argument("--split", choices=("publication", "calibration", "development"),
                        default="publication")
    parser.add_argument("--only-case", action="append")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-chunks", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=1,
                        help="1 reuses the proven scalar generator; >1 is experimental")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.run)
            or not 1 <= args.limit <= 100 or not 1 <= args.max_chunks <= 32
            or not 1 <= args.batch_size <= 8):
        parser.error("Use a safe run name and finite case, chunk and batch budgets")
    if args.base_only:
        args.adapter = None
    benchmark, manifest = load_manifest(), load_manifest(args.manifest)
    if args.split == "publication":
        catalog, catalog_hash = json_snapshot(FULL / "selection.json")
        validate_publication(manifest, benchmark, catalog, catalog_hash,
                             file_sha256(ROOT / "data" / "report.json"))
        archive_publication(manifest)
    elif manifest["sha256"] != benchmark["sha256"]:
        parser.error("Calibration and development require the frozen benchmark manifest")
    if not args.execute:
        print("Plan only: local same-base batched inference; no model calls or downloads.")
        return
    require_safe_power()
    os.environ.update(AGX_RELAX_CDM_CTXSTORE_TIMEOUT="1", HF_HUB_OFFLINE="1",
                      TRANSFORMERS_OFFLINE="1")
    if not args.worker:
        command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
        if sys.platform == "darwin":
            command = ["/usr/bin/caffeinate", "-s", "-i", *command]
        child = subprocess.Popen(command, start_new_session=True)
        try:
            while child.poll() is None:
                require_safe_power()
                time.sleep(10)
        except (RuntimeError, KeyboardInterrupt):
            os.killpg(child.pid, signal.SIGTERM)
            child.wait()
            raise
        raise SystemExit(child.returncode)
    model = native_identity(args.base, args.adapter, args.batch_size, args.max_chunks)
    archive_runtime(model)
    run_worker(args, benchmark, manifest, model)


if __name__ == "__main__":
    main()
