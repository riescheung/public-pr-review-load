# Public PR review load

The [`PostHog/posthog`](https://github.com/PostHog/posthog) dashboard shows
weighted PR (WPR) as its primary metric across seven 14-day intervals.
WPR estimates review load from public file changes; it is **not** author effort,
engineering impact or verified customer benefit. The outcome field stays
**blank / not assessed**, not zero. Top-five insignia mark WPR order only.

## Snapshot

- UTC window: **2026-07-29 through 2026-11-03**, 98 complete days.
- **19,827** merged PRs collected across all 98 UTC days; 17,344 authored by
  GitHub `User` accounts, 2,479 by `Bot` accounts, and 4 without an author.
- **214** observed human accounts (PR authors or latest reviewers), including
  review-only contributors with no authored PR review-load total.
- **17,220** of 17,234 conservative change groups have substantive changed
  files. Only **1,447** have an extra release or closing-issue link; links do
  not determine WPR.
- **19,827** complete PR file lists were collected for estimated review load.
  The client bundle includes only the compact report, not raw PR bodies/diffs.

The public snapshot does not establish lasting benefit or individual
ownership. WPR totals grow with PR volume; a zero or missing public PR
does not mean zero impact. This index is not a personnel assessment.

## Method

1. Search merged PRs for every UTC day in the window, paging until each day's
   count matches its results. Collect title, PR text, GitHub actor type, linked
   closing issues, labels, and latest review per reviewer. Separately fetch
   repo releases and every PR's changed files.
2. Estimate each PR's 0–10 WPR from changed-file type, size and density;
   discount trivial/generated files and assign net reverts zero. Sum WPR
   for authored merged PRs by merge interval and contributor. The sum is
   review-load scope, not a contribution point or outcome score.
3. Show the PRs behind each total. Release and issue links do not add WPR
   and do not verify adoption or benefit. The old title-derived point
   fields remain in the frozen report for historical reproducibility but
   are **not displayed** or used to order contributors.
4. Keep the outcome field unassigned until an independently validated
   method exists. PR code reviews alone cannot prove customer outcomes.

Grouping and the old title-based point rubric are retained in the research
pipeline, not the visible index. This WPR ranking cannot capture private work,
reviews, mentorship or delayed effects.

### Code-review pilot (not in the dashboard)

`AI_RUBRIC.md` defines a diff-grounded base tier (1, 2 or 3) with an
abstention option. The 50-group pilot selection and first-pass AI review
are in `data/ai_pilot/selection.json` and `data/ai_pilot/reviews.json`.
Of 50 groups, 45 were scored and five abstained; the review found both
title-heuristic overestimates and underestimates. The selection is not
representative, large patches need chunked review and metadata-gaming
resistance has not yet been tested blind. **The dashboard uses WPR, not
the pilot tiers or historical title-derived point fields.**
The opening dashboard-status sentence in `AI_RUBRIC.md` describes the
historical point display. Its review-contract text is hash-frozen to
preserve the three existing calibration records; this README and the
dashboard describe the current WPR-only display.

Estimated WPR follows the supplied file-weighted review-cost rubric: adjusted
changes by language density, file type, and change type; generated/trivial
files excluded; config-only promotion; nonlinear file-count factor; 0–10
clamp; net reverts zero. Unlike the full V13 implementation, this snapshot does
**not** subtract direct child PR overlap from slush parents. WPR measures an
estimate of review load borne by reviewers, *not* the author's engineering
effort. A historical, unpublished point calculation capped WPR's
scope adjustment at one point; the visible index does not use it.

## Run and refresh

Use Node 22+, Python 3, an authenticated `gh` CLI, and npm:

```bash
npm ci
npm run dev
python3 -m unittest discover -s tests -v
```

To inspect the pilot with an authenticated GitHub CLI, run
`python3 scripts/ai_pilot.py --fetch`. This caches public diffs under
the ignored `data/ai_pilot/diffs/` directory; it does not invoke an AI
model or modify the report. The checked-in reviews were performed in
this conversation, and cached diff hashes are validated by the tests
when the diffs are available locally.

### PostHog-aware scoring harness (offline until configured)

The review orientation in `POSTHOG_REVIEW_CONTEXT.md` maps the paths in
this public snapshot to PostHog product and operational mechanisms. It
does not assign a tier to paths or claim official product priorities.
`scripts/score_harness.py` takes the frozen rubric plus that orientation,
verifies cached patch hashes and hunk completeness, and writes blinded
model packets that omit authors, titles, links, WPR and old scores:

```bash
python3 scripts/score_harness.py prepare --index 2
# data/ai_pilot/harness/packets/02.json
python3 scripts/score_harness.py prepare  # all 50 groups, without model calls
```

For actual AI review, supply an executable adapter that reads a JSON object
`{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."}]}`
from stdin and writes **one JSON object** to stdout. The harness calls it
once per complete diff chunk for code-backed observations, then once for
a group-level 1–3 decision or abstention. Each observation must cite a
hunk ID and quote a literal changed line; scored decisions must explain
their PostHog mechanism and flag ambiguous multi-PR grouping. For
example, after approving the chosen model/runtime and any network access:

```bash
python3 scripts/score_harness.py run --index 2 --reviewer-id reviewer-a \
  --model-id your-model-version \
  --model-command /path/to/your-review-adapter
# Repeat with --reviewer-id reviewer-b and an independent model review.
python3 scripts/review_queue.py queue
```

Runs are stored separately under ignored
`data/ai_pilot/harness/runs/<index>/<reviewer-id>.json` with instruction
and diff hashes, model label, observations and decision. Reusing a reviewer
ID for the same group fails rather than overwriting its prior decision.
The queue is refreshed after each reviewer run or human answer; rerun
`review_queue.py queue` to inspect it at any time. Flagged cases live in ignored
`data/ai_pilot/harness/review_queue.json`. It flags reviewer disagreement
(including an abstention), grouping issues, abstentions and *scope
tensions*: WPR >= 7 with a 1-point base tier, or WPR < 3 with a 3-point
base tier. The latter can be a perfectly valid small but critical fix;
WPR is never a correction factor or proof the AI is wrong.

After a human inspects the cited diff, record the decision. Omit
`--manual` for an automatically flagged case:

```bash
python3 scripts/review_queue.py answer --index 2 --score 1 --manual \
  --reviewer posthog-expert --reason "Narrow release-status change only"
```

Human answers are appended to tracked `data/ai_pilot/calibration.json`
with the PR diff hashes, rubric/context hash, AI votes and explanation.
The queue compares later AI reviews with that human tier and flags any
mismatch; a changed diff or rubric needs a fresh calibration. The three
expert judgments previously given in conversation are recorded as
manual calibrations (no machine-readable AI runs existed then).
These answers are a benchmark for rubric improvement and reviewer
evaluation, **not** automatic model training or live score overrides.
The caller's adapter is responsible for model access and isolation; this
script does not sandbox it or make network requests on its own. Invalid
JSON, uncited evidence, stale patches and incomplete group diffs fail
closed. A model's explanation of PostHog relevance is still a judgment,
not verified user impact; the model can still misunderstand a valid hunk
or claim independence it did not achieve. Review 3-point cases and
disagreements independently before promoting scores into `data/report.json`.

### Full-snapshot review (separate from the dashboard)

`build_review_catalog.py` creates a deterministic catalog of the 17,220
eligible groups from the existing 98-day snapshot, retaining WPR as a
separate review-load proxy. Fetching the public diffs is resumable and can
be batched; a full fetch makes over 17,000 public PR-diff requests. The
`--fetch-limit` option is a useful cost/availability check before `--all`.
The tracked catalog stores PR identifiers and diff hashes; cached diffs
and model runs are ignored by git.

```bash
python3 scripts/build_review_catalog.py
python3 scripts/build_review_catalog.py --fetch-limit 25
# Once ready for the full public-diff fetch:
python3 scripts/build_review_catalog.py --all
```

For the local Codex SDK adapter, install `cursor-sdk` in your own Python
environment and set `CURSOR_API_KEY` (never commit it). This adapter chooses
the local runtime, creates an isolated temporary working directory per
review, asks for JSON-only output and does not grant a sandbox: model
permissions and network access still need to be governed separately.
Specify a model available to your account with `WEAVE_REVIEW_MODEL` or
leave it at `auto`. Model runs may incur significant cost; no automatic
full run is started by the app.

```bash
python3 scripts/score_harness.py run --scope full --index 1 \
  --reviewer-id pass-a --model-id auto \
  --model-command python3 scripts/codex_review_adapter.py
python3 scripts/score_harness.py run --scope full --index 1 \
  --reviewer-id pass-b --model-id auto \
  --model-command python3 scripts/codex_review_adapter.py
python3 scripts/review_queue.py queue --scope full
python3 scripts/build_review_status.py
```

The second run is a fresh review, not a different model by default.
`data/review_status.json` preserves research progress and calibration
offline; the public index does not display its incomplete model counts.
Only a validated and adjudicated set of code-grounded tiers could be
shown as a *separate* classifier. A 1–3 tier estimates visible engineering
work, **not** a measured outcome score.

### Paused SWE-2 experiment and proposed local Qwen follow-up

The prototype can use SWE-2 through a **local, signed-in Devin CLI**, but
the full run was stopped for this presentation. No full-snapshot SWE-2
score is used in the index.
This is not the Codex SDK adapter above, a Devin Cloud session, or a
locally trained model. It requires `devin auth login` by the account owner,
then `devin models list` to confirm the exact SWE-2 ID available to that
account. The runner requires `--execute` and an explicit attempt limit;
it will not silently switch to a different model if SWE-2 is unavailable.
The adapter runs in a temporary workspace with a read-only permission
mode, checks that the CLI prints one JSON object, and passes that answer
through the diff citation validator. Each successful review is recorded
with its model ID and exact diff/rubric hashes, never overwritten on
resume. An unavailable, malformed or incomplete patch gets **no invented
model result**. Large groups still require one model call per chunk plus
a group-level decision, so all-group inference is substantial work.

```bash
devin auth status
devin models list
python3 scripts/run_full_swe_review.py --model-id swe-2
# After confirming that SWE-2 is available, try one complete group:
python3 scripts/run_full_swe_review.py --model-id swe-2 --index 2 --limit 1 --execute
# Resume every remaining group with a complete cached diff:
python3 scripts/run_full_swe_review.py --model-id swe-2 --limit 0 --execute
```

Substitute the **exact catalog ID** if it differs from `swe-2`. The
public diff fetch is paused; resume it only if a full run is warranted.
The runner does not fetch patches. Free SWE-2 CLI use is a plan offer,
not proof of unlimited batch throughput or availability indefinitely.
Check the current offer and account billing before a large run. Model
votes remain **off the contributor dashboard**. A future design would
use local Qwen reviews and human-adjudicated training labels.
Independent votes expose disagreement, but two Qwen models trained on
the same labels can share mistakes. The existing review queue flags
disagreements and large WPR/tier tensions
(group WPR >= 7 with tier 1 or WPR < 3 with tier 3). A human would inspect
each flag, choose the final tier or abstain and save the reason as
calibration; the flag never automatically overrides a model or publishes
an outcome. WPR stays a separate review-load proxy; outcome remains blank.

### Blind Qwen benchmark

`BENCHMARK.md` describes the current experiment. The frozen manifest reserves
60 fresh final-test cases, alongside 40 development cases and three separate
historical human calibrations. Earlier pilot/teacher PRs and identical patch
hashes are excluded from the fresh cases. The installed Qwen 3.5 9B baseline
matched two of the three historical decisions; that tiny public calibration
set does not establish general accuracy. Fresh expert labels and semantic
evidence audits are still required.
The full 40-case development baseline has also finished: 38 accepted reviews,
one evidence-preflight rejection and one invalid abstention response.
Those are operational counts, not accuracy; no fresh expert labels exist yet.

```bash
python3 scripts/pr_benchmark.py export
python3 scripts/pr_benchmark.py run --run qwen-base-v2 \
  --split development --model qwen3.5:9b --limit 5 --max-chunks 8
python3 scripts/pr_benchmark.py evaluate --run qwen-base-v2 --split development
```

`prepare_lora_data.py` now requires complete human-approved development
reviews, preserves semantic abstentions and supports chunked changes.
It exports only `train` and `valid`; reserved test/calibration cases cannot
enter training. The old automatically selected training quotes and weak
teacher labels are not used by default.
The human-supervised training path stays blocked until enough adjudications
exist. A separate, explicitly experimental path can distill the 20 historical
AI teacher proposals. It excludes every benchmark case and cannot qualify
for promotion. See `BENCHMARK.md` for local-weight import and training commands.
The evaluated step-10 adapter lowered weak-label validation loss but failed
citation checks on all three calibration packets. Full 40-step attempts hit
local Metal GPU errors. No candidate is promoted.
The installed Ollama MLX tensors and tokenizer can be repackaged without
downloads; their content hashes pin the exact inference base. The older 3B
model is not a substitute. New model downloads need separate approval.

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
