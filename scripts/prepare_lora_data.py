#!/usr/bin/env python3
"""Build a provenance-labelled local fine-tuning set from reviewed public diffs."""

import hashlib
import json
from pathlib import Path
import random

from review_contract import FULL, PILOT
from score_harness import make_packet, one_pass_prompt


ROOT = Path(__file__).resolve().parents[1]
DATASET = FULL / "lora" / "data"
SEED = 20261104
LIMIT = 18000


def example(index, group, score, reason, source, diff_dir, hunk=None, quote=None,
            evidence_paths=(), max_chars=LIMIT):
    packet = make_packet(group, diff_dir=diff_dir)
    if packet["abstention_reason"] or len(packet["chunks"]) != 1:
        return None
    chunk = packet["chunks"][0]
    if len(chunk["text"]) > max_chars:
        return None
    allowed = chunk["changed_lines"]
    if hunk is None:
        paths = [path.strip() for path in evidence_paths if path.strip()]
        for hunk_id, path in [
            (identifier, part.split(" path=", 1)[1].split(">", 1)[0].strip('"'))
            for part in chunk["text"].split("<hunk id=")[1:]
            for identifier in [part.split(" ", 1)[0]]
        ]:
            candidates = allowed[hunk_id]
            if path in paths and candidates:
                hunk = hunk_id
                quote = next(
                    (line for line in candidates if len(line.strip()) >= 8
                     and not line.strip().startswith(("#", "//", "import", "from "))),
                    next((line for line in candidates if len(line.strip()) >= 8), None),
                )
                if quote is not None:
                    break
    if (hunk not in allowed or quote not in allowed[hunk]
            or len(quote.strip()) < 8 or score not in (1, 2, 3)):
        return None
    answer = {
        "observations": [{
            "hunk": hunk,
            "behavior": reason,
            "posthog_connection": reason,
            "code_quote": quote,
        }],
        "limitations": "The public diff does not prove adoption or measured user benefit.",
        "score": score, "reason": reason,
        "posthog_relevance": reason,
        "confidence": "medium" if source != "historical_ai_assisted" else "low",
        "evidence": [hunk],
        "uncertainty": "The public diff does not prove adoption or avoided incidents.",
        "metadata_dependency": False,
        "grouping_issue": False,
        "abstention_reason": None,
    }
    return {
        "source": source, "index": index, "prs": group["prs"],
        "diff_sha256": group["diff_sha256"],
        "instructions_sha256": packet["instructions_sha256"],
        "row": {"messages": [
            {"role": "system", "content": packet["system"]},
            {"role": "user", "content": one_pass_prompt(chunk)},
            {"role": "assistant", "content": json.dumps(answer, separators=(",", ":"))},
        ]},
    }


def build():
    pilot = json.loads((PILOT / "selection.json").read_text())
    old = json.loads((PILOT / "reviews.json").read_text())
    expert = json.loads((PILOT / "calibration.json").read_text())
    full = json.loads((FULL / "selection.json").read_text())
    teacher = json.loads((FULL / "teacher_labels.json").read_text())
    expert_indices = {answer["index"] for answer in expert}
    samples = []
    for answer in old:
        index = answer["index"]
        if index in expert_indices or answer["score"] is None:
            continue
        sample = example(
            index, pilot[index - 1], answer["score"], answer["reason"],
            "historical_ai_assisted", PILOT / "diffs",
            evidence_paths=answer["evidence"].split(";"),
        )
        if sample:
            samples.append(sample)
    for answer in teacher:
        index = answer["index"]
        sample = example(
            index, full[index - 1], answer["score"], answer["reason"],
            "gpt6_sol_in_session", FULL / "diffs",
            hunk=answer["hunk"], quote=answer["code_quote"],
        )
        if sample is None:
            raise ValueError(f"GPT-6 Sol label {index} lacks a complete diff and exact quote")
        samples.append(sample)
    heldout = []
    for answer in expert:
        index = answer["index"]
        group = pilot[index - 1]
        if (answer["diff_sha256"] != group["diff_sha256"]
                or answer["human_score"] not in (1, 2, 3)):
            raise ValueError(f"Expert calibration {index} is stale or unassessed")
        sample = example(
            index, group, answer["human_score"], answer["reason"],
            "human_expert", PILOT / "diffs",
            evidence_paths=old[index - 1]["evidence"].split(";"),
            max_chars=18000,
        )
        if sample is None or sample["instructions_sha256"] != answer["instructions_sha256"]:
            raise ValueError(f"Expert calibration {index} no longer matches the rubric")
        heldout.append(sample)
    if len({tuple(sample["prs"]) for sample in samples + heldout}) != len(samples + heldout):
        raise ValueError("A change group appears more than once")
    rng = random.Random(SEED)
    train, validation, test = [], [], []
    for score in (1, 2, 3):
        group = [
            item for item in samples
            if json.loads(item["row"]["messages"][-1]["content"])["score"] == score
        ]
        rng.shuffle(group)
        holdout = max(1, len(group) // 8) if len(group) >= 3 else 0
        validation.extend(group[:holdout])
        test.extend(group[holdout:2 * holdout])
        train.extend(group[2 * holdout:])
    return {"train": train, "valid": validation, "test": test + heldout}


def main():
    splits = build()
    DATASET.mkdir(parents=True, exist_ok=True)
    for name, samples in splits.items():
        path = DATASET / f"{name}.jsonl"
        path.write_text("".join(json.dumps(item["row"]) + "\n" for item in samples))
    manifest = {
        "purpose": "Weak AI-to-local-model rubric distillation; not human-verified outcomes",
        "seed": SEED, "max_diff_chars": LIMIT,
        "splits": {
            name: [{
                "index": item["index"], "prs": item["prs"],
                "source": item["source"], "diff_sha256": item["diff_sha256"],
                "instructions_sha256": item["instructions_sha256"],
                "score": json.loads(item["row"]["messages"][-1]["content"])["score"],
            } for item in samples] for name, samples in splits.items()
        },
        "dataset_sha256": {
            name: hashlib.sha256((DATASET / f"{name}.jsonl").read_bytes()).hexdigest()
            for name in splits
        },
    }
    (DATASET / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print({name: len(samples) for name, samples in splits.items()})
    print("Weak AI labels are not independent expert validation.")


if __name__ == "__main__":
    main()
