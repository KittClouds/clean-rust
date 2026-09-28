# FAS-S04: Controlled Factor-to-Decision Transfer Geometry

## Question

Using only the sealed S01-2 `mean_full` and `final_position` features and the
already-fitted S01-3 exact-target probes, measure how controlled S01-2
counterfactual surface changes move semantic-state decision margins, and how
those movements differ between the two readout surfaces.

The central descriptive quantity is

`Gamma_f = (m_f(final_position) - m_A(final_position)) - (m_f(mean_full) - m_A(mean_full))`

for each declared within-quartet variant `f` and each semantic-state pair
margin. This is a surface differential of the same fixed probe task; it is not
a causal representation-only effect because the two probes were fitted
separately.

## What the S01 counterfactuals change

S01-2 variants are exactly `A`, `C`, `E`, and `P`:

- `C` substitutes the context **alias** in observation and query. The
  canonical context, world fact, relation, state, target, candidates, order,
  and templates remain fixed.
- `E` substitutes the entity **alias** in observation and query. The
  canonical entity and all other declared semantics remain fixed.
- `P` substitutes the observation template. The query and semantic slots stay
  fixed.

These are lexical alias and wording interventions. They do not change the
latent canonical context, entity, relation, or world state. The three state
surfaces are the invented S01 terms `zavik`, `nurex`, and `pavom`; S04 will
retain state IDs and those names and will not rename one as “idle,” “safe,” or
“risky.”

The S01 quartet has no combined `CE` variant. Relation and state are crossed
between quartets, not supplied as within-quartet counterfactual edges. S04 will
report C/E/P response strata by relation and state, but will not interpret
those strata as `Delta_R` or `Delta_S` interventions. It will not construct a
cross-quartet surrogate for the missing CE cell.

## Fixed inputs and population

- S01-2 factorial-balanced track only.
- S01-3's sealed group-split test quartets only; all four A/C/E/P siblings
  must be in the test manifest.
- S01-2 views `V0_MEAN_FULL` and `V1_FINAL_POSITION` only.
- S01-3's sealed `EXACT_TARGET` probe state for each view only. No fit,
  optimizer continuation, normalization change, or parameter update.
- S01-2 corpus metadata, feature-row manifest, S01-3 test-event manifest,
  prediction arrays, probe states, and their sealed parent receipts.

The S01-3 probe's output classes are candidate positions. For each event,
reorder the three output logits by the sealed `candidate_identity_order` and
the corpus `candidate_semantics` mapping to obtain logits in semantic state-ID
order `[0, 1, 2]`. Verify argmax parity against the sealed S01-3 prediction
array for every selected event. Fail closed on any mismatch.

## Frozen calculations

For each variant and view, record the three pair margins in state-ID order:

- `state_0 - state_1`
- `state_0 - state_2`
- `state_1 - state_2`

Also record the correct-state margin: target-state logit minus the largest
other-state logit. For each quartet, compute `Delta_C`, `Delta_E`, and
`Delta_P` as variant margin minus A margin, separately by view. Compute each
`Gamma_f` as final-position delta minus mean-full delta. Also retain the
paired final-position minus mean-full margin shift for every variant and
quartet. These compare complete separately fitted pipelines and are not
representation-only effects.

All feature standardization and linear arithmetic use the sealed S01-3 probe
state: scaler mean and scale are cast to FP32; raw FP32 features are
standardized in FP32; the saved FP32 linear weights and bias produce FP32
logits. Margin differences and summaries are then calculated in FP64.
Quartet rows are the unit of aggregation. Use the frozen summary set: `n`,
mean, median, nearest-rank p10/p90, min/max, and positive/zero/negative
counts. Report the full declared grouping axes in the analysis contract.
`context_term_id` and `entity_term_id` group by the A-variant anchor aliases;
the C and E replacement alias IDs remain explicit in each ledger row. No
significance tests or confidence intervals.

## Limits and failure behavior

S01-3 exact-target probes reached their fixed 300-iteration limit. S04 uses
those sealed states as they stand; this is not a convergence repair. The
result describes the paired score response of these fixed fitted pipelines
on the held-out S01 quartets. It cannot establish semantic context/state
effects, identify causal representation components, or generalize beyond the
exploratory S01 corpus.

If any parent hash, row mapping, sibling invariant, class remapping,
finite-value check, or sealed-prediction parity check fails, stop before
sealing a scientific result. Preserve the failed receipt and do not alter
S01 artifacts.

Terminal authority remains:

```text
S04_PROTOCOL_SEALED                   true
S04_DESIGN_AUDIT_PASS                 true/false
S04_MARGIN_ANALYSIS_COMPLETE          true/false
S04_MODEL_CONTACT                     false
S04_PROBE_FITTING                     false
FAS00_SENSOR_PASS                     false
FAS00_PHASE4_AUTHORIZED               false
SAE_ANALYSIS_AUTHORIZED               false
```
