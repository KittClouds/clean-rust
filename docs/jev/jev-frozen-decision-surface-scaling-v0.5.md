# Frozen Decision Surface Scaling v0.5

Status: frozen scaling protocol. This protocol does not reopen or modify the
sealed v0.4 gate and cannot authorize QLoRA.

## Purpose

Measure how far the validated, sub-0.5M dynamic compatibility head improves
when supplied with broader synthetic-control supervision and a typed lane of
audited real data. All three causal backbones remain frozen:

- `openbmb/MiniCPM5-1B-Base`
- `Qwen/Qwen3-0.6B-Base`
- `IFM/K2-Horizon-0.9B`

The v0.4 evaluation families, targets, and reports are protected inputs. No
v0.4 gate field may be rewritten, and no v0.5 result is a QLoRA decision.

## Fixed architecture and extraction

Use the v0.4 primary readout unchanged: final-layer `mean_full` frozen
features, `name_definition` candidate profile, the validated MLP head, L3
semantic/Brier/invariance loss, reorder augmentation, projection 128, and the
same optimizer schedule. Only the training information changes.

The backbone is used only for feature extraction. Head optimization receives
cached state and candidate representations. Feature extraction cost and head
training cost are reported separately.

## Banks and mixtures

Nested synthetic-control training banks are family-safe and target group
counts of 50k and 100k. The existing v0.4 20k result is retained as a
reference, not regenerated as a v0.5 point. A 250k bank is not automatic; it
requires a prospective cost/usefulness decision after 100k.

The initial mixture matrix is:

| Mixture | Synthetic | Real |
| --- | ---: | ---: |
| S100 | 100% | 0% |
| S75/R25 | 75% | 25% |
| S50/R50 | 50% | 50% |

Fractions apply to training groups. Real sources remain typed by authority and
probability source. Exact synthetic posteriors, empirical human distributions,
and hard labels are never pooled into one untyped calibration claim.

Real lane priority is ChaosNLI, raw GoEmotions, and MASSIVE. A source remains
bounded or excluded when its pinned public access path is unavailable. DocRED
remains a separate structured lane and is not coerced into this head.

## Evaluation

Every scale and mixture uses the protected v0.4 synthetic evaluation bank,
plus held-out real source partitions. Synthetic metrics are stratified by
exact posterior source; real metrics are reported by source and probability
source.

Required synthetic metrics include hard-sibling rank accuracy, ontology/world
OOD rank accuracy, NLL, Brier, intervention delta correlation, and locality.
Real metrics include hard-label accuracy, human-distribution NLL/Brier, and
multi-label F1 where applicable. No composite score is primary.

The same v0.4 residual identities are tracked at each new scale as:

- `resolved_by_data`
- `improving_but_unresolved`
- `stable_residual`
- `regressed_under_real_mixture`

## Contradictory binding

The v0.5 diagnostic bank contains held-out synthetic choice siblings where an
opaque candidate ID is paired with another candidate's definition. These are
not ordinary training rows. Gold follows the exposed runtime definition under
the declared binding diagnostic and is reported separately from normal schema
profiles.

## Reproducibility and boundary

Every bank records generator version, source revision, family IDs, source
lineage, mixture seed, backbone revision, feature-cache manifest, and head
configuration. Downloaded corpora and run outputs live outside the repository.

This protocol ends with a data-efficiency and residual report. It must not
create a new QLoRA PASS/FAIL gate. Future adaptation requires a new protocol
based on the persistent residual inventory.
