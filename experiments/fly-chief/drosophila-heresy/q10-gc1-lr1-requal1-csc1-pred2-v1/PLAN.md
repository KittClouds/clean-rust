# CSC1-PRED2: difficulty-stratified audit of the frozen PRED1 rankings

Engineering analysis of existing receipts only. No replay, fitting, score tuning,
new candidate domain, global assembly, GC2, AG1, behavior, or scientific seeds.
This is retrospective stratification of an already observed cohort, not a fresh
prospective test. Historical parents remain unchanged.

## Interpretation correction

PRED1's full cosine score had 93.4545% top-one success versus 87.2727% for its
deterministic random ordering, 89.8182% for magnitude, and 88.3636% for axis.
The partner-readout baseline achieved 100%; it must remain in every comparison.
It uses available singleton readout, not the held-out pair outcome, and is not
an oracle baseline. The geometry score has not beaten the strongest baseline.

The 60.4582% estimated saving was against exhaustive evaluation of each observed
pool. Random saved 57.7023%, a difference of 2.7558 percentage points of pool
size. These are simulated stopping costs on cached outcomes, not measured
runtime speedups, and exclude upstream domain-generation costs.

The pair domain was screened using full committed-state geometry before pair
readout replay. All 4,999 pairs are geometry-valid by construction. This cohort
cannot estimate discrimination between valid and invalid pairs. Its outcome
variation concerns readout advantage over fresh V conditional on admissibility.

## Frozen population and methods

Reconstruct PRED1's exact hash-selected directional observations, source filter,
role-bearing source identities, tie rules, scores, and five ranking methods.
Preserve those semantics to isolate the denominator/difficulty audit. A/B role
is part of the historical source key: these are source pools, not necessarily
independent distinct actions. Do not interpret them as independent samples.
Retain pools with no successful partner and report size-one pools separately.
Primary ranking comparisons use all pools with at least two observed partners.
Reconcile the original success-containing 275-pool subset to PRED1's report.

For each pool n=observed held-out partners, k=successful partners, p=k/n.
Freeze bins: NO_SUCCESS_OBSERVED p=0; HARD 0<p<=0.25;
MEDIUM 0.25<p<=0.75; EASY p>0.75. A zero means none in this observed pool,
not impossibility over all legal partners. Outcome-based bins are descriptive.
Report all contexts separately, including empty contexts and empty difficulty
bins. Do not enlarge the sample when the hard bin is small or empty.

Cosine already removes vector magnitude. Unit-direction normalization is the
same scoring rule mathematically, not an independent ablation. Check that
identity on synthetic fixtures and compare the frozen cosine to magnitude.

## Metrics

Persist every source pool's n,k,difficulty and per-method first-success rank.
Use reciprocal rank zero when no success exists and null first-success rank;
an exhaustive failed attempt costs n. Report hit@1/5/10 separately from true
recall@k (fraction of available successes retrieved; undefined when k=0).
Report mean/median first rank conditional on success, unconditional stopping
cost, and fraction saved versus exhaustive observed-pool evaluation.
Define normalized budget success area as the mean of success-found indicators
at integer budgets 1..n: (n-first+1)/n for a success, otherwise zero.
Retain paired wins/ties/losses in stopping cost and paired cost differences
against random, magnitude, and readout. No claim of significance from a single
deterministic random permutation. Also report analytic uniform-random expected
first rank (n+1)/(k+1), cost n for k=0, and hypergeometric hit probabilities.

## Integrity and execution

Before execution freeze source, plan, and all consumed data hashes in CONTRACT
and PREEXECUTION. Validate current PRED1 bindings and transitive consumed inputs
before and after analysis. Use PYTHONDONTWRITEBYTECODE=1 and python -B; syntax
checks use compile()/ast, never py_compile. Refuse existing measured outputs.
Write only REPORT.json and source-records.jsonl after sealing. Compare complete
write surface with baseline plus these allowed files; unexpected writes block.
Any mismatch stops promotion; never edit a sealed parent or rewrite a result.

PRED3 is not opened here. A deterministic unfitted cosine has no training stage;
relabeling context summaries as leave-one-context-out would add no transfer
evidence. A future transfer protocol needs genuinely unseen contexts or an
explicit train-only calibration rule and an independently frozen test domain.
