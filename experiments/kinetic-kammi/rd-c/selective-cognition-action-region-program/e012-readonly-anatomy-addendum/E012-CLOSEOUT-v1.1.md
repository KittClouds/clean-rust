# E012 Closeout — Review-Corrected Addendum v1.1

**E012 disposition:** `SEALED_FAILURE_PRESERVED`  
**E012 run:** `e012-20260926-frame-decomposition-01`  
**Scope:** corrected descriptive anatomy and prospective control design only. The E012 run remains byte-identical.

## Synthesis

E012 primarily falsified portability of the v5 self-reported acceptance rectangle as a trust instrument on this bank. It did not show that the small observer lacks all useful capability. Both observers produced wrong accepted actions; the runtime's presentation binding, deterministic authority, replay, and duplicate-effect prevention remained healthy.

- Small: 16 accepted, 6 correct, 10 wrong accepted; 6/48 completed.
- Large: 33 accepted, 23 correct, 10 wrong accepted; 23/48 completed.
- Hybrid: 22/48 completed, with 17 wrong accepted actions; one fewer completion than large-only because false small acceptance suppressed fallback.
- Every accepted small response self-reported applicability `1000`, abstention `0`.
- Small/large wrong-accept sets overlap on 3 tasks; each has 7 wrong-accept tasks not shared by the other.

The external anatomy found 40 candidate-selection tasks and 8 pure-abstention tasks. Uniform candidate choice expects 11/40 correct overall. On the exact 16 small-accepted tasks it expects 3.5 correct; small produced 6. The exact independent-uniform reference tail for at least six is 0.112, so this bank gives only a descriptive lead, not a persuasive above-chance result.

On 24 fixed-candidate-sequence contrasts with changed valid patch sets, small produced both variants correctly in 1 contrast and large in 10. The review-corrected report distinguishes **raw choice absent** from **runtime did not accept**; those are different states and must not be called the same kind of abstention.

## Preserved artifacts

- Original reviewed v1 anatomy, its source manifest and its seal remain unchanged as the first addendum version.
- Corrected v1.1 anatomy is in `E012-READONLY-ANATOMY-v1.1.md/.json`, using a separate v1.1 analyzer and seal.
- E012 original source tree was checked against its 498-file SHA-256 manifest and matched exactly.
- Positive control is versioned separately and remains unrun.

## Boundary

No E012 fitting, threshold search, subgroup authorization, frame intervention, model contact, or E014 work. E013 remains protocol-only and unauthorized for model contact.
