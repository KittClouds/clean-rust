# AR-04C — Sentinel Reuse and Adaptive Generalization Leakage

**Status:** prospective closed-loop experiment. No result exists until the
frozen run completes and its integrity receipt validates. This is a new AR-04
identity, not an AR-03 continuation or a retuning exercise.

## Parent seal and question

Parent result commit: `c6daf025d3db08908a5a16bd2e0ee50e69c08787` on
`codex/ar-04b-generalization-objective-bridge-20260921`.

AR-03D-R1 remains terminal: projected-order runtime benefit was not replicated
and is closed. H47/H49 remain bounded diagnostic results; no AR-03 controller
work is reopened. AR-04B supports bounded H52/H53 only: independent sentinel
evidence partially aligned immediate action ranking with the final measurement
objective, and Taylor scores tracked exact sentinel rankings at the tested
scale. Neither result establishes closed-loop benefit or grants runtime
authority.

AR-04C asks whether the AR-04B bridge survives repeated operational exposure:

> Does an independent sentinel panel remain useful when it repeatedly controls
> action selection, and does a prospectively rotating, non-reused panel behave
> differently from reusing one fixed panel?

This is a three-arm diagnostic/controller comparison on the frozen synthetic
substrate. Only the verifier examples differ between arms. No Taylor scoring,
projected ordering, quota repair, adaptive refresh, panel-size tuning, or other
new controller feature is allowed.

## Frozen substrate and runtime

- Fresh five-dataset × five-initialization crossed design (25 cells), generated
  under AR-04C-only seed namespaces.
- The AR-03A-R2 8D interaction-label generator and 8-8-8-3 ReLU MLP, 171
  parameters, bounds `[-2,2]`, and action grammar `{0, ±0.005, ±0.01, ±0.02}`.
- Same P16 proposal generator, K2 top-2 × top-2 selector, rotating coordinate
  pair schedule, commit function, and four sequential replans per evidence
  round as AR-03D-R1.
- 4,200 decision slots per cell and arm; checkpoints at `0`, `600`, `2400`, and
  `4200` commits.
- Paired arms within a cell share the training set, initial model, proposal
  stream seed, evidence-round proposal indices, and schedule offsets. Their
  selected actions and resulting states may diverge naturally.
- Training proposals always use P16 examples sampled from the 96-example
  training set. Sentinel or final-measurement samples never enter proposal or
  candidate generation.

## Arms

1. **`training_full96`** — exact verifier score on all 96 training examples.
   This is the ordinary training-objective reference. It is not compute-matched
   to the sentinel arms; the sample count and measured cost difference will be
   reported explicitly.
2. **`sentinel_fixed128`** — exact verifier score on one independent 128-example
   panel per crossed cell. That same panel is reused at all 1,050 evidence
   rounds (four decisions per round; 4,200 decision exposures per row).
3. **`sentinel_rotating128`** — exact verifier score on a fresh independent
   128-example panel at each evidence round. Panels are selected prospectively
   by a fixed seed/round mapping, never reused, and each is used for exactly
   four sequential decisions. This provides 134,400 distinct rows per cell.

The fixed-versus-rotating contrast is the matched reuse comparison: both use
exact V128 on the same four-commit evidence clock. The training arm uses exact
V96 and is an objective control, not a matched-cost arm. No arm accesses the
final-measurement data during trajectory execution.

Each 128-example panel is assembled from the first 64 rows of two independently
seeded generator draws, then permuted by a separately seeded Fisher-Yates
ordering. All panel seeds are predeclared by namespace and cell/round index.
Rotating panels are generated from their frozen seed schedule before their
cell's trajectories run; panel hashes and seed identities are recorded. Exact
row-level checks enforce disjointness among training, fixed sentinel, rotating
sentinel, and final-measurement examples. Rotating raw rows are reproducible
from the frozen generator, seeds, and source commit; the panel ledger retains
each panel's SHA-256 rather than committing a 121 MB duplicated sample bank.

## Measurement and chronology

Primary endpoint: final independent 96-example measurement cross-entropy at
commit 4,200, summarized first by the 25 paired dataset × initialization cells,
then by equal-weight cell mean/median and dataset/initialization marginals.
Accuracy is secondary. The final set is generated, persisted, and first read
only after every arm's trajectory and checkpoint model has been frozen.

