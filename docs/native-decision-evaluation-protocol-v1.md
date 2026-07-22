# Native Decision Evaluation Protocol v1

Status: implemented tribunal contract for Frozen Graph Decision Trajectories v1.

## Purpose

This cut installs one evaluator boundary for Phoenix-native ranking,
classification/adjudication, and policy-shaped decision tasks. A model family may
change how it produces scores. It may not change metric arithmetic, filtering,
tie behavior, slices, reward semantics, or test access.

The evaluator consumes immutable trajectory tables plus content-addressed model
predictions. It produces a content-addressed report. Every prediction binds its
producer model identity; every report binds the frozen dataset, protocol,
partition, prediction set, and all slice results.

## Protocol identity

`NativeDecisionEvaluationProtocol` binds:

- frozen trajectory dataset identity;
- exactly one task family;
- exactly one temporal partition;
- calibration bin count;
- Recall@K and nDCG@K cutoffs;
- certified risk-coverage points;
- the fixed tie policy;
- the fixed five-axis slice policy;
- an explicit reward scalarization identity for policy tasks.

Policy reward scalarization is never implicit. Its eight fixed-point weights
map, in ontology order, to:

1. evidence support;
2. temporal consistency;
3. canonical identity preservation;
4. contradiction reduction;
5. minimal edit cost;
6. human acceptance;
7. future stability;
8. abstention correctness.

Pending policy rewards fail closed. They are not silently treated as zero.
Classification and ranking protocols reject a reward scalarization because they
do not need one.

## Prediction contract

Each `NativeDecisionPrediction` contains:

- decision identity;
- producer model identity;
- content-addressed prediction identity;
- one score and probability per frozen candidate;
- eligibility and relevance masks;
- the selected output ordinal, or `None` for classification abstention;
- confidence for selective risk evaluation;
- optional reference scores for paired ranks;
- authoritative candidate outcomes for policy evaluation.

The evaluator rejects shape drift, non-finite values, invalid probabilities,
ineligible selected predictions, missing relevant candidates, producer/model
identity drift, empty slice keys, and policy outcomes without authority.

The recorded selected action must be relevant. For policy tasks, its candidate
reward must exactly equal the frozen authoritative reward vector. This prevents
the scorer from substituting a model-produced outcome for recorded truth.

## Exact ranking semantics

Ranking uses the existing Phoenix filtered average-tie rule:

```text
rank = 1 + strictly_greater + 0.5 * tied_other_candidates
```

Hits@1/3/10 are fractional when the cutoff crosses a tie block. A filtered-out
correct action receives zero Hits and a rank one worse than the eligible
candidate count. Candidate coverage records how often the correct action
survived filtering.

The ranking report contains:

- filtered MRR;
- Hits@1, Hits@3, and Hits@10;
- Recall@K;
- nDCG@K;
- candidate coverage;
- paired mean rank delta;
- paired win, loss, and tie counts.

Recall and nDCG must turn a score tie into a concrete top-K boundary. That tie is
resolved by immutable candidate action identity, never array arrival order.
Paired rank deltas retain average-tie semantics and report positive values when
the submitted model improves upon its reference.

## Exact classification and adjudication semantics

The binary candidate surface uses the authoritative Phoenix AP, Brier, log-loss,
and expected-calibration-error implementation. The chosen action family supplies
the multiclass label for macro-F1. Macro-F1 averages only action classes present
as authoritative labels in the evaluated subset, which keeps small certified
slices interpretable without rewarding absent classes.

Risk-coverage orders decisions by descending confidence and then immutable
decision identity. This makes a coverage boundary through equal confidences
replay exactly. An abstention is incorrect for ordinary class accuracy; an
explicit ontology `abstain` candidate remains a normal legal predicted action.

The classification report contains:

- average precision;
- macro-F1;
- Brier score;
- log loss;
- expected calibration error;
- abstention count;
- risk at each certified coverage point.

## Exact policy semantics

