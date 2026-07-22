# Counterfactual Candidate Groups v1

## Status

The immutable contract, builder, mmap-backed artifact, corruption checks, and
synthetic correctness gates are implemented. No Phoenix production trajectory
is certified for this dataset yet. Phase 0 found no authoritative historical
decision population with complete candidate outcomes, so this cut must not be
described as a populated training dataset.

## Purpose

`phoenix-counterfactual-candidate-groups/v1` binds a decision-time graph state
to a fixed seven-action tribunal. It supports ordinary group ranking now and a
later group-relative objective without changing the data meaning.

Every group contains exactly one candidate in this canonical order:

| Role | Required contract |
| --- | --- |
| Recorded action | Candidate identity and reward equal the frozen Phase 2 label |
| Hard plausible alternative | Grammar-valid action that passes hard constraints |
| Safe abstention | Explicit `abstain` action that passes hard constraints |
| Minimal repair | Explicit `repair_graph_region` action that passes hard constraints |
| Aggressive repair | Distinct `repair_graph_region` action that passes hard constraints |
| Evidence-rich alternative | Grammar-valid action with non-empty evidence |
| Temporally attractive invalid alternative | Fails closed with `future_information` |

There is no fallback role and no inferred reward. Missing roles, duplicate
action identities, pending reward dimensions, or absent constraint receipts
reject dataset construction.

## Authority boundary

The recorded candidate is joined to the source trajectory by:

- decision ID;
- observation cutoff;
- pre-state snapshot ID;
- candidate identity with approval removed;
- selected-action identity;
- the Phase 2 recorded reward vector;
- decision authority.

Every counterfactual candidate carries its own:

- complete eight-dimensional reward vector;
- outcome authority;
- outcome availability timestamp;
- content-addressed hard-constraint receipt;
- semantic action payload and content identity.

All reward dimensions must be `Observed`. A recorded decision is not evidence
for the reward of an unchosen alternative. Counterfactual rewards therefore
require explicit outcome authority; the builder never derives them from the
chosen action.

## Temporal rule

Outcomes may become known after `observation_cutoff` because they are labels.
They must be known no later than `frozen_at`, and
`outcome_used_as_feature` must remain false. Reward evidence must obey its own
availability timestamp. This preserves the difference between:

```text
information available to the policy
and
information later used to judge the policy
```

The temporal-invalid candidate is a required leakage sentinel. Its grammar may
be valid, but its hard-constraint receipt must reject it specifically for
future information.

## Immutable artifact

The artifact is written in crash-safe immutable order:

```text
content-addressed payload
then
manifest
```

Both files use create-new semantics and are individually flushed. The manifest
contains the semantic dataset identity, source trajectory identity, physical
BLAKE3 digest, byte count, group and candidate counts, and the complete dataset
certificate. Opening mmaps the payload, verifies the physical digest before
JSON decoding, recomputes the semantic identity, validates exact group ranges,
and rechecks every action, reward, constraint receipt, and certificate count.

The payload remains a single mmap-backed immutable envelope. A frozen fixed
layout sidecar is intentionally deferred until profiling proves JSON decoding
or traversal material. Introducing one now would duplicate truth without an
observed pressure point.

## Dataset certificate

Installation requires:

```text
seven roles per group
100% recorded-action coverage
all reward dimensions observed
one valid hard-constraint receipt per candidate
zero outcome fields used as features
zero outcomes after frozen_at
zero duplicate action identities
zero invalid temporal sentinels
```

`labels_after_observation` is measured rather than treated as leakage. It is
expected for later outcomes and is safe only while the feature-use counter is
zero.

## Launch boundary

Cut 6 becomes empirically usable only after an authoritative Phoenix decision
surface supplies fully observed outcomes for all seven candidates. Synthetic
fixtures prove machinery, not research population or label validity.

Phoenix Native Decision/Outcome Receipt v1 now supplies that capture and
resolution path. The direct bridge is identity-equivalent to this builder, but
the live corpus remains empty until real decision producers accumulate complete
receipt lineages.
