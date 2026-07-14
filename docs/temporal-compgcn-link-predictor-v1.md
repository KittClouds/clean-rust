# Temporal CompGCN Link Predictor v1

Status: implemented research rung; frozen R-GCN retained.

Date: 2026-07-13.

## Decision

Temporal CompGCN v1 was implemented and evaluated against the exact frozen
Temporal R-GCN control on the frozen Smallpedia chronological link-prediction
task. None of the six composition/relation-update arms beat the control.

The acceptance gate therefore emitted no deployable CompGCN model artifact.
Every failed arm instead produced a content-addressed negative candidate
receipt containing its model identity, weight digest, exact validation score
certificate, control certificate, deterministic configuration, training
receipt, staging receipt, and resource counters.

This is the intended stop condition from the focused paper-to-contract sprint:
retain the negative result, keep the frozen R-GCN as the learned rung, and move
the next research slice to the qualifier-aware task rather than tuning on test
or changing the evaluator.

## Frozen authority

- Source dataset:
  `b3-81d8edf1ee6b88557ae555ed15696561d8bcc2740a73b21be1e6fa4f090d9eba`
- Canonical task:
  `b3-4a89c46f19d4636e5669d84ba1795eb89fe082c4185506e297e9a0ffbe21db5d`
- Frozen R-GCN manifest:
  `b3-eb3b3b7ca9999403b440a87c1a310a4b08c30f579766bb524c064294781f3049`
- Frozen R-GCN model:
  `b3-261c2935b5b80b6f999f7cb065c9bd53bab6a7f8436e8a8a08bf38e9de2b7e43`
- Frozen R-GCN validation MRR: `0.05817527887231176`
- Evaluator: exact all-entity filtered ranker, query batch 64, query tile 4,
  candidate tile 4096.
- Test split: unopened.

## Architecture

The implementation changes only the learned graph-message arm:

`message(u, r) = W_direction(r) * phi(h_u, z_r)`

`z'_r = W_rel * z_r`

The frozen structural relation/destination-frequency prior and final score
formula remain unchanged.

The model contains:

- one 16-float state per entity;
- one 16-float state per directed relation plus one self relation;
- three shared 16 x 16 direction matrices for original, inverse, and self
  messages;
- one shared 16 x 16 relation projection;
- one bias per directed relation.

The relation-specific 16 x 16 R-GCN matrices are gone. The released artifact
shape is therefore compact and directly mmap-readable.

## Ablation identities

The following choices are serialized into the architecture and model identity:

- composition: `multiply`, `subtract`, or `circularCorrelation`;
- relation update: `jointLinear` or `frozen`;
- epochs, learning rate, L2, negative count, residual scale, and seed;
- source, task, topology, runtime, trainer, optimizer, and frozen-control
  identities.

Circular correlation uses the fixed scalar definition

`phi[k] = sum_i entity[i] * relation[(i + k) mod 16]`

with a fixed operation order. No FFT and no platform-dependent reassociation
are used.

## Training and memory contract

- Full-batch deterministic SGD.
- One preallocated gradient arena.
- SIMD `f32x8` dot and triple-product kernels.
- Zero heap allocation inside every epoch for all six arms.
- The existing train-only typed adjacency is reused directly; no relation-batch
  sidecar was introduced.
- Relation-state bytes and composition-kernel time are reported separately.
- Wall-clock and allocation observations are excluded from model identity.
- Same input/configuration/seed reproduces model ID, weight digest, exact score
  certificate, and score digest.

The reproducibility test caught and removed an early design error where
composition time had entered the model identity. Performance measurements now
live only in candidate/performance receipts.

## Exact control compatibility

Before an ablation arm can be evaluated, the trainer:

1. opens the frozen R-GCN manifest and mmap weights;
2. verifies source, binary, task, and task-binary identities;
3. rebuilds the control encoding from its own frozen configuration;
4. reruns the authoritative exact canonical evaluator;
5. requires the replayed certificate and score digest to equal the frozen
   validation certificate bit-for-bit.

