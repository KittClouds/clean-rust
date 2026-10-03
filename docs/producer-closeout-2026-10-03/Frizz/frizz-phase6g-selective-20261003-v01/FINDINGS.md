# Phase 6G — selective classifier retired as constructed

The three-way target is scientifically cleaner, but this bounded frozen-state
classifier does **not** acquire a reliable epistemic legality boundary.

| Primary DEV endpoint | Result | Frozen survival requirement |
|---|---:|---:|
| False certainty among truly unresolved candidates | 45.94% (1,250/2,721) | ≤5% |
| Candidate certainty coverage | 78.29% | ≥70% |
| Exact three-way root partition | 1/333 (0.30%) | ≥5-point gain over fixed binary reference |

The paired rendering agrees qualitatively: 47.15% false certainty, 78.16%
coverage, 1/333 exact partitions. No threshold, epoch or architecture rescue.

## What was learned—and what was not

Macro F1 is 0.5159 and three-class BA is 0.6946. UNRESOLVED recall is 54.06%.
CERTAIN_LEGAL precision is only 19.81% (recall 79.45%); CERTAIN_ILLEGAL
precision is 91.59% (recall 74.86%). False abstention is 16.84% of truly certain
candidates. There is status signal, but both precise legal grounding and
uncertainty detection remain inadequate. This is not a Qwen capacity ceiling.

The fixed Phase6D binary gate achieves 82.64% accuracy on certain cases, yet
predicts certainty on every unresolved case and reconstructs no exact
three-way partitions. That baseline cannot represent the epistemic contract.
All frozen Phase6D/E arms are rescored, not just a chosen favorable baseline.
Canonical legality is diagnostic only; unresolved candidates never receive a
hidden canonical legal/illegal training label.

## Selection under uncertainty

Unresolved candidates are always retained. With the unchanged consequence
ranker, same-type selected top1 is 12.01% with learned selective filtering,
versus 13.81% without filtering and 61.26% with the strict observable oracle.
These are gold-action-type-conditioned diagnostics, not unrestricted results.
Full-set selected top1 stays 0.30% on all three paths. Exact logged-action and
optimal-set denominators remain separate in the recorder.

The authority diagnostic **authorizes 333/333 full-menu roots**, but both the
model and oracle paths choose **WAIT in all 333**. Authorized logged-action and
optimal-set accuracy are each only 1/333. WAIT is certainly legal and cheapest
under this frozen ranker, so the stipulated resolved-competitor rule passes
trivially. That is a degeneracy of the decision/authority contract, not evidence
that the system knows enough to pursue the goal. The result is retained as-is;
no goal condition or ranking intervention was added after scoring.

## Sealed scope

One 55,299-parameter MLP, fixed cs320 + e32 + type + four presence bits,
TRAIN-only root-balanced normalization/class weighting, seed0, ordinary CE,
AdamW, fixed epoch12. Fit time 22.19 seconds; endpoint CPU forward about
0.271 ms per rendered root. Qwen, E, goal heads and consequence ranker remain
unchanged. No new extraction, LoRA, data regeneration or protected evaluation.

Six unit controls, independent reconstruction of all 210,850 strict target
instances, and fresh-process replay of init/epoch12 logits, every binary
baseline, metrics, dispositions and explanatory diagnostics pass. Artifacts,
input/source identities and costs are hash-bound in the lane seal.
