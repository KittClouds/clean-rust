# Q10-RH1-AC2: Coverage-Equalized Authority Feature Qualification

AC2 creates a complete authority table for the frozen RH1 cohort without
running the RH1 factorial.

For every unique `(endpoint, set_index, coordinate)` in the 84 frozen RH1
groups, the runner evaluates every legal member of the frozen prefix domain
`{0, -1, +1, -2, +2, -4, +4, -8, +8, -16, +16}` from the hash-bound PF5
endpoint state. Prefixes that violate the declared bounds/reserve are recorded
as measured illegal domain members, never as missing observations.

The runner uses the actual PF5 committed f32 bits and learner-order sequential
f32 readout. It extracts the complete physical support as every bound endpoint
readout row containing the coordinate, records the committed weight bits, and
stores exact support-row effect bits for every legal prefix.

AC2 is a measurement qualification only. It performs no ranking, beam search,
candidate selection, scientific replay, behavioral probe, or DH08B work.
