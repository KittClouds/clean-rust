# E012 bank amendment A04 — task construction and condition accounting

**State:** frozen before scored task fixtures. **Model contact remains prohibited.**

This amendment resolves the effective v0.3 condition matrix into concrete source-to-frame rules, states the scope of the executable tasks, and fixes the frame count before construction.

## Task scope

The 48 tasks are isolated Rust consumer-code integration tasks built against the three pinned library snapshots (`bytes`, `clap`, and `serde_json`). Candidate patches modify only the task-owned adapter/test overlay; they do not modify upstream library source. The bank may support claims about these bounded executable workflows, not about repairing the upstream libraries or broad repository-level coding competence. Each candidate is checked in a clean overlay against the frozen dependency snapshot and a task-specific executable contract.

For `bounded-prefix-copy`, the executable contract is narrowed to the **bounded zero-copy prefix view** implied by the borrowed `Bytes` API. The scored check verifies both returned prefix bytes and shared backing storage. The previously feasible `copy_prefix` implementation remains in the candidate set but does not satisfy this task contract; the value-only feasibility run remains unchanged and is not relabeled.

## Effective cells and frame count

The v0.3 lock and protocol amendment A03 define six valid sufficiency cells and four diagnostic-only cells. The four diagnostic cells are `E_t`, `E_x`, `E_r`, and `E_t+E_x`; they are distinct from the valid cells. Add `identity_only_diagnostic`: all truth-bearing channel content is replaced by its typed absent sentinel while the stable candidate identity envelope (`E_c.identity`) remains present. This cell is an input-leakage diagnostic; it is not a sufficiency claim.

The sufficiency and other content-presence cells comprise 10 truth-channel masks. The extra `identity_only_diagnostic` is the all-content-absent mask with the identity envelope retained, so it is counted as its own condition. Each of the 48 tasks receives:

1. one full frame;
2. four leave-one-channel-out frames;
3. ten single/pair/triple diagnostic or sufficiency frames;
4. four one-channel noninformative-control frames;
5. four one-channel isomorphic-swap frames;
6. two candidate-coordinate frames (balanced control and eligible donor schedule).

Total: **26 conditions × 48 tasks = 1,248 frames**. `E_p` has no absent condition. Conditions that are ineligible for a task's declared donor structure are recorded `NOT_APPLICABLE` before generation and are not replaced post hoc; the locked 48-task bank is designed so all four truth-channel donors and both coordinate schedules are eligible.

Each request, execution, joint, or context task receives one case-specific check per candidate (8 families × 4 tasks × 4 candidates = 128 task-candidate rows). Each task in the two candidate-action families receives a four-case contract suite per candidate (2 × 4 × 4 = 32 task-candidate rows, 128 case invocations). Each abstention-positive task receives the full four-case contract suite per candidate (2 × 4 × 4 = 32 task-candidate rows, 128 case invocations). Totals: **192 task-candidate rows and 384 isolated case invocations**. Base checks total **48 task rows and 96 case invocations** under the same schedule: 32 case-specific rows plus 16 full-suite rows. A compiler failure is a construction failure, not an incorrect-action label.

## Projection and authority

Use the frozen `rdc-real-coding-observation.v1` frame shape and E009 v5 prompt/output contract. Keep `E_c.identity` (opaque action IDs, option count, schema, and patch identity) in every condition. `E_c.content` alone is projected to authentic candidate content, a fixed absent sentinel, a matched-size noninformative payload, or the preregistered donor content. `E_t`, `E_x`, and `E_r` use the corresponding frozen channel slots and sentinels. No condition label, donor ID, truth-support set, task label, candidate role, candidate test result, or completion label is observer-visible.

The E011 producer-order runtime is copied byte-for-byte for Rust sources/tests and receives only a path-adjusted Cargo manifest so it resolves the same E001/E002/E009/runtime-contract dependencies from this deeper E012 directory. The same presentation and deterministic authority code handles every condition. Each condition gets its own task digest, ordered presentation receipt, and replay record. No model call is permitted by this amendment.

## Joint evidence projections

Execution logs remain sealed. The frame projector exposes only the predeclared typed factor for joint tasks, never the raw numeric assertion that could reveal both factors. For `bytes/composite-frame-field`, `E_t` is the requested target (`header` or `payload`) and `E_x` is the observed byte order (`big` or `little`). For `serde_json/number-mode-plus-error-site`, `E_t` is requested number mode (`whole` or `ratio`) and `E_x` is failing path (`/header` or `/payload`). Each factor alone leaves two offered actions; their combination resolves the candidate role. This projection rule is checked mechanically against all four factorial cells.

## Preservation

The v0.3 protocol, v1.3 bank design lock, prior feasibility failures, selected feasibility inputs, source snapshots, and E011 integration source remain immutable. Any construction defect is repaired in a numbered sibling attempt and included in a new manifest; no observer outputs may select, repair, or exclude bank items.
