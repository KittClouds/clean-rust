# Q10-SR2: Capacity-Gated Sequential-f32 Repair Qualification

Status: `FROZEN_PRE_EXECUTION__NOT_EXECUTED`

Q10-SR2 is a new engineering-only identity after Q10-SR v1's frozen
full-vector beam exceeded its 40-minute first-block performance window. It
does not reopen v1, spend seed 9501 again, or authorize behavior, science, or
DH-08B.

The question is whether a safety-margined Q10-SM alternate endpoint can be
diagnosed and, when its local one-ULP effect dictionary has exact relaxed
capacity, repaired to the endogenous endpoint's authoritative sequential
binary32 cue-by-MBON readout.

The diagnostic is staged:

1. Reconstruct the Q10-SM endpoint and authoritative mismatch.
2. Build the legal one-ULP bank and run the frozen relaxed capacity analysis.
3. Enter discrete repair only for mismatched events with
   `CAPACITY_EXACT_WITHIN_TOLERANCE`.

Capacity-partial, empty-bank, or numerically ambiguous events receive complete
diagnostic receipts and a fail-closed `CAPACITY_GATE_SKIPPED` repair status.
They are not counted as repaired or as search failures. The protocol makes no
claim about nonlinear multi-move repairability for those events.

The discrete search preserves Q10-SR v1's objective order, legal moves,
reserve, beam, branch, depth, coordinate-spend, inverse-move, RNG, and final
gate semantics. The state representation changes only implementation detail:
beam states store sorted sparse coordinate deltas and committed bits rather
than cloning the full weight vector. The authoritative sequential readout is
still recomputed in production order for every candidate. Candidate objective
evaluation uses a bounded top-error cache instead of allocating and sorting
the full readout for every successor; a wide-incidence fallback scans exactly.
Coordinates absent from all authoritative rows are removed as proven dead
states because they can never affect the objective or final readout.

## Frozen lineage

The parent is the completed Q10-SM qualification:

| File | SHA-256 |
| --- | --- |
| `PLAN.md` | `8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D` |
| `CONTRACT.json` | `5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF` |
| `RESULT.md` | `68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337` |
| `STATUS.json` | `D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4` |

Q08, Q09, Q10-BG, Q10-SM, Q10-SR v1, Q10-RC v1, and Q10-RC2 are immutable
lineage. Q10-SR v1's performance-abort receipt is evidence for this redesign,
not a result to be pooled with it.

## Qualification tranche

Fresh engineering seeds are `9511..9515`. Stage 1A uses seed `9511` and
exactly 1,024 events. Stage 1B uses `9512..9515` and adds exactly 4,096
events, for 5,120 cumulative events. Sides are `R` and `L`; taus are `4` and
`16`; each side/tau contributes 256 events. No replacement seed, top-up,
scientific seed, measured CLI, behavior, reward inference, or DH-08B is
allowed.

The first real-anatomy engineering run is forbidden until the source,
executable, reviewer, output schema, and this plan/contract are sealed.
Ignored single-event profiling remains a diagnostic test and writes no
qualification receipt.

## Required outputs and interpretation

Every configured event receives a parent status. Every parent-eligible event
receives mismatch and capacity diagnostics. Mismatched capacity-exact events
also receive bank, search, and final-gate diagnostics. The aggregate reports
separate denominators for configured, parent-eligible, initially equal,
initially mismatched, capacity-exact, capacity-gated, search-entered, and
repair-valid events.

The only valid protocol outcomes are engineering diagnostics:

- `Q10_SR2_STAGE2A_VALID__REPAIR_FOUND`
- `Q10_SR2_STAGE2A_VALID__NO_REPAIR_WITHIN_FROZEN_SEARCH`
- `Q10_SR2_STAGE2A_VALID__READOUTS_ALREADY_EQUAL`
- `Q10_SR2_STAGE2A_VALID__CAPACITY_GATED_MIXTURE`
- `Q10_SR2_STAGE2A_NUMERICALLY_AMBIGUOUS`
- `Q10_SR2_STAGE2A_INVALID`

No valid outcome establishes exchangeability, meaningful direction, a
behavior effect, a future-learning effect, hidden learning state, or
metaplasticity. A successful repair remains only a committed-readout
engineering result until a separately authorized study tests the downstream
learner.

## Performance and integrity gates

Before Stage 1A, tests must cover sparse-state equivalence to the frozen
objective on synthetic operators, exact committed-byte tie ordering, dead
coordinate pruning, observer purity, RNG nonconsumption, finite values,
determinism, support and boundary preservation, final reserve, and the
independent replay script. The pre-execution seal must record source manifest,
target-D executable hash, parent hashes, arithmetic identity, capacity policy,
search envelope, and the capacity-gate rule.

Any change to endpoint reconstruction, sequential arithmetic, capacity
factorization, gate semantics, sparse-state objective, seeds, budgets,
tolerances, receipt schema, or reviewer after Stage 1A requires a new identity
and fresh engineering seeds. Stage 1B may begin only after independent review
of Stage 1A passes without such a change.
