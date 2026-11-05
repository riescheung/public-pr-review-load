#!/usr/bin/env python3
"""Build a deterministic full-snapshot review selection and fetch diffs in batches."""

from collections import defaultdict
import argparse
import json
from pathlib import Path
import tempfile

import ai_pilot
from build_report import DATA, cluster_key, score_group
from weighted_pr import weighted_pr


FULL = DATA / "ai_review"
SELECTION = FULL / "selection.json"


def save_selection(groups):
    FULL.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=FULL, suffix=".json", delete=False) as output:
        json.dump(groups, output, separators=(",", ":"))
        temp = Path(output.name)
    temp.replace(SELECTION)


def select_all():
    pulls = [
        pr for path in sorted((DATA / "raw").glob("*.json"))
        for pr in json.loads(path.read_text())["pulls"]
        if (pr.get("author") or {}).get("__typename") == "User"
    ]
    files = {
        int(number): entries
        for path in sorted((DATA / "raw_files").glob("*.json"))
        for number, entries in json.loads(path.read_text()).items()
    }
    loads = {
        pr["number"]: weighted_pr(files[pr["number"]], pr["title"])
        for pr in pulls
    }
    groups = defaultdict(list)
    for pr in pulls:
        groups[cluster_key(pr)].append(pr)
    existing = {
        group["id"]: group for group in json.loads(SELECTION.read_text())
    } if SELECTION.exists() else {}
    selected = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda pr: pr["mergedAt"])
        _, _, scope, _, owners = score_group(group, files, loads)
        if not owners:
            continue
        numbers = [pr["number"] for pr in group]
        old = existing.get(key, {})
        selected.append({
            "id": key, "prs": numbers, "wpr": scope,
            "diff_sha256": old.get("diff_sha256", {}) if old.get("prs") == numbers else {},
        })
    expected = json.loads((DATA / "report.json").read_text())["manifest"]["scored_groups"]
    if len(selected) != expected:
        raise RuntimeError(f"Catalog has {len(selected)} groups; report has {expected}")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-limit", type=int, default=0,
                        help="Fetch this many groups without cached hashes; 0 builds catalog only")
    parser.add_argument("--all", action="store_true", help="Fetch all missing public PR diffs")
    args = parser.parse_args()
    if args.fetch_limit < 0 or args.all and args.fetch_limit:
        parser.error("Choose a nonnegative --fetch-limit or --all")
    selected = select_all()
    save_selection(selected)
    if args.all or args.fetch_limit:
        pending = [group for group in selected if set(group["diff_sha256"]) != set(map(str, group["prs"]))]
        count = len(pending) if args.all else min(args.fetch_limit, len(pending))
        ai_pilot.OUT = FULL
        for start in range(0, count, 25):
            ai_pilot.fetch(pending[start:start + 25])
            save_selection(selected)
    print(f"{len(selected)} eligible groups; "
          f"{sum(set(group['diff_sha256']) == set(map(str, group['prs'])) for group in selected)} complete diff sets")


if __name__ == "__main__":
    main()
