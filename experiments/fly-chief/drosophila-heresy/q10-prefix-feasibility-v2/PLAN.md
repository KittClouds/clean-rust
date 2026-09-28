# Q10-PF2 Multi-Coordinate Sequential-f32 Superposition Audit

## Question

Q10-PF1 measured isolated per-coordinate committed endpoint effects and summed
them in an additive product-of-hulls surrogate. The PF1 residual math was
internally correct, but sequential f32 accumulation may make jointly committed
multi-coordinate effects non-additive. Q10-PF2 measures that interaction before
any exact prefix search is considered.

This is qualification-only engineering. It opens no scientific seed bundle,
does not inspect behavioral endpoints, and cannot authorize DH-08B.

## Frozen sample and intervention

Fresh engineering seeds are `9661` and `9662`. Each seed is run on both sides
(`R`, `L`) and both taus (`4`, `16`) at trial `128`, yielding eight events.
For every event, deterministic legal endpoint pairs are selected from eligible
interior coordinates: 12 pairs sharing at least one cue-by-MBON row and 12
pairs with disjoint row support. Directions and prefix lengths are derived
from a fixed hash of the event and pair identity; no simulation RNG is used.
Prefix lengths are selected from `1, 2, 4, 8, 16` and every endpoint retains the
frozen 16-ULP reserve in both directions.

For each pair, compute the actual sequential-f32 readout effect of moving A,
moving B, and moving A and B together. The interaction is:

`joint_effect - isolated_A_effect - isolated_B_effect`.

Disjoint-row pairs are an implementation control: their interaction should be
zero because the two changes affect different sequential sums. Shared-row
interactions quantify the non-additivity that PF1's isolated-effect hull does
not model.

## Interpretation frozen before execution

- Complete pair coverage and finite metrics validate the audit only.
- If shared-row interaction is negligible relative to the base readout error
  and the PF1 residual plateau, a future relaxation may use PF1's additive
  surrogate with an explicit approximation bound.
- If shared-row interaction is comparable to the PF1 residual plateau, the
  additive hull is not an adequate proxy and the next solver must evaluate
  jointly committed states.
- Any nonzero disjoint-row interaction beyond the fixed arithmetic tolerance,
  missing pair category, stale manifest, duplicate event, or firewall failure
  invalidates the audit rather than supporting a scientific conclusion.
- No result here authorizes exact search or DH-08B.

## Firewall and lineage

Q10-SM hashes are checked at seal and execution. Receipts contain only
engineering pair geometry and readout interaction metrics. They contain no
accuracy, reward, action, old-map, or behavior fields. The independent reviewer
checks source identity, eight-event coverage, 24-pair category coverage,
finite metrics, and the firewall.
