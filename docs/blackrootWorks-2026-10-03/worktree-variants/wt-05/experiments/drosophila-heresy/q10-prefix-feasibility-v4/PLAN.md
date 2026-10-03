# Q10-PF4 Capacity-Stratified Joint Bundle Order Audit

PF3 was rejected because one engineering event had only three available
common-row triples against its predeclared four. PF4 freezes a capacity-aware
redesign before execution: it requires three shared-row and three disjoint-row
triples per event, then exhaustively evaluates all 125 combinations of prefix
lengths `1, 2, 4, 8, 16` for each triple.

Fresh engineering seeds are `9681` and `9682`; both sides, both taus, and trial
`128` produce eight events. Directions are deterministic per triple and every
endpoint retains the 16-ULP reserve. The third-order remainder is computed
from actual jointly committed sequential-f32 readouts:

`I3 = Eabc - Eab - Eac - Ebc + Ea + Eb + Ec`.

The design is still engineering-only. It opens no scientific seed bundle, does
not inspect behavioral endpoints, and cannot authorize DH-08B.

The disjoint triples are a zero-interaction implementation control. If an
event has fewer than three triples in either category, PF4 fails closed. If
coverage passes, shared remainders are descriptive evidence about whether a
pair/block solver is justified; they do not certify fourth- or higher-order
interactions or authorize exact search by themselves.
