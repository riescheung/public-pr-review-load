#!/usr/bin/env python3
"""Fetch every changed file for the same PR snapshot, for review-load context."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUTPUT = ROOT / "data" / "raw_files"
SEARCH = """
query($searchQuery: String!, $cursor: String) {
  search(query: $searchQuery, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        files(first: 100) {
          totalCount pageInfo { hasNextPage endCursor }
          nodes { path additions deletions changeType }
        }
      }
    }
  }
}
"""
EXTRA = """
query($number: Int!, $cursor: String!) {
  repository(owner: "PostHog", name: "posthog") {
    pullRequest(number: $number) {
      files(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { path additions deletions changeType }
      }
    }
  }
}
"""


def graphql(document, **variables):
    command = ["gh", "api", "graphql", "-f", f"query={document}"]
    for name, value in variables.items():
        command += ["-F", f"{name}={value}"]
    for attempt in range(5):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            response = json.loads(result.stdout)
            if not response.get("errors"):
                return response["data"]
            error = str(response["errors"])
        else:
            error = result.stderr.strip()
        if attempt == 4:
            raise RuntimeError(error)
        time.sleep(min(2 ** attempt * 3, 30))


def fetch(day_path):
    dest = OUTPUT / day_path.name
    if dest.exists():
        return day_path.stem, len(json.loads(dest.read_text())), True
    day = day_path.stem
    source = json.loads(day_path.read_text())
    expected = {pr["number"] for pr in source["pulls"]}
    result = {}
    cursor = None
    while True:
        query = f"repo:PostHog/posthog is:pr is:merged merged:{day}..{day}"
        variables = {"searchQuery": query}
        if cursor:
            variables["cursor"] = cursor
        search = graphql(SEARCH, **variables)["search"]
        for pr in search["nodes"]:
            if not pr:
                continue
            connection = pr["files"]
            files = connection["nodes"]
            page = connection["pageInfo"]
            while page["hasNextPage"]:
                next_page = graphql(
                    EXTRA, number=pr["number"], cursor=page["endCursor"]
                )["repository"]["pullRequest"]["files"]
                files.extend(next_page["nodes"])
                page = next_page["pageInfo"]
            if len(files) != connection["totalCount"]:
                raise RuntimeError(f"PR #{pr['number']}: truncated file list")
            result[pr["number"]] = files
        if not search["pageInfo"]["hasNextPage"]:
            break
        cursor = search["pageInfo"]["endCursor"]
    if set(result) != expected:
        raise RuntimeError(
            f"{day}: diff coverage {len(result)} PRs, expected {len(expected)}"
        )
    with tempfile.NamedTemporaryFile(
        mode="w", dir=OUTPUT, prefix=".files-", suffix=".json", delete=False
    ) as output:
        json.dump(result, output, separators=(",", ":"))
        temp = Path(output.name)
    temp.replace(dest)
    return day, len(result), False


def main():
    paths = sorted(RAW.glob("*.json"))
    if len(paths) != 98:
        raise RuntimeError(f"Expected 98 days of PRs, found {len(paths)}")
    total = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, path) for path in paths]
        for index, future in enumerate(as_completed(futures), 1):
            day, count, cached = future.result()
            total += count
            print(
                f"{day}: {count} PR diffs{' (cached)' if cached else ''} "
                f"[{index}/98, total {total}]",
                flush=True,
            )
    print(f"Fetched all files for {total} PRs")


if __name__ == "__main__":
    main()
