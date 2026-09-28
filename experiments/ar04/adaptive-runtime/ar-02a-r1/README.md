# AR-02A-R1 — Corrected verifier weighting and evidence-size oracle

Status: completed, engineering-only, toy-scale; no biological correspondence and no general optimizer claim. AR-02A remains unchanged as the original record.

## Questions

1. Does verifier quality depend on sample composition after correcting unequal quota weighting?
2. Does the AR-01 proposal/verifier asymmetry port: does P16/V96 work when P16/V16 does not?
3. If verifier evidence matters, do population-weighted cell or decision-margin strata help at 16 or 48 examples?

## Frozen protocol

- Reuse AR-02A's memory-mapped 12-cell anisotropic Gaussian dataset exactly (SHA-256 `a83d5dcce8bd8926cf1d548c58d4a9cbbef0ca97c72e1fd4331bc5d825a7a14a`). Keep the copied AR-00 K2 model, initialization, bounds, action grammar, pair partition/schedule, top-2 shortlist, 4 commits per evidence round, 4,800 total commits, and the same three seeds.
- Keep validation (48 observations) fully outside proposal, verifier, stratifier construction, schedule, and selection. Train-only generative margins define the decision strata.
- Verifier estimator arms:
  - Random 16 and 48: uniform draws with replacement and ordinary sample mean.
  - Class-weighted 16: five per class plus one extra observation whose class rotates deterministically by evidence round; average within class, then average the three class means equally. Class-weighted 48 uses 16 per class and the same estimator.
  - Cell-weighted 16: one example per each of 12 cells plus four repeats assigned by a deterministic rotating schedule; average within cell, then average the 12 cell means equally. Cell-weighted 48 uses four per cell.
  - Decision-margin-weighted 16: one example per each of 12 class × class-conditional Bayes-margin quartile strata plus four rotating repeats; weight each stratum equally. Margin-weighted 48 uses four per stratum.
  - Full training verifier: all 96 training examples, ordinary mean.
- Decision strata are constructed once from the frozen training data and known Gaussian generator. For each class, calculate the true-class log-mixture likelihood minus the highest competing-class log-mixture likelihood; sort that class's 32 examples and assign four rank quartiles of eight examples each. This yields 12 equal-population strata. It uses no model output, validation data, or runtime outcome.
- Proposal/verifier oracle matrix: `P16/V16 random`, `P16/V96 full`, `P96/V16 random`, `P96/V96 full`. In P96 conditions, proposal ranking uses the complete training set; in V96 conditions, compound scoring uses the complete training set. K2's action shortlist remains unchanged.
- At each accepted commit, record full-training loss change in shadow. Every 50 commits, also compute the exhaustive full-training immediate best across all scheduled blocks and the complete seven-by-seven action grid (singletons on the unmatched coordinate); compare the runtime-selected transition against that reference. This audit never affects selection. Regret percentiles are therefore explicitly sparse-checkpoint metrics, not per-commit regret.
- Run every declared spec on all three seeds. No best-seed selection or post-hoc quota changes.

## Outputs and integrity

- `ar-02a-r1-runs.csv`: per-seed metrics, cost counters, harmful-commit magnitudes, sparse full-reference regret statistics.
- `ar-02a-r1-curve.csv`: train/validation curves every 50 commits.
- `decision-strata.csv`: frozen train-example class, cell, generative margin, and assigned margin stratum.
- `ar-02a-r1-report.json`: protocol and per-spec mean summary.
- `gaussian-cells.bin`: exact reused AR-02A dataset artifact.
- Unit tests cover margin quartiles, quota rotation, population-weighted utility, K2 selection parity, and regret-audit accounting. The smoke test uses a four-commit run; the full experiment is run by the release binary.

## Interpretation limits

Only three seeds are used. The Bayes-margin strata are available because this synthetic generator is known; that is not a claim that real tasks provide such strata. The full-reference regret is audited every 50 commits and must not be described as dense per-step regret. Runtime timing includes an expensive shadow full-training audit and exhaustive reference checks; it is diagnostic cost, not production throughput. AR-02B/C remain gated on reviewing these results.

## Observed results

Completed 33 runs (11 configurations × three configured seeds), 4,800 commits per run, in 415.79 seconds total. The copied dataset hash matches AR-02A. The generated curve CSV contains 3,168 observations (96 checkpoints × 33 runs); all runs have 96 sparse regret audits. Random P16/V16 reproduces AR-02A's independent-random validation loss exactly (0.462739 mean), confirming the frozen K2/proposal lineage.

Validation loss is reported as mean ± sample standard deviation across the three seeds; accuracy is the seed mean. These are descriptive small-n results, not inferential claims.

