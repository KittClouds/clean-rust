# JEV v0.8I Phase B — Controlled Fact-Flip Intervention

## Status and question

Phase-A v01 is quarantined and non-promotable. The clean Phase-A identity is
`phase-a-v02-clean`; its scientific definitions and artifacts are read-only.
Phase B asks whether controlled single-fact choice-flip supervision improves
held-out local choice discrimination relative to matched sham supervision.

The primary contrast is `F100` versus `S100` on 2,000 held-out anchor/fact-flip/
sham triplets. The direct contrast surface is the primary mechanistic endpoint;
NewTight-Eval and the pinned legacy panels are secondary transfer and collateral
capability surfaces. This protocol does not authorize a follow-on experiment.

## Frozen treatment and runtime

The sealed contract is
`experiments/jev-information-density-v08i/phase_b/phase-b-v01-contract.json`.
Both arms contain 100,000 occurrences, a shared 90,000-group skeleton, and
10,000 matched replacements. Independently reproduced `D_train` is 0.05.

Use the pinned `LiquidAI/LFM2.5-1.2B-Base` revision, frozen end to end. Feature
extraction is exact-length, single-row, no-padding, final-layer `mean_full`.
The dynamic compatibility MLP has projection width 128 and uses the existing
source-typed L3 loss. The head-only recipe is AdamW, learning rate 0.002,
weight decay 0.01, batch 256, three epochs, no scheduler or clipping, with the
frozen Brier and invariance weights in the contract. Seeds are paired:
20260927, 20260928, and 20260929. The interleaved arm schedule is frozen in the
contract. The terminal comparison is epoch 3; no best-epoch selection occurs.

No LoRA/QLoRA, backbone update, bank regeneration, architecture/pooling search,
or result-driven tuning is permitted. Phoenix is out of scope.

## Evaluation and analysis

For every seed and epoch, preserve direct held-out predictions and separately
measure fact-flip response and sham invariance. Fact-flip analysis aligns by
`candidate_semantic_id` and reports new-winner probability movement versus exact
gold movement, direction agreement, delta correlation/error, strict certified
old-to-new MAP transition, rank gain, and old/new margin movement. Sham
analysis reports aligned distribution L1, MAP flips, exact-gold movement, and
winner/margin movement. Results are also grouped by held-out world family;
triplet descendants are not treated as independent inferential replicates.

NewTight typed choice, applicability, and ordinal panels are retained alongside
schema-binding drift and world-intervention geometry. Legacy typed panels are
secondary. Calibration is reported separately from semantic ordering; no
composite score or arbitrary win threshold is used. Paired seed differences and
all individual seeds are shown. A treatment effect is specific to this
controlled intervention and frozen substrate; it is not a claim that one bank
is universally superior.

## Execution boundary

`preflight_phase_b.py` must independently validate the v02 Phase-A hashes,
protection receipts, bank identities, held-out certificate composition, pinned
LFM snapshot, reference caches, and implementation hashes before it mints the
model-contact receipt. The materializer may then construct only the held-out
Phase-B evaluation view and append its representation inputs; Phase-A bank
files remain untouched. Feature extraction and training refuse to proceed if
the authorization, contract, input, feature, or implementation hashes drift.

The accepted output is written outside the repository at
`D:/codex-runs/jev-information-density-v08i/phase-b-v01`. Reports are
post-hoc only. No result authorizes further training or a new experiment.
