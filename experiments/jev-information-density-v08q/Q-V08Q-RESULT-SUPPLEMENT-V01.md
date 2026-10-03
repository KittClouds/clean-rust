# JEV v0.8Q — single-dose gain intervention

## Result in one sentence

Halving the SHAM auxiliary-event weight increased fact-response gain in two of three paired seeds and produced a meaningful fact-view MAP response in two seeds, but **no more than one seed jointly met the preregistered gain, direction, material-locality-advantage, and preservation criteria**. The cohort-level tunable-operating-point label is therefore false.

This is a heterogeneous dose response, not a reliable one-dimensional gain/locality control.

## What was run

The four frozen arms were DUP, MATCHED, SHAM, and SHAM-LOW. SHAM-LOW changed only the auxiliary loss multiplier to 0.5; event identities, counts, positions, schedule, denominator, optimizer, head, and training duration were unchanged. The run used three paired seeds and the sealed 2,000-neighborhood panel (500 per family).

All 12 runs completed to step 120. The four contracted checkpoints per run (40, 80, 100, 120) yielded 48 trained checkpoints plus three shared initialization templates. Evaluation produced 408,000 prediction rows over 51 cells with one recorded panel opening. The independent verifier passed after recomputing the prediction matrix, 102,000 neighborhood metric rows, 204 family cells, and all 45 paired intervals.

## Step-120 results

| Seed | New-winner probability movement, SHAM → LOW (paired change) | Fact-view new MAP, SHAM → LOW | Strict transition, SHAM → LOW | Anchor old MAP, SHAM → LOW | Sham L1, DUP → LOW | Matched L1, DUP → LOW | Joint operating-point pass |
|---:|---:|---:|---:|---:|---:|---:|:---:|
| 2540205348 | 0.036342 → 0.097117 (+0.060775) | 0.0000 → 0.0000 | 0.0000 → 0.0000 | 1.0000 → 1.0000 | 0.179714 → 0.071095 | 0.105532 → 0.044219 | Yes |
| 2603246505 | 0.011231 → 0.011453 (+0.000223) | 0.0000 → 0.1635 | 0.0000 → 0.1635 | 0.9995 → 0.7835 | 0.157825 → 0.014400 | 0.097762 → 0.006939 | No |
| 3565067208 | 0.010809 → 0.115439 (+0.104631) | 0.0000 → 0.6905 | 0.0000 → 0.6900 | 1.0000 → 0.9995 | 0.043037 → 0.083123 | 0.026234 → 0.046365 | No |

Correct-direction rates under SHAM-LOW were 1.0000, 0.9935, and 1.0000. All three pass the frozen direction floor; the middle seed is 0.65 percentage points below SHAM and remains within the one-point tolerance.

The table deliberately separates continuous movement, boundary crossing, locality, and preservation. They do not move as one score.

## The three trajectories differ in kind

**Seed 2540205348 — more gain, still no crossing.** SHAM-LOW raised new-winner probability movement by 0.060775, with paired neighborhood 95% interval [0.060524, 0.061032]. Direction and anchor preservation remained intact. Sham and matched L1 remained materially below DUP (0.071095 vs 0.179714; 0.044219 vs 0.105532), and both MAP-flip rates were zero. But fact-view new MAP and strict transition both stayed at zero. This is a continuous-gain/locality operating point under the frozen rule, not a demonstrated boundary transition.

**Seed 2603246505 — modest movement, some crossings, severe preservation cost.** The probability-movement increase was only 0.000223 [0.000188, 0.000259], far below the preregistered +0.020 practical margin. Fact-view new MAP and strict transition each rose by 16.35 points [15.30, 17.40], but anchor old-MAP preservation fell 21.6 points [20.85, 22.35] relative to SHAM. The family pattern is sharply split: the fact-view new-MAP rate reached 65.4% in respiratory monitoring, while anchor old-MAP preservation in vibration monitoring fell from 99.8% under SHAM to 13.4% under SHAM-LOW (−86.4 points). This is not successful localized control.

**Seed 3565067208 — broad crossings, locality lost.** Probability movement rose by 0.104631 [0.104423, 0.104835]. Fact-view new MAP increased by 69.05 points [67.55, 70.50], strict transition by 69.00 points [67.50, 70.45], and anchor old-MAP preservation changed by only −0.05 points [−0.15, 0.00]. But sham L1 under SHAM-LOW was 0.083123, almost twice DUP's 0.043037; matched L1 was 0.046365 versus DUP's 0.026234. The arm gained boundary response while losing the preregistered material locality advantage over DUP.

