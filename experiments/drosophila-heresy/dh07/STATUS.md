# DH-07 implementation status

Updated: 2026-09-15 (pre-seal qualification work)

## Current stage

Constructor-first implementation and qualification. No DH-07 seal exists and no measured seed has been run.

The frozen DH-06 directory and the parent-owned `supervision/dh07` files are read-only inputs. DH-07 is isolated in this directory and builds through the `target` junction to `D:\drosophila-heresy\dh07-target`.

## Frozen design decisions implemented

- Eight conditions: immediate, quiet, neither, parallel only, true perpendicular, null perpendicular, both true, and parallel plus null.
- The true endpoint preserves the DH-06 partial-update/clipping semantics.
- `P = W_T - W_B` is measured after the true endpoint is bounded.
- The null is constructed on the same active support, jointly orthogonal to the masked acquisition axis and realized true `P`, and norm-matched to `P`.
- The null target must be feasible without final clipping. Search is capped at 64 deterministic attempts and consumes no simulation RNG.
- Geometry is audited from committed `f32` weights converted to `f64`, rather than from the ideal scratch vector.
- A failed 64-attempt search means this declared constructor failed. It is not evidence that the constrained feasible set is empty.
- Rewards remain action-dependent. DH-07 pairs simulation RNG and exogenous schedules; it does not claim identical realized reward sequences after trajectories diverge.
- Provisional delivered-geometry tolerances are `5e-6` for relative L2 mismatch and both null cosines. These are not yet frozen by qualification.
- The true delivered intervention is also audited. A true-axis cosine above `5e-6` currently fails the strict “only off-axis direction differs” contract.

## Commands and results

`cargo test --release --offline`

- Cargo lock updated only for the package rename.
- 54 tests compiled and ran: 44 passed, 7 ignored, 3 failed.
- The null constructor's ordinary synthetic test passed committed-f32 L2 and joint-orthogonality gates.
- The bounded-cone test reached the new true-axis gate before its expected 64 bound rejections; the test expectation needs updating to isolate the intended constructor branch.
- Two DH-07 synthetic task tests failed before null search because the DH-06-compatible true endpoint leaked onto the acquisition axis:
  - reversal trial 6: support 45, bounds `(0,0)`, target L2 `0.1309040730`, true-axis cosine `-0.0019045772`.
  - reversal trial 3: support 41, bounds `(2,0)`, target L2 `0.1251421791`, true-axis cosine `-0.0352579706`.

These values are far above plausible committed-f32 roundoff. They are evidence that true endpoint clipping can violate the strict acquisition-orthogonal comparison even in synthetic fixtures.

## Next action

The declared non-measured real bundle (`seed=9000`, right slice, tau 4) was run once. It blocked at reversal event 1 in both null contexts:

- `null_perpendicular`: true delivered acquisition-axis cosine `-0.0008165776171753395`, above the `5e-6` gate; no candidate search and no weight commit.
- `parallel_null`: true-axis cosine `-4.72447759400283e-9`; all 64 candidates violated bounds; no weight commit.

Both true endpoints exactly matched DH-06 final weights, curves, and acquisition hashes. The full receipt is `qualification/constructor-first-real-seed9000.json`, SHA-256 `B0807C8BCF6A3A0595570AC7215890276A5E7A21A74F79D6AFEA6E265796CFAA`.

The independent replay in `../supervision/dh07/snapshot_audit.json` reproduced true norms/cosines within `1e-12` and all 64 bound failures. Every candidate had 175 to 228 violating coordinates; ideal null cosines stayed below `5.44e-18`.

## Final state

`BLOCKED_PRESEAL_QUALIFICATION`. No measured run, seal, analysis, or figure exists. The inherited DH-06 analysis and plotting scripts were removed. `scripts/seal_run.py` is now an explicit nonzero-exit guard.

Software verification after the receipt:

- `cargo test --release --locked --offline`: 48 passed, 0 failed, 8 ignored.
- `cargo clippy --release --locked --offline --all-targets -- -D warnings`: first pass failed on dead DH-06 compatibility code and a large error type; those test-only/layout issues were corrected. Parent independently reran the final check successfully after Sol stopped.
- Parent independently reran release tests: 48 passed, 0 failed, 8 ignored. Passing rejection tests verify fail-closed software behavior; they do not qualify the scientific control.
- Parent exercised the Python launcher guard: it refused sealing/execution and returned nonzero as required.

The prototype also omits reversal event index from the null counter key. This did not affect the first-event receipt, but it violates the intended full-run stream contract and is recorded rather than repaired after qualification.

Sol stopped at its usage limit after producing the prototype and scientific
qualification receipts. The parent completed final software checks and
packaging. No measured study was launched, and no new qualification training
was run by the parent.
