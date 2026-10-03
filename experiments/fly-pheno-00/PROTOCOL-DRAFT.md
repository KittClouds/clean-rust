# FLY-PHENO-00 — Adaptive Damage Recovery

**Protocol status:** `PREEXECUTION_SEALED_NOT_AUTHORIZED`  
**Study class:** engineering phenotype mining  
**Measured execution:** not authorized by this draft  
**Biological promotion:** out of scope

## Question and claim boundary

After the learner reaches a frozen competence criterion, does controlled damage to its learnable connection set produce a reproducible recovery trajectory, and does ordinary weight adaptation change that trajectory relative to a weight-frozen control and a matched shuffled substrate?

The target claim is limited to the named learner implementation, task, lesion operator, and frozen evaluation panel. No circuit mechanism, biological repair function, or general claim about fly computation follows from this experiment.

FLY-DROP-00 remains closed with disposition `PRIMARY_TOPOLOGY_EFFECT_NOT_SUPPORTED`. FLY-PHENO-00 tests a separate dynamic damage-response question; it is not a rescue projection or a reinterpretation of FLY-DROP-00.

## Source and identity boundary

The closest local implementation is the DH-08A simulator. Its protocol records a `FROZEN_UNOPENED` pre-execution state, while the current DH-08A tree also contains run artifacts. Treat that study identity and its outcome files as protected: do not add lesion conditions, alter its source, inspect its outcomes, or reuse its run identity. FLY-PHENO-00 must use a new study identity and an independently snapshotted source tree containing only authorized source inputs.

The new source snapshot must identify the learner code, anatomy files, task generator, executable, and evaluator by content hash before any measured fit. This draft is not a source snapshot or run authorization.

## Prospective design choices

### Host and task

- Preserve the ordinary DH-08A adaptive learner as the host: the existing activity dynamics and ordinary `KC→MB` weight-update rule remain unchanged except for the explicit lesion mask and the weight-frozen control.
- Use one stationary balanced cue-to-action task. There is no reversal, task B, curriculum, augmentation, or task-specific lesion placement. This keeps the treatment on damage response rather than sequential-task interference.
- Freeze the task bank, training stream, evaluation panel, and competence criterion before measured execution. Training and recovery inputs are identical within each paired arm. Evaluation episodes never update learner state.
- A learner that fails the frozen pre-lesion competence criterion is recorded as a criterion failure. It is not replaced, and its recovery ratio is not imputed.

The pre-execution package freezes a 512-trial pretraining cap and competence threshold `held-out error fraction <= 0.25` on exactly 256 competence responses. A substrate×learner block that fails at that fixed endpoint is recorded as `CRITERION_FAILURE`; it is never early-stopped, replaced, or tuned. The global primary support is the intersection of blocks competent on the fly substrate and every one of the eight null graph realizations. At least 8 of 12 blocks must survive that intersection; otherwise the primary is `NOT_EVALUABLE`. Competence rates remain reported per substrate.

### Lesion target and operator

The lesion target is the learner's **unique trainable `KC→MB` edge set**, with one edge index as one lesionable element. It is not a neuron ablation, whole-brain lesion, or deletion of an anatomical data row.

For edge universe size `E` and severity `p`, set `K = floor(p × E)` and create a binary permanent mask over exactly `K` distinct edge indices. Apply the mask at a trial boundary after the pre-lesion checkpoint. Masked connections contribute zero to activity and are excluded from every later weight update; they cannot regrow during recovery. The graph and index arrays remain immutable.

Frozen severity ladder:

| Severity `p` | Lesioned edge count |
| --- | --- |
| 0 | sham; no masked edges |
| 0.01 | `floor(0.01 × E)` |
| 0.05 | `floor(0.05 × E)` |
| 0.10 | `floor(0.10 × E)` |
| 0.20 | `floor(0.20 × E)` |

Frozen lesion samplers:

1. **Uniform random:** sample `K` distinct edge indices without replacement using the sealed lesion seed.
2. **High-degree targeted:** rank edges by presynaptic KC out-degree in the frozen `KC→MB` layer, highest first; resolve ties by `(pre_id, post_id)` ascending; mask the first `K` edges.

The mask is generated from anatomy and the declared seed only. It may not use learned weight magnitude, activity, task outcomes, or recovery outcomes. The same mask is shared by the paired adaptive and weight-frozen arms. Four lesion permutations (`m=1..4`) are frozen for every substrate and side. Each is one deterministic permutation of the canonical edge list; the severity masks are prefixes, so `.01 ⊂ .05 ⊂ .10 ⊂ .20` within a permutation. Lesion hashes and exact counts are recorded before fitting.

