# Q10-PF4 result

Status: `Q10_PF4_STAGE1_VALID__SPARSE_THIRD_ORDER_NONADDITIVITY`

PF4 completed all eight predeclared engineering events with 48 bundles: 24
shared-row triples and 24 disjoint-row triples. The independent reviewer
returned `VERIFIED`; source-manifest, coverage, prefix-grid, finite-metric, and
firewall checks passed. No scientific seed bundle or behavioral endpoint was
opened, and no DH-08B authorization was issued.

The disjoint control was exact across all 24 bundles:

- third-order remainder was zero for every tested prefix combination;
- maximum pair interaction ratio was zero;
- no nonzero interaction rows occurred.

Shared triples were mostly quiet, but 4 of the 24 bundles contained nonzero
third-order cases. The maximum third-order remainder ratio was `0.1307929`
relative to the event base readout error. The mean of the per-bundle maxima
was `0.0054497`. The interaction is therefore sparse and threshold-local, but
its largest excursions are the same order as the PF1 residual plateau.

## Interpretation

PF4 confirms that sequential f32 non-additivity is not limited to pairwise
effects. A pairwise correction or additive isolated-effect hull cannot be
treated as a globally safe proxy for jointly committed endpoints. The next
repair qualification must replay jointly committed active blocks and audit
their realized f32 readouts directly.

PF4 does not establish that fourth- or higher-order interactions are absent,
and it does not establish global repair feasibility or infeasibility. Exact
prefix search, behavior, scientific seeds, and DH-08B remain gated.
