#!/usr/bin/env python3
"""Turn the GitHub snapshot into an auditable, conservative impact report."""

from collections import Counter, defaultdict
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re

from weighted_pr import weighted_pr


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MANIFEST = json.loads((DATA / "manifest.json").read_text())
START = date.fromisoformat(MANIFEST["window_start"])
END = date.fromisoformat(MANIFEST["window_end"])
SEVERE = re.compile(
    r"\b(data loss|data corruption|security bypass|ssrf|incident|outage|"
    r"deadlock|silent(?:ly)? drop|permanent(?:ly)? fail|unavailable)\b", re.I
)
PERFORMANCE = re.compile(
    r"\b(p95|p99|latency|throughput|memory leak|oom|backpressure)\b", re.I
)
MEASURED = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|ms|seconds?|minutes?|x)\s+"
    r"(?:faster|slower|reduction|improvement|lower|higher)\b|"
    r"\bfrom\s+\d+(?:\.\d+)?\s*(?:ms|s|%)?\s+to\s+"
    r"\d+(?:\.\d+)?\s*(?:ms|s|%)\b)", re.I
)
PART = re.compile(r"\b(?:part|phase)\s*\d+\s*(?:/|of)\s*\d+\b", re.I)
PREFIX = re.compile(r"^(?:feat|fix|perf|chore|docs|test|refactor|ci)"
                    r"(?:\([^)]*\))?!?:\s*", re.I)


def category(title):
    text = title.lower()
    if re.search(r"\b(security|ssrf|xss|permissions?|auth)\b", text):
        return "Security"
    if re.search(r"\b(perf|latency|throughput|memory|oom|query speed)\b", text):
        return "Performance"
    if re.search(r"\b(incident|ingestion|outage|retry|data loss|"
                 r"reliability|race condition|deadlock)\b", text):
        return "Reliability"
    if re.match(r"^(?:chore|ci|refactor|test|build)", text):
        return "Platform"
    if re.match(r"^(?:docs|documentation)", text):
        return "Documentation"
    return "Product"


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
    # is not evidence that unrelated fixes are one outcome.
    subject = title_key(pr)
    if len(subject) > 28 and len(subject.split()) >= 5:
        return f"title:{pr['author']['login']}:{subject}"
    return f"pr:{pr['number']}"


def score_outcome(prs, released):
    title = prs[0]["title"]
    body = "\n".join(pr["bodyText"][:3500] for pr in prs[:3])
    source = "release" if released else (
        "issue" if any(pr["closingIssuesReferences"]["nodes"] for pr in prs)
        else "PR-reported metric" if MEASURED.search(body)
        else "PR description"
    )
    confidence = 0.75 if source in ("release", "issue") else 0.5
    meaningful = len(body.strip()) > 80
    kind = category(title)
    if re.match(r"^revert(?:\b|:)", title, re.I):
        return 0, confidence, "Reverted change; not credited as a new outcome."
    if source == "PR description":
        return (
            0, confidence,
            "No linked issue, release note, or quantitative result to substantiate "
            "an outcome beyond the merged PR.",
        )
    if re.match(r"^(?:chore|docs|test|ci|build|release|bump)", title, re.I):
        value = 1 if meaningful or source != "PR description" else 0
        reason = "Documented maintenance or enabling work."
    elif not meaningful and source == "PR description":
        value = 0
        reason = "Merged, but the available description cannot establish an outcome."
    elif SEVERE.search(title):
        value = 4 if source != "PR description" else 3
        reason = "Addresses a described high-severity correctness or availability risk."
    elif PERFORMANCE.search(title) and MEASURED.search(body):
        value = 3
        reason = "Performance work with a quantitative result reported in the PR."
    elif re.match(r"^(?:feat|feature)", title, re.I):
        value = 3 if source != "PR description" else 2
        reason = "Adds a documented user-facing capability."
    elif re.match(r"^fix", title, re.I):
        value = 2
        reason = "Fixes a described failure or user-visible defect."
    else:
        value = 1 if meaningful else 0
        reason = "Documented improvement with limited outcome evidence."
    if kind == "Documentation" and value:
        reason = "Improves documented user or developer guidance."
    return value, confidence, reason


