# JEV v0.8N synthesis

## Disposition

`v0.8N` construction is complete and sealed as a two-road, training-only
program. Neither road contacted a model head, opened evaluation inference, or
authorized Phase B.

```text
N0 shared semantic basis              PASS
shared LFM feature cache              PASS
Road A geometry atlas                 PASS
Road B radius-matched control         PASS
Phase-B preflight                     PASS: execution contract closed; not authorized
Phase B model contact                 NOT AUTHORIZED
```

The umbrella identity is `v0.8N-base-v01`. The shared contract hash is:

```text
f72947a53c7df85d12c7d9f91620c0c32925c047b0c556d9298038c80c51f103
```

## Shared basis and boundary

N0 generated 12,000 training neighborhoods and 2,000 held-out neighborhoods,
with the held-out family/template split intact. The training selection is 5,000
feature-free, family-balanced neighborhoods. Each selected training
neighborhood has the fixed role order:

```text
A, F, S, N1, N2, N3, N4, N5, N6, N7, N8
```

The shared cache contains 55,000 training-only LFM representations with the
pinned revision, exact-length single-row extraction, no padding, and final-layer
`mean_full`. Its feature-file SHA-256 is:

```text
da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6
```

The deterministic smoke test passed with zero repeat error. No held-out or
protected evaluation body was opened.

## Road A: geometry atlas

Road A was read-only and did not select controls. Across 5,000 selected
training neighborhoods, the sham displacement radius had mean approximately
`2.21367`. The eight neutral axes were not geometrically interchangeable:

| Axis | Mean radius | Mean radius / sham | Mean relative error to sham | Mean cosine to sham |
| --- | ---: | ---: | ---: | ---: |
| neutral_1 | 2.99 | 1.35 | 0.35 | 0.68 |
| neutral_2 | 3.29 | 1.49 | 0.49 | 0.63 |
| neutral_3 | 3.11 | 1.41 | 0.41 | 0.64 |
| neutral_4 | 2.54 | 1.15 | 0.15 | 0.63 |
| neutral_5 | 2.11 | 0.96 | 0.05 | 0.60 |
| neutral_6 | 1.65 | 0.75 | 0.25 | 0.54 |
| neutral_7 | 1.19 | 0.54 | 0.46 | 0.48 |
| neutral_8 | 0.74 | 0.33 | 0.67 | 0.23 |

The nearest sham-radius candidate had mean relative error `0.04424` and p95
absolute error `0.20180`. The nearest-axis histogram was concentrated on
`neutral_4` (566) and `neutral_5` (4,434). This is evidence of structured
substrate geometry with family/anchor variation; it is descriptive and not a
causal training result.

Road-A report SHA-256:

```text
644cf23f3342b44f8a1f443670d808a91a29307a8052f8430d9184df3ca2798b
```

Road A received a local independent fallback seal. The Luna reviewer produced
no independent artifact; no Luna PASS is inferred.

## Road B: prospective matched control

Road B used only the frozen radius-only rule:

```text
select argmin_j abs(||h_Nj-h_A|| - ||h_S-h_A||)
```

No direction, learned output, historical result, held-out data, family
performance, or Road-A result was used. No replacement selection or threshold
relaxation occurred.

All frozen gates passed:

| Gate | Value | Limit |
| --- | ---: | ---: |
| Mean relative radius error | 0.0442418260 | <= 0.10 |
| p95 absolute radius error | 0.2017967463 | <= 0.25 |
| Maximum family mean relative error | 0.0828768774 | <= 0.15 |

The branch materialized read-only `B-DUP`, `B-MATCHED`, and `B-SHAM` objective
manifests with 5,000 auxiliary events per arm and identical primary/event
budgets. Independent validation passed, the complete 18-artifact hash tree
matched, and the branch is explicitly sealed as not authorized for Phase B.

## Phase-B execution contract closure

The first outcome-blind preflight was correctly blocked because the sealed
Road-B branch did not itself materialize the execution-level primary stream,
the primary/auxiliary schedule, or the head-input manifest. Those omissions
were closed without changing the scientific design or the Road-B arms.

The v02 execution contract now binds:

