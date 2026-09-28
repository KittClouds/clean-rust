# FAS-R1 stage-zero seam inventory v0.1

Status: `SEALED_FOR_STAGE0_CONSTRUCTION`, 2026-09-25. This remains a read-only seam inventory snapshot, not a construction receipt. Amendment 01 authorizes Stage 0 construction only; the seal does not certify construction readiness or authorize model contact, training, or evaluation.

## Current authority and available anchors

| Surface | Live evidence | R1 treatment |
| --- | --- | --- |
| FAS-00 closure | Original-checkout provenance: `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\closure-v01\closure-record-v01.json` sets `SENSOR_FAIL_NO_SIGNAL`, `FAS00_ONLINE_MECHANISMS_AUTHORIZED=false`, and Phase 4/5 false. The failed held-out exact-target probe was `0.565406...` against `0.60`. | R1 is a new identity. The failed FAS final-layer global mean is a warning about sensing, not a verdict on R1's new per-constraint representation. Add an R1-specific qualification gate before controller training. |
| Shared model identity | Original-checkout provenance: `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\FAS-00-PROTOCOL.md` pins `LiquidAI/LFM2.5-1.2B-Base@7453bca97ca1e67754c4035a4b4c584e1c9dd725`. `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\phase2a-execution-v02\execution-plan-v02.json` expected a 2048-wide hidden layer. | Pin the same model family/revision in a new R1 manifest, then independently verify tokenizer, checkpoint files, hidden shape, and output bytes when model contact is authorized. Do not copy FAS cache rows. |
| Feature contract | Original-checkout provenance: `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\contracts\feature-contract-v01.json` encodes FAS observation/query prompts and global mean features. | R1 needs a new input and feature contract for each constraint and the whole task; FAS_FEATURE_V1 does not define this representation. |
| Existing generator/validator | Original-checkout provenance: `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\src\world.rs` and `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\src\validate.rs` show deterministic seed and independent-check patterns for another domain. | Reimplement R1's constraint grammar, exact solver, validator, solution counting, and symmetry group under the new identity. Treat FAS code as a design example only. |
| Existing arm/resource surfaces | Original-checkout provenance: `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\src\interface.rs` and `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\contracts\resource-accounting-contract-v01.json` are domain-specific. | Define R1 trace, proposal/value operation ledger, CPU/GPU time, memory, and merge accounting directly. |
| S05 replay | Original-checkout provenance: `C:\code land\clean-rust\experiments\fas-s05-crossed-representation-readout-decomposition-v01\S05-PROTOCOL.md` describes a fixed offline crossed replay over preexisting arrays/probes. | Its outcome and authority do not transfer to R1. |

At inventory time, the source checkout was on `codex/phoenix-native-cleanroom-cut3`, ahead of its remote by one commit, with broad unrelated dirty work; the FAS source and abandoned Bend trial were untracked there. This R1 packet is now held in the isolated worktree `C:\Users\shuga\.codex\worktrees\fas-r1-stage0-20260925\clean-rust`; the inventory-time branch note is not a current branch-status claim.
Use an isolated worktree or checkout for later R1 implementation, carrying only this R1 packet into it; keep the present dirty checkout intact.

## Detached locations

- Source identity: `experiments/fas-r1-semantic-particle-reachability-v00/` (this packet).
- Proposed later run root: `D:/codex-runs/fas-r1-semantic-particle-reachability-v00/`.
- Proposed later Cargo target: `D:/cargo-targets/fas-r1-semantic-particle-reachability-v00/`.
- Link/copy to `C:` for a test or distribution artifact only when the implementation phase requires it, following the user's `:G` build / `:C` link convention.

No run root or Cargo target is created by this paperwork step. Source, run, cache, and target identities must not alias FAS-00 or other experiments.

## Frozen packet decisions and later-stage gates

Amendment 01 freezes the value/selector split, hierarchical sensor gate, trace-prefix time estimands, and teacher name/telemetry. The executor directive freezes the Stage 0 task grammar and proposed defaults. Assignment-level raw/canonical merging remains an explicit heuristic while latent histories differ; strict full-state duplicate identity remains diagnostic.

Stage 0 must instantiate and account for the specified grammar, exhaustive tiny-world checks, merge/recycle behavior, complete trace replay, and operation timestamps using stub policies only. It must stop at `R1_CONSTRUCTION_READY` or a named construction failure. A successful construction receipt does not authorize feature extraction or model contact.

Before any protected evaluation, freeze the measured-time cutoff grid from development/runtime feasibility and record it in a versioned run manifest. The R1 feature/tokenizer/model hashes, exact render/encoding recipe, three-stage sensor qualification (including action relevance), and later model-contact/training/evaluation authority remain separate gates. FAS-00's closed sensor result cannot be borrowed or bypassed.

The solver may report exact solution-class coverage only for tasks with proven enumeration exhaustion; verify generation/solver throughput at `N=20` and exclude capped or timed-out counts from exact denominators. The “Interference Search” source remains optional; the implementation hypothesis does not depend on that attribution.

The design-packet seal is an engineering authorization state, not construction readiness or a scientific result. Any later model-contact and training/evaluation run needs its own bounded authority and manifests.
