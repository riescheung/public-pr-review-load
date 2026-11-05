#!/usr/bin/env python3
"""Publish compact review progress without turning pilot judgments into rankings."""

import json
from pathlib import Path

from review_contract import FULL, OUTPUT, PILOT, review_instructions
from review_queue import CALIBRATION, read_json, review_case


DATA = Path(__file__).resolve().parents[1] / "data"
DESTINATION = DATA / "review_status.json"


def build_status(report, selection, calibrations, run_root, full_selection=(), full_run_root=None):
    prompt_hash = review_instructions()[1]
    cases = [
        review_case(index, group, run_root, prompt_hash, calibrations)
        for index, group in enumerate(selection, 1)
    ]
    all_cases = [
        review_case(index, group, full_run_root, prompt_hash)
        for index, group in enumerate(full_selection, 1)
    ] if full_run_root else cases
    calibrated = []
    for answer in calibrations:
        index = answer["index"]
        if not 1 <= index <= len(selection):
            continue
        group = selection[index - 1]
        if (answer["diff_sha256"] != group["diff_sha256"]
                or answer["instructions_sha256"] != prompt_hash):
            continue
        calibrated.append({
            "index": index,
            "prs": group["prs"],
            "wpr": group["wpr"],
            "tier": answer["human_score"],
            "reason": answer["reason"],
            "reviewer": answer["reviewer"],
        })
    flags = [{
        "scope": scope,
        "index": case["index"],
        "prs": case["prs"],
        "wpr": case["wpr"],
        "flags": case["flags"],
        "status": case["status"],
        "votes": [
            {"reviewer": review["reviewer_id"], "tier": review["score"]}
            for review in case["reviews"]
        ],
        "human_tier": case.get("human_score"),
    } for scope, group_cases in (
        ("full", all_cases), ("pilot", cases)
    ) for case in group_cases if case["flags"]]
    total = report["manifest"]["scored_groups"]
    reviewed = sum(bool(case["reviews"]) for case in all_cases)
    return {
        "scope": "PostHog/posthog 98-day snapshot",
        "total_groups": total,
        "pilot_groups": len(selection),
        "catalog_groups": len(full_selection),
        "cached_diff_groups": sum(
            set(group["diff_sha256"]) == set(map(str, group["prs"]))
            for group in full_selection
        ),
        "ai_reviewed_groups": reviewed,
        "awaiting_ai_review": total - reviewed,
        "pending_flags": sum(case["status"] == "pending" for case in all_cases if case["flags"])
            + sum(case["status"] == "pending" for case in cases if case["flags"]),
        "flags": flags,
        "calibrations": calibrated,
        "score_source": "The contributor grid ranks WPR review-load estimates. Outcome scores are blank; AI tiers are not applied.",
    }


def main():
    report = read_json(DATA / "report.json", {})
    selection = read_json(PILOT / "selection.json", [])
    calibrations = read_json(CALIBRATION, [])
    status = build_status(
        report, selection, calibrations, OUTPUT / "runs",
        read_json(FULL / "selection.json", []), FULL / "harness" / "runs",
    )
    DESTINATION.write_text(json.dumps(status, indent=2) + "\n")
    print(f"{status['ai_reviewed_groups']}/{status['total_groups']} groups have model runs; "
          f"{status['pending_flags']} flags need human review -> {DESTINATION}")


if __name__ == "__main__":
    main()
