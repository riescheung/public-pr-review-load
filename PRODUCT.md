# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React (user choice). Build tooling and hosting provider are not yet decided.

## Users

Busy PostHog engineering leaders who need to understand which engineers have
demonstrated impact without reading every PR or issue.

## Product Purpose

Analyze at least 90 days of public PostHog/posthog GitHub evidence and explain
the five highest-ranked contributors, while allowing exploration of every
observed human contributor.

## Operating Context

The dashboard is a single-page, laptop-screen-first report. It uses seven
adjacent, non-overlapping 14-day periods (98 days total) to show when distinct
outcomes were realized. Every person remains accessible through a compact,
paginated list, with the top five easy to scan.

## Capabilities and Constraints

- Base impact on distinct, evidence-linked outcomes, not lines changed, commit
  volume, or PR counts.
- Group PRs serving one outcome; do not count a feature once per PR.
- No arbitrary cap on a person's outcome count.
- Distinguish merged, shipped, and result-verified evidence; show uncertainty.
- Include all observed human contributors in the paginated list, including
  external contributors. Exclude bot accounts from rankings, and do not infer
  employment where public evidence does not establish it.
- Show the evidence, rubric, data window, and coverage limits behind rankings.
- Data acquisition from public GitHub is approved. External publication has not
  yet been approved.

## Evidence on Hand

The user supplied the assignment and the analysis framework, but no downloaded
PostHog data or verified engineer rankings. These must not be fabricated.

## Product Principles

1. Make each ranking challengeable through direct source links.
2. Prefer observed outcomes to activity proxies and unverified claims.
3. Show repeated contributions without rewarding PR splitting.
4. Say what public GitHub cannot establish.
