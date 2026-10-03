# Q10-DN3 Stable Multi-Step Direction Novelty Audit

## Question

Q10-SR4 found substantial one-ULP unreachable readout residuals. Q10-SR5 and
Q10-SR6 showed that a full 16-step capacity sweep is too expensive to run over
all engineering states. Q10-DN3 repeats the narrow sample after DN2 failed its
post-execution numerical audit: Gram-derived rank exceeded the available active
rows and cumulative curves were nonmonotone. DN3 uses direct active-row f64 SVD,
an explicit one-million relative rank multiplier fixed before execution, and
restores the parent constructor key `seed ^ tau_bits ^ trial`.

> Do 2–16 ULP committed moves add readout-space directions beyond the one-ULP
> span, and do those directions point toward the actual SR4 unreachable error?

This is diagnostic engineering only. It contains no repair search, scientific
inference, behavioral endpoint, or DH-08B authorization.

## Frozen sample

Fresh engineering seeds are `9631` and `9632`. Each seed is run on both sides
(`R`, `L`) and both taus (`4`, `16`). The captured reversal policy contains
trials 1–256, so the selected trials are exactly `1, 64, 128, 256`: early,
middle, and late reversal. This yields 32 events.

## Measurements

For every selected event, each legal interior coordinate is evaluated in both
directions for committed steps 1 through 16. The implementation streams sparse
effects into cumulative readout-space Gram matrices for step limits
`1, 2, 4, 8, 16`, then reports:

- rank and normalized error residual `R(k)` for each step limit;
- per-effect novelty fraction relative to the one-step span;
- alignment of novel components with the one-step unreachable error;
- one-step versus 16-step readout-row authority and newly authorized rows;
- numerical rank distribution of each coordinate's 32-effect family.

No repair coefficients are applied. The streamed matrices are a span audit,
not a claim that arbitrary linear coefficients are realizable by a monotone
per-coordinate path.

## Interpretation before execution

- Flat `R(k)` and near-zero novelty: multi-step moves add amplitude only; SR4's
  one-step structural diagnosis is sufficient.
- Falling `R(k)` with aligned novelty: multi-step directions are relevant and a
  compressed or sampled repair qualification is justified.
- Falling `R(k)` without alignment: multi-step span expands in irrelevant rows;
  do not infer repairability.
- Large row-authority expansion but flat `R(k)`: support grows without covering
  the observed error.
- Any nonfinite, identity, coverage, rank-bound, nesting, or firewall failure
  invalidates DN3.

The post-execution audit must independently confirm that every reported rank is
at most its active-row count, cumulative ranks never decrease, cumulative
residuals never increase beyond `1e-10`, and the 32-event coverage is unique.

## Firewall and lineage

The parent Q10-SM hashes are checked at seal and execution. Receipts contain no
behavioral fields and declare zero scientific seed bundles. The independent
reviewer checks the 32-event coverage, plan hash, pre-execution manifest, finite
metrics, and the absence of forbidden fields.