The matched control is a separate **substrate factor**, not a third lesion sampler: apply the same lesion samplers and severity ladder to independently frozen degree-preserving shuffled graphs. `p=0` is the sham condition for both substrate classes. These graph controls are synthetic topology nulls, not a non-fly biological system.

Eight null graph realizations are frozen prospectively. Each side and each directed layer uses repeated double-edge swaps with exactly four accepted swaps per original edge. Swaps reject duplicate pairs, illegal layer pairs, equal source endpoints, and equal destination endpoints. A source row retains its weight when its destination changes. The algorithm does not run to outcome-dependent convergence; edge overlap is reported and never used as a realization-replacement rule.

### Substrate and controls

- **Fly-derived substrate:** the exact frozen graph realization in the independent FLY-PHENO-00 source snapshot.
- **Topology control:** multiple independently seeded, layer-wise degree-preserving rewired realizations from the same frozen node and edge tables. Freeze every realization and its hash before fitting. Preserve each layer's node universe, edge count, in/out degree sequence, and source-strength value per source node as defined by the rewire implementation.
- **Adaptive arm:** continue the ordinary learner's weight updates after damage, excluding permanently masked edges.
- **Weight-frozen control:** continue the identical recovery input and reward stream while freezing all trainable weights at their post-lesion values. Activity, baseline, neuromodulator, eligibility, RNG, scale, work, and event state may continue according to the ordinary implementation; no eligibility or reward signal may be committed to weights. This is the state-settling control, not a claim that every internal variable is frozen. The persistent-state allowlist is recorded in `source/persistent-state-schema.json`.

Each adaptive/frozen pair starts from the same complete pre-lesion learner checkpoint, mask, task stream, and evaluation bank. Every graph-control realization is a separate experimental factor; more learner seeds on one null graph do not substitute for more graph realizations.

### Timeline and measurements

At pre-lesion competence, store the full learner checkpoint and evaluate the fixed panel. Apply the lesion, clone the resulting state into adaptive and weight-frozen arms, and evaluate immediately at `t=0`. Continue for a fixed recovery budget of 512 task trials, recording at `t={0,1,2,4,8,16,32,64,128,256,512}` recovery trials. All trial schedules and checkpoint times are frozen before fitting.

Use two disjoint, prospectively frozen read-only banks: `E_competence` for the support criterion and `E_measurement` for `L_pre`, `L_t=0`, and the recovery checkpoints. Training never reads either bank. Each bank contains 256 fixed counter-based response rows in a separate seed namespace. The evaluator must be read-only with respect to the learner checkpoint, training RNG, counters, and future recovery stream. It may operate on a disposable evaluation copy; repeated evaluation of an identical checkpoint must produce bit-identical output and state hashes.

Report separately:

- **Initial vulnerability:** `D = L_post-lesion,t=0 − L_pre-lesion`.
- **Absolute recovery:** `A(t) = L_post-lesion,t=0 − L(t)`.
- **Normalized recovery:** `R(t) = A(t) / D`, only when `D >= epsilon_D`. The frozen minimum damage denominator is `epsilon_D = max(4/256, 0.01) = 0.015625`. Otherwise report `R` as undefined and classify the observation as resistance/no measurable damage for ratio purposes. Never drop such a fit from the raw-loss analysis.
- **Weight displacement:** distance from the pre-lesion weight vector, reported separately from functional recovery. Any broader state-distance summary must name its included persistent state fields; transient buffers and RNG state are reported separately.

Where defined, `R=0` denotes no measured recovery, `R=1` return to pre-lesion loss, and `R>1` performance beyond the pre-lesion level. Always show `D` with `R`; the ratio alone is not interpreted.

The complete loss trajectories and vulnerability measures are retained regardless of whether the normalized ratio is defined.

## Primary estimand and analysis order

The primary cell is **uniform random lesion at `p=0.10`, endpoint `t=512`**. Other severities and lesion families are secondary, with no outcome-based severity selection. The intended measured cardinalities are 12 learner/task blocks, 8 null graph realizations, and 4 random lesion permutations, with both sides retained and averaged within a block-level estimand.

For substrate `g`, learner/task seed block `s`, and random lesion permutation `m`, define adaptation benefit:

