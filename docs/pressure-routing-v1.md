# Pressure Routing v1 and Corrected WD50K Envelope

Status: complete, independently replayed, validation-only, test partition locked.

Authoritative envelope:

`target/graph-research-models/pressure-routing-v1-envelope-final/b3-28ea0c09ad55f4f168345c5262663a25f406337ff628537f9c50e3ec4997c872.optimization-envelope.json`

Independent replay:

`target/graph-research-models/pressure-routing-v1-envelope-replay/b3-28ea0c09ad55f4f168345c5262663a25f406337ff628537f9c50e3ec4997c872.optimization-envelope.json`

Grouped learning-gate receipt:

`target/graph-research-models/pressure-routing-v1-learning-gates-final/b3-0ba3a7470770584127d5c0e21639440ab4fd873858cc32b891c7182cc3d2e759.learning-gates.json`

## Intervention

The optimizer has exactly two clipping groups in this order:

1. decoder bias;
2. every non-bias parameter.

There are no decoder-weight tensors in this encoder. Entity embeddings,
relation embeddings, direction matrices, relation projection, qualifier
projection, qualifier value rows, and qualifier role rows remain in one shared
non-bias group. Qualifier parameters receive no privileged learning rate or
clip threshold.

Both groups use maximum norm `1.0`, learning rate `0.02`, sum reduction,
loss scale `256`, clip-scaled-gradient semantics, deterministic batches of
65,536 examples, and no decay. The seed, primary-target negative schedule,
four arms, and checkpoints are unchanged from the frozen global-clipping
envelope.

The exhaustive partition is content-addressed as ordered tuples of parameter
block, global start offset, length, and clipping group:

- optimizer: `b3-78d607505dd380986501852fca5474fb44091fc4c753d05ca6ff8bb47f37f9e7`;
- partition: `b3-a6888711fa282bb1085f15bd278ff022d1cca4b541e68aaae6f3ef3daccf1bed`.

Every trainable scalar belongs to exactly one span. There is no default group.

## Correctness gates

Before WD50K opened, the runtime proved:

- grouped thresholds above observed norms produce the exact unclipped weights;
- the partitioned single-global group produces the exact legacy-global weights;
- changing only a sentinel bias norm leaves the non-bias coefficient and update
  direction unchanged;
- duplicate, omitted, reordered, and overlapping spans all fail validation;
- generic-pair, qualifier-value, and qualifier-role learning gates pass under
  grouped clipping;
- cold model restart reproduces every gate score.

## Fair-race result

| Epoch | CompGCN | Null | Value-only | Full StarE |
|---:|---:|---:|---:|---:|
| 0 | 0.001785504 | 0.001783264 | 0.001895877 | 0.001783264 |
| 1 | 0.001953132 | 0.001949033 | 0.002096403 | 0.001949024 |
| 2 | 0.002135952 | 0.002126550 | 0.002248843 | 0.002126800 |
| 4 | 0.002768052 | 0.002764011 | 0.002908432 | 0.002764591 |
| 8 | 0.002560267 | 0.002545902 | 0.002527584 | 0.002552195 |
| 16 | 0.002052721 | 0.002055572 | 0.002134493 | 0.002057682 |
| 32 | 0.003044394 | 0.003045062 | 0.002993483 | 0.003051623 |

Optimization is now functionally active:

| Full StarE measure | Global clipping | Grouped clipping |
|---|---:|---:|
| Epoch-32 train BCE | about 0.6931477 | 0.6785827 |
| Positive-negative margin | about 4.8e-10 | 0.3907281 |
| Qualifier-projection update/weight | 8.72e-9 | 5.98e-5 |
| Decoder-bias update/weight | 1.9251 | 0.00517 |

The qualifier-projection relative update increased by roughly 6,856 times.
The intended experiment is occurring, not merely changing parameter bits.

The measured non-bias recovery versus the legacy global coefficient is:

| Epoch | Recovery |
|---:|---:|
| 1 | 243.57x |
| 2 | 263.31x |
| 4 | 263.31x |
| 8 | 43.90x |
| 16 | 1.0005x |
| 32 | 1.0003x |

The recovery naturally returns near one after the encoder wakes and the
non-bias group develops enough gradient mass to clip itself. This is a healthy
change in which group controls its own step, not renewed bias strangulation.

At epoch 32, non-bias clipping activated on `79.8295%` of updates and bias
clipping on `99.4318%`. Every retained batch is exactly balanced. Full StarE's
epoch-32 batches contain 32,768 positive and 32,768 negative examples, except
the final balanced partial batch with 5,190 of each. Positive logits are
positive and negative logits are negative while the active relation-bias mean
remains modestly negative.

## Causal interpretation

At epoch 32:

- Null minus CompGCN: `+6.6882e-7` MRR;
- Full StarE minus Null: `+6.5604e-6` MRR;
- Value-only minus CompGCN: `-5.0911e-5` MRR.

Full StarE versus Null has 20,914 paired-query wins, 21,669 losses, and 5,243
ties. The positive mean MRR delta is therefore produced by the size of rank
rescues, not by winning more queries.

The qualifier-specific result remains negative:

| Arm | Qualified MRR | Unqualified MRR |
|---|---:|---:|
| CompGCN | 0.008280106 | 0.002225285 |
| Null | 0.008285360 | 0.002225236 |
| Value-only | 0.008281596 | 0.002166176 |
| Full StarE | 0.008284668 | 0.002232931 |

Full StarE now diverges from Null, but it does not improve the qualified slice.
Value-only's favorable checkpoint-zero geometry does not become a learned
advantage and is negative overall by epoch 32. Neither encoder is promoted.

This is a successful pressure-routing intervention and a clean architectural
non-promotion. The next justified question is narrow: whether explicit
qualifier-value and qualifier-role corruption can convert the now-healthy
optimizer pressure into qualifier-specific discrimination. It must remain a
separate objective identity. If that single corrected objective still produces
no qualified causal gain, this WD50K recipe stops.

## Reproducibility

Two independent full executions produced the same envelope identity. Their 84
files have identical filename sets and byte content:

- 29 JSON manifests/compositions/receipts;
- 55 immutable weight, rank, and causal-delta blobs;
- zero filename differences;
- zero SHA-256 content differences.

Every checkpoint also passed its own mmap reopen and exact full-validation
rescore before installation. The WD50K test partition was never opened.

## Execution ledger

Frozen on 2026-07-14 as the completed Pressure Routing v1 and Real-Batch
Gradient Pressure Audit research cut.

- authoritative envelope: `b3-28ea0c09ad55f4f168345c5262663a25f406337ff628537f9c50e3ec4997c872`;
- independent replay envelope: `b3-28ea0c09ad55f4f168345c5262663a25f406337ff628537f9c50e3ec4997c872`;
- grouped learning gates: `b3-0ba3a7470770584127d5c0e21639440ab4fd873858cc32b891c7182cc3d2e759`;
- optimizer identity: `b3-78d607505dd380986501852fca5474fb44091fc4c753d05ca6ff8bb47f37f9e7`;
- clipping partition: `b3-a6888711fa282bb1085f15bd278ff022d1cca4b541e68aaae6f3ef3daccf1bed`;
- example schedule: `b3-add353e84db1f6502378daa47d633fdf24f904348ed241d92083ff3d4bcf1c34`.

Freeze gates: Rust formatting, Clippy with warnings denied, seven focused
library tests, grouped learning gates, release artifact reopen, independent
84-file byte replay, and diff hygiene. Both envelopes are validation-only and
the WD50K test partition remains locked.