def periods():
    return [
        {
            "start": str(START + timedelta(days=14 * index)),
            "end": str(START + timedelta(days=14 * index + 13)),
            "label": (START + timedelta(days=14 * index + 13)).strftime("%m/%d"),
        }
        for index in range(7)
    ]


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return 0
    return ordered[round((len(ordered) - 1) * fraction)]


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
    outcome_list = []
    for key, group in groups.items():
        group.sort(key=lambda pr: pr["mergedAt"])
        linked_releases = [
            release_by_pr[pr["number"]]
            for pr in group if pr["number"] in release_by_pr
        ]
        release = min(
            linked_releases, key=lambda item: item["published_at"]
        ) if linked_releases else None
        value, confidence, reason = score_outcome(group, release)
        issue = next(
            (item for pr in group
             for item in pr["closingIssuesReferences"]["nodes"]), None
        )
        owners = sorted({pr["author"]["login"] for pr in group})
        merged = group[-1]["mergedAt"][:10]
        event = release["published_at"][:10] if release else merged
        event = min(event, str(END))
        period = (date.fromisoformat(event) - START).days // 14
        if not 0 <= period < 7:
            raise RuntimeError(f"Outcome {key} outside the 98-day window")
        outcome_list.append({
            "id": key,
            "title": issue["title"] if issue else group[-1]["title"],
            "kind": category(group[-1]["title"]),
            "status": "Released" if release else "Merged",
            "event": event,
            "period": period,
            "score": value,
            "confidence": confidence,
            "points": round(value * confidence, 2),
            "rationale": reason,
            "evidence": (
                [dict(type="Release", url=release["url"], label=release["tag"])]
                if release else []
            ) + (
                [dict(type="Issue", url=issue["url"],
                      label=f"#{issue['number']}")]
                if issue else []
            ) + [
                dict(type="PR", url=pr["url"], label=f"#{pr['number']}")
                for pr in group[:5]
            ],
            "pr_count": len(group),
            "owners": owners,
        })
    outcome_list.sort(key=lambda item: (-item["points"], item["event"]))
    people = {}
    pr_summaries = {}
    for pr in human:
        login = pr["author"]["login"]
        person = people.setdefault(login, {
            "login": login, "score": 0, "wpr": None,
            "merged_prs": 0, "reviewed_prs": 0, "outcome_count": 0,
            "periods": [
                {"score": 0, "wpr": None, "outcomes": 0, "examples": [], "prs": []}
                for _ in range(7)
            ],
            "featured": [],
        })
        person["merged_prs"] += 1
        index = (date.fromisoformat(pr["mergedAt"][:10]) - START).days // 14
        if not 0 <= index < 7:
            raise RuntimeError(f"PR {pr['number']} outside the 98-day window")
        summary = {"number": pr["number"], "title": pr["title"], "wpr": None}
        person["periods"][index]["prs"].append(summary)
        pr_summaries[pr["number"]] = summary
    for pr in pulls:
        for review in pr["latestReviews"]["nodes"]:
            author = review.get("author") or {}
            login = author.get("login")
            if author.get("__typename") != "User" or not login:
                continue
            person = people.setdefault(login, {
                "login": login, "score": 0, "wpr": None,
                "merged_prs": 0, "reviewed_prs": 0, "outcome_count": 0,
                "periods": [
                    {"score": 0, "wpr": None, "outcomes": 0, "examples": [], "prs": []}
                    for _ in range(7)
                ],
                "featured": [],
            })
            person["reviewed_prs"] += 1
    for outcome in outcome_list:
        if not outcome["score"]:
            continue
        share = round(outcome["points"] / len(outcome["owners"]), 3)
        for login in outcome["owners"]:
            person = people[login]
            person["score"] += share
            person["outcome_count"] += 1
            cell = person["periods"][outcome["period"]]
            cell["score"] += share
            cell["outcomes"] += 1
            credited = {**outcome, "credited_points": share}
            cell["examples"].append(credited)
            if len(person["featured"]) < 5:
                person["featured"].append(credited)
    for person in people.values():
        person["score"] = round(person["score"], 1)
        for cell in person["periods"]:
            cell["score"] = round(cell["score"], 1)
    diff_days = sorted((DATA / "raw_files").glob("*.json"))
    has_wpr = len(diff_days) == 98
    if has_wpr:
        files = {
            int(number): entries
            for path in diff_days
            for number, entries in json.loads(path.read_text()).items()
        }
        if len(files) != len(pulls):
            raise RuntimeError("WPR coverage does not match the PR snapshot")
        mature_cutoff = END - timedelta(days=28)
        for person in people.values():
            person["wpr"] = 0
            person["mature_wpr"] = 0
            person["mature_score"] = 0
            for cell in person["periods"]:
                cell["wpr"] = 0
        load_by_pr = {}
        for pr in human:
            person = people[pr["author"]["login"]]
            load = weighted_pr(files[pr["number"]], pr["title"])
            load_by_pr[pr["number"]] = load
            pr_summaries[pr["number"]]["wpr"] = load
            person["wpr"] += load
            index = (date.fromisoformat(pr["mergedAt"][:10]) - START).days // 14
            person["periods"][index]["wpr"] += load
            if date.fromisoformat(pr["mergedAt"][:10]) <= mature_cutoff:
                person["mature_wpr"] += load
        for outcome in outcome_list:
            if date.fromisoformat(outcome["event"]) > mature_cutoff:
                continue
            for login in outcome["owners"]:
                people[login]["mature_score"] += (
                    outcome["points"] / len(outcome["owners"])
                )
        cohort = [person for person in people.values()
                  if person["merged_prs"] >= 10]
        load_cutoff = percentile(
            [person["mature_wpr"] for person in cohort], 0.75
        )
        impact_cutoff = percentile(
            [person["mature_score"] for person in cohort], 0.50
        )
        scored_keys = {item["id"] for item in outcome_list if item["score"]}
        attention_prs = defaultdict(list)
        for pr in human:
            if pr["mergedAt"][:10] <= str(mature_cutoff) and (
                cluster_key(pr) not in scored_keys
            ):
                attention_prs[pr["author"]["login"]].append(pr)
        for person in people.values():
            person["attention"] = (
                person["merged_prs"] >= 10
                and person["mature_wpr"] >= load_cutoff
                and person["mature_score"] <= impact_cutoff
            )
            if person["attention"]:
                samples = sorted(
                    attention_prs[person["login"]],
                    key=lambda pr: (-load_by_pr[pr["number"]], pr["number"]),
                )[:3]
                person["attention_context"] = {
                    "mature_wpr": person["mature_wpr"],
                    "mature_score": round(person["mature_score"], 3),
                    "unscored_examples": [
                        {
                            "number": pr["number"],
                            "title": pr["title"],
                            "url": pr["url"],
                            "wpr": load_by_pr[pr["number"]],
                        }
                        for pr in samples
                    ],
                }
            del person["mature_wpr"]
            del person["mature_score"]
    else:
        for person in people.values():
            person["attention"] = False
    for person in people.values():
        for cell in person["periods"]:
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
            "outcome_groups": len(outcome_list),
            "linked_release_prs": sum(pr["number"] in release_by_pr for pr in human),
            "scored_outcomes": sum(bool(item["score"]) for item in outcome_list),
            "wpr_complete": has_wpr,
            "attention_cohort": (
                {
                    "as_of": str(mature_cutoff),
                    "contributors": len(cohort),
                    "minimum_merges": 10,
                    "wpr_cutoff": load_cutoff,
                    "impact_cutoff": round(impact_cutoff, 3),
                }
                if has_wpr else None
            ),
            "wpr_note": (
                "Estimated weighted PR review load from file diffs; "
                "slush-branch residual subtraction is not available in this "
                "snapshot. The attention marker uses the mature (28+ days) "
                "upper-quartile load and lower-half observed impact among "
                "authors with at least 10 merged PRs."
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
        "top": [(p["login"], p["score"], p["outcome_count"])
                for p in report["people"][:12]],
        "coverage": report["manifest"],
    }, indent=2))


if __name__ == "__main__":
    main()
