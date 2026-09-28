# JEV v0.8M preflight: local-geometry diagnostic

## Status

Read-only diagnostic complete. This identity is non-promotable and is not a
repair or parent of sealed v0.8L. No head training, evaluation inference,
protected-evaluation body access, or Phoenix access occurred.

## Purpose

The failed v0.8L construction showed that independently sourced same-target
examples were far from the certified sham in the frozen LFM representation.
This diagnostic measures that geometry directly before designing a fresh
local-vs-local generator experiment.

The audit uses the sealed v0.8L A1 training-only feature cache, the 5,000
certified training triplets, the training-only F100 metadata, and the sealed
candidate pool. It does not infer a causal effect and does not reopen the L
construction gate.

## Measurements

For each certified anchor, the audit reports:

- certified sham radius `||hS - hA||`;
- exact-target candidate radii and radius errors from the L candidate pool;
- nearest state within the available feature scope;
- nearest state sharing world/topology family;
- nearest state sharing ontology family;
- nearest state sharing schema-composition family;
- family- and entropy-quintile stratifications.

The candidate pool is descriptive only. It is not promoted as a NOVEL arm.

## Results

Across 5,000 anchors and 9,984 scoped training states:

| Quantity | Mean | Median | P10 | P90 |
| --- | ---: | ---: | ---: | ---: |
| Certified sham radius | 1.8212 | 1.8107 | 1.5679 | 1.9587 |
| All exact-target candidate radius | 3.8485 | 3.7741 | 2.8344 | 4.9653 |
| Exact-target radius error vs sham | 2.0291 | 1.9627 | 1.0271 | 3.1046 |
| Nearest alternative scoped state, sham excluded | 2.1710 | 2.3369 | 0.8604 | 3.3681 |

Each anchor had 88--119 eligible exact-target candidates. The sealed L
matching lower bound remains 1.0673 mean error and 2.0952 p95 error, versus
the former acceptance gate of 0.05 mean and 0.15 p95. This confirms that the
failed NOVEL control was support-limited, not merely a greedy assignment
failure.

The sham radius was stable across entropy quintiles (mean 1.8181--1.8254),
while exact-target radius-error means stayed in the narrow range 1.9872--2.0504.
Across the 12 world families, sham-radius means ranged from 1.5384 to 2.2798,
and exact-target radius-error means ranged from 0.9066 to 3.1951. The gap is
therefore not explained by one entropy band or one family alone.

## Artifacts

- [audit script](../experiments/jev-information-density-v08m/geometry/audit_local_geometry.py)
- [external geometry report](D:/codex-runs/jev-information-density-v08m/geometry-v01/geometry-audit.json)
- [external receipt](D:/codex-runs/jev-information-density-v08m/geometry-v01/geometry-audit-receipt.json)

## Interpretation boundary

This audit can establish that the current training universe lacks a valid
generic local same-target control at the declared radius. It cannot establish
that the sham semantics caused the v0.8K effect. A valid local-neutral arm must
be generated prospectively as a distinct target-preserving semantic
intervention, yielding a fresh v0.8M identity.
