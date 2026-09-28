# PRED1 interpretation correction

This addendum leaves the original PRED1 report and all parent artifacts intact.
The 42 recorded PRED1 input hashes were checked against live files and matched
before preparation of this derived audit.

| Frozen ordering | Top-one hit rate | Mean trials to first success |
|---|---:|---:|
| Partner singleton readout | 100.00% | 1.0000 |
| Full constraint cosine | 93.45% | 1.0655 |
| Partner magnitude | 89.82% | 1.1273 |
| Scalar axis direction | 88.36% | 1.1382 |
| Deterministic random | 87.27% | 1.1527 |

These numbers apply to the 275 role-bearing source pools with at least two
observed partners and at least one successful partner, selected from 1,226
held-out directional observations. They are conditional on a successful
partner existing. The original code excluded zero-success pools.

The original assistant summary omitted the strongest baseline. Partner readout
uses already available singleton measurements; calling it an oracle would be
incorrect. Geometry did not beat that baseline on the reported cohort.

The original 60.46% estimated evaluation saving is relative to exhaustive pool
enumeration. Random achieved 57.70%, so geometry's incremental pool-size saving
is 2.76 percentage points. Neither figure measures wall-clock runtime or the
cost of screening/generating the candidate library.

The source pair-domain PLAN explicitly screens committed-state geometry before
pair readout replay. Therefore validity is constant in the retained cohort.
The ranking outcome is readout advantage conditional on prior geometry
acceptance; these results cannot qualify an unscreened validity router.

The split is by directed pair observation, and source keys include A/B role.
It is not an independent candidate-identity or context holdout. CSC1-R1 also
described the same full cohort before PRED1. A deterministic hash split alone
does not turn this into fresh unseen evidence after that inspection.

Cosine is already invariant to positive rescaling of a displacement: the
proposed unit-direction arm would duplicate the full-vector score. Similarly,
an unfitted cosine rule run on eight existing contexts has no training stage
to leave one context out of. Genuine transfer needs a separately defined test.

Safe current conclusion: within PRED1's selected, geometry-prescreened pools,
the frozen cosine ordering outperformed three simpler tested orderings but
underperformed singleton-readout ordering. This is a descriptive engineering
ranking result with outcome-conditioned denominators. PRED2 will expose those
denominators and difficulty strata without changing the score or domain.

No biological, scientific adaptive-state, or global-constructor claim follows.
