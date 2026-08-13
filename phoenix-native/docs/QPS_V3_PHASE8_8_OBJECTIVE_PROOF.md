# QPS V3 Phase 8.8 Objective Proof

Date: 2026-08-13

Status: diagnostic complete; no promotion; **V2 active**.

## Decision

Phase 8.8 does not justify further objective-only tuning of the canonical
30-feature global monotonic linear model.

The development feasibility audit proves that most current errors are not
trivially outside the nonnegative linear cone. Query-normalized static top-rank
weighting and genuine current-order LambdaRank training nevertheless fail to
transfer to the frozen independent graded suite or repair worst-query-shape
MRR. The next experiment must test group-distribution evidence rather than add
another loss or unconstrained hyperparameter search.

The frozen V2 retrieval substrate, constitutional tiers, candidate cap, stable
tie-breaking, canonical `RankEvidenceV3` schema, and append-only ledger remain
unchanged.

## Evaluation-contract repair

Phase 8 now uses quality contract
`phoenix.memory.qps-v3-quality-qualification/v2`:

- MRR is capped at rank 10.
- Graded IDCG@10 is built from the full judged candidate pool, not from the
  returned top ten.
- The obsolete absolute stretch MRR gate is replaced by a preregistered 20%
  normalized gap-closure gate:

  `G = (MRR_V3 - MRR_V2) / (MRR_oracle - MRR_V2)`

The corrected canonical receipt is:

`C:\benchmarks\phoenix-qps-v3-20260804\review-checkpoints\865b45f8e732-6295b016f13f\phase8-quality-v2-metric-repair.json`

SHA-256:
`384c13fa08d8311bb8976052f0fb2ebd048ef003204973aa115c11a3ac87ac24`

## Corrected canonical baseline

| Metric | Canonical | Gate | Gap |
|---|---:|---:|---:|
| LongMemEval hit@10 | 0.984000 | >= 0.984 | pass |
| LongMemEval MRR@10 | 0.897808 | >= 0.910 | -0.012192 |
| Independent graded NDCG@10 delta | -0.007341 | >= +0.020 | -0.027341 |
| Independent normalized MRR gap closure | -0.052439 | >= +0.200 | -0.252439 |
| Blind pairwise accuracy | 0.785377 | >= 0.800 | -0.014623 |
| Held-out top-1 improvement | +4.184 points | >= +2.000 | pass |
| Worst-query-shape MRR regression | 0.016345 | <= 0.005 | +0.011345 excess |

Nine of fifteen corrected quality gates pass. The six failures are LongMemEval
MRR@10, independent gap closure, independent NDCG@10 delta, blind pairwise
accuracy, per-class pairwise accuracy, and worst-query-shape regression.

The four sub-0.75 blind classes are:

| Failure class | Judgments | Canonical accuracy |
|---|---:|---:|
| Partial-match saturation | 40 | 0.350000 |
| Phrase/order failure | 152 | 0.684211 |
| Common-term dominance | 66 | 0.742424 |
| Length-prior failure | 17 | 0.411765 |

## Monotone-feasibility and collision audit

Receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_8-objective-proof-v1\phase8_8-monotone-feasibility-v1.json`

SHA-256:
`1b3bb06d6f15bdafb398adc9932b77ffca6f10a11c1b1281ce4599c1334422a2`

This audit reads development judgments only. It does not inspect blind labels.

- 843 development judgments.
- 194 errors under the canonical Phase 7 model.
- 166 errors, or 85.57%, have at least one positive feature delta and are
  therefore potentially expressible inside the nonnegative cone.
- 28 errors, or 14.43%, are monotonic-score impossible with the current
  evidence orientation.
- Zero exact feature-vector collisions.
- Zero near collisions at `1e-6`.
- Zero constitutional tier blocks.
- All four target failure classes have a majority of errors inside the cone.

| Failure class | Expressible errors | Total errors | Expressible |
|---|---:|---:|---:|
| Partial-match saturation | 24 | 34 | 70.6% |
| Phrase/order failure | 43 | 45 | 95.6% |
| Common-term dominance | 17 | 21 | 81.0% |
| Length-prior failure | 5 | 5 | 100.0% |
| Wrong-concept proximity | 31 | 38 | 81.6% |
| Document/conversation confusion | 11 | 16 | 68.8% |

The audit also proves that `matched_group_fraction` and
`missing_group_absence` are numerically identical, with maximum observed
absolute difference `5.9604645e-8`. Their learned weights sum to `0.18841472`;
splitting that effective direction across two coordinates gives it the expected
half-cost L2 geometry.

Thirteen features are ranking-dead on this development split, including the
query-only `query_group_count`, `single_group_flag`, and `long_query_flag`.
Several complete-coverage/positional primitives are also constant because the
reviewed eligible pairs are same-tier.

## Phase 8.8 objective experiments

Both experiments preserve the canonical serving kernel: one fixed 30-value
slice walk, nonnegative weights, no serving allocation, and no runtime
training. Model selection uses development data only; blind labels remain
sealed until the final Phase 8 evaluation.

### Static top-sensitive objective

- Per-pair weight: authority/confidence times binary-gain DCG@10 swap delta,
  with a preregistered `0.05` off-top floor.
- Pair weights are normalized inside each query, so every query contributes
  total training force 1.
- Selected by minimum development weighted logistic loss, not row accuracy.

Model receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_8-objective-proof-v1\phase8_8-top-sensitive-linear-model-v1.json`