Failure stops before candidate training. This is the no-composition
compatibility arm: the control path itself remains the authority rather than a
new approximation of R-GCN inside CompGCN.

## Full six-arm result

All arms used seed `8099846411260622849`, four epochs, learning rate `0.02`,
L2 `0.00001`, one negative per positive, and learned residual scale `0.01`.

| Composition | Relation update | Validation MRR | Delta vs R-GCN | Train ms | Composition ms | Exact eval ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| subtract | frozen | 0.058126678086967566 | -0.000048600785344194 | 814.380 | 307.753 | 3383.992 |
| subtract | joint | 0.058125894987127134 | -0.000049383885184626 | 738.818 | 284.763 | 3062.447 |
| multiply | frozen | 0.05804911932818758 | -0.00012615954412418 | 812.530 | 299.800 | 3442.895 |
| multiply | joint | 0.05804911144052594 | -0.00012616743178582 | 839.287 | 291.213 | 3041.763 |
| circular correlation | joint | 0.05802030257520512 | -0.00015497629710664 | 2130.255 | 633.772 | 3042.306 |
| circular correlation | frozen | 0.05801823251062671 | -0.00015704636168505 | 2146.030 | 646.810 | 3119.815 |

Every arm used 2.936 MiB of parameters, an 8.795 MiB fused gradient arena, and
zero epoch allocation bytes.

The best arm was subtraction with frozen relation states, but it still missed
the frozen R-GCN by `0.000048600785344194` MRR. Joint relation projection did not
improve any operator enough to pass the gate. Circular correlation cost roughly
three times the training time of subtraction without improving rank quality.

## Negative candidate receipts

The authoritative receipts are under:

`target/graph-research-models/temporal-compgcn-v1-final-candidates`

Best-arm receipt:

`sub-frozen/b3-fc3368ee262949eca2c975d016e33e61973c2c9edb985b9c57fbedcbc2a12982.temporal-compgcn-candidate.json`

Best-arm identities:

- model:
  `b3-833e28a7b8407e282467bdbe2cf237cc561fa76112c3d2c9203cd527dd6409de`
- exact score digest:
  `b3-029ec7ec815ddf8709f4f51e43234d81da4912e129524799776ac59be7e894ec`

Candidate receipts are not deployable model manifests. They intentionally do
not persist weights. A passing arm would instead write the mmap `.tcw` payload,
immutable `.temporal-compgcn.json` manifest, restart the scorer from those two
files, and require exact witness/certificate parity before returning success.

## Additional ladder evidence

The default-seed subtraction arm was also checked at 8, 16, and 32 epochs and
at learning rates `0.1`, `0.5`, `2.0`, and `10.0`. Longer training was flat and
larger updates degraded validation. Seeds 17 and 29 also remained below the
control. No test score was requested or observed.

These probes reinforce the stop decision: the deficit is architectural on this
task, not an obvious under-training artifact.

## Verification gates

- CompGCN composition exact-operation-order unit test.
- Circular-correlation central-difference backward test.
- Mmap artifact round trip and corruption rejection test.
- Non-winning candidate rejection and no-model-artifact test.
- Same-seed negative rerun reproduces model ID, weight digest, validation
  certificate, and score digest.
- Existing control exact replay is mandatory on every real candidate run.
- D: target compilation and C: workspace test execution.
- Rust formatting and Clippy with warnings denied.

## Next research slice

Proceed to **Canonical Hyper-Relational Link Prediction Task v1** over the
already frozen WD50K statement artifact.

The next task must preserve primary triple roles and qualifier `(relation,
entity)` pairs, derive train-only qualifier message surfaces, define filtered
full-candidate validation/test queries, and freeze exact statement/qualifier
identities before any StarE-style model work begins.
