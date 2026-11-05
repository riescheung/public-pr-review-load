#!/usr/bin/env python3
"""Turn the GitHub snapshot into an auditable, explicitly provisional report."""

from collections import defaultdict
from datetime import date, timedelta
import json
from pathlib import Path
import re

from weighted_pr import classify, is_net_revert, weighted_pr


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MANIFEST = json.loads((DATA / "manifest.json").read_text())
START = date.fromisoformat(MANIFEST["window_start"])
END = date.fromisoformat(MANIFEST["window_end"])
PART = re.compile(r"\b(?:part|phase)\s*\d+\s*(?:/|of)\s*\d+\b", re.I)
PREFIX = re.compile(r"^(?:feat|fix|perf|chore|docs|test|refactor|ci)"
                    r"(?:\([^)]*\))?!?:\s*", re.I)
HIGH_RISK = re.compile(
    r"\b(data loss|data corruption|security bypass|ssrf|outage|"
    r"deadlock|silent(?:ly)? drop|permanent(?:ly)? fail)\b", re.I
)


def title_key(pr):
    title = PREFIX.sub("", pr["title"].lower())
    title = PART.sub("", title)
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    return title


def cluster_key(pr):
    issues = pr["closingIssuesReferences"]["nodes"]
    if issues:
        return f"issue:{issues[0]['number']}"
    # Only exact, specific repeat titles are folded; a shared product area alone
    # is not evidence that unrelated fixes are one change group.
    subject = title_key(pr)
    if len(subject) > 28 and len(subject.split()) >= 5:
        return f"title:{pr['author']['login']}:{subject}"
    return f"pr:{pr['number']}"


def evidence_source(prs, released):
    if all(is_net_revert(pr["title"]) for pr in prs):
        return None
    if released:
        return "Release note"
    if any(pr["closingIssuesReferences"]["nodes"] for pr in prs):
        return "Closing issue"
    return None


def score_group(prs, files, loads):
    eligible = [
        pr for pr in prs
        if not is_net_revert(pr["title"]) and any(
            entry["additions"] + entry["deletions"] > 0
            and classify(entry["path"])[0] not in {"ASSET", "GENERATED"}
            for entry in files[pr["number"]]
        )
    ]
    if not eligible:
        return 0, 0, 0, "Revert or no substantive changed files.", []

    def tier(pr):
        title = pr["title"]
        if re.match(r"^(?:chore|docs|test|ci|build|refactor|bump)", title, re.I):
            return 1
        if HIGH_RISK.search(title) and len(pr["bodyText"].strip()) > 80:
            return 3
        if re.match(r"^(?:fix|feat|feature|perf)", title, re.I):
            return 2
        return 1

    base = max(tier(pr) for pr in eligible)
    scope = max(loads[pr["number"]] for pr in eligible)
    bonus = 1 if scope >= 7 else 0.5 if scope >= 3 else 0
    rationale = {
        1: "Maintenance, documentation, or enabling change.",
        2: "Described fix, capability, or performance change.",
        3: "Described high-risk failure or security change; severity is unverified.",
    }[base]
    return base, bonus, scope, rationale, sorted({
        pr["author"]["login"] for pr in eligible
    })


def periods():
    return [
        {
            "start": str(START + timedelta(days=14 * index)),
            "end": str(START + timedelta(days=14 * index + 13)),
            "label": (START + timedelta(days=14 * index + 13)).strftime("%m/%d"),
        }
        for index in range(7)
    ]


