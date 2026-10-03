# Qwen two-run trial — repaired protocol v1

**Complete and verified:** see [RESULTS.md](RESULTS.md). Both authorized graft
runs and all four requested pre-seal checks are finished. The hard legal-MOVE
slice remains weaker under isolation; aggregate scores must not hide that result.

User-selected checkpoint: `Qwen/Qwen3.5-0.8B-Base`, revision
`dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68`. The older Qwen3-0.6B-Base and
post-trained Qwen3.5-0.8B are not substitutes.

The user authorized repairing Qwen only. MiniCPM artifacts remain historical
references; no MiniCPM reruns, overwritten receipts, or claims of a fully matched
substrate-only comparison. Source-level audit found DEV renderer pairs inside
Phase 1 training, an absent Phase 1B pair term, a detached Phase 1B variance
penalty, incorrect global packed-entity indexing, and zero rather than excluded
padded action logits. Historical source-to-execution identity is not sealed, so
these are findings about the inspected implementation, not reconstructed proof
of every historical invocation. Historical primitive caches supply row IDs only;
Qwen features are independently extracted from BANK-v1 input text and bindings.

## Frozen scope

- Exactly two graft-training runs: Phase 1 baseline, then Phase 1B isolated
  `candidate_satisfies_goal` plus legality preservation. Global and action losses
  are excluded from Phase 1B. No rescue architecture or checkpoint shopping.
- Same causal graft topology, six surfaces, exhaustive 28-candidate contract,
  canonical target expressions, independent-source weighting, 8 epochs,
  AdamW 3e-4, weight decay .01, cosine schedule, batch 64, gradient clip 1, seed 0.
  Hidden width follows Qwen, so parameter counts are not identical to MiniCPM.
- Both runs start from the same saved full initialization. TRAIN alone supplies
  prevalence, normalization, variance reference and differentiable renderer pairs.
  DEV supplies frozen checkpoint selection and reporting only.
- Full candidate identity and entity IDs align renderer pairs. Packed entity
  indices address the correct world's entities, never guessed/clamped mappings.
- Frozen recoverability diagnostics follow baseline training; readout fitting is
  analysis, not another graft-training run. Include an independently solvable
  positive control; failed instrumentation cannot support a target negative.
- Report initialization accessibility separately from trained acquisition and
  deltas, with the whole response vector including goal-relative structure and
  MOVE. An aggregate two-point gain alone is not survival.
- Protected TEST, BANK-v2, new-corpus curation and Lexi operational coordination
  are out of scope. Recurrence is deferred, not mathematically ruled out. If Qwen
  lacks a qualitative acquisition win, stop substrate shopping; LFM architecture
  fan-out is a subsequent user-directed program, not an automatic third run.

## Execution

`python experiments/s15-lepori-qwen-two-run/prepare.py` qualifies the pinned text
tower before extracting TRAIN/DEV features. Artifacts are stored separately at
`C:/phoenix-target-overgraph/s15-qwen-two-run-20261001-v02`; model weights at
`D:/codex-runs/s15-lepori-qwen-0.8b-base-v01/models/Qwen3.5-0.8B-Base`.
Qualification failure stops before any graft-training run is consumed.

Preparation v01 passed substrate qualification but stopped before sealing a
feature chunk on an absent renderer mention. Its artifacts are preserved. v02
retains the inherited absent-mention zero-vector convention and records every
such occurrence; it does not infer missing mention text from latent truth.

The first diagnostic port mistakenly interpreted batch 64 as candidates, rather
than worlds. Its completed readout receipts remain in `recoverability` as
**unmatched exploratory analysis**, not primary evidence. The orchestration was
stopped after Phase 1 and before Phase 1B. `finish_trial.py` binds a versioned
continuation, runs `diagnostics_world.py` with the inherited 64-world batch,
FP16 frozen representation cache and fixed TRAIN-subset secondary selection,
then consumes the sole remaining Phase 1B graft run. Phase 1 is not rerun.
`audit_trial.py` independently replays final scoring, identities and canonical
targets and reports extra strata as descriptive analysis only.
