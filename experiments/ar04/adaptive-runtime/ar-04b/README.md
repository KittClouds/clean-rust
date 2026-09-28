# AR-04B — Generalization Objective Bridge

**Status:** diagnostic protocol; no score controls training, proposal generation,
action selection, or verifier allocation. This is a new AR-04 identity, not an
AR-03 repair and not an AR-04A continuation-value experiment.

## Parent seal and scope

Parent result commit: `6f731c135e56fc87cb7f6cdfaa0ae2b26cd8a0dd` (AR-04A).
AR-04A remains unchanged. The AR-03D-R1 projected-order runtime benefit remains
not replicated and closed. H47/H49 are diagnostic only; AR-03 controller work
is not reopened. CF-01 and fly-science artifacts are outside scope.

AR-04A found that training-objective immediate utility was nearly unrelated to
held-out action effect already at `H=0`, while the immediate held-out score
strongly retained its ranking through forced common continuations. AR-04B asks
whether small, independent sentinel panels can estimate that held-out-aligned
**immediate** action ranking. No continuation is used in AR-04B.

## Frozen estimands

For frozen model `W`, candidate action `a`, and dataset `D`, define exact
immediate utility as `U_D(a) = L_D(W) - L_D(T_a(W))`; positive means the
candidate lowers mean cross-entropy on `D`.

- `U_train`: exact utility on the full 96-example training set.
- `G0_reference`: exact utility on an independently generated 96-example
  final measurement set. This is the reference ranking, not a population-truth
  claim and never affects state or candidate generation.
- `S_n_exact`: exact utility on a sentinel prefix of size
  `n ∈ {8,16,32,64,128}`.
- `S_n_taylor`: `-mean_x(gradient_W loss_x · delta_a)` over the same sentinel
  prefix and candidate action. It is a diagnostic first-order estimate only.

Within a dataset, each of four independent 128-example sentinel pools is made
from the first 64 rows of each of two separately seeded draws from the frozen
AR-03A-R2 generator. A separately seeded Fisher-Yates permutation fixes the
panel order; each `n` uses its prefix. The five panel sizes are therefore
nested and paired, while the four panel pools are independent. Sentinel pools
are shared across the five initializations and three states for that dataset;
they are repeated measurements, not independent replication units.

Training, sentinel, and final measurement samples use disjoint seed namespaces.
An exact row-level overlap check must pass before scoring. Sentinel and final
measurement sets are not inputs to the state trajectory or candidate builder.
Candidate identities are frozen and fingerprinted before any sentinel or final
measurement utility is calculated.

## Frozen substrate and crossed design

- Same synthetic 8D interaction-label generator and 8-8-8-3 ReLU model as
  AR-04A, imported read-only from AR-03A-R2.
- Same 96-example training-set size, parameter/action bounds, K2 grammar,
  rotating pair schedule, P16 proposal, V48 hash-placebo verifier, and four
  commits per evidence round as AR-04A's state-generation substrate.
- Five fresh training datasets × five fresh initializations (25 crossed cells).
- Frozen learner snapshots after commits `600`, `2400`, and `4200` (75 states).
- At each state, one fresh P16 proposal selects the existing K2 top-2 × top-2
  compound candidates per legal rotating pair block. The pre-existing
  deterministic development/evaluation diagonal split is preserved; only the
  two evaluation compounds per eligible block are scored. Candidate generation
  receives training data only. This is a measurement candidate set, not a
  runtime decision.
- Four independent sentinel pools per dataset, each 128 examples; all five
  declared panel sizes use fixed prefixes of each pool.
- Exact final measurement set: one independently seeded 96-example draw per
  training dataset, shared over its five initializations.

The crossed dataset × initialization cell is the replication unit. States,
actions, and four sentinel panel replicates are nested. Reports first average
panel replicates within state, then the three stages within each crossed cell,
then weight the 25 cells equally. Dataset and initialization marginals are
reported separately. No outcome-dependent state selection, seed replacement,
panel replacement, or action-set change is allowed.

## Primary analysis

For each state, compare `U_train`, `S_n_exact`, and `S_n_taylor` with the
candidate-wise `G0_reference` vector using:

- Spearman rank correlation with average ranks for ties;
- pairwise ordering agreement, excluding tied pairs and reporting the usable
  pair count;
- top-1 agreement, breaking exact score ties by the lowest frozen action ID;
- candidate-set regret: best `G0_reference` utility minus the reference utility
  of the candidate selected by the source score.

Report these at each panel size and method, with equal-cell summaries plus
dataset and initialization marginals. Also report exact-versus-Taylor sentinel
fidelity on the same panel (RMSE, Spearman, and pairwise agreement). These are
descriptive diagnostic metrics; no pass/fail threshold is chosen after results.

## Integrity boundary and outputs

The runner refuses an existing output directory, dirty source, wrong branch or
parent ancestry, reused/overlapping seeds, and any duplicate sample row across
training, sentinel, and final measurement pools. It records source commit,
optimized executable SHA-256, seed roles, data hashes, state/action
fingerprints, full raw action scores, and cardinalities. Candidate generation
is a separate function with no sentinel/final-measurement argument.

The run is measurement-only. It does not fit a predictor, choose a panel,
change an optimizer, control training, or alter any AR-03/AR-04A mechanism.
No runtime promotion is authorized by any result.

Outputs under `artifacts/run-20260921-ar04b-v1/`:

- frozen raw train, final measurement, and sentinel sample pools;
- `dataset-manifest.csv`, `state-manifest.csv`, `candidate-manifest.csv`;
- `reference-action-scores.csv`, `sentinel-action-scores.csv`;
- `ranking-metrics.csv`, `immediate-vs-generalization-ranking.json`;
- `taylor-fidelity.json`, `integrity-receipt.json`;
- `tools/validate_artifacts.py` independently rechecks file hashes, sample
  disjointness, score cardinalities, and every state-level ranking metric;
- `validation-receipt.json` is written only after that read-only audit passes;
- `RESULTS.md`, added only after an independent read-only artifact audit.

## Frozen seed namespaces

All seeds use a unique AR-04B prefix and one-based low-32-bit indices. These
prefixes are disjoint from AR-04A and the AR-03 namespaces.

| Role | Prefix | Count |
| --- | --- | ---: |
| Training dataset | `0xa404_b101_0000_0000` | 5 |
| Final measurement dataset | `0xa404_b102_0000_0000` | 5 |
| Sentinel sample draws | `0xa404_b103_0000_0000` | 40 |
| Sentinel panel permutation | `0xa404_b104_0000_0000` | 20 |
| Model initialization | `0xa404_b105_0000_0000` | 5 |
| State-generation runtime | `0xa404_b106_0000_0000` | 25 |
| Candidate proposal | `0xa404_b107_0000_0000` | 75 |
