#!/usr/bin/env python3
"""Build explicitly weak AI-distillation data, isolated from benchmark gold."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random

from benchmark_data import digest, load_manifest, write_new
from import_ollama_mlx import file_sha256
from prepare_lora_data import review_examples
from review_contract import FULL
from score_harness import make_packet

try:
    from mlx_lm.utils import load_tokenizer
except ImportError:
    load_tokenizer = None


def teacher_review(label, packet):
    if packet["abstention_reason"] or len(packet["chunks"]) != 1:
        raise ValueError("Historical teacher proposals require one complete chunk")
    return {
        "source": "historical_ai_proposal_not_human_gold",
        "score": label["score"],
        "review": {
            "score": label["score"], "reason": label["reason"],
            "posthog_relevance": label["reason"], "confidence": "low",
            "evidence": [label["hunk"]], "metadata_dependency": False,
            "grouping_issue": False, "abstention_reason": None,
            "uncertainty": "Historical AI proposal; not independently validated; no measured outcomes.",
            "observations": [{
                "observations": [{
                    "hunk": label["hunk"], "behavior": label["reason"],
                    "posthog_connection": label["reason"], "code_quote": label["code_quote"],
                }],
                "limitations": "A cited hunk may omit relevant behavior elsewhere in the group.",
            }],
        },
    }


def assert_unreserved(group, manifest):
    for case in manifest["cases"]:
        reserved = case["group"]
        if (set(group["prs"]).intersection(reserved["prs"])
                or set(group["diff_sha256"].values()).intersection(reserved["diff_sha256"].values())
                or group["id"] == reserved["id"]):
            raise ValueError("Experimental training overlaps reserved benchmark cases")


def assert_disjoint(groups):
    families, prs, hashes = set(), set(), set()
    for group in groups:
        fingerprints = set(group["diff_sha256"].values())
        if (group["id"] in families or prs.intersection(group["prs"])
                or hashes.intersection(fingerprints)):
            raise ValueError("Historical teacher groups overlap by family, PR or patch")
        families.add(group["id"])
        prs.update(group["prs"])
        hashes.update(fingerprints)


def build(tokenizer, max_tokens=8192):
    benchmark = load_manifest()
    catalog = json.loads((FULL / "selection.json").read_text())
    labels = json.loads((FULL / "teacher_labels.json").read_text())
    assert_disjoint([catalog[label["index"] - 1] for label in labels])
    examples, excluded = [], []
    for label in labels:
        group = catalog[label["index"] - 1]
        assert_unreserved(group, benchmark)
        packet = make_packet(group, FULL / "diffs")
        proposal = teacher_review(label, packet)
        case = {"id": "T" + digest(group)[:12], "group": group}
        rows = review_examples(case, packet, proposal)
        for row in rows:
            tokens = tokenizer.apply_chat_template(
                row["row"]["messages"], tokenize=True, enable_thinking=False,
                return_dict=False,
            )
            if len(tokens) > max_tokens:
                excluded.append({"id": case["id"], "reason": "overlength", "tokens": len(tokens)})
            else:
                row["tokens"] = len(tokens)
                examples.append(row)
    buckets = defaultdict(list)
    for example in examples:
        buckets[example["score"]].append(example)
    rng = random.Random(20261105)
    train, valid = [], []
    for score in sorted(buckets):
        rows = sorted(buckets[score], key=lambda row: row["index"])
        rng.shuffle(rows)
        held = max(1, len(rows) // 5) if len(rows) >= 3 else 0
        valid.extend(rows[:held])
        train.extend(rows[held:])
    if not train or not valid:
        raise ValueError("Need nonempty weak-label train and validation sets")
    return {"train": train, "valid": valid}, excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experimental-ai-labels", action="store_true")
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=8192)
    args = parser.parse_args()
    if not args.experimental_ai_labels:
        parser.error("Explicit --experimental-ai-labels is required; these are not human gold")
    if not args.base_model.is_dir():
        parser.error("Local matching base model required; no download is attempted")
    if load_tokenizer is None:
        parser.error("Run with the existing local MLX-enabled Python environment")
    tokenizer = load_tokenizer(args.base_model)
    splits, excluded = build(tokenizer, args.max_tokens)
    receipt = json.loads((args.base_model / "conversion_receipt.json").read_text())
    if args.output.exists():
        parser.error("Experimental dataset already exists; choose a versioned output")
    args.output.mkdir(parents=True)
    for split, rows in splits.items():
        with (args.output / f"{split}.jsonl").open("x") as output:
            output.write("".join(json.dumps(row["row"]) + "\n" for row in rows))
    write_new(args.output / "manifest.json", {
        "purpose": "Experimental AI-label distillation, not independent accuracy validation",
        "human_gold": False, "eligible_for_promotion": False,
        "benchmark_sha256": load_manifest()["sha256"],
        "base_ollama_digest": receipt["ollama_model_digest"],
        "teacher_labels_sha256": file_sha256(FULL / "teacher_labels.json"),
        "max_tokens": args.max_tokens, "enable_thinking": False,
        "excluded": excluded,
        "splits": {
            split: [{k: v for k, v in row.items() if k != "row"} for row in rows]
            for split, rows in splits.items()
        },
        "dataset_sha256": {
            split: file_sha256(args.output / f"{split}.jsonl") for split in splits
        },
    })
    print({split: len(rows) for split, rows in splits.items()})
    print(f"Excluded {len(excluded)} overlength rows without truncation.")
    print("Weak-label agreement is not human accuracy; promotion is disabled.")


if __name__ == "__main__":
    main()
