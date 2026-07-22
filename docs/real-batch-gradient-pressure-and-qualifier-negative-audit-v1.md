# Real-Batch Gradient Pressure and Qualifier-Negative Audit v1

Status: complete, bounded diagnostic, WD50K test partition locked.

Authoritative receipt:

`target/graph-research-models/gradient-pressure-audit-v1-final/b3-493fc8340f1d2cebd000a2fdcbc653931c67d44d581ec967744c29683b069d5c.gradient-pressure.json`

Independent replay:

`target/graph-research-models/gradient-pressure-audit-v1-replay/b3-493fc8340f1d2cebd000a2fdcbc653931c67d44d581ec967744c29683b069d5c.gradient-pressure.json`

## Question and authority

This cut determines whether real WD50K qualifier learning is suppressed by
gradient cancellation, global clipping, inadequate negative pressure, or a
combination. It does not install a new optimizer, mutate the primary graph, or
run another model-selection envelope.

All measurements start from the immutable epoch-32 Full StarE checkpoint:

- model: `b3-1f0c340e5fc9a8a7474fd389fc5eb658be3de542c0e0ab0d385906fca596d6bc`;
- manifest: `b3-def4eeb0a756cf220fe7bea650a12ba967a3af26590414a9d7189ae0017199a3`;
- original initialization: `b3-79e0065692eff88ba642e602aa5bb998a46d394132dab11f1a36cb2c0c8c2d5f`.

The runner validates source, task, seed, StarE mode, epoch count, initialization,
and exact frozen example schedule before measuring anything. The test partition
is not opened. Qualifier corruptions are checked against the complete frozen
train-positive context set.

## Decision

**Clipping dominant.** The next certified cut is **Pressure Routing v1 with
isolated clipping groups**.

All eleven frozen real batches are dominated by decoder bias:

| Measure | Minimum | Maximum | Mean |
|---|---:|---:|---:|
| Raw global gradient L2 | 243.5724 | 1677.9948 | 1493.4627 |
| Global clip coefficient | 0.00059595 | 0.00410556 | 0.00093540 |
| Decoder-bias share of squared global norm | 0.9999999962 | 0.9999999981 | 0.9999999976 |
| Non-bias pressure recovery if routed separately | 243.57x | 1677.99x | 1493.46x |

The final partial batch reproduces the frozen envelope pressure point:

- raw decoder-bias gradient L2: `243.5724`;
- raw qualifier-projection gradient L2: `8.40773e-5`;
- global clip coefficient: `0.00410556`;
- qualifier-projection post-clip gradient L2: `3.45184e-7`.

The bias counterfactual is algebraic over the exact same raw gradient. Freezing
the bias, excluding it from the global norm, or clipping it as its own group
raises the final-batch non-bias coefficient from `0.00410556` to `1.0`.
Counterfactual changed-bit counts are deliberately marked unmeasured.

## Negative-pressure audit

Each diagnostic schedule contains eight deterministic positive/negative pairs.
Qualifier schedules replace only the query qualifier span; the mmap graph,
message topology, and qualifier payload remain unchanged.

| Corruption | Global gradient L2 | Qualifier projection L2 | Qualifier norm share | Value-row L2 | Role-row L2 |
|---|---:|---:|---:|---:|---:|
| Primary target | 4.36524e-4 | 8.77953e-6 | 0.04045% | 2.55427e-5 | 7.75116e-6 |
| Qualifier value | 2.61756e-5 | 5.23911e-6 | 4.00608% | 5.33790e-6 | 4.00405e-6 |
| Qualifier role | 1.76622e-5 | 3.80113e-6 | 4.63167% | 4.35830e-6 | 3.83296e-6 |
| Mixed | 4.32777e-4 | 9.16409e-6 | 0.04484% | 2.51888e-5 | 9.32588e-6 |

Qualifier corruptions route roughly one hundred times more of their squared
gradient norm through the qualifier projection than primary corruption, but do
not increase its absolute gradient. They prove the path can receive targeted
pressure; they do not displace clipping as the first failure mechanism.

Value and role rows share the entity and relation tables. Their separate norms
are optimizer-visible lower bounds derived from actual `f32` parameter deltas,
the learning rate, and the clip coefficient. Exact changed-bit counts accompany
them so rounded-away updates remain visible as absence, not invented precision.

## Cancellation audit

For each 16-example stratum, the runner compares the aggregate gradient with
the sum of single-example gradient norms:

`C = 1 - ||sum(g_i)|| / sum(||g_i||)`

Qualifier-projection cancellation is moderate, not dominant:

| Stratum | Cancellation | Sign agreement |
|---|---:|---:|
| All examples | 0.5493 | 0.9790 |
| Qualified, one pair | 0.5988 | 0.8328 |
| Unqualified | 0.0364 | 0.9893 |
| Qualified, two or more pairs | 0.7002 | 0.9055 |
| Qualifier-value corruption | 0.3802 | 0.9426 |
| Qualifier-role corruption | 0.5610 | 0.9668 |
| Mixed corruption | 0.4738 | 0.8845 |

Cancellation is worth retaining in the receipt, especially for multi-qualifier
examples, but no qualifier-projection stratum approaches the `0.9` dominance
threshold. It cannot explain a global norm whose squared mass is more than
`99.9999996%` decoder bias.

## Stop boundary and horizon

The audit authorizes one separate Pressure Routing v1 cut, followed by one
corrected narrow WD50K optimization run. If healthy qualifier margins, visible
updates, and isolated pressure still leave Full StarE minus Null functionally
zero, this WD50K recipe stops.

- External calibration: prove the learner can exploit known qualifier value and
  role signals under measured pressure.
- Phoenix-native value: carry understood routing into canonical memory delta,
  discrepancy, episode, and context decisions.
- Exit criterion: healthy qualifier pressure without causal gain ends benchmark
  refinement rather than starting another optimizer ladder.

## Verification

- Release binary compiled to `D:\phoenix-target-overgraph` and executed against
  artifacts on `C:`.
- All eleven real batches and four negative schedules have per-block raw,
  post-clip, update, ratio, and changed-bit evidence.
- Seven cancellation strata include aggregate/single-example evidence, sign
  agreement, and split-half cosine.
- Durable receipt self-hash and cold open passed.
- Independent execution produced the same receipt identity and byte-exact file.
- Focused trainer library tests, formatting, and Clippy passed.
