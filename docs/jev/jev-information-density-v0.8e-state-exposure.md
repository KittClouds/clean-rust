# v0.8E — State-Exposure Contract Resolution

## Purpose and boundary

This is a bounded metadata-only construction stage following the sealed v0.8D
support-capacity result. It attempts to repair the best existing common-support
witness without changing the P* quotas, 100,000-group bank size, eligibility
firewall, profile tolerances, family/coverage requirements, or treatment gate.
It does not contact a model, extract features, materialize training data, or
access Phoenix.

The v0.8D source contracts, runs, and results remain read-only. This document
does not reopen or reinterpret v0.8D. It records the implementation boundary
for state-exposure diagnostics and bounded witness repair.

## Signature terminology

The unqualified phrase `input occurrence` is retired for this work.

- `state_signature`: digest of shared state/context before query- or
  candidate-specific material. It measures how decision views are distributed
  across underlying situations.
- `selector_input_signature`: digest of the complete model-visible input for
  one selector/query/candidate view.
- `training_signature`: identity of all values that can alter a training loss,
  including selector input, target semantics, decision type, visible candidate
  order, masks, weights, and loss mode.

These are distinct audit dimensions. A profile passing selector-input matching
does not imply state-exposure matching. Training-signature distance is the
learner-visible treatment measure; row-ID turnover is provenance telemetry.

## Frozen construction limits

The best v0.8D attempt is reconstructed exactly from its pinned support index,
quota allocator, and seed. It is the starting incumbent. The repair objective
is to reduce the frozen state-signature occurrence-histogram TV to `<= 0.02`.
All other frozen profile checks must continue to pass. No tolerance or target
may be changed by this implementation.

Allowed engineering includes metadata diagnostics, warm-started deterministic
swaps/cycles, bounded neighborhood optimization, checkpoints, and independent
validation. An implementation correction must state `semantic_impact: none`
and record its source hash and tests.

Bounded search failure is `WITNESS_SEARCH_BOUNDED_UNKNOWN`, not infeasibility.
The agent stops for review if satisfying the contract would require changing a
semantic definition, profile dimension, quota, size, threshold, eligibility
rule, protected artifact, or model-contact boundary.

## State histogram and witness repair

The state occurrence histogram counts the number of unique state signatures
appearing exactly `k` times in an arm. Its TV is calculated over those
multiplicity buckets, as in v0.8D. Diagnostics also list state-level A/B count
differences and support/stratum availability; these are explanatory and do not
replace the frozen histogram metric.

The best attempt is selected by recorded state TV, not by model outcomes. A
reconstructed candidate must match the v0.8D recorded metrics before it may be
used as an incumbent. Each accepted change preserves exact per-stratum quotas;
the independent validator recomputes selector, root, family, topology,
intervention, coverage, state histogram, source eligibility, and held-out
exclusion from source records.

## Result-dependent next step

Only an independently validated `state TV <= 0.02` freezes a P* profile. The
next authorized operation is a metadata-only common-profile treatment-capacity
test. It must establish a substantial distance between learner-visible
training-signature multisets before policy arms can be built. Target
`D_train >= 0.20` is desirable; `D_train < 0.10` after bounded search stops the
branch. No LFM/model contact is authorized in this stage.
