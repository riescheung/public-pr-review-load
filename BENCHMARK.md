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
- All 40 development cases have been processed: 38 accepted model reviews,
  one oversized-hunk preflight rejection and one invalid abstention response.
  There are no fresh expert labels or independent semantic audits, so tier
  accuracy remains unmeasured. `data/benchmark/development_baseline.json`
  records the operational results and prompt-token budget check.
- A same-base experimental LoRA run now completes all 40 planned updates
  using the full 20 historical AI proposals. A process-scoped Metal watchdog
  workaround resolved the earlier crashes. This is still separate from
  human-supervised training; no adapter is promoted.
- The reserved final test has not been run. Frontier-reference distillation
  can now proceed without waiting for expert labels. The separate human-gold
  path still requires real human adjudications.

## Frontier references and queue feedback

The working reference judge is GPT-6.1 Sol High, exact CLI ID
`gpt-6-1-sol-high`. Its answers are accepted as estimates for development and
distillation. They are not relabelled as human gold. Agreement with this judge
is useful for model selection, but it is not an objective accuracy estimate.
Queue users can approve or correct complete cited reviews. Their corrections
take precedence over the original frontier answer in later dataset versions.
The first development batch finished with 35 valid Sol references, four
contract failures and one evidence-preflight rejection. The unchanged Ollama
Qwen baseline agrees with 22 of the 35 references (62.9%, counting its invalid
response as a failure). This is development agreement with Sol, not a final
test result or expert accuracy. The queue contains all 35 valid references.
`data/benchmark/reference_learning_v1.json` records the batch and dataset.

The first reference dataset contains 24 training groups (86 rows) and seven
validation groups (24 rows). Four other groups are excluded whole because at
least one row exceeds the sequence or completion budget. No code or answer
is truncated. A new 40-step adapter attempt uses that frozen dataset; no
completion or improved agreement is claimed until its result and paired
inference checks exist.

The 60 final-test cases are reserved PR diffs, not existing teacher answers.
Neither those cases nor the historical calibrations enter the new queue or
training data. Development has a stable family-hash train/validation split:
adding feedback does not move an existing case between those splits.
Validation cases remain out of gradient updates even when corrected.

Run a finite frontier batch using the locally signed-in CLI:

```bash
python3 scripts/frontier_reference.py run --reference sol61-dev-v1 \
  --model gpt-6-1-sol-high --limit 40 --max-chunks 8 --execute
python3 scripts/frontier_reference.py evaluate --reference sol61-dev-v1 \
  --run qwen-base-v2 --output data/benchmark/reports/sol61-baseline-v1.json
```

The reference judge sees the rubric and code, not Qwen's answers, WPR,
authors or earlier labels. Every chunk receives a checked observation pass;
multi-chunk cases also receive a combined decision. The runner records the
exact model, CLI version and adapter/contract hashes. Invalid responses,
timeouts, explicit chunk deferrals and evidence-preflight rejections stay
separate from deliberate abstentions. Existing attempts are not overwritten.
These calls use the account's model allowance or billing; `--execute` and a
finite case limit are required.

Export a queue snapshot after the reference batch:

```bash
python3 scripts/reference_learning.py queue --reference sol61-dev-v1 \
  --run qwen-base-v2 --output data/benchmark/packets/queue-sol61-dev-v1.json
```

The published `data/reference_queue.json` is a copy of a versioned snapshot.
It is loaded only when a visitor opens the review queue. Each case shows the
frontier estimate, Qwen's decision, explanations and the full frozen diffs.
No held-out case is published in that asset.

In the queue, identify yourself, explain your correction, approve the review
and check its cited code. Save locally, then use **Export feedback**. The
static Pages site stores corrections in that browser; it does not send them
to a server or retrain weights. Browser storage is not a backup. The exported
file must be imported into the local project:

