# C-G0 — residual edge-pruning census (plan, written before anything is computed)

Written 2026-09-29. Graph Surface Extraction v2 (Lexi) passed its stop gate on one operation only: `edge_existence`. That result answers *discrimination on a balanced sample of pairs*. It does not answer whether the 230M is worth a runtime slot,
because in a real world the pair universe is mostly non-edges and a deterministic type-pair table already separates many of them (Lexi's own "identifier" control scores AUC 0.89 on her sample). C-G0 asks the question the runtime cares about:

**On the natural ordered-pair universe of each world, does the frozen 230M pair observer (T1) materially extend the non-edge pruning frontier beyond a deterministic type-pair table (T0), at matched true-edge loss?**
No retraining, no new head, no controller. Census only.

## Two populations, never blended

- **Sampled-pair capability** — Lexi's result: balanced positives and an equal number of random negatives per world; AUC 0.982 test, 0.955 on held renderers. It is reproduced here only as an integrity check (below) and is reported in its own section.
- **Full-pair pruning utility** — this census: every ordered pair of matched, typed entities in each world, at its natural class balance. Nothing in one population's headline is computed from the other.

## Frozen inputs (bound by hash; nothing is refit)

The selected edge-existence observer exactly as delivered: `middle_plus_final` / `tiny_mlp` (Linear 4096→128, GELU, dropout, Linear 128→2; the score is the class-1 logit, the column her own AUC uses) from Lexi's run `BANK-v1-GRAPH-SURFACE-V2-2026-09-29`, with her local-vector extraction seal, scaler seal, task-derivation identity, spec, script hashes and the selected model's own hash.
All are recorded from her score receipt and re-checked against the files before use; the run stops on any mismatch. Her experiment source is uncommitted in her worktree, so these hashes are the custody. Inference is reimplemented here (not imported) and must reproduce her sampled-pair DEV and TEST AUC (integrity gate: within 1e-5).

## The pair universe

Exactly her candidate rule, at natural balance: for each selected row, the typed nodes are the entities with a matched span; the universe is every ordered pair (a, b), a ≠ b, of typed nodes; an **edge** is a pair that is the subject and object of any binary `initial_state` fact with a valid predicate between typed nodes; everything else is a **non-edge**.
Row selection follows hers: canonical rows for DEV and TRAIN; canonical plus paired-renderer rows for the TEST partitions. Renderer family is the row's `surface_family` (S0–S11); **S7/S8/S9 are the held-out renderer families**.

## The tiers

- **T0**, a deterministic type-pair table: for each ordered `(type_a, type_b)` (from the entity-id prefix), the natural edge rate over the full pair universe of **TRAIN** canonical worlds. T0 prunes whole type pairs in ascending rate order.
  The entity type is *given by the observation* here (id prefix); a real deployment would need a typer (node typing was trivial in BANK, and this assumption is stated in the report).
- **T1**, the frozen 230M pair observer: prunes residual pairs whose edge score is below a threshold.
- **T0+T1**: T0 prunes a prefix of type pairs; T1 prunes among the rest. Reported also: **T1 alone** (no T0), for reference.

## Measures

For edge-loss budgets **ε ∈ {0.5%, 1%, 2%, 5%}** (edge loss = true edges pruned / all true edges in the evaluated split):

1. **Matched frontier:** the largest share of non-edges pruned at loss ≤ ε, for T0, T0+T1 (T0 prefix and T1 threshold optimised jointly) and T1 alone, evaluated on each split with the same optimisation for every arm.
2. **Gain** = (T0+T1 pruned share) − (T0 pruned share), in absolute points.
3. **Held renderers:** the same on S7, S8 and S9 individually, and on the in-family pool.
4. **DEV-fitted transfer:** thresholds fitted on DEV at each ε, applied unchanged to TEST and to S7/S8/S9: achieved edge loss and pruned share (reported, not gated).
5. **Noise band:** the T0+T1 gain recomputed with T1 scores shuffled among the evaluated pairs (200 permutations, fixed seed): what re-optimising a threshold on unrelated scores finds by chance.
6. **Within-type-pair AUC** (pairs weighted, type pairs with both classes), and **confidence geometry:** the score distribution of edges versus non-edges, and how much of T1's pruning comes on which side.

## Prediction stated in advance

The useful lane will be mostly confident non-edges (pruning is the "no edge" side by definition), and T0 will already take a large share of them. Whether T1's residual gain clears the bar is the open question.

## Gate (fixed now; numbers as approved)

T1 **advances** iff, on the pooled TEST pairs:
- at **ε = 1% and ε = 2%**, the gain is **≥ 10 absolute percentage points** at both; and
- the gain is **> 0 on S7, S8 and S9 individually** at both; and
- the gain **exceeds the noise band's 95th percentile** at both.

ε = 0.5% and 5% are reported, not gated. Otherwise **STOP**: the type-pair table wins and the result is handed to FF as "pretrained source not earned for this operation". That is a complete outcome.
If T1 advances, the frozen two-tier design goes on to C-G1 (contract) and C-G2 (runtime) — not started here.

## Data status (stated strongly)

DEV calibrates thresholds. TEST and S7/S8/S9 were read by Lexi and **helped select edge existence as the surviving operation**, so every TEST number here is **development-grade characterisation, not independent validation**. The purpose is architecture selection.
The first confirmatory test of any frozen machine is a **fresh graph split**, which does not exist yet.

## Correction made before anything was computed

The first draft of this plan described the head's output layer as `128→1`; the delivered checkpoint has two outputs, and the score used throughout is the class-1 logit exactly as Lexi's metric uses it. Nothing else changed.

## Not done here

No retraining or refitting of any head, no new operations, no controller, no runtime, no C0 v2 records (those are C-G1/C-G2), no fresh split, no rescue of a failed gate.
