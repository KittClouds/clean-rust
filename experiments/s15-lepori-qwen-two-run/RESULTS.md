# Qwen two-run trial — verified results

Completed 2026-10-02. **Both authorized graft-training runs are complete.**
Final verification is PASS: exact replay of both production evaluations, all
13 matched candidate readouts and 16 global readouts (final and best-TRAIN
scores), unchanged sealed sources/inputs, shared initialization, and canonical
target replay on all 20,000 TRAIN / 2,000 DEV worlds.

**Program reading:** Qwen remains live. Under the repaired harness, training
substantially improves goal-relative access, rather than merely exposing a strong
initialization baseline. This is not a clean substrate-only victory over MiniCPM:
MiniCPM is a historical reference with source-qualified harness defects, not a
repaired matched control. No third graft run, rescue architecture, protected TEST
evaluation, or Lexi coordination was started.

## The two runs

| DEV measure | Run 1 baseline | Run 2 isolation |
|---|---:|---:|
| Candidate goal-relative balanced accuracy | 0.9468 | 0.9454 |
| Candidate legality balanced accuracy | 0.8530 | 0.8862 |
| Exact logged-action accuracy, eligible rows only | 0.7863 | Not evaluated/reconnected |
| MOVE exact logged-action accuracy | 0.4740 | Not evaluated/reconnected |
| ACTIVATE exact logged-action accuracy | 0.9200 | Not evaluated/reconnected |
| NOOP exact logged-action accuracy | 0.9885 | Not evaluated/reconnected |
| Frozen selection epoch | 8 | 8 |

Run 2 excludes global/action losses. Its inactive global/action/alias heads are
byte-identical to initialization. Legality improves by 0.0333 relative to Run 1;
aggregate goal accuracy is approximately retained, not improved by isolation.

Both runs use the same full initialization, six-surface graft topology, exhaustive
28-candidate universe, frozen TRAIN-only normalization/prevalence/variance
reference, TRAIN-only renderer consistency, 8 epochs, 64-world batches, AdamW
3e-4 / weight decay .01 / cosine / clipping 1 / seed 0. Qwen's hidden width is
1024 rather than MiniCPM's 1536, so parameter counts differ: 1,908,367 active
parameters in baseline and 1,907,618 in isolation.

## Check 1 — initialization accessibility versus training delta

Fixed MLP readout: Linear(input,64)-GELU-Linear(64,1), AdamW 1e-3 / wd .01 /
cosine / clip 1 / seed 0 / 4 epochs / **64 worlds**, final-epoch DEV reporting.
The linear arms are also reported in the receipts; this table is not a
DEV-selected maximum over readouts. Aliases are not extra capability cells.

| Independent channel | Frozen representation | Init probe | Trained probe | Delta |
|---|---|---:|---:|---:|
| Solvability | s | 0.6947 | 0.9609 | +0.2662 |
| Initial goal satisfied | s | 0.7035 | 0.9778 | +0.2743 |
| Missing information present | s | 0.7278 | 0.8791 | +0.1513 |
| Contradiction present | s | 0.6908 | 0.9932 | +0.3024 |
| Candidate legality | e_j | 0.7781 | 0.8557 | +0.0775 |
| Candidate satisfies goal | e_j | 0.5556 | 0.9477 | +0.3920 |

Legality is accessible at initialization **and** improves after training. The
goal-relative candidate channel does not clear the inherited margin at init,
but clearly does after training. These are accessibility changes under the fixed
readout family, not proof that the frozen backbone acquired new information.
Production-head initialization is a different baseline: goal 0.5082 and legality
0.4277. It must not be confused with a fitted probe on untrained representations.

Matched goal probes: e_j linear 0.9466 / MLP 0.9477; c_j linear 0.5703 / MLP
0.5797; [c_j;s] linear 0.9264 / MLP 0.9479. Fixed 12-epoch sensitivity: e_j MLP
0.9478, c_j MLP 0.5901. The candidate-local branch alone is weaker; this is a
representation localization observation, not a demonstrated binding mechanism.

