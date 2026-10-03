# FIN-OPEN-01 — Range-Freeze Economic Consequence Protocol

Agent: Vega — Financial Research Authority  
Status: protocol design only  
Outcome inspection: forbidden

## Purpose

FIN-OPEN-01 asks one question:

> Does the causally known orientation of a frozen opening range have a reproducible relationship with the subsequent price path?

The study has one causal anchor family, one primary outcome surface, and no strategy interpretation.

The primary scales are the complete range family:

```text
R_k = [09:30, 09:30 + k) America/New_York,  k = 1, ..., 30
```

At the exact causal freeze time for `R_k`, the protocol admits only:

- range high;
- range low;
- range midpoint;
- range width;
- terminal price at freeze;
- exact source knowledge time;
- already-qualified session, source, calendar, and clock metadata.

No width, volatility, event, weekday, month, previous-session, macro, volume, terminal-state, or Science-derived conditioning is admitted.

## Authority boundary

FIN-OPEN-01 consumes infrastructure authority only from the qualified OBS-OPEN-01 branch:

- admitted source and clock authority;
- NYSE session/calendar identity;
- the exact 257-session discovery population;
- R01–R30 identities and causal freeze semantics;
- qualified source hashes and lineage roots.

The 69-session Science confirmation population is not an input. It remains `FROZEN_UNOPENED`.

Substantive OBS-OPEN-03 findings, reports, scale summaries, candidate commentary, and interpreted results are outside the read allowlist.

## Financial Probe

One Financial Probe exists per eligible `(session, k)`:

```text
Q_i,k = (R_k, t_freeze, I_t_freeze, s_i,k, O)
```

This is a research object, not a trade proposal. It contains no order direction, entry, stop, target, exit, position, execution, or portfolio state.

The orientation is:

```text
s_i,k = +1  if terminal_price_at_freeze > range_mid
s_i,k = -1  if terminal_price_at_freeze < range_mid
s_i,k =  0  if terminal_price_at_freeze == range_mid
```

`s = 0` is `NON_DIRECTIONAL_MIDPOINT_EQUALITY` and is excluded from directional estimands. It is never assigned a direction.

## Primary outcome surface

The only primary outcome is the orientation-aligned future displacement path:

```text
Y_i,k(h) = s_i,k * (P_i(t_freeze + h) - P_i(t_freeze))
```

Positive values mean displacement in the same geometric direction as the freeze orientation. Negative values mean displacement opposite that orientation. The protocol does not rename either result continuation or reversal.

The horizon lattice is frozen before outcomes:

```text
h = 5, 10, 15, ... minutes
```

through the last completed regular-session observation at 16:00 America/New_York. A future price is the close of the completed source M1 bar whose close timestamp equals `t_freeze + h`; this keeps every relative horizon exact even when the freeze minute is not aligned to a global M5 boundary. The complete raw M1 price path remains required for reconstructibility.

The primary object is one complete `k × h` surface, not a collection of independently selectable tests.

## Development and validation

The 257 discovery sessions are ordered by `(civil_date, session_id)` using metadata only.

- `D_F`: first 180 sessions, through 2025-01-30;
- `V_F`: remaining 77 sessions, beginning 2025-02-03;
- both partitions contain both qualified server-offset regimes, 120 and 180 minutes;
- the exact partition manifest is sealed before outcomes are read;
- `V_F` remains `FROZEN_UNOPENED` until a later financial validation gate.

Science’s 69-session confirmation population is not used for development, validation, or confirmation.

## Null and dependence

Sessions are the independent research unit. The 30 nested ranges and all horizons inside a session are dependent observations.

The null preserves each session’s future path and the marginal distribution of whole 30-scale orientation profiles while breaking their session/path association:

1. group sessions by qualified server-offset regime and exact eligibility mask;
2. move a complete 30-scale orientation profile as one block within its group;
3. leave each session’s raw future path in place;
4. recompute the complete surface for every permutation.

The cell estimand is the observed orientation-aligned session mean minus the mean under this block-permutation null, in source price units. The family statistic is the maximum absolute standardized deviation across the complete preregistered surface.

Production inference is frozen at 8,192 deterministic block permutations, a fixed seed, and two-sided familywise alpha `0.05`. No real outcome-dependent choice enters the procedure.

## Candidate and robustness policy

FIN-OPEN-01 disables formal region promotion. Surface-local islands may be displayed descriptively, but they cannot define their own candidate boundaries after observation.

The future validation estimand is the exact full-surface maximum-statistic test using `V_F`, with the development freeze and all surface coordinates unchanged. If a later protocol explicitly enables a region rule, that is a new sealed protocol root; it cannot be smuggled into this one.

Predeclared robustness views are:

- chronological halves of `D_F`;
- qualified server-offset strata;
- the same complete surface and same sign convention.

Robustness is typed as `TEMPORALLY_SUPPORTED`, `TEMPORALLY_UNSTABLE`, or `INSUFFICIENT_TEMPORAL_SUPPORT`. A lack of independent significance in a small slice is not instability; contradictory supported direction is.

## Synthetic qualification

Before any financial outcome is opened, the complete machinery is exercised on deterministic synthetic/adversarial surfaces covering:

- no orientation/path association;
- strong same-orientation association;
- strong opposite-orientation association;
- one isolated false-looking cell;
- a contiguous scale/horizon region;
- temporal sign reversal;
- sparse midpoint/non-evaluable probes;
- nested cross-scale dependence;
- highly correlated horizon paths;
- block randomization preserving profile structure;
- outcome and Science-confirmation read guards.

The synthetic receipt is part of the sealed protocol root.

## Required end state

The seal may report:

```text
PROTOCOL_QUALIFIED
FINANCIAL_DEVELOPMENT_OUTCOMES = FROZEN_UNOPENED
FINANCIAL_VALIDATION = FROZEN_UNOPENED
SCIENCE_CONFIRMATION = FROZEN_UNOPENED
```

This root grants no economic finding, no candidate, and no trading authority. Then Vega stops.
