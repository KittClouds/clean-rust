# OBS-OPEN-02 — Discovery Measurement Protocol and Scale-Space Census Freeze

## Authority boundary

This gate defines how the qualified OBS-OPEN-01 discovery population may later be measured. It does not read substantive discovery observations and does not open the untouched confirmation population.

Parent qualification root:

`6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235`

Parent commit:

`8c6902181d6252d635c45d784ffd1f072006b2fc`

The observer, clock transport, source coverage, session admission, and temporal partition are inherited unchanged from OBS-OPEN-01.

## Scientific question

No substantive claim is authorized here. The purpose is to preregister an exhaustive, reversible opening-range scale-space and boundary-response census over the complete peer family:

`R_k = [09:30, 09:30 + k minutes)`, for `k = 1 ... 30`.

Every duration is a peer. No duration is preferred, optimized, or selected from later behavior.

## Object identity and dependence

The fundamental identity is `(session_id, range_duration_k, interaction_timeframe)`. The thirty ranges are nested observations of one session, not thirty independent experiments. Session identity remains the primary resampling and dependence unit. Candle rows and range rows must never be treated as independent by default.

Frozen observer states and typed events remain authoritative. Derived measurements are sidecars with explicit ancestry and never replace the source observer record.

## Measurement views

The first-pass machinery exposes four reversible views:

1. **Raw geometry:** high, low, midpoint, width, freeze time, knowledge time, eligibility, and source lineage.
2. **Range-relative geometry:** `(price - midpoint) / (width / 2)` when width is nonzero. This is an additional view. Degenerate width is `NOT_EVALUABLE_GEOMETRY`, never zero.
3. **Interaction sequence:** completed-candle locations and frozen grammar events, preserving event type, order, timing, censoring, and unavailable states.
4. **Continuous path:** raw path plus mechanically derived displacement, excursions, path length, efficiency, returns, and duration. Censored objects expose observed prefixes only.

A fifth relational view records adjacent and contiguous cross-scale relations. It measures how the observer family changes as `k` changes; it does not identify a correct scale.

## Causality and time

Every record retains event time, range freeze time, knowledge time, eligibility, censor time, and session termination. A retrospective measurement may summarize a completed object, but it may not imply that information was available before its recorded knowledge time. No future confirmation observation may enter a discovery artifact.

## Typed availability

The following states remain distinct: `ELIGIBLE`, `NOT_EVALUABLE`, `CENSORED`, `DATA_GAP`, `UNAVAILABLE`, `NOT_APPLICABLE`, `OPEN`, and `FROZEN_UNOPENED`. Missingness is never converted to zero, false, a negative outcome, or an omitted denominator.

## Statistical contract

The session is the primary independent unit. The frozen protocol uses a deterministic session-block bootstrap with 2,000 resamples, seed `20260814`, and percentile 95% intervals where uncertainty intervals are requested. Every estimate carries its eligible denominator, censoring count, unavailable count, session support, and temporal support.

Predeclared robustness views are aggregate discovery, calendar month, server-offset regime, leave-one-supported-month-out, and chronological block. These views are not search knobs. New strata discovered after opening the drawer are exploratory and cannot inherit confirmatory status.

## Multiplicity and candidate classes

The multiplicity family is measurement view × range duration × temporal view. The complete descriptive census reports every preregistered cell, including empty and not-evaluable cells. An isolated maximum, attractive plot, or single duration cannot become a finding by selection.

Candidate evidence classes are neutral: `RECURRING_STRUCTURE`, `SCALE_DEPENDENT_STRUCTURE`, `SCALE_STABLE_STRUCTURE`, `TEMPORALLY_UNSTABLE_STRUCTURE`, `REPRESENTATION_SENSITIVE_STRUCTURE`, `CONDITIONAL_STRUCTURE`, `SUPPORTED_NULL_OR_NEAR_NULL`, `INSUFFICIENT_SUPPORT`, and `NOT_EVALUABLE`.

Promotion requires an exact finding identity, discovery population hash, denominator, measurement and representation identities, uncertainty receipt, multiplicity family, temporal support, sensitivity receipt, insufficiencies, and a future confirmation estimand. A promoted candidate remains unconfirmed until a later gate opens the frozen confirmation partition.

## Confirmation firewall

Only the discovery partition may be opened by the later execution gate. The confirmation partition remains `FROZEN_UNOPENED`. The guard fails closed on confirmation paths, confirmation partition identifiers, or any request that does not explicitly declare the discovery partition. Tests use synthetic and adversarial inputs only.

## Implementation-before-observation

Before any real discovery output is read, the measurement code is tested against synthetic fixtures covering nested identity, boundary equality, degenerate geometry, missing observations, discontinuities, censored suffixes, event ordering, and adjacent/contiguous scale transitions. Real discovery values are not golden fixtures.

## Determinism

The protocol binds the parent qualification root, observer identity, discovery and confirmation manifest identities, measurement and statistical contracts, candidate-promotion contract, firewall, code identity, and synthetic fixture identities. Two clean protocol builds must reproduce byte-identical protocol artifacts and seal receipts.

## Forbidden in OBS-OPEN-02

No substantive range-width distribution, event frequency, direction, persistence, excursion, terminal-location, scale relationship, trajectory example, plot, candidate regularity, model, economic analysis, or trading rule may be inspected or reported. This gate freezes the eyepiece; it does not hand it to the observer.

## Exit condition

OBS-OPEN-02 exits only with a sealed measurement contract, representation contracts, dependence and uncertainty contract, multiplicity contract, candidate schema, confirmation firewall, synthetic/adversarial test pass, and deterministic protocol rebuild. Substantive discovery remains `FROZEN_UNOPENED`.
