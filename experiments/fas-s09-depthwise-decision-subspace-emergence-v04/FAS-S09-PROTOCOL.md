# FAS-S09 v04: Depthwise Decision-Subspace Emergence

Version 04 continues the already-authorized fixed S09 analysis after v03 stopped at its terminal metric verifier. The v03 recovery cache remains the input. The v03 failed analysis and its terminal M probe state remain preserved as provenance.

## Correction boundary

The v03 runner compared a metric bundle containing `ALL_TEST_ROWS` and eleven named conditions against a reference mapping containing only the eleven conditions. The reference also carries an `interpretation_scope` provenance string that is not produced by the metric calculation. A read-only audit found the M terminal probe state and probabilities exact and every numeric/structural metric field exact for all eleven conditions after excluding only those two schema differences.

Version 04 makes that comparison explicit: require equal condition-name sets, omit the additional all-test aggregate, omit the reference-only `interpretation_scope` field, and compare every remaining field exactly. No metric definition, label, split, probe, optimizer, solver limit, or scientific threshold changes.

## Fixed analysis

Use only the v03 requalified 32-matrix feature cache and sealed S01/S08 inputs. Do not load the model. Fit the same 32 fixed exact-target linear probes from S09-v02. Fit layer-16 M and F first and require exact probe-state and probability reproduction, exact condition metrics, and the S08 plane tolerance before fitting layers 1–15. Then evaluate the same four native/cross-surface pipelines per layer.

The S01 grouped split was already revealed, so the result remains exploratory. No FAS-00 access, significance test, layer selection, additional representation, or adaptive mechanism is authorized.
