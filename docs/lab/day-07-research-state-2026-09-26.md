# Day 7 Research State

**Snapshot:** 2026-09-26 12:15 UTC. This is the next dated checkpoint after the immutable [Day 6 state](day-06-research-state-2026-09-25.md). It preserves that starting line and adds today’s observer-bundle engineering result. Cross-lab states below are carried forward from Day 6 or the user's current queue unless explicitly marked as freshly audited today.

## Starting line and program direction

- **FAS observer science:** S08–S10 geometry was exploratory on the earlier population; S11 supplied fresh-world transport confirmation. The proposed S12 equal-energy random-plane intervention remains a separate causal question.
- **JEV:** Q-R1's 12-seed result rejected half-weight as a reliable gain/locality control; the common-history late-dose branch remains proposed.
- **R&D-C:** E001 established the deterministic authority base; E010 found a bounded fast-action region on two repositories; E011-R2 did not establish candidate-order robustness.
- **Observer-bundle engineering:** the starting hypothesis is the S01-motivated pattern `frozen LFM representation + narrow independent observers`. The historical S01 results motivate this branch only. This run neither fine-tuned LFM nor revalidated S01 performance.
- **Program ladder from the current user direction:** prove known narrow capabilities → route them safely → prospect for unknown capabilities. Keep FAS, JEV, R&D-C, F4/Fly, and R1 scientifically separate; shared receipts and execution infrastructure do not merge their claims.

## Current frontier: frozen observer bundle

| Coordinate | Current evidence |
|---|---|
| Strongest claim | A single pinned `LFM2.5-1.2B-Base` `V1_FINAL_POSITION` cache supports five separately fitted linear observers. E3 v02 completed with 147,528 trainable parameters (590,112 bytes) plus 81,920 scaler bytes, for 672,032 bytes total observer/scaler state. Independent audit passed. |
| Input substrate | Pinned `LiquidAI/LFM2.5-1.2B-Base@7453bca97ca1e67754c4035a4b4c584e1c9dd725`. E0 v10 root `899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd`; E1 v04 root `6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03`; E2 v07 root `a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a`. |
| Cache identity | 106,496 × 2,048 little-endian float32 values; 872,415,232 bytes (832 MiB); SHA-256 `8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4`. E2 v07 matched the preserved v01 comparator byte-for-byte. |
| Five fit tasks | Context identity (32 classes, 85,204 FIT rows); entity identity (32, 85,204); relation (2, 21,188); observed state (3, 21,188); exact target (3, 21,188). Each head has its own parameters and scaler. |
| Resource receipt | E2 extraction took 3,402.17 s; E3 fitting took 19.47 s. E2 PyTorch CUDA caching-allocator reserved peak: 4,710,203,392 bytes. E3 v02 process reserved peak: 2,113,929,216 bytes; allocated peak: 1,938,966,528 bytes. These are process-scoped allocator readings, not total device VRAM claims. E3 v02 disk preflight recorded 742,069,653,504 free bytes on D: before fit against the frozen 1 GiB minimum. E2 runtime: Python 3.13.15, PyTorch 2.11.0+cu128, Transformers 5.17.0, CUDA runtime 12.8. |
| Explicitly not established | Held-out accuracy, the eight per-task performance gates, bundle parity, serving latency/cost, measured savings against repeated-backbone baselines, integration value, scale behavior, or broad capability accessibility. No evaluation labels or held-out rows were opened; no scoring occurred. Training objectives are optimizer diagnostics, not performance evidence. |
| Next boundary | E3 scoring remains closed. Any held-out evaluation requires a separately versioned, reviewed authorization bound to these roots and gates. E4 integration, shared heads, view search, and scale comparisons remain closed. |

### Engineering history worth retaining

