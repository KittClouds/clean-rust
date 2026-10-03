# Ratification record — BANK-v2 constitution v0.7 (2026-09-30)

Kept outside the sealed files on purpose: changing `BANK-V2-FREEZE.md` or `bank-v2-objects.json` would change the seal hash.

**Ratified by the program owner (ruling of 2026-09-30):**

- The eleven builder-forced amendments that were provisional are **ratified, not reopened**: F1–F5 (v0.6) and G1–G6 (v0.7). They are the class of semantic-coherence correction the amendment mechanism exists for: reason nullability, unreachable reasons, `OUT_OF_SCOPE` ordering, the G17 witness mismatch, closed-slot hiding semantics, the `WAIT` coverage impossibility, the target of a transitive requirement, the `prohibited_edge` obligation source, the report/conflict/uncertainty definitions, observation sufficiency, and step-1a worlds. The `WAIT` exemption in particular is exact: the action is precondition-free by definition, so an illegal `WAIT` is semantically impossible, not merely rare.
- **No rerun to thicken thin cells.** `prohibited_edge` requirements (0.6% of rows) and `TRANSFER` (the thinnest action) are represented and pass their coverage gates. If a later experiment needs more power in either cell, it gets a **targeted supplemental panel** under its own declared identity; the 800,000-row bank is not regenerated for symmetry.
- The G10 episode stands as the intended behavior of a sealed instrument: 46 of 120,000 pairs failed, the row corpus was untouched, only the paired panels were regenerated, and the seal verified the row-stage source hashes before accepting the repair.
- **C-G1b stays separate.** BANK-v2 is not a confirmation split for C-G1b. C-G1b is a post-hoc derated candidate found on BANK-v1's graph distribution; its confirmation needs a fresh sealed sample from that generating regime. BANK-v2 is a later, independent generalization challenge: passing native confirmation and then surviving v2 is interesting; failing on v2 marks an applicability boundary and does not retroactively invalidate the v1 result.

**Standing consequence:** no model touches BANK-v2 until the V2-0 evaluation constitution (`../ff-s15-v2-eval-00/V2-0-CONSTITUTION.md`) is frozen, and nothing in V2-0 opens escrowed test truth.
