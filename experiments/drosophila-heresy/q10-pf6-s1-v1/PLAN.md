# Q10-PF6-S1: Oversize Distributed Beam Multi-Group Qualification

Q10-PF6-S1 is an engineering-only qualification of the sealed Q10-PF6
constructor across 84 PF5 oversized raw-support groups. It does not modify
PF5 or PF6, apply a repair, update a canonical endpoint, load scientific
seeds, expose behavior, or authorize DH08B.

The question is descriptive: across a balanced sample of oversized groups,
does the frozen PF6 beam produce exact-f32 candidate endpoints, and does the
search appear limited by its coordinate horizon, replay budget, target
alignment, or final geometry gates? Bounded failure is never an infeasibility
claim.

## Frozen parent and population

Before sampling, revalidate the sealed PF5 audit and PF6 contract. The PF5
population is exactly 1,457 groups classified `OVERSIZE_UNTESTED`, from 28
primary endpoints. Exclude PF5 partial-feasibility groups, complete-domain
blocked groups, non-primary/probe groups, malformed groups, and the existing
PF6 one-group implementation slice. If any parent hash, count, or runtime
helper hash differs, stop with
`Q10_PF6_S1_INVALID__PARENT_LINEAGE_MISMATCH`.

## Frozen sampling rule

Select exactly three eligible oversized groups from each of the 28 endpoints.
The sample therefore contains exactly 84 unique groups. If any endpoint has
fewer than three eligible groups, fail closed; do not substitute from another
endpoint.

Within each endpoint, compute only PF5 baseline metadata:

* coordinate count `C_G`;
* mismatched-row count `R_G`;
* residual mass `E_G = sum(e_j^2 for j in M_G)`;
* raw-row bridge count available in the sealed PF5 receipt;
* threshold-gated fraction when already present in the receipt.

Choose the groups closest to the endpoint's lower quartile, median, and upper
quartile of coordinate count. Ties are broken by greater `E_G`, greater
`R_G`, greater bridge count, then stable group identity hash. The selection
is computed before any PF6 replay and is immutable once written to
`PREEXECUTION.json`.

## Frozen PF6 execution

The following are inherited without tuning:

* exploit width 24;
* exploration width 8;
* beam width 32;
* coordinate horizon 16;
* replay cap 32,768 candidates per group;
* PF6 target-aware coordinate ranking;
* exact learner-order sequential binary32 replay;
* PF5 intermediate geometry guardrails;
* inherited DA2 final geometry gates;
* stable tie-breaking and prefix vocabulary.

Every beam state is a complete legal endpoint. Visited coordinates receive one
legal prefix choice; unvisited coordinates remain at legal zero. A zero choice
actually considered by expansion is `tested_zero`. A coordinate beyond the
horizon is `unselected_zero_by_horizon`, and is never described as ineffective
or lacking authority.

The objective is the sealed lexicographic objective: bitwise mismatch count,
total row ULP distance, f64 residual L2, and maximum absolute residual.
Intermediate states may be nonmonotonic but must obey PF5 exploration
guardrails. Only the final independently reconstructed f32 candidate faces
the final geometry gates.

## Required receipts

`PREEXECUTION.json` must contain the parent hashes, current PF5 runtime-helper
hash, all 1,457 eligible identities, all 84 selected identities, endpoint and
stratum for each selection, baseline metadata, frozen PF6 configuration,
stable-hash identity, source manifest, and execution timestamp. No candidate
replay begins before this receipt is sealed.

For each group, preserve round diagnostics for every round 0 through 16:

* best search state and best final-gate-valid state separately;
* mismatch count, total ULP distance, residual L2, and max residual;
* axis, norm, and cue-linear geometry debt;
* active nonzero-coordinate count;
* selected, tested-zero, and unselected coordinate ids;
* replay count for the round and cumulative replay count;
* exploit/exploration survivors;
* intermediate-guard and bounds/reserve rejection counts;
* unique beam-state count and stable best-state hash;
* descriptive residual improvement `D_r` and late pressure `H_G = D_16-D_12`.

The final candidate is rebuilt from committed f32 bytes and independently
audited for sequential readout, signed-zero identity, mismatch/ULP/L2/max
residual, prefix legality, support, bounds, boundary, reserve, axis, norm,
and cue-linear gates.

## Engineering classifications

Use only:

* `EXACT_TARGET_REACHED`;
* `PARTIAL_FEASIBILITY_FOUND`;
* `READOUT_IMPROVEMENT_GEOMETRY_REJECTED`;
* `INCONCLUSIVE_BOUNDED_SEARCH`;
* `REPLAY_BUDGET_EXHAUSTED`;
* `INVALID_GROUP_EXECUTION`.

Never report `BLOCKED_WITHIN_DECLARED_DOMAIN` for S1. The oversized domains
are not exhausted.

## Fail-closed conditions

Stop the run on parent or runtime hash drift, sample mismatch, duplicate or
missing identity, baseline replay mismatch, target-readout mismatch,
non-finite arithmetic, impossible prefix domain, sealed-predecessor or
canonical-state mutation, forbidden scientific/behavioral fields, or
nondeterministic replay from identical committed bytes. A group-specific
malformed input may be isolated only if the receipt distinguishes it from a
shared implementation failure.

## Predeclared branch logic

After the sealed result, use descriptive counts only. If at least 25% of
valid sampled groups improve during rounds 13–16, the next identity may test a
longer horizon. If fewer than 10% improve after round 8, investigate ranking
before widening the horizon. If at least 20% have readout-improving states
rejected only by final geometry, prioritize geometry balancing. Widespread
flat search calls for an authority/ranking audit. Strong repeated success
calls for fresh constructor qualification. None of these branches opens
behavior or DH08B.

## Scientific firewall

S1 does not establish biology, memory storage, memory expression, future
behavioral learning, full-domain feasibility, global repair feasibility, or
optimality of PF6. Its sole purpose is to profile the frozen engineering
constructor across a balanced real oversized-group sample.
