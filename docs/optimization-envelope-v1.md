# WD50K Optimization Envelope v1

Status: complete, validation-only, test partition locked.

Authoritative artifact:

`target/graph-research-models/optimization-envelope-v1-final/b3-2f6e8fd8017df1734c9d7b4754861a2f6967d3b1c08f7d93f03913c15391b0f2.optimization-envelope.json`

Independent replay:

`target/graph-research-models/optimization-envelope-v1-replay/b3-2f6e8fd8017df1734c9d7b4754861a2f6967d3b1c08f7d93f03913c15391b0f2.optimization-envelope.json`

## Frozen intervention

- Arms: CompGCN, QualifierGradientNull, Value-only, Full StarE.
- Checkpoints: 0, 1, 2, 4, 8, 16, 32 cumulative epochs.
- Seed: `0x51a7e001`.
- Optimizer: deterministic batch SGD.
- Batch size: 65,536 examples, 11 ordered updates per epoch.
- Reduction: sum.
- Learning rate: 0.02.
- Global loss scale: 256.
- Loss-scale semantics: clip the scaled gradient.
- Global-norm clip: 1.0.
- Weight decay: none.
- Sampling: natural qualified/unqualified distribution.
- Training negatives: one primary entity corruption per positive from the frozen schedule.

The null arm is not independently trained. It composes the exact CompGCN checkpoint backbone with the checkpoint-zero qualifier parameters under the role-scoped routing policy. Primary reads come from the trained backbone; qualifier value, role, and projection reads come from checkpoint zero.

## Evidence retained at every checkpoint

- training BCE, positive/negative score means, margin, and ordering fraction;
- validation MRR and Hits@1/3/5/10;
- qualified, unqualified, qualifier-count, primary-relation, and provenance slices;
- train-only relation-frequency and target-entity-degree buckets;
- per-block changed parameter counts, gradient norms, and update-to-weight ratios;
- pre-clip norm, clip coefficient, and cumulative activation rate;
- exact score digest and immutable model/composition identities;
- exact doubled filtered ranks in canonical query order;
- exact per-query causal rank deltas;
- mmap reopen and full rescoring parity.

The test evaluator is not called by the envelope runner. `testPartitionAccessed` is false in the sealed manifest.

## Main result

| Epoch | CompGCN MRR | Null MRR | Value-only MRR | Full StarE MRR |
|---:|---:|---:|---:|---:|
| 0 | 0.001785504 | 0.001783264 | 0.001895877 | 0.001783264 |
| 1 | 0.001843581 | 0.001827910 | 0.001918600 | 0.001827639 |
| 2 | 0.001843618 | 0.001827957 | 0.001918613 | 0.001827668 |
| 4 | 0.001843685 | 0.001827986 | 0.001918620 | 0.001827965 |
| 8 | 0.001843950 | 0.001828226 | 0.001919597 | 0.001828212 |
| 16 | 0.001844156 | 0.001829438 | 0.001919577 | 0.001829437 |
| 32 | 0.001845810 | 0.001831803 | 0.001919964 | 0.001831747 |

Checkpoint-zero Value-only is already `+0.000110373` MRR over CompGCN. At epoch 32 the advantage is `+0.000074154`; it remains positive but narrows. This is a useful initialized value-conditioned geometry, not a widening learned advantage.

At epoch 32:

- Null minus CompGCN: `-0.0000140071` MRR.
- Full StarE minus Null: `-0.0000000554` MRR.
- Value-only minus CompGCN: `+0.0000741538` MRR.
- Full and Null qualified MRR: `0.001686240` and `0.001686205`.
- Value-only qualified MRR: `0.002060882`.
- All trained arms remain near `ln(2)` BCE.
- Positive-negative margins remain approximately `4.6e-10` to `4.8e-10`.
- Global clipping activates on `99.4318%` of the 352 updates.

The epoch-32 final-batch block economics locate an additional pressure point:

- Full StarE decoder-bias gradient L2: `263.3069`.
- Full StarE qualifier-projection gradient L2: `8.4077e-5`.
- Full StarE decoder update/weight: `1.9251`.
- Full StarE qualifier-projection update/weight: `8.7194e-9`.
- Value-only qualifier-projection gradient L2: `0.0023646`.

The global clip direction is therefore dominated by decoder bias while the Full StarE qualifier projection receives an update about eight orders of magnitude smaller relative to its weights. `255/256` qualifier-projection scalars change bits, but those changes do not materially change the learned ranking function.

## Interpretation

The experiment does not satisfy the promotion condition “Value-only wins and keeps widening.” Value-only wins, but most of the gain exists before training and the gap narrows.

Full StarE and QualifierGradientNull remain functionally coincident across the real WD50K batches. Their epoch-32 MRR difference is about `5.54e-8`, while the loss and margins show no useful positive/negative separation. The micrograph gates proved that qualifier roles and values are learnable in isolation; the frozen WD50K objective does not deliver a material qualifier-conditioned learning signal.

The next research cut is therefore gradient and objective pressure, not a new encoder:

1. Preserve this envelope as the negative reference specimen.
2. Add a real-batch gradient-pressure receipt that separates per-example accumulation, cancellation, pre/post-clip block norms, and decoder-bias share across every step.
3. Add a certified negative-generation audit measuring primary, qualifier-value, and qualifier-role discrimination pressure.
4. If raw qualifier signal exists but clipping erases it, test an explicit blockwise or decoder-isolated clipping identity. If raw signal is absent, introduce qualifier-value and qualifier-role corruptions as a new task-recipe identity.
5. Repeat the narrow four-arm envelope only after the objective and optimizer can move real-batch margins away from zero.

Role-gate architecture work remains deferred. Roles cannot be judged fairly while the real-data learner is still functionally null.

## Reproducibility

Two complete executions into independent roots produced identical sets of:

- 21 immutable model manifests;
- 21 weight blobs;
- 7 role-scoped null compositions;
- 27 exact-rank blobs;
- 7 causal rank-delta blobs.

The filename identity sets have zero differences. Every checkpoint also passed its own mmap reopen and exact full-rescore comparison before installation in the envelope.