| Proposal / verifier | Validation loss | Validation accuracy |
| --- | ---: | ---: |
| P16 / V16 random | 0.462739 ± 0.031336 | 89.6% |
| P16 / V16 class-weighted | 0.485879 ± 0.051541 | 83.3% |
| P16 / V16 cell-weighted | 0.446349 ± 0.007588 | 84.7% |
| P16 / V16 Bayes-margin-weighted | 0.473971 ± 0.050565 | 83.3% |
| P16 / V48 random | 0.450892 ± 0.016046 | 85.4% |
| P16 / V48 class-weighted | 0.404108 ± 0.029878 | 84.0% |
| P16 / V48 cell-weighted | **0.360282 ± 0.018774** | 86.1% |
| P16 / V48 Bayes-margin-weighted | 0.417587 ± 0.030486 | **88.2%** |
| P16 / V96 full training set | 0.246372 ± 0.059526 | 91.0% |
| P96 / V16 random | 0.283027 ± 0.074991 | **93.1%** |
| P96 / V96 full training set | 0.344532 ± 0.000000 | 91.7% |

AR-02A's existing baselines, not rerun in R1, were AdamW at 0.292199 validation loss / 92.4% accuracy and sign descent at 0.253423 / 90.3%.

### Readout

- **Evidence independence and stronger verification replicate.** P16/V16 random matches AR-02A exactly. Moving to P16/V96 improves mean validation loss by 0.216367, with lower loss on all three seed-matched comparisons. The frozen K2 path remains verifier-sensitive on this task.
- **Coverage-aware verification has a bounded positive transfer at 48 examples.** At V48, all three equally weighted estimators beat same-seed random V48 on validation loss: class weighting by 0.046785 mean, cell weighting by 0.090610, and class-conditional Bayes-margin weighting by 0.033306. Cell weighting is best on loss; margin weighting is best on accuracy. At V16, none of the weighted approaches shows a consistent paired advantage. Thus the result is not “coverage rescues a 16-example verifier”; it is evidence that balanced coverage can help at this larger, still-half-dataset budget on this task.
- **The geometry choice matters.** Cell, class, and decision-margin strata all beat random at V48, but with different magnitudes. This does not establish that latent cells are generally the right geometry. The Bayes-margin result shows the improvement is not unique to the generator-cell partition in this run.
- **The P/V oracle matrix is non-monotone.** P96/V16 improves substantially over P16/V16, while P16/V96 performs best on mean validation loss. P96/V96 follows the same deterministic trajectory under all three seed labels (effective replication count one), reaches low training loss (0.062251), but has 0.344532 validation loss. Full-data proposal plus full-data verification therefore does not improve generalization here; do not infer that noise is universally beneficial from this single deterministic path.
- **Accuracy remains insufficient.** P96/V16 has the highest mean accuracy, while P16/V96 has lower mean validation loss. Keep loss and per-seed outcomes primary.

### Audit and integrity notes

- Corrected stratified scores are equal-weight means of within-stratum means; quota imbalance changes sampling variance, not population weights. The one extra class quota at V16 rotates across classes; the four extra cell/margin quotas rotate across their strata.
- All 33 run rows and 3,168 curve rows are present. The reused training/validation file SHA-256 is `a83d5dcce8bd8926cf1d548c58d4a9cbbef0ca97c72e1fd4331bc5d825a7a14a`.
- Regret is the selected program's full-training immediate utility gap against an exhaustive scheduled-block reference, sampled every 50 commits. V96 arms have no negative full-training commits by construction, but this does not imply good validation generalization.
- Mean runtime was approximately 7.2 s for V16, 9.6 s for V48, and 12.2 s for P16/V96; P96 proposal runs cost about 27.7–31.1 s. These timings include shadow/audit work and are not production comparisons.
- **Strongest alternative explanation:** at V48, gains may reflect the lower sampling variance of equal-quota estimators rather than coverage geometry per se. Three seeds cannot distinguish those explanations decisively. The margin bins are prospective and training-only, but are tailored to the known synthetic generator.
- **Disposition:** the first AR-02A coverage comparison was confounded by unequal raw-mean weighting and an unusually small verifier. Corrected R1 provides bounded evidence that balanced verification helps at 48/96 examples, most clearly with equal cell coverage. The AR-01 coverage claim is not falsified, but its portability is conditional on evidence budget and task/stratum construction. Do not begin AR-02B/C from these results alone; review first.

## Build

Build output is directed to `D:\adaptive-runtime-targets\ar-02a-r1` (`:G` convention), separate from source and artifacts.
