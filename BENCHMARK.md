# Qwen PR-tier benchmark

This experiment classifies visible code changes as tier 1, 2, 3 or unassessed.
It does not measure customer outcomes, individual performance or merge safety.
The dashboard still shows WPR; this pipeline does not modify `data/report.json`.

## Current state

- The frozen manifest has 40 development cases, 60 reserved test cases and
  three historical human calibrations.
- Fresh cases exclude all PRs and identical patch hashes from the earlier
  pilot and teacher-labelled examples. Selection covers single-chunk, large,
  multi-PR and preflight-rejected changes across cached code areas.
- This is a diversity sample from the available cache, not a representative
  sample of all PostHog PRs. Two cases test evidence preflight rejection.
- The installed `qwen3.5:9b` completed the three historical calibrations.
  Its tiers were 1, 2, 2; the expert tiers were 1, 2, 3.
  These three public, previously inspected examples are not a blind accuracy
  benchmark. Their explanations have not received an independent semantic audit.
- No new benchmark gold labels or trained adapter exist yet. The reserved
  final test has not been run. Training remains blocked on human adjudication.

The baseline pins Ollama model digest
`d63f830f28d515fefea546f213fca7a75e9dd5176ef51a6deabc952d1c99a911`.
Run specifications also record Ollama version, adapter hash and inference
protocol. New runs pin the harness implementation hash too. The initial
`qwen-base-v1` diagnostic predates that extra provenance check; keep it for
inspection, not promotion. Use `qwen-base-v2` for subsequent batches.
A changed model or protocol needs a new run ID.

## Prepare and run

Use the new repository checkout on `main`. The manifest is tracked; local
diffs, blind packets, labels, predictions and audits are ignored by git.
The existing cache can be copied from the old workspace without changing it.
Do not fetch the whole snapshot again merely to run this benchmark.

On the original preparation machine, this command froze the cases:

```bash
python3 scripts/pr_benchmark.py prepare --count 100 --development 40
```

Do not rerun preparation over an existing manifest. On another machine,
restore the exact cached diffs and regenerate the blind packets:

```bash
python3 scripts/pr_benchmark.py export
```

Each packet is addressed by an opaque case ID. It contains the rubric and
complete reviewable diff chunks, not prior scores, authors, WPR, PR titles or
links from the selection metadata. Identifiers already present in source
code are not scrubbed. The manifest is an operator file, not a review prompt.
It must not be given to the human reviewer alongside the packets.
Give the reviewer `data/benchmark/packets/development.json` and the listed
case IDs' `.md` files for the first labelling batch. These readable packets
contain the same code as the machine JSON, without operator metadata.

Run a finite batch against an already installed local model:

```bash
python3 scripts/pr_benchmark.py run --run qwen-base-v2 \
  --split development --model qwen3.5:9b --limit 5 --max-chunks 8
python3 scripts/pr_benchmark.py evaluate --run qwen-base-v2 \
  --split development --output data/benchmark/reports/development-01.json
```

The runner never downloads a model or calls a paid teacher. Each inference
call has a 360-second timeout; the chunk limit is an explicit cost budget,
not a decision that an oversized change has no value. Deferred cases,
timeouts, invalid outputs and preflight failures remain separate from a
model's deliberate abstention. Successful predictions are never overwritten.
Failed runs stay available for inspection; use a new run ID for a corrected
adapter rather than erasing failures.

The runner resumes missing cases within the same immutable run specification.
`--limit` counts new attempted cases, not total completed cases.
The reserved test requires `--split test --unlock-test`. Leave it closed
while choosing prompts, checkpoints and training settings.

## Human adjudication

A PostHog-knowledgeable reviewer should inspect blind packets before seeing
model predictions. Have a second reviewer adjudicate disagreements, proposed
tier-3 labels and difficult abstentions. Real supporting context may be needed;
do not invent it from a title or force a tier when the patch is insufficient.

Record a human decision using a JSON file with `score` (1, 2, 3 or null),
`reviewer` and a specific `reason`:

```bash
python3 scripts/pr_benchmark.py label --case CASE_ID --answer /path/to/human-answer.json
```

A score-only answer supports evaluation. Training also requires a complete
`review` approved by that human. Its shape is:

