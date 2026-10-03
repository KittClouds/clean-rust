# Phase 6D — factorized legality acquisition

One prospective trial, seed 0, eight epochs; epoch 8 is the sole endpoint.
CPU FP32, four threads. AdamW lr .001, wd .01, clip 1; 16 canonical
roots per batch, both renderings grouped. Equal root weight, class-normalized
BCE plus .1 softplus worst-illegal minus worst-legal margin of 1 within root.
No selected-ID, permission, distance, exhausted/unknown, or pairwise inference
target. Legality is canonical simulator legal at tick 0, not permitted.

Input ABI is the immutable Phase6C ABI: nine types, four positional argument
vectors (already schema-bearing), explicit observable roles, c256/e32/s64,
two goal-role vectors and counts, six full-context vectors. Full candidates.
Entity 1024->32 and world 1024->16 projections; separate 64-dimensional
candidate/context pathways; [q,w,q*w] ->32->1. One construction, no sweep.
Qwen, E, goal heads, corpus, consequence checkpoint and cost formula frozen.
Only this legality sidecar trains. Root IDs are joins only, not features.

Threshold is strictly logit>0. No tuning. Empty sets abstain, no fallback.
Gate rejection NEVER changes selected/optimal eligibility denominators.
Same-type diagnostic uses logged selected type, not an acquired type predictor.

Primary precision rule: full exact sets >=.50, same-type exact >=.75,
root Jaccard >=.80, precision >=.95, recall >=.90, selected retention >=.95,
full exact improvement vs init >=.10 with paired-root 95% CI lower >0.
Conditional composition: B same-type top1 >= C-.10, improvement over A >=.20,
paired CI lower >0. Full operational qualification separately requires full
top1 gain over A >=.05 and CI lower >0. Bootstrap 2000, seed 20261002.
Candidate-only improvement is descriptive if exact-set rule fails.

A uses frozen Phase6C cost without filtering; B uses learned legality;
C uses canonical gold legality, diagnostic only. Gold legality previously
gave 81.98% SAME-TYPE but 0.30% FULL-SET top1. A full-set gain from an
incorrect learned set must not be mistaken for faithful legality acquisition.
Record performance on exactly recovered sets and B/C equality there.

Canonical EXECUTE eligible population: 1333 TRAIN /333 DEV roots, two
renderings each. Retain all support counts; <200 roots is descriptive.
Conflict diagnostic-only. Protected evaluation unopened. No automatic
raw-access audit or F/comparator/recurrence/LoRA escalation after failure.
Preservation is immutable E/head/input identity and saved full goal/binding/
globalization/renderer panel, not a new accessibility fit.

Fresh-process replay must reproduce all gate logits, metrics and frozen
consequence values, independently reproduce legal targets, and verify hashes.
Active pipeline logs are excluded from seal closure; source snapshots and
completed receipts are included. Original Phase6C remains retired as an
integrated construction regardless of conditional-component usefulness.
