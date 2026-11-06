#!/usr/bin/env python3
"""Finalize and evaluate a saved checkpoint without hiding an interrupted run."""

import argparse
import json
from pathlib import Path
import re
import shutil

import mlx.core as mx
from mlx_lm.tuner.trainer import evaluate
from mlx_lm.utils import load_adapters

from benchmark_data import timestamp, write_new
from import_ollama_mlx import file_sha256
from mlx_qwen_loader import load_local_model
from mlx_training_loss import completion_loss
from train_experimental_qwen import encoded_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--interruption", required=True, help="Observed reason the source run stopped")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    match = re.fullmatch(r"(\d+)_adapters\.safetensors", args.checkpoint)
    if not match:
        parser.error("Supply an existing numbered MLX checkpoint filename")
    step = int(match.group(1))
    experiment = json.loads((args.source / "experiment.json").read_text())
    if (experiment.get("human_gold") is not False
            or experiment.get("eligible_for_promotion") is not False
            or not 0 < step <= experiment["iters"]):
        parser.error("Only an explicitly experimental saved checkpoint is supported")
    if (file_sha256(args.dataset / "manifest.json") != experiment["dataset_manifest_sha256"]
            or file_sha256(args.base_model / "conversion_receipt.json")
            != experiment["base_receipt_sha256"]):
        parser.error("The source experiment's base or dataset changed")
    manifest = json.loads((args.dataset / "manifest.json").read_text())
    receipt = json.loads((args.base_model / "conversion_receipt.json").read_text())
    for filename, digest in receipt["output_files"].items():
        if file_sha256(args.base_model / filename) != digest:
            parser.error(f"Base model file changed: {filename}")
    valid_path = args.dataset / "valid.jsonl"
    if file_sha256(valid_path) != manifest["dataset_sha256"]["valid"]:
        parser.error("Validation examples changed")
    if args.output.exists():
        parser.error("Finalized adapter output already exists; preserve it")
    args.output.mkdir(parents=True)
    for source, name in (
        (args.source / args.checkpoint, "adapters.safetensors"),
        (args.source / "adapter_config.json", "adapter_config.json"),
    ):
        with source.open("rb") as incoming, (args.output / name).open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
    mx.set_memory_limit(24 * 1024 ** 3)
    mx.set_cache_limit(512 * 1024 ** 2)
    model, tokenizer = load_local_model(args.base_model)
    rows = [json.loads(line) for line in valid_path.read_text().splitlines()]
    data = encoded_rows(rows, tokenizer, experiment["max_seq_length"])
    before = evaluate(model, data, batch_size=1, num_batches=len(data),
                      max_seq_length=experiment["max_seq_length"], loss=completion_loss)
    model = load_adapters(model, str(args.output))
    after = evaluate(model, data, batch_size=1, num_batches=len(data),
                     max_seq_length=experiment["max_seq_length"], loss=completion_loss)
    result = {
        **experiment, "completed": True, "training_completed": False,
        "finished_at": timestamp(), "completed_iterations": step,
        "planned_iterations": experiment["iters"],
        "source_checkpoint_sha256": file_sha256(args.source / args.checkpoint),
        "source_experiment_sha256": file_sha256(args.source / "experiment.json"),
        "evaluation_implementation_sha256": file_sha256(Path(__file__)),
        "initial_weak_label_validation_loss": before,
        "final_weak_label_validation_loss": after,
        "adapter_sha256": file_sha256(args.output / "adapters.safetensors"),
        "peak_memory_bytes": mx.get_peak_memory(),
        "interruption": args.interruption,
        "interpretation": "Teacher imitation only; not expert accuracy or a completed planned run.",
    }
    write_new(args.output / "result.json", result)
    print(json.dumps({
        "checkpoint": step, "training_completed": False,
        "initial_weak_label_validation_loss": before,
        "final_weak_label_validation_loss": after,
        "eligible_for_promotion": False,
    }, indent=2))


if __name__ == "__main__":
    main()
