#!/usr/bin/env python3
"""Train a local same-base LoRA probe; weak labels never authorize promotion."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path

from benchmark_data import timestamp, write_new
from import_ollama_mlx import file_sha256

try:
    import mlx.core as mx
    import mlx.optimizers as optim
    import numpy as np
    from mlx_qwen_loader import load_local_model as load
    from mlx_training_loss import COMPLETION_BUDGET, completion_loss
    from mlx_lm.tuner.trainer import TrainingArgs, evaluate, train
    from mlx_lm.tuner.utils import linear_to_lora_layers
except ImportError:
    mx = None
    COMPLETION_BUDGET = 512


def encoded_rows(rows, tokenizer, max_length):
    encoded = []
    for row in rows:
        messages = row["messages"]
        if messages[-1]["role"] != "assistant":
            raise ValueError("Expected a teacher assistant target")
        prefix = tokenizer.apply_chat_template(
            messages[:-1], tokenize=True, add_generation_prompt=True,
            enable_thinking=False, return_dict=False,
        )
        answer = tokenizer.encode(messages[-1]["content"], add_special_tokens=False)
        end = tokenizer.encode("<|im_end|>", add_special_tokens=False)
        tokens = list(prefix) + list(answer) + list(end)
        if (not answer or len(end) != 1 or len(tokens) > max_length
                or len(answer) + len(end) > COMPLETION_BUDGET):
            raise ValueError("Empty, malformed or overlength target; truncation is forbidden")
        encoded.append((tokens, len(prefix)))
    return encoded


def record_failure(output, error, recorded_after_run=False):
    failure = {
        "completed": False, "failed_at": timestamp(), "error": str(error),
        "recorded_after_run": recorded_after_run,
        "saved_checkpoints": {
            path.name: file_sha256(path) for path in sorted(output.glob("*_adapters.safetensors"))
        },
    }
    write_new(output / "failure.json", failure)
    return failure


def train_experiment(base, dataset, output, iters, max_length, layers):
    manifest = json.loads((dataset / "manifest.json").read_text())
    receipt = json.loads((base / "conversion_receipt.json").read_text())
    if (manifest.get("human_gold") is not False
            or manifest.get("eligible_for_promotion") is not False
            or manifest["base_ollama_digest"] != receipt["ollama_model_digest"]):
        raise ValueError("Expected explicitly weak labels and the matching baseline weights")
    for filename, expected in receipt["output_files"].items():
        if file_sha256(base / filename) != expected:
            raise ValueError(f"Base model changed: {filename}")
    rows = {}
    for split in ("train", "valid"):
        path = dataset / f"{split}.jsonl"
        if file_sha256(path) != manifest["dataset_sha256"][split]:
            raise ValueError("Dataset changed after export")
        rows[split] = [json.loads(line) for line in path.read_text().splitlines()]
    if output.exists():
        raise FileExistsError("Adapter output already exists; preserve previous experiments")
    if mx is None:
        raise RuntimeError("Run with the existing MLX-enabled Python environment")
    mx.random.seed(20261105)
    np.random.seed(20261105)
    mx.set_memory_limit(24 * 1024 ** 3)
    mx.set_cache_limit(512 * 1024 ** 2)
    mx.disable_compile()
    print("Loading the exact local text weights; no network or fallback model.", flush=True)
    model, tokenizer = load(base)
    data = {split: encoded_rows(values, tokenizer, max_length) for split, values in rows.items()}
    model.freeze()
    parameters = {"rank": 8, "scale": 8.0, "dropout": 0.05}
    linear_to_lora_layers(model, layers, parameters)
    output.mkdir(parents=True)
    write_new(output / "adapter_config.json", {
        "fine_tune_type": "lora", "num_layers": layers, "lora_parameters": parameters,
    })
    run = {
        "started_at": timestamp(), "completed": False, "human_gold": False,
        "eligible_for_promotion": False, "base_ollama_digest": receipt["ollama_model_digest"],
        "base_receipt_sha256": file_sha256(base / "conversion_receipt.json"),
        "dataset_manifest_sha256": file_sha256(dataset / "manifest.json"),
        "iters": iters, "max_seq_length": max_length, "num_layers": layers,
        "learning_rate": 1e-4, "optimizer": "adam", "lora_parameters": parameters,
        "seed": 20261105, "enable_thinking": False, "mask_prompt": True,
        "compiled_training_step": False, "completion_budget": COMPLETION_BUDGET,
        "metal_command_buffer_limits": {
            name: os.environ.get(name)
            for name in ("MLX_MAX_OPS_PER_BUFFER", "MLX_MAX_MB_PER_BUFFER")
        },
        "metal_context_store_timeout": os.environ.get("AGX_RELAX_CDM_CTXSTORE_TIMEOUT"),
        "implementation_sha256": {
            name: file_sha256(Path(__file__).with_name(name))
            for name in ("train_experimental_qwen.py", "mlx_qwen_loader.py", "mlx_training_loss.py")
        },
        "versions": {name: importlib.metadata.version(name) for name in ("mlx", "mlx-lm", "transformers")},
    }
    write_new(output / "experiment.json", run)
    model.eval()
    before = evaluate(model, data["valid"], batch_size=1,
                      num_batches=len(data["valid"]), max_seq_length=max_length,
                      loss=completion_loss)
    print(f"Initial weak-label validation loss: {before:.5f}", flush=True)
    args = TrainingArgs(
        batch_size=1, iters=iters, val_batches=len(data["valid"]),
        steps_per_report=5, steps_per_eval=10, steps_per_save=10,
        max_seq_length=max_length, adapter_file=str(output / "adapters.safetensors"),
        grad_checkpoint=True,
    )
    train(model=model, optimizer=optim.Adam(learning_rate=1e-4),
          train_dataset=data["train"], val_dataset=data["valid"], args=args,
          loss=completion_loss)
    model.eval()
    after = evaluate(model, data["valid"], batch_size=1,
                     num_batches=len(data["valid"]), max_seq_length=max_length,
                     loss=completion_loss)
    write_new(output / "result.json", {
        **run, "completed": True, "finished_at": timestamp(),
        "initial_weak_label_validation_loss": before,
        "final_weak_label_validation_loss": after,
        "adapter_sha256": file_sha256(output / "adapters.safetensors"),
        "peak_memory_bytes": mx.get_peak_memory(),
        "interpretation": "Teacher imitation only; this is not expert accuracy.",
    })
    print(f"Final weak-label validation loss: {after:.5f}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iters", type=int, default=40)
    parser.add_argument("--max-seq-length", type=int, default=8192)
    parser.add_argument("--num-layers", type=int, default=1)
    parser.add_argument("--experimental-ai-labels", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute or not args.experimental_ai_labels:
        parser.error("Training requires --execute --experimental-ai-labels")
    if not args.base_model.is_dir() or not args.dataset.is_dir():
        parser.error("Only existing local weights and data are accepted")
    if not 1 <= args.iters <= 200 or not 1 <= args.num_layers <= 8:
        parser.error("Use a finite small local experiment budget")
    try:
        train_experiment(args.base_model, args.dataset, args.output, args.iters,
                         args.max_seq_length, args.num_layers)
    except RuntimeError as error:
        if ((args.output / "experiment.json").is_file()
                and not (args.output / "failure.json").exists()):
            record_failure(args.output, error)
        raise


if __name__ == "__main__":
    main()