Known-solvable linear and MLP positive controls both score 1.0000. The legality
capability control also works. Global probes were added after Run 1 at the user's
request; they are explicitly descriptive, not prospective checkpoint selectors.

## Check 2 — unsatisfied-goal and legal-MOVE slices

| Candidate goal-relative DEV balanced accuracy | Run 1 | Run 2 |
|---|---:|---:|
| All valid candidates | 0.9468 | 0.9454 |
| Initial goal not satisfied (678 positive / 20,180 negative) | 0.7920 | 0.7273 |
| Legal MOVE, initial goal not satisfied (468 positive / 1,299 negative) | 0.7049 | 0.6155 |

The baseline improvement is not solely an already-satisfied-goal shortcut.
However, isolation weakens the hard legal-MOVE slice despite retaining the
aggregate score. **Do not describe Run 2 as an across-the-board goal-binding win.**
No slice enters selection, changes a threshold, or retrofits a survival rule.

## Checks 3 and 4 — endpoint eligibility and optimal-set denominators

Of 2,000 DEV worlds, 960 have no selected action and 109 have a selected action
absent from the candidate set. Both categories remain unscored: no coercion,
default candidate, or fabricated action identity. The exact-action endpoint covers
931 worlds (46.55% of DEV), not the entire policy population.

| Run 1 action measure | Hits / denominator | Rate |
|---|---:|---:|
| Predicted action equals logged action, all eligible rows | 732 / 931 | 0.7863 |
| Predicted action belongs to supplied gold optimal set, nonempty sets only | 334 / 496 | 0.6734 |
| Predicted action equals logged action, same 496-row subset | 302 / 496 | 0.6089 |

There are 435 eligible rows with empty supplied gold optimal sets. They do not
enter the meaningful optimal-set denominator and are not repaired with invented
NOOP truth. The raw all-eligible optimal-set calculation is 334/931 = 0.3588;
it is retained as an audit value, not treated as a meaningful success/failure rate.
Logged exact action and optimal-set membership are different endpoints.

With variable candidate cardinalities, expected accuracy for uniformly selecting
a candidate **per row** is E[1/m] = 0.0801. The inherited reciprocal-mean statistic,
1/E[m] = 0.0637, is separately labeled; it is not that expected accuracy.

## Identity, repairs and preserved attempts

Model: Qwen/Qwen3.5-0.8B-Base, revision
`dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68`. Hugging Face CLI pinned and verified
all 12 repository files. All 320 text-tower parameter tensors match disk exactly;
the text tower has 752,393,024 parameters, is frozen and uses no vision inputs or
chat template. Full 25-entry hidden stack and depths 6/12/18/24 qualified.

Independent entity replay finds zero cross-world references. All candidates are
retained. TRAIN/DEV renderer truth signatures have zero mismatches. Absent mention
bindings use the inherited zero-vector convention, receipted individually (807
TRAIN / 99 DEV); no latent-world names are substituted into observation features.

Preparation v01's failed strict mention extraction is preserved. The first
candidate-batched diagnostic port is also preserved as **unmatched exploratory
analysis** in `recoverability`; it had a different optimizer dose and is excluded
from the matched tables above. A sealed continuation corrected the inherited batch
unit to worlds in `recoverability-world-v02`, without rerunning completed Phase 1.
MiniCPM checkpoints, caches and numerical receipts remain unchanged.

## Receipts

Artifact root: `C:/phoenix-target-overgraph/s15-qwen-two-run-20261001-v02`.

- `trial-verification.json`: final PASS, exact scoring replay and denominator audit.
- `phase1/receipt.json`, `phase1b/receipt.json`: the two graft runs.
- `recoverability-world-v02/receipt.json`: matched candidate init/trained probes.
- `global-init-probes-v01/receipt.json`: all independent global access checks.
- `canonical-label-replay.json`: exact targets and endpoint eligibility on TRAIN/DEV.
- `dataset-verification.json`: packed entity/candidate identity and alias replay.
- `prepare-lock.json`, `training-lock.json`, `continuation-lock.json`: pinned identities.

Protected TEST and BANK-v2 remain unopened. These are single-seed TRAIN/DEV results,
not protected generalization evidence or a claim that action computation is solved.