1. E0 v07/v08 audit attempts were preserved after newline-digest and missing wait-receipt defects. E0 v09 audited, but its preflight falsely matched its own PowerShell query. E0 v10 corrected the process identity check and independently passed all 21 checks.
2. E2 v02/v03 stopped before model contact on contract-literal/schema assumptions. These were verifier compatibility failures, not model or science failures. The completed S12 contention wait was recorded before E2 contact.
3. E2 v07 passed the pinned preflight, repeatability, cache integrity, process-scoped GPU, and byte-equivalence gates. E2 audit confirmed the exact cache above.
4. E3 v01 produced five fit artifacts, then source review found that its contract declared a disk-space minimum that the fitter had not measured. The v01 artifacts remain preserved but are **not resource-qualified**; disposition SHA-256 `0654bf91f22928ca0395c58b7fdbd6731dfdd1648ae6a034ada1f7575bc6e68e` records this gap.
5. E3 v02 kept the same data, tasks, model, optimizer, and no-scoring boundary; it added a pre-output filesystem check and receipt. Six tests passed. Independent audit passed all 14 checks and sealed 64 artifacts at root `899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1`.

**Observer artifacts:** [E3 v02 contract](../experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e3-fit-v02.json) · [authorization](../experiments/fas-frozen-observer-bundle-engineering-v01/audits/e3-fit-authorization-v02.json) · [v01 resource disposition](../experiments/fas-frozen-observer-bundle-engineering-v01/audits/e3-v01-resource-gate-disposition-v01.json). Contract SHA-256 `cd76401226b7335ae03567c8fbf7579a6f3212ba55e71edf04e2565ce053076e`; authorization SHA-256 `9748158dbd089c95bc34bbc7ce645c6878723f0ef0fcefd5982de96f7c22e228`. Run artifacts are under `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02`; the seal manifest SHA-256 is `b8dce8dc7ff2d1a1739619f1ed00444d970ccc46872bb1acca2f1e07bf31a485`, the independent audit SHA-256 is `a0950baf5aa64f77b9789a6fcb64a7c3afd2c3c03dea87d66c76a47049ab6cbe`, and the deploy-shaped training-only manifest SHA-256 is `8fa86f8c9891949196844ca62522822a246e47b4185cc4ed45c45136ada6576f`.

## Other labs and current queue

The following are carry-forward states, not new audits in this checkpoint:

- **FAS S11 / S12:** S11 remains the bounded fresh-world observer-transport result; no S12 authorization is recorded. The separate FAS-00 disposition remains `SENSOR_FAIL_NO_SIGNAL`. FAS-R1 remains a distinct construction lineage and inherits no FAS-00 cache, authority, or model-contact permission.
- **JEV Q-R1:** the fixed half-dose did not meet its registered repeatability threshold. The common-history step-80 comparison remains a proposal until separately frozen and authorized.
- **R&D-C:** E010's direct-action region is repository- and task-bank-bounded. E011-R2 is evidence against the tested candidate-order robustness claim; it is not a new general capability claim.
- **F4/Fly and R1:** continue their own bounded questions and gates; do not force a merge with the observer bundle. Their detailed current states should be read from their own sealed histories.
- **Priority order:** finish the observer-bundle authorization boundary; then routing integration; then frozen universal capability cartography. R1 should run only after its own pre-model gates and GPU lane are ready. Scale comes later, after the current bundle earns its performance result.

## Questions answered so far

1. **Can this pinned substrate produce one byte-stable feature cache under the frozen ABI?** Yes; E2 v07 matched its preserved comparator exactly.
2. **Can the cache feed five independent, small linear observers in one engineering run?** Yes; E3 v02 constructed and audited their training artifacts and resource receipts.
3. **Are the five observers useful on held-out cases, mutually equivalent to standalone heads, or cheaper in serving?** Still unknown. Those questions were not scored or measured here.

**Storage snapshot:** At capture, C: had 355,667,570,688 bytes free and D: had 742,067,978,240 bytes free. E2's cache is 832 MiB; E3's five parameter sets and scalers total 672,032 bytes, with one shared immutable cache. These numbers describe the named artifacts and current free-space readings, not all lab/model-cache storage.

**For all agents:** Keep this file as the Day 7 snapshot. Use [Day 6](day-06-research-state-2026-09-25.md) as the prior baseline, keep failed and unqualified attempts in the ledger, and distinguish `executed`, `authorized`, `proposed`, `audited`, and `scientifically established`. Do not open evaluation labels or infer bundle performance from fit artifacts.