```json
{
  "reviewer": "actual-reviewer-identifier",
  "score": 2,
  "reason": "Explain the observed bounded behavior change.",
  "review": {
    "score": 2,
    "reason": "Explain the observed bounded behavior change.",
    "posthog_relevance": "Explain the code-supported operational mechanism.",
    "confidence": "medium",
    "evidence": ["P1.F1.H1"],
    "uncertainty": "State missing context and unverified outcomes.",
    "metadata_dependency": false,
    "grouping_issue": false,
    "abstention_reason": null,
    "observations": [{
      "observations": [{
        "hunk": "P1.F1.H1",
        "behavior": "Describe what the added and removed code actually does.",
        "posthog_connection": "Explain the supported product connection.",
        "code_quote": "REPLACE WITH AN EXACT CHANGED LINE"
      }],
      "limitations": "State what this chunk cannot establish."
    }]
  }
}
```

That is a schema example, not a label to import unchanged. For multiple
chunks, approve one observation set per chunk in packet order. An unassessed
decision uses null score, confidence `none`, empty evidence and a specific
abstention reason; keep observations of the code that is actually available.
Unrelated grouped PRs require `grouping_issue: true` and abstention.
Missing/unparseable evidence is handled by preflight and is not training data.

The tool validates provenance and literal quotes. It cannot verify that a
human really inspected the code or that the explanation is correct.
No teacher-generated answer becomes human gold by changing its source field.

After gold decisions are saved, audit model explanations separately. Read the
addition/removal direction, callers, tests and claimed mechanism, not just
whether a quote exists. An audit JSON needs `reviewer`, a specific `reason`
and `verdict` (`correct`, `incorrect` or `unclear`):

```bash
python3 scripts/pr_benchmark.py audit --run qwen-base-v2 \
  --case CASE_ID --answer /path/to/evidence-audit.json
```

Audits bind to the exact prediction hash. An unaudited explanation gets no
invented semantic-correctness score.

## Training

```bash
python3 scripts/prepare_lora_data.py \
  --output data/ai_review/lora/data-v1
```

This currently exits with a training-blocked message: no fresh human-approved
development reviews exist. Default experiment minimums are 30 reviewed groups
and at least three examples each of tiers 1, 2, 3 and semantic abstention.
These are minimum checks for an experiment, not a sufficient sample size or
a promise of generalization. Check class coverage in both resulting splits.

Only adjudicated development cases enter `train` and `valid`. Historical
calibrations and reserved test PRs, patch hashes and change families cannot
enter either split. Related chunks stay in the same split. Large groups produce
chunk-observation examples plus one combined decision; their group tier is
never copied onto each chunk. Abstention is retained. The builder never
selects a quote on the human's behalf and does not export a test JSONL.
Exact-overlap checks do not detect every near-duplicate or related feature;
an expert must check split independence before training.

Before running MLX LoRA:

1. Obtain the matching Qwen 3.5 9B training weights and tokenizer, with an
   exact source revision. Verify their lineage against the Ollama baseline.
   An Ollama tag alone does not establish the Hugging Face source revision.
2. Record the base-weight, tokenizer, dataset and adapter hashes. Do not use
   the older Qwen2.5 3B model as a substitute for this 9B baseline.
3. Measure tokenized lengths using that tokenizer. Do not silently truncate
   code or approved answers to fit a sequence limit. Rechunk and reapprove
   overlength examples or explicitly exclude them.
4. Train on `train`, choose a checkpoint on `valid`, and compare its
   development errors against the untrained model. Keep final-test feedback
   out of checkpoint and prompt selection.

No matching training-weight download or training run has been started.
Ollama serves inference; it does not perform this fine-tuning step.

## Final comparison

After choosing one candidate, run the baseline and candidate against the
same reserved test cases with `--unlock-test`, then independently label and
audit the predictions. Give the candidate a new run ID and retain its base,
dataset and adapter provenance.

```bash
python3 scripts/pr_benchmark.py compare --run qwen-candidate-v1 \
  --baseline-run qwen-base-v2 --unlock-test \
  --output data/benchmark/reports/final-comparison.json
```

The provisional comparison gate requires complete paired runs, at least 50
labelled cases, independent semantic audits, improved macro-F1 and no
regression in exact accuracy, coverage or tier-3 precision. It also requires
at least 10 true tier-3 cases and 10 tier-3 predictions, at least 90% tier-3
precision and 95% semantic-evidence accuracy. If the test lacks enough
tier-3 cases, the experiment cannot establish that claim; do not relabel
cases to make it pass. Report uncertainty around these small-sample results.

Passing makes the candidate eligible for human approval, not automatically
promoted. There is no code path here that writes model tiers into the
contributor dashboard or turns them into outcome scores.
