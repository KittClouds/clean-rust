# FAS-S01-3: Frozen Linear Accessibility Cartography

## Purpose and boundary

S01-3 measures which prospectively fixed linear readouts can decode the
counterfactual corpus factors from the already sealed S01-2 feature cache. It
is diagnostic cartography. It cannot revise FAS-00, promote a representation,
or authorize adaptive mechanisms.

The S01-2 corpus, seven-view cache, and all parent artifacts remain immutable.
No LFM weights are loaded, no feature is re-extracted, and no new view is
created. The entire evaluation is exploratory because the S01-2 geometry
results have already been revealed.

## Frozen probe and split

Every probe is a multinomial linear logistic classifier with an unregularized
intercept, fixed L2 coefficient `1e-4`, and zero initialization. Each view is
standardized using only that probe's training rows, with population standard
deviation and unit scale for constant columns. Optimization uses PyTorch
L-BFGS on the pinned CUDA device and fixed solver limits in
`contracts/linear-accessibility-contract-v01.json`. There is no validation
search, model selection, nonlinear layer, class weighting, or threshold.

Quartets are assigned as a unit by the first 32 bits of
`SHA256("FASS01-S01-3-GROUPSPLIT-V01|" + quartet_id) mod 5`. Bucket 0 is test;
buckets 1–4 are training. Thus A/C/E/P siblings cannot cross the split.
Observation and query template IDs 6 and 7 are excluded from every fit, as
required by the sealed S01-2 corpus contract.

Context and entity identity probes use all 32 identity labels in their
training set. Their scores measure closed-set identity decoding on unseen
quartets; they do not measure classification of a label never shown during
training. Relation, state, and exact-target probes train only on quartets
whose context and entity terms are both `TRAIN_SIDE_STYLE`; this keeps novel
term transfer genuinely out of their fitting data.

## Tasks and evaluation

All seven views are reported separately for context identity, entity
identity, relation identity, observed state, and exact target. The factor
probes retain every class from the sealed corpus. For the relation, state,
and target probes, results are reported on the fixed in-domain, held-out
context, held-out entity, joint held-out, held-out observation-template,
held-out query-template, both-held-out-template, any-held-out-template, and
crossed factor/template slices specified in the JSON contract. Identity
probes additionally report train-side and novel term IDs on seen templates;
those term labels are present during identity-probe fitting.

Every slice reports support, accuracy, balanced accuracy, multiclass log
loss, Brier score, confusion matrix, and per-class recall. Predictions and
probe states are retained. There is no composite score and no best-view
selection.

## Sealing and terminal state

The fitting contract, source snapshot, parent bindings, metadata-derived
group split, and support audit are sealed before the first feature row is
loaded for fitting. The run seals all predictions, probe parameters, metrics,
and receipts before scientific interpretation. A preflight or execution
invariant failure stops the run without changing any parent artifact.

Expected terminal state:

```text
S01_3_COMPLETE                         true/false
S01_3_LINEAR_ACCESSIBILITY_DIAGNOSTIC   COMPLETE/FAILED
S01_3_LFM_LOADED                       false
S01_3_FEATURE_REEXTRACTION              false
S01_3_ADAPTIVE_MECHANISMS_AUTHORIZED    false
FAS00_PHASE4_AUTHORIZED                 false
```
