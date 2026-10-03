# Phase 6A — frozen-state candidate comparison

No Qwen/graft training, no protected evaluation, no architecture search. Reuse
exact sealed bridge/E initialization and fixed epoch-eight states. Separate c256,
[c256;s64], and e32. Primary rendering per canonical root; paired rows are not
independent samples. Cached FP16 states reproduce Phase-5 readout arithmetic.

Fixed readouts: linear and one hidden 64-unit GELU TinyMLP, seed0, four epochs,
AdamW lr .001 wd .01, shuffled batches of 64 TRAIN roots. Same population/dose
for all arms; masking excludes ineligible roots from each target. No DEV fitting,
normalization, checkpoint selection or post-hoc best readout.

Five fits per surface/family: root first-action-type from masked mean candidate
representation; selected-candidate scalar scorer by masked full-universe CE;
optimal membership scalar scorer by TRAIN-prevalence balanced BCE; selected-pair
preference and optimal-pair preference from ordered representation concatenations
using an antisymmetric linear/MLP score (half the forward-minus-swapped score).
Linear shared context cancels algebraically; the MLP can condition comparisons
on it. Pooling is explicit, not selected-candidate input.
First-action-type is the nine-type ABI, not named-candidate selection.

Pairs: canonical candidate order; up to four positive candidates and four evenly
spaced negative candidates (maximum16 pairs/root). Alternate left/right orientation;
pair indices and labels are receipt-bound before any DEV score. No candidate IDs,
labels, gold legality or action type restriction enter readout features.

Ranking: stable descending score, canonical ID order breaks exact ties. Separate
logged-selected rank/MRR/top1/3/5 and best-optimal rank/MRR/top1/3/5, eligible-only
denominators. Report count bands 1–28,29–64,65–128,129–171, root supports, and
unrestricted, gold logged-type restriction, predicted-type restriction. Predicted
type uses the matching TRAIN-fit pooled type readout. If a restriction excludes
the correct candidate/member, rank is censored as N+1, reciprocal rank/top-k=0,
and exclusion count reported. Oracle gold-type restriction is diagnostic only.

Pair accuracy is an oracle-generated contrast, not proof of deployable ranking.
Candidate goal linear/MLP readouts from Phase5 are preserved as exact-hash controls.
Known-solvable scalar/ranking and pair controls must pass >=.99 accuracy before
target interpretation. Full parameter/logit/metric replay in a fresh process.

Branch thresholds frozen before DEV scoring, operational not a universal ceiling:
"well-ranked" = unrestricted selected top1>=.35 AND selected MRR>=.50 AND
top1 exceeds uniform-within-root expectation by >=.20, >=200 eligible DEV roots.
Report optimal ranking independently, not as replacement for the named endpoint.
If fixed E e-linear clears this, simple scorer sufficient; no F.
If c+context clears this but E e does not (same family), integration contract is
the next branch, not F. If trained E e-MLP clears it, E e-linear does not, and
paired-root top1 gain >=.10 with CI lower>0, nonlinear-only access earns one F.
Otherwise no F automatically; seal weak-access/partial-localization findings.
All six trained surface/family arms remain in the report, no composite score.
Bootstrap: paired canonical roots, seed20261002,2000 replicates. Marginal passes
are exploratory one-dose DEV diagnostics, not protected generalization claims.
