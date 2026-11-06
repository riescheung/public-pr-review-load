#!/usr/bin/env python3
"""Export only human-approved development examples; never export the locked test."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random

from benchmark_data import (
    BENCHMARK, case_packet, digest, load_manifest, load_records, validate_label, validate_review,
)
from review_contract import FULL
from score_harness import decision_prompt, observation_prompt, one_pass_prompt


DATASET = FULL / "lora" / "data"
SEED = 20261104


def approved_examples(case, packet, label):
    if label.get("source") != "human_adjudicated":
        raise ValueError("Only explicit human adjudications may enter training")
    if "review" not in label:
        raise ValueError("A complete human-approved review is required; never invent quotes")
    validate_label(label, packet)
    return review_examples(case, packet, label)


def review_examples(case, packet, label):
    """Serialize a structurally checked review; this function does not confer approval."""
    validate_review(label["review"], packet)
    if packet["abstention_reason"]:
        return []  # Operational missing-evidence checks do not need learned weights.
    review = label["review"]
    rows = []
    if len(packet["chunks"]) == 1:
        answer = {
            **{k: v for k, v in review.items() if k not in ("observations", "model_id")},
            **review["observations"][0],
        }
        rows.append(("combined", one_pass_prompt(packet["chunks"][0]), answer))
    else:
        for chunk, observations in zip(packet["chunks"], review["observations"]):
            rows.append(("observation", observation_prompt(chunk), observations))
        answer = {k: v for k, v in review.items() if k not in ("observations", "model_id")}
        rows.append(("decision", decision_prompt(review["observations"]), answer))
    return [{
        "source": label["source"], "index": case["id"], "prs": case["group"]["prs"],
        "diff_sha256": case["group"]["diff_sha256"],
        "instructions_sha256": packet["instructions_sha256"],
        "label_sha256": digest(label), "score": label["score"], "kind": kind,
        "row": {"messages": [
            {"role": "system", "content": packet["system"]},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": json.dumps(answer, separators=(",", ":"))},
        ]},
    } for kind, prompt, answer in rows]


def split_examples(cases, labels, packets=None):
    reserved = [c["group"] for c in cases if c["split"] != "development"]
    reserved_prs = {pr for g in reserved for pr in g["prs"]}
    reserved_hashes = {h for g in reserved for h in g["diff_sha256"].values()}
    reserved_families = {g["id"] for g in reserved}
    eligible, prs, hashes = [], set(), set()
    for case in cases:
        if case["split"] != "development" or case["id"] not in labels:
            continue
        group = case["group"]
        fingerprints = set(group["diff_sha256"].values())
        if (reserved_prs.intersection(group["prs"]) or reserved_hashes.intersection(fingerprints)
                or group["id"] in reserved_families):
            raise ValueError("Development data overlaps held-out PRs, patches or change families")
        if prs.intersection(group["prs"]) or hashes.intersection(fingerprints):
            raise ValueError("Training groups overlap by PR or patch hash")
        prs.update(group["prs"])
        hashes.update(fingerprints)
        eligible.append(case)
    selected = []
    for case in eligible:
        packet = packets[case["id"]] if packets is not None else case_packet(case)
        examples = approved_examples(case, packet, labels[case["id"]])
        if examples:
            selected.append((case["group"]["id"], examples))
    # Split whole families before expanding observation/decision rows.
    families = sorted({family for family, _ in selected})
    rng = random.Random(SEED)
    rng.shuffle(families)
    holdout = max(1, len(families) // 5) if len(families) >= 2 else 0
    validation = set(families[:holdout])
    splits = {"train": [], "valid": []}
    for family, examples in selected:
        splits["valid" if family in validation else "train"].extend(examples)
    return splits


def build():
    manifest = load_manifest()
    labels = load_records(BENCHMARK / "labels", manifest)
    return split_examples(manifest["cases"], labels)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-groups", type=int, default=30)
    parser.add_argument("--min-per-label", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DATASET)
    args = parser.parse_args()
    if args.min_groups < 2 or args.min_per_label < 1:
        parser.error("Do not disable the minimum human-data checks")
    splits = build()
    groups = {item["index"]: item["score"] for values in splits.values() for item in values}
    counts = Counter(groups.values())
    if (len(groups) < args.min_groups
            or any(counts[label] < args.min_per_label for label in (1, 2, 3, None))):
        parser.error(
            f"Training blocked: {len(groups)} human-approved groups, "
            f"labels={dict(counts)}. Need >= {args.min_groups} groups and "
            f">= {args.min_per_label} of each tier and semantic abstentions. "
            "These are experiment minimums, not proof of accuracy."
        )
    destination = args.output
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.glob("*.json*")):
        parser.error("Dataset already exists; preserve it and choose a versioned location")
    for name, samples in splits.items():
        path = destination / f"{name}.jsonl"
        with path.open("x") as output:
            output.write("".join(json.dumps(item["row"]) + "\n" for item in samples))
    manifest = {
        "purpose": "Human-adjudicated code tiers; not verified outcomes",
        "benchmark_sha256": load_manifest()["sha256"],
        "seed": SEED, "groups": len(groups),
        "test_exported": False,
        "splits": {
            name: [{
                "index": item["index"], "prs": item["prs"],
                "source": item["source"], "diff_sha256": item["diff_sha256"],
                "instructions_sha256": item["instructions_sha256"],
                "label_sha256": item["label_sha256"], "kind": item["kind"],
                "score": item["score"],
            } for item in samples] for name, samples in splits.items()
        },
        "dataset_sha256": {
            name: hashlib.sha256((destination / f"{name}.jsonl").read_bytes()).hexdigest()
            for name in splits
        },
    }
    with (destination / "manifest.json").open("x") as output:
        output.write(json.dumps(manifest, indent=2) + "\n")
    print({name: len(samples) for name, samples in splits.items()})
    print("No test JSONL is exported. Training still requires a pinned matching Qwen base.")


if __name__ == "__main__":
    main()
