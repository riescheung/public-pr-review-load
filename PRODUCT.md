# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React (user choice). Build tooling and hosting provider are not yet decided.

## Users

PostHog engineering leaders inspecting estimated public contributions without
treating documentation coverage or review load as verified individual impact.

## Product Purpose

Show WPR review-load estimates across at least 90 days of public
PostHog/posthog work, alongside explicitly labelled AI-estimated contribution.
Do not present either as verified customer outcomes.

## Operating Context

The dashboard is a single-page, laptop-screen-first report. It uses seven
adjacent, non-overlapping 14-day periods (98 days total) to show WPR
and a mean code-change tier with review coverage. Every person remains accessible through a
compact, paginated list, with the top five WPR totals first.

## Capabilities and Constraints

- Group related PRs before scoring; do not reward PR splitting.
- Never publish historical title-based points. AI tiers require validated,
  cited Qwen reviews, model provenance and explicit partial coverage.
- Keep all merged PRs inspectable, including work with no additional public link.
- Label release inclusion and closing-issue relationships without awarding
  extra points or claiming independently verified user benefit.
- Show WPR as the primary review-load proxy, not author effort or value.
- Include all observed human contributors in the paginated list, including
  external contributors. Exclude bot accounts from the index, and do not infer
  employment where public evidence does not establish it.
- Show source PR links, WPR breakdowns, data window and coverage limits.
- Public GitHub acquisition and publication to the existing repository and
  Pages site are approved. Push directly to main; do not introduce another PR.

## Evidence on Hand

The 98-day public GitHub snapshot is available, but user benefit and individual
impact are not independently verified.

## Product Principles

1. Make each WPR total traceable through direct PR links.
2. Do not equate activity proxies, documentation, or unverified claims with
   measured user impact.
3. Show repeated contributions without rewarding PR splitting.
4. Say what public GitHub cannot establish.
