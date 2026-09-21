# AR-04A — Continuation-Conditioned Action Value

Status: frozen diagnostic protocol; no measured outcome may control training.
This is a new experiment identity, not an AR-03 repair or confirmation.

## Predecessor seal

The terminal AR-03D-R1 result is recorded on branch
`codex/ar-03d-r1-independent-5x5-20260921`, commit
`486b262cbd5c4eda6a217d897acccc0c25e60e6b`.

- AR-03D was favorable but inconclusive; independent R1 reversed direction.
- R1 final held-out cross-entropy was 1.854741 projected versus 1.774218
  hash, difference +0.080523. Hash won 18/25 cells, four of five dataset
  marginals, and all five initialization marginals.
- The projected-order closed-loop runtime-benefit claim is **not replicated
  and closed**. D and R1 are not pooled.
- H47/H49 remain bounded diagnostic findings only. They do not authorize
  runtime promotion. No further AR-03 controller experiment is authorized.
- AR-03 source and result artifacts are inherited read-only and are not edited.
  AR-04A writes only beneath this new directory.

## Question and estimands

At a frozen state `W`, measure whether existing immediate utility ranks
candidate actions by their consequence after a common frozen continuation.
The measurement objective `J` is mean cross-entropy on the independent
measurement-only held-out set.

For action `a`, continuation realization `gamma`, and horizon `H`:

```text
Q_H(a | W, gamma) = J(W) - J(T_gamma(T_a(W)))
DeltaQ_H(a | W, gamma) = J(T_gamma(W)) - J(T_gamma(T_a(W)))
```

Larger is better. `DeltaQ` is the primary action-effect estimand because the
paired no-action branch subtracts the continuation's own effect. Both `Q` and
`DeltaQ` means and sample standard deviations across continuations are
reported. Immediate utility `u0_train` is the exact full-training-set loss
reduction under the frozen K2 program semantics; immediate held-out reduction
is logged separately as a measurement-only diagnostic. No held-out metric is
read by state generation, action generation, or continuation generation.

Each continuation is generated once from the unperturbed frozen state by the
unchanged hash-placebo K2 runtime, then its exact committed parameter updates
and exogenous proposal/verifier indices are frozen. Every candidate and the
no-action branch receives that same sequence. There is no branch-specific
replanning. Future updates are replayed without clipping; if any candidate or
no-action branch would hit a parameter bound during a continuation, that
entire state × continuation is marked bounds-censored and excluded for all
actions at that state. Censor counts and valid continuation support are
reported; no substitute continuation is drawn.

## Frozen design

- Substrate: same 8D synthetic interaction-classification generator and
  8-8-8-3 ReLU MLP (171 parameters), bounds, K2 action grammar, rotating
  pair schedule, P16 proposals, V48 hash-placebo verifier, and four commits
  per evidence round as the frozen AR-03D-R1 substrate.
- Fresh crossed factors: five training datasets × five independent model
  initializations (25 cells), with one independently seeded state-generation
  path per cell. Generate one independent held-out dataset per training
  dataset; it is shared across that dataset's five initializations.
- Frozen state stages: steps 600, 2,400, and 4,200, yielding 75 states.
- At each state, make a separate P16 candidate-proposal draw. Freeze the
  evaluation half of the existing K2 top-2 × top-2 compound shortlist for
  every legal two-coordinate pair block at that schedule phase. This is two
  programs per eligible pair block; it is the diagnostic action set, not a
  controller or an exhaustive global action universe. Action identities and
  the set fingerprint are recorded before future-value scoring.
- For each state, generate exactly eight unique, prospectively seeded
  128-commit hash-control continuations. Use prefixes of those same
  continuations at `H ∈ {0, 8, 32, 128}`. Seed namespaces and all assignments
  are frozen in `src/protocol.rs` before collection.
- State trajectory and continuation paths use only training examples and the
  frozen hash-control runtime. The measurement-only held-out data is used
  only to score the no-action and candidate branches at the declared horizons.

## Primary analysis

At each state and horizon compare the rank of `u0_train` with the rank of the
mean paired future effect `mean(DeltaQ_H)`; separately compare held-out
immediate effect with future effect to isolate train/held-out mismatch. Report
state-level Spearman correlation, top-1 agreement, pairwise ordering agreement,
tie counts, and candidate-set regret of selecting the immediate-utility winner
when judged by mean `DeltaQ_H`. Aggregate states equally within each
dataset × initialization cell, then report cell, dataset, and initialization
marginals; actions, continuations, and checkpoints are nested measurements,
not independent replication units.

Also report per-action `mean(Q_H)`, `sd(Q_H)`, `mean(DeltaQ_H)`, and
`sd(DeltaQ_H)` across the valid common continuations. Measure the spread in
future value among actions in the same within-state quartile of immediate
training utility. Quartiles are equal-count rank bins sorted by immediate
training utility, with action ID as the deterministic tie-break; they use no
future-value measurement.

Existing geometry is diagnostic only: log immediate train/held-out utility,
parameter/action identity and magnitude, training stage and state loss/RMS,
the frozen AR-03D projected ordering, and the output-gradient response
partition summaries. Report simple held-out state/action associations with
future mean and continuation sensitivity; fit no predictor, threshold, or
composite score.

## Integrity and required outputs

The runner refuses an existing output directory and a dirty source checkout.
It records source commit, optimized executable SHA-256, all seed values,
training/held-out dataset hashes, state fingerprints, candidate-set
fingerprints, continuation/action-sequence fingerprints, common-random-number
fingerprints, branch/horizon loss measurements, and bounds-censoring counts.

Output files:

- `action-continuation.csv` — complete valid action × continuation × horizon
  table, plus explicit censored state-continuation records in its own ledger.
- `state-manifest.csv`, `continuation-manifest.csv`, and
  `bounds-censor-ledger.csv` — frozen identities and replay audit.
- `immediate-vs-future-ranking.json`
- `horizon-decay.json`
- `continuation-sensitivity.json`
- `action-effect-vs-noop.json`
- `existing-geometry-associations.json`
- `integrity-receipt.json`
- `RESULTS.md` — written only after collection and independent validation.

No AR-04A value controls training or verifier sampling. No estimator,
controller, proposal change, or AR-03 tuning is authorized by this protocol.
CF-01 and fly-science artifacts remain untouched.

## Frozen seeds

Seed prefixes (index starts at one) are disjoint from one another and from the
AR-03 seed namespaces:

| Role | Prefix | Count |
| --- | --- | ---: |
| Training dataset | `0xa404_41da_0000_0000` | 5 |
| Held-out dataset | `0xa404_4e7a_0000_0000` | 5 |
| Initialization | `0xa404_1a17_0000_0000` | 5 |
| State-generation runtime | `0xa404_57a7_0000_0000` | 25 |
| Candidate proposal | `0xa404_ca7a_0000_0000` | 75 |
| Continuation | `0xa404_c07a_0000_0000` | 600 |
