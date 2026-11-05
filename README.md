# Engineering impact, with receipts

An evidence-constrained, single-page React report for the public
[`PostHog/posthog`](https://github.com/PostHog/posthog) repository. It shows the
five highest-ranked people first, then all observed human contributors in
five-person pages. Each row has seven adjacent 14-day intervals and links to
the underlying PRs, issues, and release notes.

## Snapshot

- UTC window: **2026-07-29 through 2026-11-03**, 98 complete days.
- **19,827** merged PRs collected across all 98 UTC days; 17,344 authored by
  GitHub `User` accounts, 2,479 by `Bot` accounts, and 4 without an author.
- **214** observed human accounts (PR authors or latest reviewers), including
  contributors whose review participation has no scored outcome.
- **1,513** of 17,234 conservative change groups meet the scoring evidence
  threshold. Most groups have only a merged PR and remain unscored.
- **19,827** complete PR file lists were collected for estimated review load.
  The client bundle includes only the compact report, not raw PR bodies/diffs.

This is a ranking of **publicly corroborated outcomes**, not a claim about
individual employee performance. Release notes in this repo are dominated by
Desktop; uneven publication systematically favors that area. Impact from
private repos, mentorship, incidents, reviews, and long-running work is
largely invisible. A zero means *no qualifying evidence here*, not no impact.

## Method

1. Search merged PRs for every UTC day in the window, paging until each day's
   count matches its results. Collect title, PR text, GitHub actor type, linked
   closing issues, labels, and latest review per reviewer. Separately fetch
   repo releases and every PR's changed files.
2. Group PRs closing the same issue, or with the same specific normalized
   title and author. Otherwise keep them separate. This deliberately avoids
   collapsing unrelated work in a product area; it can miss related stacked
   PRs without an explicit common reference.
3. Score only when a group has an independent linked issue or release note,
   or an explicit numerical improvement reported in the PR. The latter is a
   *claim*, not an independently verified result. A PR-only narrative does not
   automatically become impact.
4. Use a problem-oriented rubric: **1** documented maintenance/enabling work;
   **2** a bounded defect fix or capability with evidence; **3** a substantial
   user capability or quantitative performance claim; **4** a corroborated
   high-severity correctness/availability risk addressed; **5** reserved for
   independently measured major outcomes (none assigned automatically here).
   The deterministic classification is a screening estimate, not a human
   judgment of actual business impact. Inspect linked sources before making
   personnel decisions.
5. Multiply rubric points by evidence strength: `0.5` for a PR-reported metric,
   `0.75` for a linked issue or published release note. No item gets `1.0`
   without independently observed results. Split an issue cluster equally
   among its PR owners, marking this as a provisional ownership allocation.
   Reviews without a traceable change of outcome are not assigned fake credit.
   Sum **all** supported outcomes; there is no top-five-outcomes cap.
   The contributor drawer shows five highlights, while clicking an interval
   exposes its complete set of scored outcomes and each person's credited
   share. Individual credit can differ from the outcome's full value when
   multiple PR owners share it. Grid totals round to one decimal.
6. Attribute an outcome to the period in which the earliest linked release
   appeared, otherwise its last PR merge. Each outcome enters one interval.
   GitHub release inclusion confirms publication, not availability to every
   customer or usage. The dashboard does not claim verified results.
   Review load belongs to the PR's merge period instead: an interval may show
   merged PRs and WPR but zero supported outcomes. Each period's PR list
   reconciles the estimated WPR total independently of outcome points.

The "worth a closer look" symbol is **not** part of impact. It selects authors
with at least 10 merged PRs whose estimated review load on PRs 28+ days old is
in the upper quartile, while their public-evidence outcome score through that
cutoff is in the lower half of the same cohort. This is a prompt to investigate
missing evidence or a review-to-outcome mismatch, **not** a quality or employee
performance judgment. The panel shows the cohort cutoffs and examples of
high-WPR PRs without qualifying links; those examples do not prove that the
changes were unimportant or unshipped. The signal uses 121 eligible authors
in this snapshot, a 410-WPR upper-quartile threshold and a 1.75-point
lower-half threshold through 2026-10-06. Uneven release coverage, delayed
outcomes, heuristic WPR, and arbitrary cohort thresholds create false alarms.

Estimated WPR follows the supplied file-weighted review-cost rubric: adjusted
changes by language density, file type, and change type; generated/trivial
files excluded; config-only promotion; nonlinear file-count factor; 0–10
clamp; net reverts zero. Unlike the full V13 implementation, this snapshot does
**not** subtract direct child PR overlap from slush parents. WPR measures an
estimate of review load borne by reviewers, *not* the author's engineering
effort. It never changes the impact score.

## Run and refresh

Use Node 22+, Python 3, an authenticated `gh` CLI, and npm:

```bash
npm ci
npm run dev
python3 -m unittest discover -s tests -v
```

To rebuild the evidence snapshot, run these in order:

```bash
python3 scripts/fetch_github.py --end 2026-11-03
python3 scripts/fetch_releases.py
python3 scripts/fetch_files.py
python3 scripts/build_report.py
npm run build
```

Daily caches in `data/raw/` and `data/raw_files/` are excluded from the public
repo; use a new checkout or move existing caches aside before choosing a
different end date. The tracked `data/manifest.json` pins the snapshot date.

The public GitHub Pages build uses the tracked compact `data/report.json`.
The source is auditable, but the GitHub search index and release list can change
after the snapshot; a rerun may not reproduce every count byte-for-byte.