```bash
python3 scripts/reference_learning.py import --reference sol61-dev-v1 \
  --queue data/benchmark/packets/queue-sol61-dev-v1.json \
  --answers /path/to/qwen-feedback.json
python3 scripts/reference_learning.py dataset --reference sol61-dev-v1 \
  --base-model data/ai_review/model/qwen3.5-9b-ollama \
  --output data/ai_review/lora/reference-v1 --max-tokens 8192
python3 scripts/train_experimental_qwen.py \
  --base-model data/ai_review/model/qwen3.5-9b-ollama \
  --dataset data/ai_review/lora/reference-v1 \
  --output data/ai_review/lora/adapter-reference-v1 \
  --iters 40 --max-seq-length 8192 --num-layers 1 \
  --execute --experimental-ai-labels
```

Each import validates the original queue, case, diff, reference and parent
correction hashes. Reserved cases, stale corrections, duplicate cases,
invented quotes and incomplete reviews are rejected. Feedback events are
append-only and remain `user_feedback`, not verified human adjudications.
Re-export the queue after an import so the next correction points to its
current parent. Preserve older snapshots for outstanding browser exports.

Dataset export prefers the latest accepted correction, retains chunked
reviews and semantic abstentions, and excludes an entire group if any row
exceeds the sequence or completion budget. It never truncates code or
answers. New dataset and adapter versions preserve the prior experiment.
Compare a candidate with the unchanged base under the same inference
protocol before changing any default. The current human-gold promotion tool
is unchanged: AI-reference agreement does not silently satisfy its gates.

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
The local `data/benchmark/packets/development-review-v1.zip` bundles those
40 development documents, instructions and blank answer templates. It contains
no test cases, operator manifest, model predictions or existing labels.
Templates are deliberately invalid until a human fills them in; no quote,
hunk or tier is selected on the reviewer's behalf. The archive stays local
and ignored by git; its hash is recorded in `runtime_recovery.json`.

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

Ollama serves inference; it does not perform this fine-tuning step.

### Isolated AI-distillation experiment

This path tests local training mechanics without pretending that AI proposals
are expert labels. It uses the 20 historical teacher proposals already in the
repository, never development, calibration or final-test cases. The full
stratified split has 17 training groups and three validation groups, all under
8,192 tokens. Long-sequence training repeatedly hit the local Metal GPU
interactivity limit. The bounded retry explicitly excludes four proposals
over 3,072 tokens, leaving 13 training groups and three validation groups.
It has no tier-3 examples or semantic abstentions. This is a training-mechanics
probe, not a reliable judge.
The optional Python 3.12 packages are pinned in `requirements-mlx.txt`.
The initial training attempts reused installed packages and weights. The
later constrained-decoding work adds `outlines-core` and JSON schema test
dependencies in an isolated local directory; it downloads no model weights.

`import_ollama_mlx.py` verifies the installed model manifest and tensor hashes,
copies packed text-tensor bytes unchanged, and renames their scale keys for
MLX-LM. Vision and speculative multi-token-prediction tensors are not used.
It preserves the tokenizer and records conversion hashes. The installed
MLX-LM version does not apply Ollama's NVFP4 tensor-global scales itself;
`mlx_qwen_loader.py` retains those scales in a tested quantized linear layer.
The base and adapter use the same loader and non-thinking chat formatter.

```bash
python3 scripts/import_ollama_mlx.py \
  --digest d63f830f28d515fefea546f213fca7a75e9dd5176ef51a6deabc952d1c99a911 \
  --output data/ai_review/model/qwen3.5-9b-ollama

# Use an existing Python environment containing mlx, mlx-lm and transformers.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python \
  scripts/experimental_distillation.py --experimental-ai-labels \
  --base-model data/ai_review/model/qwen3.5-9b-ollama \
  --output data/ai_review/lora/experimental-v2 --max-tokens 3072

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python \
  scripts/train_experimental_qwen.py --execute --experimental-ai-labels \
  --base-model data/ai_review/model/qwen3.5-9b-ollama \
  --dataset data/ai_review/lora/experimental-v2 \
  --output data/ai_review/lora/adapter-experimental-v4 \
  --iters 40 --num-layers 1 --max-seq-length 3072
```

