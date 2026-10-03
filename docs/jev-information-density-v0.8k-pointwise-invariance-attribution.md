# JEV v0.8K — Pointwise Invariance Attribution

Status: Phase A complete and sealed; Phase B not authorized.

Protocol: `jev-information-density/v0.8k-phase-a-v01`

Phase-A identity: `phase-a-v01-clean`

Parent: v0.8J Phase B, sealed locally as `COMPLETE_NONPARENTABLE`.

## Purpose

v0.8K isolates the source of the v0.8J J10 improvement. Both arms receive the
same primary F100 bank, the same 5,000 certified triplets, the same auxiliary
event count, target multiset, loss weight, schedule, and feature universe. The
only treatment is the input receiving the additional pointwise event:

- **K-DUP:** the anchor feature receives the anchor target again.
- **K-SHAM:** the certified sham feature receives the anchor target.

This distinguishes extra supervision dose from information carried by the
semantic invariant view.

## Construction result

Phase A passed independent local validation.

| Property | Result |
| --- | ---: |
| Primary groups per arm | 100,000 |
| Certified triplets | 5,000 |
| Auxiliary events per arm | 5,000 |
| Primary-row distance | 0 |
| Target-multiset distance | 0 |
| Feature-universe distance | 0 |
| New invariance edges | 0 |
| Model contact | false |
| Feature extraction | false |
| Training | false |
| Evaluation inference | false |
| Phoenix access | false |

The two auxiliary event streams differ only in `auxiliary_source_role`:
`anchor` for K-DUP and `sham` for K-SHAM.

## Integrity identifiers

- Objective-graph SHA-256: `bd574cd15bc0630ecfcc91116dda5554696313c5b3d03fd161940242f6518670`
- F100 SHA-256: `fc298d2d38e04b269e648e89fe0431634f076e0c50f859d949e24f33ba33416e`
- Triplet identity SHA-256: `6e2597e727ce93969166d4111aba578bfe9abfb2bda586b71d2993b83bb63701`
- K-DUP auxiliary events: `5c6a68c6d947bc77672ae60b409133edf66501202a2e9f1b2e0e590d7ab825d2`
- K-SHAM auxiliary events: `c96ac027b6f346a2b17d333b79f80f7705786fa4460652d12bc10064e0c112c3`

The materialized Phase-A identity is:

`D:\\codex-runs\\jev-information-density-v08k\\phase-a-v01-clean\\`

Key receipts:

- [phase-a-receipt.json](D:\\codex-runs\\jev-information-density-v08k\\phase-a-v01-clean\\phase-a-receipt.json)
- [phase-a-lineage-audit.json](D:\\codex-runs\\jev-information-density-v08k\\phase-a-v01-clean\\phase-a-lineage-audit.json)
- [phase-a-triplet-audit.json](D:\\codex-runs\\jev-information-density-v08k\\phase-a-v01-clean\\phase-a-triplet-audit.json)
- [k-phase-a-seal-manifest.json](D:\\codex-runs\\jev-information-density-v08k\\phase-a-v01-clean\\seal\\k-phase-a-seal-manifest.json)
- [k-phase-a-seal-audit.json](D:\\codex-runs\\jev-information-density-v08k\\phase-a-v01-clean\\seal\\k-phase-a-seal-audit.json)

## Disposition

The independent local seal reports:

`PHASE_A_COMPLETE_NONPARENTABLE_PHASE_B_UNAUTHORIZED`

The local fallback was used after the requested Luna sealing attempts did not
produce seal artifacts. This is recorded in the seal audit; it is not reported
as a Luna PASS. No K artifact was modified after construction, and the seal
audit reports zero mismatches.

Phase B remains separately gated. No model load, feature extraction, training,
evaluation inference, LoRA/QLoRA, lambda search, or Phoenix access is
authorized by this Phase-A result.
