#!/usr/bin/env python3
"""Flag AI review disagreements and record human calibration without changing the report."""

import argparse
from datetime import datetime, timezone
import json

from review_contract import FULL, OUTPUT, PILOT, REPOSITORY, VERSION, review_instructions


CALIBRATION = PILOT / "calibration.json"
HIGH_WPR = 7
LOW_WPR = 3


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def review_case(index, group, run_root, instructions_hash, calibrations=()):
    reviews = []
    for path in sorted((run_root / f"{index:02}").glob("*.json")):
        record = read_json(path, {})
        if any((
            record.get("version") != VERSION,
            record.get("repository") != REPOSITORY,
            record.get("index") != index,
            record.get("diff_sha256") != group["diff_sha256"],
            record.get("instructions_sha256") != instructions_hash,
            record.get("reviewer_id") != path.stem,
        )):
            raise ValueError(f"Stale or invalid review: {path}")
        review = record.get("review", {})
        score = review.get("score")
        if (type(score) is not int and score is not None
                or score not in (1, 2, 3, None)
                or type(review.get("grouping_issue")) is not bool):
            raise ValueError(f"Invalid score or grouping flag: {path}")
        reviews.append({
            "reviewer_id": path.stem,
            "model_id": record.get("model_id"),
            "score": score,
            "grouping_issue": review["grouping_issue"],
            "reason": review.get("reason", ""),
        })

    scores = [review["score"] for review in reviews]
    flags = set()
    if len(reviews) >= 2 and len(set(scores)) > 1:
        flags.add("reviewer_disagreement")
    if any(review["grouping_issue"] for review in reviews):
        flags.add("grouping_issue")
    if any(score is None for score in scores):
        flags.add("unassessed")
    if group["wpr"] >= HIGH_WPR and 1 in scores:
        flags.add("high_wpr_low_tier")
    if group["wpr"] < LOW_WPR and 3 in scores:
        flags.add("low_wpr_high_tier")

    votes = [{
        "reviewer_id": review["reviewer_id"], "score": review["score"],
        "grouping_issue": review["grouping_issue"],
    } for review in reviews]
    case = {
        "index": index, "prs": group["prs"], "diff_sha256": group["diff_sha256"],
        "instructions_sha256": instructions_hash, "wpr": group["wpr"],
        "reviews": reviews, "flags": sorted(flags), "review_votes": votes,
        "status": "pending",
    }
    for answer in reversed(calibrations):
        if all((
            answer.get("index") == index,
            answer.get("diff_sha256") == group["diff_sha256"],
            answer.get("instructions_sha256") == instructions_hash,
        )):
            case["status"] = "calibrated"
            case["human_score"] = answer["human_score"]
            case["human_reason"] = answer["reason"]
            case["review_votes_at_calibration"] = answer["review_votes"]
            if any(score != answer["human_score"] for score in scores):
                flags.add("human_calibration_mismatch")
            break
    case["flags"] = sorted(flags)
    return case


def build_queue(selection, run_root, calibrations):
    instructions_hash = review_instructions()[1]
    return [
        case for index, group in enumerate(selection, 1)
        if (case := review_case(index, group, run_root, instructions_hash, calibrations))["flags"]
    ]


def save_queue(selection, run_root, calibrations, destination):
    queue = build_queue(selection, run_root, calibrations)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(queue, indent=2) + "\n")
    return queue


def record_answer(case, score, reason, reviewer, path=CALIBRATION, manual=False):
    if not case["flags"] and not manual:
        raise ValueError("No review flag for this group; use --manual for expert-initiated reviews")
    if not reason or len(reason.strip()) < 15:
        raise ValueError("Give a specific explanation (at least 15 characters)")
    if not reviewer or not reviewer.strip():
        raise ValueError("Identify the human reviewer")
    if type(score) is not int and score is not None or score not in (1, 2, 3, None):
        raise ValueError("Human score must be 1, 2, 3 or unassessed")
    answers = read_json(path, [])
    if not isinstance(answers, list):
        raise ValueError("Calibration file must be an array")
    answer = {
        "index": case["index"], "prs": case["prs"],
        "diff_sha256": case["diff_sha256"],
        "instructions_sha256": case["instructions_sha256"],
        "review_votes": case["review_votes"], "flags": case["flags"],
        "human_score": score, "reason": reason.strip(),
        "reviewer": reviewer.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    answers.append(answer)
    path.write_text(json.dumps(answers, indent=2) + "\n")
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("queue", "answer"))
    parser.add_argument("--scope", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--index", type=int, help="1-based pilot group number")
    parser.add_argument("--score", choices=("1", "2", "3", "unassessed"))
    parser.add_argument("--reason", help="Human explanation for the chosen tier")
    parser.add_argument("--reviewer", help="Human reviewer identifier")
    parser.add_argument("--manual", action="store_true",
                        help="Record an expert review even without an AI flag")
    args = parser.parse_args()
    source = PILOT if args.scope == "pilot" else FULL
    output_dir = OUTPUT if args.scope == "pilot" else FULL / "harness"
    calibration_path = CALIBRATION if args.scope == "pilot" else FULL / "calibration.json"
    selection = read_json(source / "selection.json", [])
    calibrations = read_json(calibration_path, [])
    if args.action == "queue":
        destination = output_dir / "review_queue.json"
        queue = save_queue(selection, output_dir / "runs", calibrations, destination)
        print(f"{len(queue)} flagged groups -> {destination}")
        for case in queue:
            print(f"{case['index']:02}: {', '.join(case['flags'])} [{case['status']}]")
        return
    if (args.index is None or not 1 <= args.index <= len(selection)
            or args.score is None or not args.reason or not args.reviewer):
        parser.error("answer requires --index, --score, --reason and --reviewer")
    case = review_case(
        args.index, selection[args.index - 1], output_dir / "runs",
        review_instructions()[1], calibrations,
    )
    try:
        answer = record_answer(
            case, None if args.score == "unassessed" else int(args.score),
            args.reason, args.reviewer, path=calibration_path, manual=args.manual,
        )
    except ValueError as error:
        parser.error(str(error))
    save_queue(
        selection, output_dir / "runs", read_json(calibration_path, []),
        output_dir / "review_queue.json",
    )
    print(f"Recorded expert tier {answer['human_score']} for group {args.index}; report unchanged")


if __name__ == "__main__":
    main()
