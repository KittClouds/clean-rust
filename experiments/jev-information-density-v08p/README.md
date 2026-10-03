# JEV v0.8P: Late Transition Localization

**Identity:** `v0.8P-fresh-trajectory-instrumented-rerun-v01`  
**Disposition:** contracts frozen for review; no panel construction, training, or evaluation is authorized.  
**Original v0.8N Phase B:** remains `EVALUATION_INPUT_CONTRACT_INCOMPLETE`.  
**Primary evaluation:** a new sealed P panel, not E1.

## Why P exists: measured v0.8O evidence

v0.8O evaluated the 27 sealed epoch checkpoints and three shared initialization templates on E1. It produced a complete 288,000-row prediction matrix. O had snapshots at global steps 40, 80, and 120 only. It therefore brackets behavior to the epoch-2-to-epoch-3 interval; it does not reveal an intermediate event time or justify inserting imagined states into the sealed trajectory.

The table below transcribes selected, preregistered coordinates from O's complete arm × seed × epoch matrix. Rates are proportions; `Δp` is the fact-view new-winner probability minus its anchor probability. All three seeds had zero strict transitions at step 80.

| Seed | Arm | Strict, step 80 → 120 | `Δp_new`, step 80 → 120 | `A_old`, step 80 → 120 | `F_new`, step 80 → 120 |
|---:|---|---:|---:|---:|---:|
| 20260927 | DUP | 0.0000 → 0.0000 | 0.000035 → 0.000768 | 1.0000 → 0.9630 | 0.0000 → 0.0000 |
| 20260927 | MATCHED | 0.0000 → 0.6470 | 0.000664 → 0.244583 | 1.0000 → 0.6470 | 0.0000 → 1.0000 |
| 20260927 | SHAM | 0.0000 → 0.0000 | 0.000114 → 0.007380 | 0.5000 → 0.5000 | 0.0000 → 0.0000 |
| 20260928 | DUP | 0.0000 → 0.0020 | 0.000864 → 0.037532 | 1.0000 → 1.0000 | 0.0000 → 0.0020 |
| 20260928 | MATCHED | 0.0000 → 0.0000 | 0.000693 → 0.007199 | 1.0000 → 1.0000 | 0.0000 → 0.0000 |
| 20260928 | SHAM | 0.0000 → 0.0000 | 0.000057 → 0.005062 | 0.8095 → 1.0000 | 0.0000 → 0.0000 |
| 20260929 | DUP | 0.0000 → 0.9955 | 0.003968 → 0.196950 | 1.0000 → 0.9995 | 0.0000 → 0.9960 |
| 20260929 | MATCHED | 0.0000 → 0.9545 | 0.009425 → 0.267683 | 1.0000 → 0.9545 | 0.0000 → 1.0000 |
| 20260929 | SHAM | 0.0000 → 0.7220 | 0.008578 → 0.259618 | 1.0000 → 0.7515 | 0.0000 → 0.9705 |

These outcomes separate several forms: in seed 20260927 MATCHED acquires a strong strict transition while SHAM does not; in seed 20260928 all arms remain near the low-response regime, with only 0.2% DUP strict transitions; and in seed 20260929 all arms acquire strong fact-view responses, while SHAM has a larger anchor-preservation loss. In that last cell, the four-cell `¬A ∧ F` proportion is 0.2485 for SHAM versus 0.0455 for MATCHED. This supports a seed- and treatment-conditioned change in the measured coordinates between the two observed endpoints. It does not locate the change within steps 81–120, establish a monotone transition, or show that full trajectories were shared before step 80.

The arms shared initialization within seed, not an observed common early path. For example, at epoch 1 / step 40 in seed 20260927, `A_old` was 0.25 / 0.50 / 1.00 for DUP / MATCHED / SHAM.

For seed 20260929 at step 120, parameter displacement from initialization was similar—MATCHED `‖Δφ‖₂=6.62806`, SHAM `6.46146`—while their behavior differed; the update-vector cosine was `0.58944`. These are descriptive comparisons, not evidence that parameter orientation or a basin mechanism caused the behavioral difference.

O's sealed source is `D:/codex-runs/jev-information-density-v08o/v0.8O-capability-trajectory-cartography-v01/trajectory-cartography-v01.md` (SHA-256 `51afebacbe33bb95a4eed1e1ce95153cc9aa01b2e72abda7a21060864c9a3a0b`), under result seal `v08o-result-seal-v01.json` (SHA-256 `6327e2c3e83bbff7d511c5ba4bfd09792d5adad6aa95ae4d2abfce351e224ff7`).

## Frozen P design

P is a new run, with three new hash-derived seeds (`3243871208`, `669993655`, `3076094663`). It reuses the sealed v0.8N training occurrences, arm payloads, state features, and candidate features, but no old initialization or checkpoint. The three arms remain B-DUP, B-MATCHED, and B-SHAM; all model, optimizer, loss, event counts, batching, and epoch semantics remain frozen.

The new run saves epoch-1 and epoch-2 terminal snapshots and a snapshot after every optimizer update in epoch 3 (global steps 81–120): 42 trained snapshots per run, 378 total, plus one shared initialization baseline per seed. All nine runs complete without evaluation feedback. The full snapshot matrix is then evaluated once on the separately constructed fresh panel; raw predictions are sealed before analysis. No checkpoint is selected or promoted.

The fresh panel uses 2,000 newly generated world instances, 500 in each of the same four held-out semantic families. It retains the frozen p0–p3 template surfaces to keep the measurement interface comparable; it is fresh at the world/neighborhood level, not a novel-template generalization test. The panel uses the same A/F/S/MATCHED estimands and radius-only control selection as E1, but has its own generated rows, candidate-text manifest, feature extraction, join, hashes, and firewall. E1 rows, targets, joins, feature vectors, predictions, and metrics are excluded from P's primary analysis.

### Analysis

The response remains a vector: sham and matched-neutral locality, `A_old`, `F_new`, strict transition, correct direction, `Δp_new`, exact-delta MAE, anchor NLL/Brier, and the four-cell A/F decomposition. Every metric is reported by seed, arm, optimizer step, and family. Predeclared event-time summaries compare each epoch-3 step with the same panel's step-80 baseline and use three consecutive optimizer steps plus family-stratified simultaneous neighborhood-bootstrap bands. They describe timing; they are not a winner score or stopping rule. Parameter paths are reported separately and descriptively.

Three seed trajectories remain three trajectories, not a population estimate. Intermediate behavior is not an operating point. A promising window would motivate a later prospectively authorized experiment, not a retrospective checkpoint claim.

## Current gates

| Object | State |
|---|---|
| Run contract | Sealed for review; training unauthorized |
| Analysis contract | Sealed for review; inference/analysis unauthorized |
| Fresh-panel contract | Sealed specification; panel not constructed |
| Panel construction authorization | False |
| Training authorization | False |
| Evaluation authorization | False |
| E1 used as P primary panel | No |
| P external run output directory | Not created |

The P-specific trainer/evaluator implementations, schedule materialization, fresh panel artifacts, and their hash receipts remain pre-authorization gates. Any later user authorization must be separate for panel construction, training, and evaluation. The contract bundle and local source/hash audit are recorded in [contract-bundle-seal-v01.json](contracts/contract-bundle-seal-v01.json). The delegated Luna review returned no artifact; no Luna PASS is claimed.