`B_p(g,s,m) = L_weight-frozen,p(g,s,m,512) − L_adaptive,p(g,s,m,512)`.

Positive `B` means ordinary weight adaptation reduced terminal held-out error relative to continued experience with weights frozen. The sham companion is `B_0(g,s)`, with no lesion and no random-lesion identity. Define damage-specific adaptive benefit:

`C_p(g,s,m) = B_p(g,s,m) − B_0(g,s)`.

The primary contrast is:

`Delta_C = mean_{s,m}[C_0.10(fly,s,m)] − mean_{g,s,m}[C_0.10(g,s,m)]`.

Keep `B_p` mandatory beside `C_p`, including the sham subtraction, so ordinary continued-learning benefit cannot be mistaken for damage-specific compensation. Use a two-sided 20,000-replicate multiway percentile bootstrap. Resample independent learner/task blocks `s`, lesion permutations `m`, and null graph realizations `g`; use the same resampled `(s,m)` indices on fly and null sides. The literal fly substrate is fixed and is never resampled as a population of flies. Report the point estimate, percentile 95% interval, fly `C` mean, each null-graph `C` mean, and consistency across all three factors.

Analysis order is fixed:

1. Integrity receipt, competence support, and fit-matrix validation.
2. Primary `Delta_C`, interval, direction, and consistency across learner blocks, lesion permutations, and null graphs.
3. Companion `B_p` and sham `B_0` results.
4. Initial vulnerability `D` and the full recovery trajectory `A(t)`.
5. Secondary severity and lesion-family summaries.
6. Normalized `R(t)`, only where the frozen `epsilon_D` rule permits it.
7. Weight/state displacement and other exploratory summaries.

No seed replacement, metric switching, lesion redesign, evaluator rescue, or hyperparameter adjustment is allowed after measured outcomes are opened. Infrastructure failures may be rerun only as the identical frozen fit with the failed attempt preserved. Non-finite legal computations are retained as numerical outcomes and are not silently imputed.

## Interpretation ladder

- Damage with no adaptive benefit: no compensatory phenotype observed under this host, lesion, and task.
- Similar benefit on fly and shuffled substrates: generic adaptive recovery is compatible with the result; a fly-specific substrate effect is not supported.
- A reproducible fly-versus-shuffle difference in `B`: candidate fly-derived adaptive damage-response phenotype in this bounded setup.
- A stable lesion-family interaction: candidate structured damage-response phenotype, requiring independent replication before localization.

Resistance (`D` near zero), recovery (`A(t)>0`), and adaptation benefit (`B>0`) are distinct outcomes and must not be collapsed into one “robustness” score. Functional recovery with non-restored weights is reported as such; it does not identify a mechanism.

## Seal gates — all required before any measured execution

1. Create a new FLY-PHENO-00 source snapshot; verify DH-08A source and measured artifacts remain unchanged.
2. Freeze anatomy, layer-wise null graphs, task and evaluation banks, competence criterion, recovery schedule, seed counts, and all seeds; hash every input.
3. Implement the permanent lesion mask and prove exact lesion counts, mask persistence, and zero updates to masked weights.
4. Implement the weight-frozen/state-on control and prove identical inputs, rewards, and evaluation exposure within each pair.
5. Implement the read-only evaluator; prove byte-identical training checkpoint, RNG, and counters before and after every evaluation.
6. Qualify competence attainment, finite updates, sham parity, checkpoint cloning, and analysis rejection of missing/duplicate cells before sealing.
7. Hash source, executable, analysis code, configuration, and the complete fit manifest. Create a fresh run identity and integrity contract.
8. Stop at the sealed pre-execution state. A separate explicit authorization is required to open measured execution.

The preparation package contains `SOURCE-SNAPSHOT.json`, `QUALIFICATION-RECEIPT.json`, `NULL-GRAPH-MANIFEST.json`, `LESION-MANIFEST.json`, `FIT-MANIFEST.csv`, `ANALYSIS-CONTRACT.json`, and `PREEXECUTION-SEAL.json`. The qualification namespace uses seeds `910000..910005`; none may enter the measured matrix. Qualification may record only contract booleans, finite status, mask/update invariants, and pre-lesion competence attainment. It may not record adaptive-versus-frozen lesion recovery differences.

## Explicit exclusions

No Jev transfer, biological-function claim, biological promotion, circuit localization, mechanism mining, repeated-damage transfer study, CF-01 task sequence, post-outcome rescue, or modification of DH-08A belongs to FLY-PHENO-00 v0.1.