These intervals quantify neighborhood uncertainty conditional on each seed and this fixed panel. They do not estimate variation across optimizer seeds.

## Frozen labels and interpretation

- `q_operating_point_seed_pass`: **1/3**; the required ≥2/3 cohort rule fails.
- `q_map_response_seed_pass`: **2/3**; meaningful MAP response is present in two observed trajectories, but not alongside all operating-point conditions in those same trajectories.
- `q_stiff_coupling_seed`: **0/3**; the preregistered stiff-coupling label fails.
- The result is **heterogeneous**, not a universal dose law. Do not assemble gain from one seed, locality from another, and preservation from a third.

The evidence supports a bounded statement:

> At the tested 0.5 multiplier, SHAM-LOW changed the response state, but did not reliably produce a same-seed combination of increased gain, retained direction, material locality advantage over DUP, and preserved anchor decisions. Two seeds crossed more fact-view boundaries; they failed for different reasons.

It does not establish that auxiliary weight is a stable control dial, that semantic direction is the cause, or that the backbone capability itself changed. The trained object was the decision head on a frozen representation.

## What to do next

Do not turn this into a dose sweep or choose a favorable checkpoint. The next useful scientific step, if this line continues, is a prospectively registered replication of the **same fixed 0.5 treatment** with fresh worlds and additional paired seeds, retaining the separate family-level preservation and locality coordinates. The specific question is whether the respiratory-response / vibration-preservation split in seed 2603246505 recurs, and whether the seed-3565067208 locality loss is common or trajectory-specific. Until then, describe those as observed seed patterns, not training principles.

For FAS, keep S11 as the separate fresh-split replication question: test the already identified M/F transport asymmetry and distance-decay pattern before beginning mechanism work. Q does not update that claim.

## Execution and provenance

The original frozen Q training completed and remains the sole training run. The evaluator's first attempt opened the panel once, then failed during materialization before head loading or prediction. The repair corrected a root-level comparison: the feature receipt names the pre-feature construction root (`b9f77d…ed2a2`), while the evaluator had compared it with the later terminal panel root (`1b99d3…39a6`). The same opening receipt was reused byte-for-byte; no second panel opening occurred.

Two additional implementation-only defects were repaired through separate runtime shims without editing the sealed evaluator, analysis, or verifier: the analysis checked the neighborhood-metric file against the distinct inference-metric hash; the independent verifier initialized a neighborhood-to-view map as a set. The verifier then passed its full replay. The failed attempts and receipts remain preserved.

| Artifact | Identity |
|---|---|
| Execution packet | `bd263ce025146b9c57c8eebabd46336c28d6367078d153ec145b68ca7e9c177c` |
| Training seal | `de350a3256d617747617657a59088344ef8e7ed24258725be8018e7ec5a195b8` |
| Raw prediction SHA-256 | `d4bc4fce5fd1c51815ac214b794e3b5d5c51f549d80ad7e1362ec5c04abc976e` |
| Prediction tree | `745809874616d7ce22d2a415e48c27627e6b3a691de11a0f38f260f3b03e23c6` |
| Analysis root | `963f846393e8465db28f69a7223d557590e94928fc32b18e571d0871041845c0` |
| Analysis seal | `3740d9d30b5d6327b5d63f6cd1ccb9dff347803d539592c33fb7fad89cb819ac` |
| Independent verification receipt | `2b46d950753f101ed821526639fe0e4d4cfa8464855df3434fc366ea1d9684e8` |
| Independent disposition | `Q_FULL_EXECUTION_INDEPENDENT_VERIFICATION_PASS`; panel opening count `1` |

The sealed machine-generated report and full JSON analysis are in:

```text
D:\codex-runs\jev-information-density-v08q-run-v01\evaluation-continuation-v01\q-response-analysis-v01.md
D:\codex-runs\jev-information-density-v08q-run-v01\evaluation-continuation-v01\q-response-analysis-v01.json
```

This supplement interprets those sealed outputs; it is not part of, and does not modify, the sealed analysis root.
