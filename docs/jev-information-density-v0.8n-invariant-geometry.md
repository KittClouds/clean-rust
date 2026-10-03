# JEV v0.8N — Invariant Geometry Cartography & Matched-Control Recovery

## Disposition

v0.8N construction is complete. Both branches are sealed. No head training,
evaluation inference, protected-evaluation access, or Phoenix access occurred.
Road-B arms are materialized read-only and are not authorized for Phase B.

The umbrella remains a construction/diagnostic result, not a model result.

## Shared N0 basis

- Phase identity: `v0.8N-base-v01`
- Contract SHA-256: `f72947a53c7df85d12c7d9f91620c0c32925c047b0c556d9298038c80c51f103`
- Training neighborhoods: 12,000 generated; 5,000 selected by feature-free balanced hash rank
- Held-out neighborhoods: 2,000 generated for the sealed semantic basis only
- Selected neighborhood roles: `A`, `F`, `S`, `N1` through `N8`
- Shared cache: 55,000 training-only rows, shape `[55000, 2048]`
- LFM revision: `7453bca97ca1e67754c4035a4b4c584e1c9dd725`
- Representation: final-layer `mean_full`, exact-length, single-row, no padding
- Feature file SHA-256: `da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6`
- Feature tensor SHA-256: `d8f0f12296758f68c55b5e5660572dd48e4e90d1a3a1683844e59765826bafaa`

The shared feature cache is training-only and passed a deterministic extraction
smoke test. The N0 exact-world validation passed for all 132,000 training and
22,000 held-out materialized episodes, with zero target, fact-flip, surface,
schema, family-split, or template-split failures.

## Road A — geometry atlas

Road A was read-only and did not select a Road-B control. Its sealed report is:

`D:/codex-runs/jev-information-density-v08n/v0.8N-base-v01/road-a/road-a-geometry-atlas.json`

Report SHA-256:
`644cf23f3342b44f8a1f443670d808a91a29307a8052f8430d9184df3ca2798b`

The sham radius had mean approximately `2.21367`. Across the eight generated
neutral axes, the best per-anchor radius match had:

- mean absolute error: approximately `0.10013`;
- p95 absolute error: approximately `0.20180`;
- mean relative error: approximately `0.04424`;
- p95 relative error: approximately `0.08760`.

The nearest-radius candidates were concentrated on `neutral_marker_4` (566)
and `neutral_marker_5` (4,434). This is descriptive substrate geometry only;
it was not used to alter N0 or to steer Road B.

Road-A seal artifacts are under:

`D:/codex-runs/jev-information-density-v08n/v0.8N-base-v01/road-a/seal/`

The local independent fallback seal passed. A separate Luna reviewer was
attempted under the bounded-review policy; no separate Luna PASS is claimed
unless a written Luna artifact exists.

## Road B — prospective matched control

Road B used only the frozen radius-only rule:

`argmin_j |r_Nj - r_S|`, with deterministic hash tie-breaking.

Direction, cosine, learned outputs, historical outcomes, Road-A results,
evaluation material, and family performance were forbidden inputs.

The deputy branch passed all frozen gates:

- mean relative radius error: `0.0442418260` (limit `0.10`);
- p95 absolute radius error: `0.2017848492` (limit `0.25`);
- maximum family mean relative error: `0.0828768774` (limit `0.15`);
- selected controls: `5,000`;
- selected-axis histogram: `neutral_4 = 566`, `neutral_5 = 4,434`;
- independent raw-artifact validation: `PASS`;
- read-only B-DUP, B-MATCHED, and B-SHAM manifests: materialized;
- Phase B authorization: `false`.

Deputy branch artifacts are under:

`D:/codex-runs/jev-information-density-v08n/v0.8N-base-v01/road-b/`

The deputy selected-control manifest is:

`D:/codex-runs/jev-information-density-v08n/v0.8N-base-v01/road-b/selected-control-manifest.jsonl`

A transparent local fallback independently selected the identical 5,000
neutral episode IDs. It is retained separately under:

`D:/codex-runs/jev-information-density-v08n/v0.8N-base-v01/road-b-local-fallback/`

The fallback was not used to overwrite the deputy branch.

## Joint interpretation

Road A establishes that the generated exact-target-preserving nuisance axes
occupy structured but unequal representation-radius regimes. Road B establishes
that the eight-candidate basis contains sufficient prospective support for a
radius-matched neutral control under the predeclared gates.

Therefore the next scientifically justified step is a separately authorized
Road-B Phase B causal experiment, if desired. v0.8N itself authorizes no model
loading beyond the already sealed training-only feature extraction and no
training or evaluation. No follow-on experiment is authorized by this
synthesis.
