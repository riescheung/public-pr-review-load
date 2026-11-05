#!/usr/bin/env python3
"""Select varied change groups and cache their full public PR diffs for review."""

from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess

from build_report import DATA, cluster_key, score_group
from weighted_pr import weighted_pr


OUT = DATA / "ai_pilot"
SEED = 20261104
SAMPLE_SIZES = {
    "high_volume": 12,
    "other_small": 12,
    "other_medium": 10,
    "linked": 8,
    "large": 4,
    "multi_pr": 4,
}


def select():
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
    groups = defaultdict(list)
    for pr in pulls:
        groups[cluster_key(pr)].append(pr)

    candidates = defaultdict(list)
    for key, group in groups.items():
        if len(group) > 3:
            continue
        changed = sum(
            entry["additions"] + entry["deletions"]
            for pr in group for entry in files[pr["number"]]
        )
        loads = {
            pr["number"]: weighted_pr(files[pr["number"]], pr["title"])
            for pr in group
        }
        load = max(loads.values())
        base, bonus, _, _, _ = score_group(group, files, loads)
        authors = {pr["author"]["login"] for pr in group}
        sample = {
            "id": key, "prs": [pr["number"] for pr in group],
            "authors": sorted(authors), "changed_lines": changed,
            "wpr": load, "old_points": base + bonus,
        }
        if len(group) > 1 and changed <= 600:
            candidates["multi_pr"].append(sample)
        if any(pr["closingIssuesReferences"]["nodes"] for pr in group) and changed <= 300:
            candidates["linked"].append(sample)
        if load >= 7 and changed <= 2500:
            candidates["large"].append(sample)
        if load < 3 and changed <= 180:
            candidates["high_volume" if "Gilbert09" in authors else "other_small"].append(sample)
        if 3 <= load <= 6 and changed <= 400 and "Gilbert09" not in authors:
            candidates["other_medium"].append(sample)

    rng = random.Random(SEED)
    selected = []
    used = set()
    for stratum, size in SAMPLE_SIZES.items():
        choices = candidates[stratum][:]
        rng.shuffle(choices)
        picked = 0
        for sample in choices:
            if sample["id"] in used:
                continue
            selected.append({**sample, "stratum": stratum})
            used.add(sample["id"])
            picked += 1
            if picked == size:
                break
        if picked != size:
            raise RuntimeError(f"Only {picked} distinct {stratum} groups, need {size}")
    return selected


def fetch(groups):
    dest = OUT / "diffs"
    dest.mkdir(parents=True, exist_ok=True)
    for index, group in enumerate(groups, 1):
        hashes = {}
        errors = {}
        for number in group["prs"]:
            path = dest / f"{number}.diff"
            if path.exists():
                patch = path.read_bytes()
            else:
                result = subprocess.run(
                    ["gh", "api", "-H", "Accept: application/vnd.github.diff",
                     f"repos/PostHog/posthog/pulls/{number}"],
                    capture_output=True,
                )
                if result.returncode:
                    errors[str(number)] = result.stderr.decode(errors="replace")[-400:]
                    continue
                patch = result.stdout
            if not patch.startswith(b"diff --git "):
                errors[str(number)] = "GitHub returned no usable diff"
                continue
            if not path.exists():
                path.write_bytes(patch)
            hashes[str(number)] = hashlib.sha256(patch).hexdigest()
        group["diff_sha256"] = hashes
        if errors:
            group["fetch_errors"] = errors
        else:
            group.pop("fetch_errors", None)
        print(f"{index}/{len(groups)} {group['id']}: {len(hashes)}/{len(group['prs'])} diffs")
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Use GitHub network API")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "selection.json"
    groups = json.loads(path.read_text()) if path.exists() else select()
    if args.fetch:
        groups = fetch(groups)
    path.write_text(json.dumps(groups, indent=2) + "\n")
    print(f"Selected {len(groups)} groups in {path}")


if __name__ == "__main__":
    main()
