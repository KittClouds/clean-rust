# Qwen BANK-v3-core bridge v1

Date: 2026-10-02. Mechanism-free bridge before E; SYNTHETIC_ONLY evidence.
Accepted Frizz bindings and corrected PHASE5-HANDOFF-v02 supersede the packaging hold.
Original bank seal/corpus and completed BANK-v1 Qwen trial remain unchanged.

## Substrate and interface

Frozen BF16 Qwen/Qwen3.5-0.8B-Base, revision
dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68; no chat or vision.
Six inherited surfaces: lt24, mf24, ms24 (last 16 tokens), mf18, mf12, mf6.
Observable first-name mentions supply final-depth entity vectors, as the previous
first-mention entity interface did. No latent facts, bookkeeping or target inputs.
No truncation: actual lengths 195–1415 TRAIN, 199–1338 DEV. Extraction batch two,
64-row sealed restartable chunks. All 30,000 row vectors retained; all paired
renderings stay together. Padding qualification uses actual TRAIN text.

The dense graft keeps six independent 1024->128 projections, global state 64,
candidate-local state 256, candidate-context state 32. Necessary ABI adaptations:
nine action types; four positional argument vectors rather than three (arguments
ordered by sorted observable argument key); exhaustive per-batch candidate width,
never a 28-candidate cap. No role factorization, goal-specific organ, recurrence,
stochastic transition, LoRA or IHA. Entity gathers use packed global offsets.
TRAIN alone fits surface normalization and prevalence. Never fall back unknown
action types to another type. Exclude padded slots from every loss and metric.

## Training specification

One bridge graft-training run, seed 0, eight epochs, paired roots shuffled, batch
32 canonical roots / 64 renderings; include final partial batch. AdamW 3e-4,
weight decay .01, cosine decay, gradient clip 1. Final epoch eight is the endpoint;
DEV is reporting only, no composite score or post-hoc checkpoint selection.
Compared with BANK-v1, bridge batch rows/dose and target ABI differ deliberately;
v1 numbers are historical phenotype, not a matched effect estimate.

Independent supervision sources have unit weight: candidate_legal,
candidate_satisfies_goal, goal_satisfied, available solvable, disposition, reason,
missing_cardinality, requestability, EXECUTE-only first_action_type. Missing binary
is reported from the count head, not another independent weighted source.
Conflict and aliases have zero training weight and no promotion claims.
Named selected-candidate endpoint weight .5, renderer prediction JS .25,
initial-TRAIN-state variance floor .05. Candidate binary losses use TRAIN-balanced
BCE; multiclass losses use CE. No invented targets for unavailable ontology cells.
All masks follow the v3 ABI. Renderer consistency uses TRAIN pairs only and
prediction distributions, not raw latent invariance or cross-lane alignment.

## Recorder and interpretation

Save full initialization and every epoch separately with hashes. Report init,
trained and delta, per-source heads, exact candidate and optimal-set endpoints,
separate type classification, positive/negative and root denominators, all axes,
renderer disagreement, unsatisfied-goal / legal-MOVE slices, cost/latency/params.
Linear and tiny-MLP readouts are fixed-dose frozen-representation analysis, with
known-solvable controls; no post-hoc arm selection. Their implementation and
source lock must be complete before interpreting recoverability.
Functional ablations are descriptive and must remain separate from trained runs.
No composite capability score. No E judgment from v1-v3 score differences.

DEV exact/optimal endpoints: 333 roots / 666 rows. Only MOVE has >=200 DEV roots
(249). All other action-type classes are underpowered; report support/descriptive
values only, never promote reliability claims. Root-clustered uncertainty, not
independent treatment of paired rows. Restricted targets retain required strata.
Evaluation truth is not authorized; no EVAL files are opened by this bridge.
E stays behind completion and verification of the bridge flight recorder.

## Engineering record

Preparation census initially passed a dict rather than its keys to Counter.update;
fixed before the create-only preflight receipt or any model contact.
The empty split map was a Windows separator packaging defect. Frizz's normalized
manifest-derived maps are accepted and match corrected handoff v0.2; no corpus
bytes or semantic labels changed. These are reported engineering fixes, not new
requests for approval.

Extraction preparation v01 qualified all 320 text parameters and padding on
actual TRAIN text, then stopped before writing a primitive chunk on a missing
`Path` import. Preserve that attempt; corrected preparation uses artifact v02.
No graft-training run was consumed by this preparation failure.
