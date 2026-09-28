# E012 Closeout — Sealed Failure Preserved

**Disposition:** `SEALED_FAILURE_PRESERVED`  
**Run:** `e012-20260926-frame-decomposition-01`  
**Source run location:** `C:\rd-c\selective-cognition-action-region-program\experiment-012\artifacts\runs\e012-20260926-frame-decomposition-01`  
**Closeout location:** this separate addendum; no files in the E012 run were changed.

## Finding

E012 did not establish that the small observer is incapable. It showed that the frozen v5 self-reported acceptance contract did not identify a safe direct-action region on this bank. Small and large observers both made wrong accepted choices, while the authority, presentation binding, replay, and duplicate-effect checks remained clean.

| Lane | Accepted actions | Correct | Wrong accepted | Completion |
|---|---:|---:|---:|---:|
| Small | 16 | 6 | 10 | 6/48 |
| Large | 33 | 23 | 10 | 23/48 |
| Hybrid | 39 | 22 | 17 | 22/48 |

All accepted small responses reported applicability `1000` and abstention `0`. The hybrid completed one fewer task than large-only because a false small acceptance suppressed escalation. This supports the routing-cost asymmetry `false accept > false abstain` for this workflow.

Authority/replay records remained clean: no illegal commits, no replay mismatches, and no duplicate action effects. This is not evidence of semantic correctness; the authority contract validates well-formed, bound, permitted actions.

## Read-only anatomy disposition

The six E012 diagnostics are in `E012-READONLY-ANATOMY-v1.md` and `.json`, sealed by `E012-READONLY-ANATOMY-SEAL-v1.json`.

Notable descriptive results:

- Candidate-selection tasks: `40`; pure-abstention tasks: `8`.
- Uniform random selection among offered candidates has expected precision `27.5%` over the 40 candidate tasks. On the exact 16 small-accepted tasks, the expected correct count is `3.5/16`; small achieved `6/16`. The uniform-choice reference tail for at least six is `0.112`, so this small bank does not make that difference decisive.
- Among 24 fixed-candidate-order contrasts where the valid patch changed, small selected both variants correctly in `1`; large did so in `10`. Small had one or both proposals absent in 15 contrasts; large had proposals in all 24.
- Small and large wrong-accept sets overlap on `3` tasks; each has `7` additional wrong-accept tasks not shared by the other.

These are descriptive anatomy results only. They do not authorize a subgroup, threshold, or capability claim.

## Boundary

E012 stays immutable. No fitting, threshold search, subgroup authorization, frame intervention, or new model contact is derived from this closeout. The next defined program is E013 trust-signal development, with a fresh development bank and a separate untouched confirmation bank.