At checkpoints `0/600/2400/4200`, the diagnostic stage freezes a P16 candidate
set using training data only, then measures exact immediate utility on (a) the
arm's operational verifier and (b) the untouched final-measurement set. This
produces Spearman, pairwise agreement, top-1 agreement, and candidate-set regret
of operational ranking against the final-measurement ranking. These diagnostic
scores are computed only after all training trajectories are complete and
cannot affect them.

At nonzero checkpoints, the rotating arm's operational panel is the panel used
for the last completed evidence round (`stage / 4 - 1`); at stage 0 it is the
first panel, before any exposure. The fixed arm uses its fixed panel at every
stage. The training arm uses the full training set. Checkpoint operational
loss minus final-measurement loss is reported as an operational-to-final gap;
it is diagnostic, not a promotion metric.

The primary reuse diagnostic is the checkpoint trajectory of operational
ranking alignment with final-measurement action utility. Report each stage,
arm, dataset, initialization, and cell. Also report final loss/accuracy,
training loss, operational-panel loss, selected-program training-objective
shadow utility, harmful/non-positive selection counts and magnitude, verifier
sample/evaluation counts, panel exposure, and measured wall/component costs.

## Prospective interpretation

- If neither sentinel arm improves on the training-objective arm, the AR-04B
  bridge did not survive repeated operational use under this protocol.
- If fixed and rotating sentinel arms both help similarly, the bridge survives
  repeated exposure and the reuse contrast is small at the measured horizons.
- If rotating helps while fixed alignment/performance degrades, fixed-panel
  reuse is consistent with adaptive sentinel contamination under this design.
- If fixed beats rotating, report that without post-hoc rescue; stable evidence
  may be useful despite reuse.
- Any mixed or seed-sensitive result remains mixed. No extra seeds, altered
  panel sizes, alternate refresh clocks, or controller repairs are authorized
  by this run.

These outcomes are bounded to this generator, architecture, action grammar,
runtime, sample counts, and 4,200-slot horizon. No result promotes an AR
mechanism into Phoenix or reopens AR-03, CF-01, or fly-science work.

## Frozen seed namespaces

All role seeds are `prefix | one_based_index`; namespaces are pairwise disjoint.
The rotating panel index is dataset-major, initialization-major, then
evidence-round-major. Two data seeds are assigned per panel. Order seeds have
one entry per fixed/rotating panel.

| Role | Prefix | Count |
| --- | --- | ---: |
| Training datasets | `0xa404_c101_0000_0000` | 5 |
| Final measurement datasets | `0xa404_c102_0000_0000` | 5 |
| Model initializations | `0xa404_c103_0000_0000` | 5 |
| Paired runtime proposal streams | `0xa404_c104_0000_0000` | 25 |
| Fixed sentinel draws | `0xa404_c105_0000_0000` | 50 |
| Rotating sentinel draws | `0xa404_c106_0000_0000` | 52,500 |
| Fixed/rotating panel order | `0xa404_c107_0000_0000` | 26,275 |

## Integrity, collection, and outputs

The collector refuses an existing output directory, dirty source, wrong branch,
wrong parent ancestry, repeated role seed, invalid arm/panel counts, or sample
overlap. The frozen source and protocol are committed and pushed before
collection. Compile optimized into `D:\adaptive-runtime-targets\ar-04c-20260921`
and execute from this C: worktree. Incomplete outputs are retained and are not
silently overwritten or repaired.

Output path: `artifacts/run-20260921-ar04c-v1/`.

- `data/` — training, fixed sentinel, and post-trajectory final-measurement
  sample files; rotating panels are regenerable from the panel manifest.
- `dataset-manifest.csv`, `fixed-panel-manifest.csv`,
  `rotating-panel-manifest.csv` — seeds, sample counts, exposure schedule, and
  content hashes.
- `trajectory-decisions.csv`, `checkpoint-manifest.csv`,
  `checkpoint-models.bin` — action choices, exogenous stream fingerprints,
  training-objective shadow values, and frozen learner states.
- `checkpoint-action-scores.csv`, `ranking-metrics.csv`,
  `checkpoint-outcomes.csv`, `cell-contrasts.csv`, `summary.json`.
- `integrity-receipt.json`, `tools/validate_artifacts.py`,
  `validation-receipt.json`, and `RESULTS.md` (written after validation).

