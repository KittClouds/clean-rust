# FAS-R1 stage-zero seam inventory v0.1

Status: `READ_ONLY_INVENTORY`, 2026-09-25. The observations below are a snapshot of the local checkout. No R1 code, build, model call, training, or evaluation was performed for this inventory.

## Current authority and available anchors

| Surface | Live evidence | R1 treatment |
| --- | --- | --- |
| FAS-00 closure | [Closure record](../fas-frozen-adaptive-substrate-v00/closure-v01/closure-record-v01.json) sets `SENSOR_FAIL_NO_SIGNAL`, `FAS00_ONLINE_MECHANISMS_AUTHORIZED=false`, and Phase 4/5 false. The failed held-out exact-target probe was `0.565406...` against `0.60`. | R1 is a new identity. The failed FAS final-layer global mean is a warning about sensing, not a verdict on R1's new per-constraint representation. Add an R1-specific qualification gate before controller training. |
| Shared model identity | [FAS protocol](../fas-frozen-adaptive-substrate-v00/FAS-00-PROTOCOL.md) pins `LiquidAI/LFM2.5-1.2B-Base@7453bca97ca1e67754c4035a4b4c584e1c9dd725`. [Execution plan](../fas-frozen-adaptive-substrate-v00/phase2a-execution-v02/execution-plan-v02.json) expected a 2048-wide hidden layer. | Pin the same model family/revision in a new R1 manifest, then independently verify tokenizer, checkpoint files, hidden shape, and output bytes when model contact is authorized. Do not copy FAS cache rows. |
| Feature contract | [FAS feature contract](../fas-frozen-adaptive-substrate-v00/contracts/feature-contract-v01.json) encodes FAS observation/query prompts and global mean features. | R1 needs a new input and feature contract for each constraint and the whole task; FAS_FEATURE_V1 does not define this representation. |
| Existing generator/validator | [FAS world generator](../fas-frozen-adaptive-substrate-v00/src/world.rs) and [validator](../fas-frozen-adaptive-substrate-v00/src/validate.rs) show deterministic seed and independent-check patterns for another domain. | Reimplement R1's constraint grammar, exact solver, validator, solution counting, and symmetry group under the new identity. Treat FAS code as a design example only. |
| Existing arm/resource surfaces | [FAS interfaces](../fas-frozen-adaptive-substrate-v00/src/interface.rs) and [resource contract](../fas-frozen-adaptive-substrate-v00/contracts/resource-accounting-contract-v01.json) are domain-specific. | Define R1 trace, proposal/value operation ledger, CPU/GPU time, memory, and merge accounting directly. |
| S05 replay | [S05 protocol](../fas-s05-crossed-representation-readout-decomposition-v01/S05-PROTOCOL.md) describes a fixed offline crossed replay over preexisting arrays/probes. | Its outcome and authority do not transfer to R1. |

The checkout is on `codex/phoenix-native-cleanroom-cut3`, ahead of its remote by one commit, with broad unrelated dirty work. The FAS source and abandoned Bend trial are untracked here. This packet occupies a new path and leaves those surfaces untouched.
Use an isolated worktree or checkout for later R1 implementation, carrying only this R1 packet into it; keep the present dirty checkout intact.

## Detached locations

- Source identity: `experiments/fas-r1-semantic-particle-reachability-v00/` (this packet).
- Proposed later run root: `D:/codex-runs/fas-r1-semantic-particle-reachability-v00/`.
- Proposed later Cargo target: `D:/cargo-targets/fas-r1-semantic-particle-reachability-v00/`.
- Link/copy to `C:` for a test or distribution artifact only when the implementation phase requires it, following the user's `:G` build / `:C` link convention.

No run root or Cargo target is created by this paperwork step. Source, run, cache, and target identities must not alias FAS-00 or other experiments.

## Unresolved before construction is sealed

1. Freeze a legal typed-constraint grammar, exact task-isomorphism split, solution-count acceptance limit, and solver timeout policy. Proposed values are in the directive.
2. Decide whether assignment-level merging is the desired intervention while latent histories differ. The packet labels it honestly as a heuristic; a full dynamic-state duplicate diagnostic is required.
3. Freeze the main outcome cell, practical margin, seed count, and the definition of matched compute before protected evaluation.
4. Pin the exact R1 constraint/global render and feature extraction recipe, including model/tokenizer hashes, representation precision, and deterministic repeat rule before model contact.
5. Establish a separate R1 sensor qualification. FAS-00's closed sensor gate cannot be borrowed or silently bypassed.
6. Verify exact solver/model-enumeration throughput at `N=20` and reject unknown counts from exact solution-coverage denominators.
7. Identify the “Interference Search” source if a literature-specific claim is desired; the implementation hypothesis does not depend on that attribution.

Construction readiness, a seal, and a solver fixture are engineering states. A later model-contact and training/evaluation run needs its own bounded authority and manifests.
