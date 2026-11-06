#!/usr/bin/env python3
"""Export the review queue, import corrections and build estimated-label LoRA data."""

import argparse
import json
from pathlib import Path
import re

from benchmark_data import BENCHMARK, case_packet, digest, load_manifest, write_new
from frontier_reference import reference_records
from import_ollama_mlx import file_sha256
from prepare_lora_data import review_examples
from reference_feedback import development_cases, import_feedback, load_feedback, make_queue
from train_experimental_qwen import encoded_rows


def learning_examples(manifest, references, corrections, tokenizer, max_length):
    splits, excluded = {"train": [], "valid": []}, []
    for identifier, case in development_cases(manifest).items():
        record = corrections.get(identifier, references.get(identifier))
        if not record or record.get("status", "ok") != "ok":
            continue
        if record.get("source") not in ("frontier_model_reference", "user_feedback"):
            raise ValueError("Estimated training requires a frontier reference or queue correction")
        label = {
            "source": record["source"], "score": record["review"]["score"],
            "review": record["review"],
        }
        rows = review_examples(case, case_packet(case), label)
        try:
            encoded_rows([row["row"] for row in rows], tokenizer, max_length)
        except ValueError as error:
            excluded.append({"case_id": identifier, "reason": str(error)})
            continue
        # A fixed family hash keeps cases in the same split as feedback accumulates.
        split = "valid" if int(digest(["reference-learning-v1", case["group"]["id"]])[:8], 16) % 5 == 0 else "train"
        for row in rows:
            row["label_sha256"] = digest(record)
        splits[split].extend(rows)
    return splits, excluded


def export_dataset(manifest, references, corrections, base, output, max_length, reference_identity):
    from mlx_lm.utils import load_tokenizer

    receipt = json.loads((base / "conversion_receipt.json").read_text())
    splits, excluded = learning_examples(
        manifest, references, corrections, load_tokenizer(base), max_length,
    )
    if any(not rows for rows in splits.values()):
        raise ValueError("Need nonempty family-disjoint training and validation sets")
    if output.exists():
        raise FileExistsError("Preserve previous datasets; choose a new output version")
    output.mkdir(parents=True)
    for split, rows in splits.items():
        with (output / f"{split}.jsonl").open("x") as target:
            target.write("".join(json.dumps(row["row"]) + "\n" for row in rows))
    write_new(output / "manifest.json", {
        "purpose": "Distill frontier estimates and user corrections, not human-verified truth",
        "human_gold": False, "eligible_for_promotion": False,
        "benchmark_sha256": manifest["sha256"],
        "reference": reference_identity,
        "base_ollama_digest": receipt["ollama_model_digest"], "max_tokens": max_length,
        "split_policy": "Stable family-hash validation bucket; test and calibration excluded",
        "excluded": excluded,
        "source_counts": {
            source: len({row["index"] for rows in splits.values() for row in rows
                         if row["source"] == source})
            for source in ("frontier_model_reference", "user_feedback")
        },
        "splits": {
            split: [{key: value for key, value in row.items() if key != "row"}
                    for row in rows] for split, rows in splits.items()
        },
        "dataset_sha256": {
            split: file_sha256(output / f"{split}.jsonl") for split in splits
        },
    })
    return {split: len(rows) for split, rows in splits.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("queue", "import", "dataset"))
    parser.add_argument("--reference", required=True)
    parser.add_argument("--run", default="qwen-base-v2")
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--base-model", type=Path)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for value in (args.reference, args.run):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
            parser.error("Supply safe reference and run IDs")
    manifest = load_manifest()
    directory = BENCHMARK / "references" / args.reference
    feedback = BENCHMARK / "feedback" / args.reference
    references = reference_records(manifest, directory)
    if args.action == "queue":
        if not args.output:
            parser.error("--output is required; existing queue snapshots are never overwritten")
        queue = make_queue(manifest, directory, args.reference, args.run, feedback)
        write_new(args.output, queue)
        print(f"Exported {len(queue['cases'])} estimated development reviews")
    elif args.action == "import":
        if not args.answers or not args.queue:
            parser.error("Supply the original --queue snapshot and --answers export")
        queue = json.loads(args.queue.read_text())
        if queue.get("reference_id") != args.reference:
            parser.error("The queue belongs to a different reference collection")
        count = import_feedback(
            manifest, references, queue,
            json.loads(args.answers.read_text()), feedback,
        )
        print(f"Imported {count} versioned user corrections; no weights changed automatically")
    else:
        if not args.output or not args.base_model or not args.base_model.is_dir():
            parser.error("Supply a fresh --output and an existing local --base-model")
        corrections = load_feedback(manifest, feedback, references)
        print(export_dataset(manifest, references, corrections, args.base_model,
                             args.output, args.max_tokens, {
                                 "id": args.reference,
                                 "spec_sha256": file_sha256(directory / "spec.json"),
                                 "spec": json.loads((directory / "spec.json").read_text()),
                             }))


if __name__ == "__main__":
    main()