def main():
    raw = sorted((DATA / "raw").glob("*.json"))
    if len(raw) != 98:
        raise RuntimeError("Full 98-day GitHub snapshot is required")
    pulls = [pr for path in raw for pr in json.loads(path.read_text())["pulls"]]
    if len(pulls) != MANIFEST["merged_prs"]:
        raise RuntimeError("Snapshot size does not match manifest")
    human = [
        pr for pr in pulls
        if (pr.get("author") or {}).get("__typename") == "User"
    ]
    diff_days = sorted((DATA / "raw_files").glob("*.json"))
    if len(diff_days) != 98:
        raise RuntimeError("Full PR file snapshot is required to score work")
    files = {
        int(number): entries
        for path in diff_days
        for number, entries in json.loads(path.read_text()).items()
    }
    if set(files) != {pr["number"] for pr in pulls}:
        raise RuntimeError("WPR coverage does not match the PR snapshot")
    loads = {
        pr["number"]: weighted_pr(files[pr["number"]], pr["title"])
        for pr in human
    }
    releases = json.loads((DATA / "releases.json").read_text())
    release_by_pr = {}
    for release in releases:
        if date.fromisoformat(release["published_at"][:10]) > END:
            continue
        for number in release["prs"]:
            if number not in release_by_pr or (
                release["published_at"] < release_by_pr[number]["published_at"]
            ):
                release_by_pr[number] = release

    groups = defaultdict(list)
    for pr in human:
        groups[cluster_key(pr)].append(pr)
    scored_groups = []
    linked_count = 0
    for key, group in groups.items():
        group.sort(key=lambda pr: pr["mergedAt"])
        linked_releases = [
            release_by_pr[pr["number"]]
            for pr in group if pr["number"] in release_by_pr
        ]
        release = min(
            linked_releases, key=lambda item: item["published_at"]
        ) if linked_releases else None
        source = evidence_source(group, release)
        base, bonus, scope, rationale, owners = score_group(group, files, loads)
        if not owners:
            continue
        issue = next(
            (item for pr in group
             for item in pr["closingIssuesReferences"]["nodes"]), None
        )
        merged = group[-1]["mergedAt"][:10]
        event = release["published_at"][:10] if release else merged
        event = min(event, str(END))
        period = (date.fromisoformat(event) - START).days // 14
        if not 0 <= period < 7:
            raise RuntimeError(f"Group {key} outside the 98-day window")
        linked_count += bool(source)
        scored_groups.append({
            "id": key,
            "title": issue["title"] if issue else group[-1]["title"],
            "status": "Released" if release else "Merged",
            "event": event,
            "period": period,
            "source": source or "PR only",
            "base": base,
            "scope_bonus": bonus,
            "scope_wpr": scope,
            "points": base + bonus,
            "rationale": rationale,
            "evidence": (
                [dict(type="Release", url=release["url"], label=release["tag"])]
                if release else []
            ) + (
                [dict(type="Issue", url=issue["url"],
                      label=f"#{issue['number']}")]
                if issue else []
            ) + [
                dict(type="PR", url=pr["url"], label=f"#{pr['number']}")
                for pr in group
            ],
            "pr_count": len(group),
            "owners": owners,
        })
    scored_groups.sort(
        key=lambda item: (item["points"], item["event"], item["id"]),
        reverse=True,
    )
    people = {}
    for pr in human:
        login = pr["author"]["login"]
        person = people.setdefault(login, {
            "login": login, "score": 0, "wpr": 0,
            "merged_prs": 0, "reviewed_prs": 0, "group_count": 0,
            "linked_count": 0,
            "periods": [
                {"score": 0, "wpr": 0, "groups": 0,
                 "linked_count": 0, "examples": [], "prs": []}
                for _ in range(7)
            ],
            "featured": [],
        })
        person["merged_prs"] += 1
        index = (date.fromisoformat(pr["mergedAt"][:10]) - START).days // 14
        if not 0 <= index < 7:
            raise RuntimeError(f"PR {pr['number']} outside the 98-day window")
        load = loads[pr["number"]]
        summary = {"number": pr["number"], "title": pr["title"], "wpr": load}
        person["periods"][index]["prs"].append(summary)
        person["wpr"] += load
        person["periods"][index]["wpr"] += load
    for pr in pulls:
        for review in pr["latestReviews"]["nodes"]:
            author = review.get("author") or {}
            login = author.get("login")
            if author.get("__typename") != "User" or not login:
                continue
            person = people.setdefault(login, {
                "login": login, "score": 0, "wpr": 0,
                "merged_prs": 0, "reviewed_prs": 0, "group_count": 0,
                "linked_count": 0,
                "periods": [
                    {"score": 0, "wpr": 0, "groups": 0,
                     "linked_count": 0, "examples": [], "prs": []}
                    for _ in range(7)
                ],
                "featured": [],
            })
            person["reviewed_prs"] += 1
    for group in scored_groups:
        share = round(group["points"] / len(group["owners"]), 3)
        for login in group["owners"]:
            person = people[login]
            person["score"] += share
            person["group_count"] += 1
            person["linked_count"] += bool(group["source"] != "PR only")
            cell = person["periods"][group["period"]]
            cell["score"] += share
            cell["groups"] += 1
            cell["linked_count"] += bool(group["source"] != "PR only")
            credited = {**group, "credited_points": share}
            cell["examples"].append(credited)
            if len(person["featured"]) < 5:
                person["featured"].append(credited)
    for person in people.values():
        person["score"] = round(person["score"], 1)
        for cell in person["periods"]:
            cell["score"] = round(cell["score"], 1)
            cell["prs"].sort(
                key=lambda pr: (-(pr["wpr"] or 0), pr["number"])
            )
    report = {
        "manifest": {
            **MANIFEST,
            "human_prs": len(human),
            "bot_prs": sum(
                (pr.get("author") or {}).get("__typename") == "Bot"
                for pr in pulls
            ),
            "change_groups": len(groups),
            "linked_release_prs": sum(pr["number"] in release_by_pr for pr in human),
            "linked_groups": linked_count,
            "scored_groups": len(scored_groups),
            "wpr_complete": True,
            "wpr_note": (
                "Estimated weighted PR review load from file diffs; "
                "slush-branch residual subtraction is not available in this "
                "snapshot. The largest WPR in a group can add at most one "
                "scope point. Review load is not author effort or user benefit."
            ),
        },
        "periods": periods(),
        "people": sorted(
            people.values(),
            key=lambda person: (-person["score"], person["login"].lower()),
        ),
    }
    (DATA / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    )
    print(json.dumps({
        "people": len(people),
        "scored_groups": len(scored_groups),
        "coverage": report["manifest"],
    }, indent=2))


if __name__ == "__main__":
    main()
