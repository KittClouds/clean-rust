# Causal Phase 3 — supervision geometry

One new P3-BALANCED arm; the frozen Phase 2 CONSIST object is the comparator.
Unchanged causal Base final_plus_mean cache, graft, s64/e64, all 460,662 parameters,
20k TRAIN / 2k DEV, exhaustive canonical candidates with maximum 28.

Canonical replay audits every TRAIN/DEV label and availability mask before fitting.
Three global sources: goal, missing-annotation panel, contradiction.
Two candidate sources: simulator legality and legal one-step goal achievement.
The partial 0/1 missing-count proxy shares a source with missing-presence.
Its SmoothL1 and presence balanced BCE are averaged into one source unit.

Binary loss uses exact TRAIN prevalence and stable softplus. Candidate losses average
valid candidate entries per head, then heads per source, then sources per family.
No candidate/ontology cardinality multiplies an independent source's weight.
P2 prediction consistency and variance guard are unchanged; CF stays dormant;
raw latent matching is retired.

Selection is .5 J_S + .5 J_E, balanced DEV BCE weighted by frozen TRAIN prevalence.
Each independent binary source votes once; count proxy gets no extra selection vote.
Action, renderer, variance and plain BCE never select a checkpoint.
No class-weight, threshold, or loss-coefficient tuning.

Same saved Phase 0 initialization, seed, order, sampled renderer pairs, 20 full
passes, AdamW, cosine schedule, clipping and FP32 deterministic CUDA as P2 CONSIST.
No Phase 2 baseline retraining. Outputs stay on C: NVMe.

The encoder mapping snapshot contains real semantic differences, not a substrate
property: its solvable excludes already-satisfied goals and bounds search; unmet
requirements is the complement of legal; applicability duplicates legal; goal
achievement labels some illegal no-op transitions true. Unrestricted solvability,
unmet requirements and applicability cannot be made sourceable under the frozen
causal ABI without a new meaning/derivation. These targets stop as unresolved and
remain masked. All existing sourceable targets proceed unchanged. This audit does
not claim the shared cross-lane source contract is now unified.

Run from this directory:

```powershell
python test_phase3.py
python run.py
python verify.py
```

Per-source metrics include ordinary/balanced accuracy, macro/class F1, support and
TRAIN prevalence. Count metrics remain raw MAE, rounded exact count and Spearman.
Action and MOVE/ACTIVATE/NOOP stay separate. Renderer tables distinguish both
correct, first only, second only, both wrong, disagreement for every available head.
Candidate state conditioning and global variance are sanity diagnostics, not wins.

No protected TEST, BANK-v2, backbone changes, new head/surface, recurrence, new
supervision, encoder fitting, or cross-lane winner. Prior artifacts remain frozen.