Output locations are immutable: choose another version after a failed attempt.
The trainer checks weight and dataset hashes, masks the exact inference prefix,
rejects overlength answers rather than truncating them, and records both
initial and final weak-label validation loss. Lower loss means better teacher
imitation, not more accurate expert judgement.

Use `pr_benchmark.py run --mlx-model LOCAL_BASE` for the MLX baseline and add
`--mlx-adapter LOCAL_ADAPTER` for its candidate. Give each a separate run ID.
The adapter must have a completed matching-base result and unchanged weights.
The comparison gate rejects this weak-label experiment even if its measured
metrics improve. Gold-label and final-test protections remain in place.
Three attempts hit Metal GPU interactivity errors on long-sequence training.
The current runner limits LoRA to the final attention block, keeps the frozen
recurrent prefix in inference mode, and disables the monolithic compiled step.
It also avoids computing a 248,320-way vocabulary projection for every masked
prompt token. `mlx_training_loss.py` projects only completion positions; tests
check loss and gradient equivalence against full projection. Complete prompts
still reach the transformer. Targets over 512 tokens are rejected, not clipped.
Failed outputs are preserved.

The bounded attempt saved step 10, then stopped after progress reached 18/40
with the same Metal error. Its planned 40 steps did not finish. The saved
checkpoint is evaluated separately and marked `training_completed: false`:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python \
  scripts/evaluate_experimental_checkpoint.py \
  --base-model data/ai_review/model/qwen3.5-9b-ollama \
  --dataset data/ai_review/lora/experimental-v2 \
  --source data/ai_review/lora/adapter-experimental-v4 \
  --checkpoint 0000010_adapters.safetensors \
  --interruption "Metal GPU interactivity error after progress reached 18/40; saved step 10 only" \
  --output data/ai_review/lora/adapter-experimental-v4-checkpoint10
```

On its three weak-label validation examples, the independently remeasured
base loss was 1.22872 and checkpoint loss was 0.55363. This confirms that local
training changed the model toward those teacher answers. It does not measure
PR-judgement accuracy, tier-3 performance or abstention quality.

Ollama and standalone MLX differ in inference implementation and JSON
constraints even with the same packed weights. Compare the adapter against
the standalone MLX base, not directly against the Ollama result.
The first raw-MLX diagnostic produced invalid citations or decision fields
on all three calibration packets, for both models. Those failed runs remain
as `mlx-base-v1` and `mlx-distilled-v1`. The subsequent `v2` protocol allows
three fixed contract-feedback attempts for both models. Feedback names only
format or citation violations, never a target tier or expert answer.
Replies that still fail validation remain errors, not accepted scores.
The matched `v2` calibration finished with zero accepted reviews and three
contract errors for each model. The candidate produced nonliteral quotes
on two packets and unobserved hunk IDs on the third. Lower imitation loss did
not make it a usable code-grounded reviewer. Do not promote it.
`data/benchmark/distillation_probe.json` records the checkpoint, hashes,
losses and failed comparison without publishing local model weights.
The installed Ollama version also rejects direct adapter import with
`LoRA adapters are no longer supported`. The native `ADAPTER` route is
therefore unavailable here. This experiment does not claim an Ollama-ready
fine-tuned model; serving one would need a separately validated fused export
or another inference runtime with the same strict citation contract.
The next attempt on all 20 proposals used MLX's native
`MLX_MAX_OPS_PER_BUFFER=1` and `MLX_MAX_MB_PER_BUFFER=16` limits. It hit the
same Metal error before completing its first update and saved no checkpoint.
That attempt did not complete. Failed attempts retain a `failure.json` with
the error and hashes of any saved checkpoints.

### Metal watchdog recovery

The exact interactivity error is documented in
[MLX issue 3267](https://github.com/ml-explore/mlx/issues/3267).
A maintainer recommended `AGX_RELAX_CDM_CTXSTORE_TIMEOUT=1`, and the reporter
confirmed that it resolved the crash. Unlike command-buffer size limits,
this changes the Metal driver's context-store timeout for the process.
Use it only for the bounded command, not as a global shell or OS setting.
It can reduce desktop responsiveness while the GPU is busy.

The local `adapter-experimental-v6` run used that variable and completed
40/40 updates on all 17 training and three validation proposals, with an
8,192-token limit, no exclusions and no truncation. Initial weak-label
validation loss was 1.24557; final step-40 loss was 0.53401. Peak MLX memory
was 10,507,850,276 bytes. Earlier failed runs remain unchanged.
The full training split has eight tier-1 proposals, eight tier-2 proposals
and one tier-3 proposal. Validation has two tier-1 and one tier-2 proposals,
with no tier-3 or semantic abstention examples. This is not sufficient class
coverage for the human-supervised path.
The diagnostic uses the planned final checkpoint, not a checkpoint selected
against calibration or final-test answers.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 AGX_RELAX_CDM_CTXSTORE_TIMEOUT=1 python \
  scripts/train_experimental_qwen.py --execute --experimental-ai-labels \
  --base-model data/ai_review/model/qwen3.5-9b-ollama \
  --dataset data/ai_review/lora/experimental-v1 \
  --output data/ai_review/lora/adapter-experimental-v6 \
  --iters 40 --num-layers 1 --max-seq-length 8192
```

