# JEV v0.8Q: Single-Dose Gain Intervention

## Sealed question

Does halving only the SHAM auxiliary-event loss weight increase fact-response gain while retaining response direction and anchor preservation, and does it preserve a material locality advantage over concurrent DUP?

The outcome remains a vector:

```text
direction | gain | boundary crossing | locality | preservation
```

## Frozen treatment and paired runs

The four concurrent arms are `B-DUP`, `B-MATCHED`, `B-SHAM`, and `B-SHAM-LOW`. `B-SHAM-LOW` uses the byte-identical SHAM auxiliary source identities and event positions. Its one intervention is a per-auxiliary-event multiplier of exactly `0.5` on both semantic loss and Brier contribution. The original arithmetic-mean denominator remains the total active row count. The backbone, head, candidate order, primary stream, schedule, optimizer, batch boundaries, initialization pairing, precision, and 120 update steps remain bound to the R2 basis.

Three new paired optimizer seeds and one fresh panel generator seed are prospectively derived in the v01 proposal and re-bound in the v02 machine contracts. All four arms share each seed's initial head. Seed count means three observed paired trajectories, not a population estimate.

## Corrections frozen in v02

1. `Q_OPERATING_POINT_SEED_PASS` and `Q_STIFF_COUPLING_SEED` are evaluated within one seed. A cohort label requires at least two seeds that each satisfy the full same-seed conjunction. Different seeds cannot supply different pieces of a conjunction.
2. “Retains locality” means the contracted material locality advantage over concurrent DUP. It does not mean retention of SHAM-level locality. Sham and matched-neutral L1 and MAP-flip channels are each checked separately.

The proposal v01 already stated these corrections in prose. V02 gives them normative machine-readable rules, tests, and a bundle seal.

## Panel and information firewall

The panel contract binds a fresh `eval_v08q` stream, 2,000 neighborhoods, 500 per fixed family, candidate ordinals 0 through 699, the frozen five-field exclusion procedure, radius-only neutral matching, and the existing radius gates. If the fixed stream cannot fill a family or any sealed validation fails, preserve the failed attempt and stop. No reseed, candidate replacement, candidate shopping, or budget extension is allowed.

The panel, fresh feature cache, matching, targets, and Q evaluation outcomes are sealed inputs to their contracted stages. Training cannot read evaluation outputs. All 12 complete runs, 507 checkpoint/template entries, and training telemetry are sealed before the evaluator may open the fresh panel. The evaluator opens it once and emits the complete contracted prediction table before analysis.

## Analysis

Step 120 is primary. Steps 40, 80, and 100 are descriptive. Report all five response coordinates independently, paired by seed and neighborhood, with family breakdowns and the frozen family-stratified bootstrap. No checkpoint selection, composite score, pooled-seed population inference, or vibration-guided treatment change.

The two principal decision labels are computed per seed:

- Operating point: material continuous gain, direction, material locality advantage over DUP, and preservation all pass in the same seed; at least two of three seeds are required for the cohort label.
- Stiff coupling: material continuous gain and DUP-like locality both pass in the same seed; at least two of three seeds are required. A zero DUP L1 channel is unclassifiable and fails the locality part.

MAP response remains separate: both `F_new` and `Strict` must improve by at least 10 percentage points versus SHAM in the same seed, in at least two seeds. This label is not required for the continuous operating-point label.

## Terminal authorization state

This seal establishes only a prospective execution bundle. It does not authorize panel construction, tokenizer/model loading, feature extraction, head initialization, training, or evaluation.

```text
Q_BUNDLE_SEALED                 true
Q_PANEL_CONSTRUCTION_AUTHORIZED false
Q_MODEL_CONTACT_AUTHORIZED      false
Q_TRAINING_AUTHORIZED           false
Q_EVALUATION_AUTHORIZED         false
```
