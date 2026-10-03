# Q08 constructor qualification result

Status: `BLOCKED_PRESEAL_CONSTRUCTOR_QUALIFICATION`

The seed-9200 qualification smoke retained all 512 reversal events across R/L at tau 4. All events
failed the frozen contract. No full qualification or DH-08B measured execution followed.

| Gate | Failed events |
| --- | ---: |
| Cue-by-MBON sequential f32 drive match | 512 / 512 |
| Residual decorrelation | 511 / 512 |
| Aggregate cue-score match | 0 / 512 |
| Axial/norm/support/boundary/bounds/allocation gates | 0 / 512 |

Aggregate cue scores matched within `2.23517417908e-08`, while maximum normalized cue-by-MBON
drive error reached `2.55451027442e-06`, above the frozen `1e-7` gate. The corresponding f64
sum-of-committed-weight-differences diagnostic stayed below `3.16667342224e-08`. This separates
sequential f32 accumulation error from aggregate score cancellation.

The four-coordinate grouping contract had an optimistic residual-cosine floor above `1e-5` in
503 events. Even the larger all-signature-group nullspace diagnostic retained such a floor in
482 events. This certificate applies to that grouping/fixed-component contract. It is not a proof
that the weaker full cue-drive plus global-axis constraint admits no feasible alternative.

Validation passed: 59 Rust release tests, Clippy, four independent receipt-review tests, canonical
true-endpoint parity, and zero hot-loop allocations. CLI checks rejected measured mode and seed 9201
without creating output. Only qualification seed 9200 ran; seeds 9201–9205 remain unopened.

DH-08A remains sealed as `INCONCLUSIVE`. This is engineering qualification evidence from one seed,
not a new forgetting result, biological finding, or inferential sample.