Those paths identify the recorded run. Do not overwrite them on a rerun.
The full dataset can be exported with `experimental_distillation.py
--experimental-ai-labels --max-tokens 8192` using the same base and a fresh
output directory. The trainer records the watchdog variable alongside its
weight, dataset and implementation hashes.

### Constrained local inference

The current MLX adapter uses `outlines-core` to mask invalid next tokens.
The schema permits all three tiers and abstention. Observation quotes are
chosen by the model from literal changed lines paired with their hunk ID.
It does not assign supporting quotes on the model's behalf or turn an
inference error into an abstention.

The decoder reads the existing local ByteLevel vocabulary, preserving raw
UTF-8 bytes and suppressing special tokens except the terminating EOS.
The schema and decoder implementation, dependency versions and Metal
environment are part of the run identity. Base and candidate use the same
decoder, greedy sampling and three-attempt contract-feedback budget.
Use new run IDs; these are not comparable to the earlier unconstrained
MLX runs as a controlled pair.

The existing validator still rejects decisions that cite unobserved hunks.
In a combined response, the grammar restricts evidence IDs to supplied hunks;
the validator separately checks that the model actually observed each one.
A literal quote can still support a wrong explanation. Neither the grammar
nor a successful validation replaces an independent semantic evidence audit.
Human gold labels and the untouched final test remain required for promotion.

The completed `mlx-base-v4` and `mlx-distilled-v4` diagnostic runs each accepted
all three calibration reviews without errors. Both predicted tiers 2, 2, 2,
while the historical expert tiers are 1, 2, 3. The adapter does not improve
those tier decisions. These known cases do not establish fresh accuracy,
and the explanations still have no independent semantic audits.
`data/benchmark/runtime_recovery.json` records the full training run, matched
protocol and prediction hashes, reviewer bundle and unchanged promotion block.
The initial `v3` decoder integration failed on MLX's one-token lookahead after
EOS; those artifacts remain available. `v4` fixes that handling and adds a
regression test that still rejects premature EOS.

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
Both reports must pin the same base weights, inference runtime, contract
protocol and implementation. An Ollama run and a standalone MLX run are not
a controlled baseline/candidate pair, even if their source tensors match.

Passing makes the candidate eligible for human approval, not automatically
promoted. There is no code path here that writes model tiers into the
contributor dashboard or turns them into outcome scores.
