#!/usr/bin/env python3
"""Snapshot every merged PR in seven complete 14-day UTC intervals.

Requires an authenticated `gh` CLI. Each UTC day is cached independently so an
interrupted run can resume without repeating successful API requests.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
QUERY = """
query($searchQuery: String!, $cursor: String) {
  search(query: $searchQuery, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number title url mergedAt bodyText
        author { login __typename }
        labels(first: 12) { nodes { name } }
        closingIssuesReferences(first: 5) {
          nodes { number title url }
        }
        latestReviews(first: 15) {
          totalCount
          nodes {
            author { login __typename }
            state submittedAt
          }
        }
      }
    }
  }
}
"""


def graphql(day, cursor):
    query = f"repo:PostHog/posthog is:pr is:merged merged:{day}..{day}"
    command = [
        "gh", "api", "graphql", "-f", f"query={QUERY}",
        "-F", f"searchQuery={query}",
    ]
    if cursor:
        command += ["-F", f"cursor={cursor}"]
    for attempt in range(5):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if not payload.get("errors"):
                return payload["data"]["search"]
            error = str(payload["errors"])
        else:
            error = result.stderr.strip()
        if attempt == 4:
            raise RuntimeError(f"GitHub query failed for {day}: {error}")
        time.sleep(min(2 ** attempt * 3, 30))


def fetch_day(day):
    path = RAW / f"{day}.json"
    if path.exists():
        return len(json.loads(path.read_text())["pulls"]), True
    cursor = None
    pulls = []
    expected = None
    while True:
        result = graphql(day, cursor)
        expected = result["issueCount"]
        if expected > 1000:
            raise RuntimeError(
                f"{day} has {expected} PRs, above GitHub search's 1000-item "
                "pagination limit; subdivide this day before continuing."
            )
        pulls.extend(node for node in result["nodes"] if node and node.get("mergedAt"))
        page = result["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
        if not cursor:
            raise RuntimeError(f"Missing pagination cursor for {day}")
    if len(pulls) != expected or len({pr["number"] for pr in pulls}) != expected:
        raise RuntimeError(
            f"Incomplete search for {day}: received {len(pulls)} of {expected}"
        )
    payload = {"day": str(day), "count": expected, "pulls": pulls}
    with tempfile.NamedTemporaryFile(
        mode="w", dir=RAW, prefix=".day-", suffix=".json", delete=False
    ) as output:
        json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
        temp_path = Path(output.name)
    temp_path.replace(path)
    return expected, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--end", type=date.fromisoformat,
        default=datetime.now(timezone.utc).date() - timedelta(days=1),
        help="Last complete UTC day to include (YYYY-MM-DD)",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    start = args.end - timedelta(days=97)
    total = 0
    days = [start + timedelta(days=offset) for offset in range(98)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_day, day): day for day in days}
        for number, future in enumerate(as_completed(futures), 1):
            day = futures[future]
            count, cached = future.result()
            total += count
            print(
                f"{day}: {count} merged PRs{' (cached)' if cached else ''} "
                f"[{number}/98, total {total}]",
                flush=True,
            )
    manifest = {
        "repository": "PostHog/posthog",
        "window_start": str(start),
        "window_end": str(args.end),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "days": 98,
        "merged_prs": total,
        "source": "GitHub GraphQL merged PR search, UTC-day pagination",
        "limitations": [
            "GitHub search may be updated after this snapshot.",
            "Reviews are latest per reviewer; earlier review rounds are not captured.",
            "Private work, usage analytics, and unlinked deployment results are unavailable.",
        ],
    }
    (ROOT / "data" / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
