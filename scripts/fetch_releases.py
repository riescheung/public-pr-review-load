#!/usr/bin/env python3
"""Collect public repository release notes supporting shipped-status claims."""

import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "data" / "manifest.json").read_text())
start = date.fromisoformat(manifest["window_start"])
releases = []
page = 1
while True:
    command = [
        "gh", "api", "-X", "GET", "repos/PostHog/posthog/releases",
        "-f", "per_page=100", "-f", f"page={page}",
    ]
    for attempt in range(4):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            break
        if attempt == 3:
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        time.sleep(2 ** attempt * 3)
    batch = json.loads(result.stdout)
    if not batch:
        break
    for item in batch:
        published = item.get("published_at")
        if published and date.fromisoformat(published[:10]) >= start:
            body = item.get("body") or ""
            references = set(
                int(number) for number in re.findall(
                    r"github\.com/PostHog/posthog/pull/(\d+)", body, re.I
                )
            )
            releases.append({
                "tag": item["tag_name"],
                "name": item["name"],
                "url": item["html_url"],
                "published_at": published,
                "prs": sorted(references),
            })
    print(
        f"Release page {page}: {len(batch)} records; "
        f"{len(releases)} in window",
        flush=True,
    )
    if len(batch) < 100 or date.fromisoformat(batch[-1]["published_at"][:10]) < start:
        break
    page += 1

(ROOT / "data" / "releases.json").write_text(
    json.dumps(releases, separators=(",", ":"))
)
print(f"Collected {len(releases)} releases with "
      f"{sum(bool(r['prs']) for r in releases)} PR-linked notes")