Policy evaluation requires authoritative outcomes for every candidate. It does
not invent counterfactual rewards from model scores. Reward vectors are
scalarized only through the protocol's content-addressed fixed-point policy.

For a predicted action `p` and the recorded action `r`:

```text
relative_reward = scalar_reward(p) - scalar_reward(r)
regret_against_recorded = scalar_reward(r) - scalar_reward(p)
unnecessary_edit_cost = max(edit_cost(p) - edit_cost(r), 0)
```

The policy report also contains:

- hard-constraint violation count;
- unsupported-action rate;
- mean future graph stability.

An abstaining policy must select the explicit grammar-constrained abstain
candidate. A missing predicted ordinal fails closed because it has no candidate
outcome or authority.

## Mandatory slices

Every result includes all five dimensions:

```text
temporal
relation_frequency
entity_degree
evidence_count
action_family
```

The first four bucket keys come from a certified feature/slice derivation. The
action-family key is checked against the frozen selected action. The evaluator
recomputes the complete task-family metrics inside every slice; it does not
derive slice metrics by scaling overall aggregates.

## Immutable result installation

Evaluation and ladder reports are canonical JSON with BLAKE3 identities. The
filename contains the report identity. Installation uses create-new semantics
and durable file sync. Existing paths are not overwritten. Restart loading
recomputes the embedded identity and rejects corruption or filename drift before
returning a report.

## Baseline Ladder v1

The runner accepts exactly this order:

1. frequency and recency heuristics;
2. typed degree and structural overlap;
3. FTRL;
4. MLP-16;
5. frozen R-GCN with existing topology;
6. frozen R-GCN plus metadata only;
7. frozen R-GCN plus temporal history only;
8. frozen R-GCN plus evidence only;
9. frozen R-GCN plus revision structure only.

"Only" in rungs 6-9 means the named new family is the only addition to the
same frozen topology control. It does not remove topology.

Every submission binds a non-empty feature-manifest identity and the exact
enabled feature families:

| Rung | Certified families |
| --- | --- |
| Frequency/recency | label prevalence, temporal history |
| Typed degree/overlap | metadata, topology |
| FTRL | all six frozen families |
| MLP-16 | all six frozen families |
| R-GCN topology control | topology |
| R-GCN + metadata | topology, metadata |
| R-GCN + temporal | topology, temporal history |
| R-GCN + evidence | topology, evidence |
| R-GCN + revision | topology, revision structure |

The runner rejects reordering, omissions, duplicate model identities, model to
prediction identity drift, and feature-family drift. It invokes the same exact
evaluator for every rung.

Test access is locked inside the baseline ladder. The ladder is a
single-task validation tribunal. A separately frozen model-selection identity
must choose a model before a later locked-test cut can be opened.

No multi-task trainer may be introduced until this ladder has established the
single-task contribution of label prevalence, metadata, topology, temporal
history, evidence, and revision structure.

## Current launch state

The tribunal and ladder runner are installed; no empirical Phoenix-native
baseline scores are claimed by this cut. The Phase 0 authority audit found zero
usable authoritative native decisions and left Canonical Episode Assignment
locked. Fabricating or hindsight-reconstructing examples merely to exercise the
ladder would violate the leakage contract. The synthetic fixtures prove metric,
identity, slicing, durability, and ordering behavior only.

The empirical ladder opens after immutable native decision receipts accumulate,
the selected single-task dataset passes Frozen Graph Decision Trajectories v1,
and the correct-action coverage and leakage certificates remain exact.

## Acceptance gates

The cut is complete only when:

- all three task families execute through one evaluator boundary;
- selected-action relevance and policy reward authority fail closed;
- average ties and fractional Hits are preserved;
- Recall/nDCG and risk-coverage ties replay deterministically;
- all five slice dimensions are present;
- reports survive cold open without recomputation;
- corrupted reports fail before use;
- the nine baseline rungs cannot be reordered or relabeled;
- the ladder cannot access the test split;
- the full graph-research suite remains green.
