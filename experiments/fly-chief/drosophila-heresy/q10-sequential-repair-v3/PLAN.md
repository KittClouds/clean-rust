# Q10-SR3: Capacity-Gated Sequential-f32 Repair Qualification

Status: `FROZEN_PRE_EXECUTION__NOT_EXECUTED`

Q10-SR3 is a fresh engineering-only identity after Q10-SR v1's performance
abort and Q10-SR2's independent-review arithmetic failure. It preserves the
capacity-gated sparse repair implementation and fixes one reviewer detail:
Python emulation of Rust `Iterator::sum::<f32>()` begins with `-0.0`, including
empty rows. Seed 9511 is spent and may not be reused.

The qualification asks whether safety-margined Q10-SM alternate endpoints can
be diagnosed and, only when the local one-ULP effect dictionary has exact
relaxed capacity, repaired to the endogenous endpoint's authoritative
sequential binary32 cue-by-MBON readout.

## Lineage and firewall

Q08, Q09, Q10-BG, Q10-SM, Q10-SR v1, Q10-SR2, Q10-RC v1, and Q10-RC2 remain
immutable. Q10-SR2 completed producer receipts are preserved as an invalid
predecessor audit; its reviewer did not validate them. The parent Q10-SM
identities are:

| File | SHA-256 |
| --- | --- |
| `PLAN.md` | `8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D` |
| `CONTRACT.json` | `5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF` |
| `RESULT.md` | `68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337` |
| `STATUS.json` | `D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4` |

No scientific seeds, actions, rewards, behavior, measured CLI, or DH-08B are
allowed. The ignored real-anatomy profiler writes no qualification receipt.

## Fresh engineering tranche

Stage 1A uses fresh seed `9521` and exactly 1,024 events. Stage 1B uses fresh
seeds `9522..9525` and adds exactly 4,096 events, for 5,120 cumulative
events. Both sides `R/L` and taus `4/16` are required, with 256 events per
side/tau block. No top-up, replacement seed, or same-identity resume is
allowed. Stage 1B requires independent review of Stage 1A without changing
this source, contract, reviewer, arithmetic, or output schema.

## Capacity gate

Every parent-eligible event receives the authoritative sequential-f32 mismatch
and legal one-ULP bank diagnostics. Relaxed capacity uses deterministic f64
SVD with cutoff
`sigma_max * max(rows, columns) * f64::EPSILON * 1000` and normalized
projection tolerance `2e-10`.

Only initially mismatched events with `CAPACITY_EXACT_WITHIN_TOLERANCE` enter
discrete search. Partial, empty, or ambiguous capacity receives a complete
receipt and skips search. This is a denominator rule, not a claim that
nonlinear multi-move repair is impossible.

## Sparse exact search

The beam state stores sorted sparse coordinate entries containing coordinate,
relative ULP displacement, and exact committed f32 bits. The immutable initial
weight vector is shared by the search. Readout remains a full vector. Every
candidate's affected rows are replayed in the learner's canonical order using
binary32 arithmetic. Candidate ranking preserves the frozen lexicographic
objective, branch/beam tie rules, inverse-move rule, reserve, coordinate and
depth budgets, and final simultaneous gates. Full weights are materialized only
for an exact-readout returned state.

A bounded top-error cache replaces per-candidate full-readout sorting; a
fallback scan is used when a synthetic coordinate affects 64 or more rows.
Coordinates absent from every authoritative row are removed as proven dead
states. The final reviewer independently reconstructs target and final
readouts from committed bytes, including signed zero and empty-row behavior.

## Valid interpretation

Valid protocol statuses are:

- `Q10_SR3_STAGE2A_VALID__REPAIR_FOUND`
- `Q10_SR3_STAGE2A_VALID__NO_REPAIR_WITHIN_FROZEN_SEARCH`
- `Q10_SR3_STAGE2A_VALID__READOUTS_ALREADY_EQUAL`
- `Q10_SR3_STAGE2A_VALID__CAPACITY_GATED_MIXTURE`
- `Q10_SR3_STAGE2A_NUMERICALLY_AMBIGUOUS`
- `Q10_SR3_STAGE2A_INVALID`

No status establishes repair impossibility, endpoint exchangeability,
meaningful direction, a behavior effect, a future-learning effect, hidden
learning state, or metaplasticity. A valid result remains engineering-only.

Before Stage 1A, the target-D executable, source manifest, reviewer identity,
contract/plan hashes, arithmetic rules, observer purity, RNG nonconsumption,
determinism, support/boundary/reserve gates, and independent replay schema
must be sealed. Any later change requires a new identity and fresh seeds.
