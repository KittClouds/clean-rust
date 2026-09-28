# Jev Frozen Compatibility Readout v0.2

Status: exploratory, frozen-backbone research protocol. This document does not
authorize QLoRA, LoRA, SFT, PPO, RL, Phoenix integration, or production-data
mutation.

## Purpose

This slice separates the quality of a pretrained representation from the native
language-model readout. A causal backbone is used only in inference mode to
encode shared state/query text and runtime candidate definitions. A small
dynamic compatibility head is the only trainable component.

The scientific object is:

```text
frozen state representation + frozen candidate representation
                    -> learned compatibility surface
```

There is no fixed class inventory. Candidate IDs and definitions remain
episode-local and may change at evaluation time.

## Frozen backbones

The mandatory controls are pinned by immutable Hub revision:

| control | repository | revision | role |
|---|---|---|---|
| MiniCPM | `openbmb/MiniCPM5-1B-Base` | `156170697656c48f69915b33a2fb44110242187c` | broad small-LM reference |
| Qwen | `Qwen/Qwen3-0.6B-Base` | `da87bfb608c14b7cf20ba1ce41287e8de496c0cd` | tiny-capacity control |
| K2 | `IFM/K2-Horizon-0.9B` | `9fa6faa55fe1c9eb008bb241cc6fb7e4536d0e91` | same-scale distilled control |

K2 uses its published custom Transformers code path and drops
`token_type_ids` at the model boundary. This is adapter plumbing only; it does
not change canonical episode semantics. K2-Horizon-Uno is explicitly outside
this slice.

## Dataset and leakage boundary

Inputs are the validated synthetic sibling bank plus the existing external
pilot bridge. Synthetic train/dev/test partitioning keeps perturbation families
together. External rows are transfer-only in this first pass. The model-facing
state text excludes the candidate list, so candidate scoring can reuse one
state representation. Candidate profiles are encoded independently:

```text
name
name + definition
opaque ID + definition
opaque ID only
```

Opaque surfaces are derived from the semantic candidate ID when the source does
not provide one. This prevents candidate reorder tests from accidentally
changing the candidate's opaque identity.

Hard labels, empirical human distributions, and exact synthetic posteriors stay
typed by `probability_source`; they are never pooled into one probability
claim.

## Readout ablation

The first head family is deliberately small:

* dot product over independently projected state/candidate vectors;
* bilinear compatibility over projected vectors;
* MLP over `[state, candidate, state*candidate, abs(state-candidate)]`.

The default projection is 128 dimensions. The current MLP is under 0.5M
trainable parameters, far below the 5M ceiling. Heads consume a padded dynamic
candidate set and mask padding; they are not fixed classifiers.

Representations are cached from:

* last non-padding token;
* mean of the final 16 tokens;
* mean of the full state/query sequence.

The cache records model name, repository revision, hidden size, layer index,
location, and frozen status. Current first-pass extraction uses the final layer;
internal-layer probes remain an allowed follow-up.

## Training losses

`L0` is semantic loss only: soft cross-entropy for choice and soft binary
cross-entropy for independent applicability. `L1` adds a Brier term. `L2` adds
an invariance term on certified surface siblings. `L3` combines Brier and
invariance. Exact posterior targets remain distributions; hard labels are not
silently converted to probability-one targets.

Candidate reordering is aligned by semantic ID. The head's state encoding has
no candidate-list order, and candidate surfaces are semantic-stable, so any
residual order effect is a representation/readout defect rather than intended
conditioning.

## Intervention evaluation

The synthetic bank includes verified siblings for:

* surface/representation change, with strict target invariance;
* evidence intervention, with gold recomputation after hiding evidence;
* world intervention, with gold recomputation after a `do` change.

For each pair, report gold-to-model delta sign agreement, delta magnitude
correlation, rank correlation, and absolute delta error. For local interventions,
also report movement of affected queries and drift of unaffected queries. A model
that moves every query is not credited as causally sensitive.

## Native references and calibration

Every learned-head report must be paired with the existing native readouts on
the same protected bank: first-token candidate logits, sequence likelihood, and
proposition true/false where applicable. Synthetic exact posteriors are scored
with NLL, Brier, accuracy, and ECE. Human-disagreement transfer is reported
separately.

One scalar temperature may be fitted on the designated validation partition and
reported beside raw predictions. It is a diagnostic, not a backbone update.

## Cache equivalence track

Shared-prefix cache behavior is a separate systems result. FP32/BF16 hidden
state and logit differences, normalized distribution L1/JS, argmax flips, and
timings must be recorded before claiming a speedup. Numerical cache drift is not
a semantic failure unless it changes rankings or decisions materially.

## Primary matrix

The bounded first matrix is:

```text
backbone: MiniCPM, Qwen, K2
head: dot, bilinear, MLP
location: last_token, mean_suffix, mean_full
loss: L0 and L3 first; L1/L2 when the ablation budget permits
profile: name_definition primary; all profiles at evaluation
sizes: 1k, 5k, 10k groups when feasible
```

The first K2 pass is a cache extraction smoke test and one small MLP/L3 fit,
not a reason to expand the matrix before checking feasibility.

## Promotion gates

Stay with frozen backbones if reorder drift collapses, schema-OOD behavior
improves, calibration is competitive, and intervention movement tracks exact
gold. Consider QLoRA only when a stable head leaves reproducible semantic
failures such as schema binding, counterfactual movement, or world-OOD
generalization. Test a larger backbone first when native and learned readouts
fail on the same complexity-linked cases.

No composite score is used. The result is a behavioral map, not a leaderboard.

## Bounded pilot result

The executed matrix contains 18 head-only runs: 1k dot/bilinear controls,
1k alternate-pooling probes, 5k three-epoch MLP/L3 primary runs, and 10k
one-epoch scaling points. The protected test selection contains 1,512 eligible
choice/applicability groups per run; the external transfer bank contains 63
eligible groups. All three primary runs use 459,009 trainable parameters for
MiniCPM/K2 and 327,937 for Qwen, with `backbone_frozen: true`.

| frozen backbone | test NLL | test Brier | accuracy | ECE |
|---|---:|---:|---:|---:|
| MiniCPM5-1B, 5k/L3 | 0.981 | 0.081 | 0.602 | 0.077 |
| Qwen3-0.6B, 5k/L3 | 0.946 | 0.066 | 0.634 | 0.026 |
| K2-Horizon-0.9B, 5k/L3 | 0.936 | 0.063 | 0.644 | 0.025 |

The head path also retained 576 evidence-intervention and 576 world-intervention
parent/child comparisons across the run matrix. These are diagnostic, not a
claim that the frozen heads have learned causal inference: intervention
direction agreement varies by head and backbone and remains well below a
promotion gate. The native reference is deliberately bounded to 256 query
records per MiniCPM/Qwen model because the legacy sequence-likelihood evaluator
is substantially more expensive; its scope is recorded in
`frozen-readout-comparison.json`.

The current hard-sibling artifact is marked coverage-limited because the pilot
generator does not yet expose semantic-sibling similarity as a first-class
workload dimension. That is an identified next experiment, not an inferred
success.

## Reproducibility boundary

Source code belongs under `experiments/jev-frozen-readout-v01`. Model snapshots,
feature caches, head checkpoints, and JSON reports belong under
`D:\codex-runs\jev-frozen-readout-v01` and are not repository datasets. All
runs record seeds, revisions, trainable parameter counts, frozen status, and
the exact split/feature manifest used.
