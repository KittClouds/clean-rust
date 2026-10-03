# Q10-PF3 Joint Bundle Order Audit

## Question

Q10-PF2 showed that isolated endpoint effects are exactly additive on disjoint
rows but can interact on shared rows. PF3 tests whether those interactions stop
at second order or whether small jointly committed bundles create an additional
third-order f32 remainder.

This is qualification-only engineering. It opens no scientific seed bundle,
does not inspect behavioral endpoints, and cannot authorize DH-08B.

## Frozen sample and intervention

Fresh engineering seeds are `9671` and `9672`. Each seed is run on both sides
(`R`, `L`) and both taus (`4`, `16`) at trial `128`, yielding eight events.
Each event selects four deterministic coordinate triples with a common shared
readout row and four triples whose coordinate row supports are pairwise
disjoint. Directions are fixed per triple by a deterministic hash; every legal
prefix length in `1, 2, 4, 8, 16` is exhaustively evaluated for each triple.

For a triple `(a,b,c)`, the jointly committed sequential-f32 effects are
evaluated for all 125 prefix combinations. The third-order remainder is:

`I3 = Eabc - Eab - Eac - Ebc + Ea + Eb + Ec`.

Here every `E` is computed from the actual committed f32 state using the
learner's sequential accumulation order. Disjoint triples are the control and
must have zero remainder.

## Interpretation frozen before execution

- Complete four-plus-four bundle coverage and finite metrics validate the audit
  only.
- If disjoint triples have any nonzero remainder, the implementation or row
  classification is invalid and the audit fails closed.
- If shared triple remainders are zero or negligible relative to the PF1
  plateau, an interaction-aware pair/block solver may be qualified next.
- If shared triple remainders reach the PF1 plateau scale, pairwise corrections
  are insufficient and future optimization must replay jointly committed
  states in its active blocks.
- A triple audit does not establish that fourth- or higher-order interactions
  are absent. Any future solver must state its block-order assumption.
- Exact prefix search, behavior, scientific seeds, and DH-08B remain closed.

## Firewall and lineage

Q10-SM hashes are checked at seal and execution. Receipts contain only bundle
coordinates, prefix-grid coverage, and readout interaction metrics. They contain
no accuracy, reward, action, old-map, or behavior fields. The independent
reviewer checks source identity, eight-event coverage, eight bundles per event,
finite metrics, disjoint controls, and the firewall.