SHA-256:
`955a13229d5b0442b7ac52ca707a8de555fb653a77a48892b90493e708e89c41`

Result: blind pairwise accuracy and held-out top-1 improve, but LongMemEval and
independent graded ordering regress. Static V2-position weights are not a
faithful listwise objective.

### Dynamic current-order LambdaRank objective

- Builds a bounded judged-candidate working set per query.
- Recomputes deterministic current within-query ranks during training.
- Uses current-order binary-gain delta DCG@10 pair weights plus the same `0.05`
  off-top floor.
- Normalizes every query to total force 1.
- Retains projected nonnegative logistic training and the exact production
  `LinearRankerV3` scorer.

Model receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_8-objective-proof-v1\phase8_8-top-sensitive-lambdarank-model-v2.json`

SHA-256:
`77137b793843f4c4e24b3854bc705cc090e0f72ee70d199b04385819f87bac9e`

Quality receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_8-objective-proof-v1\phase8_8-lambdarank-quality-v2.json`

SHA-256:
`1fa0962ac6194e97845d0e3e3173b544f67e97b68597e4ec90727c9b7fc39dd1`

Training used 3,389 judgments, 1,028 queries, and 4,417 distinct judged
candidates. The deterministic grid selected 512 epochs, learning rate 0.025,
and L2 0.0. The objective fell from `0.69315183` to `0.5662548`.

| Metric | Canonical | Static 8.8 | Dynamic LambdaRank 8.8 |
|---|---:|---:|---:|
| LongMemEval MRR@10 | 0.897808 | 0.896669 | 0.898541 |
| Independent NDCG@10 delta | -0.007341 | -0.017635 | -0.009018 |
| Normalized MRR gap closure | -0.052439 | -0.075653 | -0.058767 |
| Blind pairwise accuracy | 0.785377 | 0.792453 | 0.781840 |
| Held-out top-1 improvement | +4.184 | +5.439 | +4.184 |
| Worst-shape MRR regression | 0.016345 | 0.016345 | 0.016345 |

Dynamic LambdaRank recovers `+0.000733` LongMemEval MRR@10 over canonical, but
remains `0.011459` below the promotion gate. It does not transfer to the
independent graded suite and does not change the worst-shape failure at all.

## What the evidence now says

The objective mismatch was real, but it was not the dominant blocker.
Query-normalized top-sensitive training changes the learned ordering in the
expected direction on reviewed preferences, yet neither static nor genuine
dynamic listwise weighting closes independent or query-shape quality.

The 14.43% monotonic-impossible development-error floor independently proves
that an objective-only solution cannot repair every reviewed preference. The
failure of the expressible majority to transfer shows that the aggregate
30-feature geometry is not globally separable enough for the frozen suites.

This is a stop decision for additional loss tuning, not authorization for a
tree. Phase 11 remains ineligible until a linear model passes promotion gates
and at least 10,000 reconciled pairs exist.

## Next cut: group-distribution evidence preflight

The next experiment should remain diagnostic and schema-preserving. It should
capture the per-group distribution already available during candidate
evaluation, then test whether preferred candidates become separable where the
canonical aggregate evidence fails.

The first candidate primitive family is:

1. weakest matched-group strength;
2. lower-tail matched-group strength, preferably a bounded deterministic
   minimum or low quantile;
3. contribution balance or concentration across matched groups;
4. only after those, source/temporal alignment for conversational retrieval.

Preflight gates before any learner or schema migration:

- evaluate only development errors plus the frozen independent sidecar;
- isolate canonical monotonic-impossible pairs and long-query/worst-shape
  failures;
- require the preferred candidate to have the better oriented new primitive in
  at least 70% of newly separated target pairs;
- require material coverage of PartialMatchSaturation, CommonTermDominance,
  LengthPriorFailure, WrongConceptProximity, and
  DocumentConversationConfusion;
- preserve candidate-pool hashes, V2 score bits, constitutional tiers, and
  stable order exactly;
- do not mutate the canonical ledger or evidence schema unless a frozen learner
  experiment transfers to LongMemEval and the independent graded suite.

Until such a primitive earns migration, the canonical Phase 7 model remains a
diagnostic challenger and the active engine remains V2.