```text
common primary occurrences       10,000
    anchor occurrences            5,000
    fact-flip occurrences         5,000
auxiliary occurrences per arm     5,000
candidate catalog entries            48
candidate feature dimension        2048
fixed schedule rows                  360
optimizer steps per seed             120
```

All three arms use the same serialized primary occurrence stream. The fixed
schedule is deterministic and seed-derived from the frozen zero-based epoch
rule, with the prospective three-arm execution order recorded in the contract.
The three head-input manifests bind candidate indices/order, masks, targets,
loss weights, normalization semantics, source roles, and feature dimensions.
Their primary portions are byte-identical after removing only the arm label.

The execution-input receipt, hash tree, and contract hash are materialized
under the v03 input identity. Candidate feature tensor extraction is expressly
deferred until a separate Phase-B authorization; this is a boundary, not a
missing scientific result. No model was loaded and no feature tensor was
extracted for head training.

Key Road-B hashes:

```text
selected-control-manifest.jsonl  fc94f9a8ab257fea07394f7f1573d99c3316bac9147d842a0e0712aec12ddd13
independent-validation.json      f299878264a80a80c5862eb4a090af5e4a692af94933f73efb4ef566eb198d72
branch-receipt.json               31d837589ba2b2e9f11ad00818adc1686075c1fa652c71539aef4d31518edf00
seal-manifest.json                5c88ee75bf5e401457c26543a6eeaf8951b98de2c77051631a0b6857c9f1680a
```

Road B also used a local fallback seal because no Luna artifact was produced.
The recorded disposition is `LUNA_NO_ARTIFACT`; no Luna PASS is claimed.

## Joint interpretation

The two roads jointly establish:

1. Exact-target-preserving nuisance interventions occupy structured and
   non-equivalent regions of the frozen LFM representation space.
2. The eight-candidate basis contains sufficient common radius support for the
   declared Road-B gates.
3. A radius-matched generic local control can be constructed prospectively
   without using direction or learning outcomes.

This is a construction result, not a model result. It does not establish that
the sham semantic direction causes a distinct learning effect. It establishes
that the corresponding causal comparison is now materially available under a
sealed, geometry-matched construction.

## Authorization boundary

No head training, NewTight evaluation, protected evaluation inference, Phoenix
access, LoRA/QLoRA, architecture change, lambda search, or follow-on experiment
is authorized by this synthesis. A separate explicit authorization is required
before any future Road-B Phase B run.

That authorization is additionally gated on a prospectively sealed held-out
matched-neutral panel. The panel must use held-out families/templates only;
independent exact-world invariance validation; feature-blind neutral generation;
the already frozen radius-only matching rule; no direction or cosine
optimization; no training-head contact; no replacement selection after
geometry inspection; frozen panel IDs and hashes; a sham/matched radius-gate
report; a semantic-axis composition report; and complete evaluation-firewall
sealing before any training or evaluation body is opened.

The held-out matched-neutral panel is now constructed and independently sealed
under `v0.8N-eval-panel-v01`. Its panel-level status is `PHASE_B_READY` with the
evaluation firewall locked; this does not by itself make the full training run
ready.

An unchanged outcome-blind Phase-B preflight was rerun after those three
execution seams were closed. The split, surface, geometry, held-out firewall,
common-primary, schedule, head-input, hash, and no-contact checks all passed.
This establishes the construction-level state:

```text
PHASE_B_READY       true
PHASE_B_AUTHORIZED  false
```

The candidate feature tensor remains deferred until explicit authorization, so
the preflight still records zero model contact, zero head training, zero
evaluation inference, and zero Phoenix access.

The authoritative preflight report is:

```text
D:/codex-runs/jev-information-density-v08n/v0.8N-base-v01/phase-b-preflight-v02/preflight-report.json
```

The authoritative external synthesis receipt is now
`D:/codex-runs/jev-information-density-v08n/v0.8N-base-v01/synthesis/v08n-synthesis-receipt-final-v09.json`.
It supersedes `final-v08` for the current construction state while retaining
all earlier receipts unchanged as research history. The v08 receipt remains
the preserved blocked preflight record.
The earlier receipts remain retained and non-destructive.
