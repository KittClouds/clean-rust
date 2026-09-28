# Q10-PF2 result

Status: `Q10_PF2_STAGE1_VALID__SHARED_ROW_NONADDITIVITY_DETECTED`

PF2 completed all eight predeclared engineering events with 192 legal pairs:
96 shared-row pairs and 96 disjoint-row pairs. The independent reviewer
returned `VERIFIED`; source-manifest, coverage, pair-category, finite-metric,
and firewall checks passed. No scientific seed bundle or behavioral endpoint
was opened, and no DH-08B authorization was issued.

The disjoint-row control was exact across all 96 pairs:

- maximum interaction norm ratio: `0`;
- maximum nonzero interaction-row count: `0`.

That validates the joint-readout construction and the pair classification.
Shared-row pairs were mostly additive, but 6 of 96 had nonzero interaction.
Their mean interaction norm divided by the event base readout error was
`2.95e-3`; the maximum was `0.131753`. The largest events were isolated to a
small number of shared rows, which is consistent with sequential accumulation
thresholds rather than broad numerical corruption.

Across events, the base readout error norm ranged from approximately
`2.37e-5` to `3.07e-5`. The maximum shared-pair interaction is therefore of
the same order as the PF1 residual plateau (`0.1787` to `0.3324` as a ratio of
the PF1 base error), even though the typical shared pair is nearly additive.

## Interpretation

PF1's residual math was correct for its additive isolated-effect surrogate,
but PF2 shows that the surrogate is not a generally safe relaxation of the
jointly committed sequential-f32 endpoint problem. A future repair can select
coordinates whose shared-row interactions materially change the readout.

The exact prefix search remains gated. The next engineering step must evaluate
jointly committed states directly, or build an interaction-aware bound before
any solver result can be interpreted as repair feasibility. PF2 supplies no
behavioral or scientific conclusion.
