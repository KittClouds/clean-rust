# FAS-S07: Sparse Compatibility Cartography

## Question

What shared sparse structure supports the native mean-full and final-position decision systems, and does their incompatibility arise from activation, feature distribution, feature-to-decision coupling, or a combination?

## Boundary

S07 reads the sealed S01, S02, S05, and S06 artifacts plus the allowlisted FAS-00 Phase-1 v03 event identity/world-state records, Phase-2A feature cache, and Phase-3 fixed probes named in the parent-binding contract. It does not load the LFM or tokenizer, extract transformer features, fit or change a probe, or modify any parent artifact. One shared TopK sparse autoencoder is fitted per fixed seed on the two S01 native-standardized feature surfaces. FAS-00 is an external diagnostic population and is never used for SAE fitting or feature-group selection. Phase-1 v03 is read only to recover prospective event state metadata for the 512 FAS-00 diagnostic rows.

## Data separation

Fit only S01 feature rows whose sealed group bucket is 1, 2, 3, or 4. All four members of each quartet share a bucket. The S01 factorial test events selected by S04 and the S02 event set for FAS-00 remain outside SAE fitting. During SAE fitting the training program receives no labels, event metadata other than row membership, test feature values, FAS-00 feature values, or probe outputs.

The training pool contains one standardized `mean_full` vector and one standardized `final_position` vector for every training-side S01 row. Each uses the matching sealed S01-3 native scaler. The two surfaces share one dictionary within each seed.

S01 row metadata stores `exact_target` as the candidate-position index. S01 metrics and conditioning use semantic state IDs: reconstruct the row's slot-to-state map from `candidate_identity_order` and `state_by_candidate_identity`, then map the target position through that map. The S05 held-out population stores `target_state_id` directly as a semantic state ID. Never compare these two encodings without the mapping.

## Frozen SAE

- Input width 2,048; dictionary width 16,384; expansion 8x.
- Encoder: affine map followed by ReLU and top-32 positive activations.
- Decoder: affine map; decoder columns are unit-normalized after every optimizer update.
- Loss: mean squared reconstruction error in standardized input coordinates.
- Initialization: seeded Gaussian decoder columns normalized to unit length; encoder initialized to decoder transpose; encoder bias zero; decoder bias equal to the streaming mean of the pooled S01 training vectors.
- Optimizer: Adam, learning rate `3e-4`, betas `(0.9, 0.999)`, epsilon `1e-8`, zero weight decay; no scheduler or gradient clipping.
- Training: 20 fixed epochs, 512 paired event rows per batch (1,024 vectors, interleaved M/F), final partial batch retained, deterministic seeded permutation each epoch.
- Seeds: `1301`, `2027`, `31415`. No seed selection or continuation.
- Execution: one NVIDIA GeForce RTX 3080 CUDA device, FP32, TF32 disabled, deterministic algorithms enabled, fixed software/hardware recorded in receipts.
- Use the final fixed-epoch state. Training loss is descriptive; it cannot select a seed, checkpoint, or setting.

## Faithfulness gate

Before any sparse-feature interpretation, encode and decode the sealed held-out S01 factorial population and the 512-event FAS-00 external population. Compare each reconstructed representation through its unchanged native scaler-plus-probe pipeline with the same raw-feature pipeline.

For every seed, surface, and contracted population/slice, reconstruction passes only if balanced accuracy degradation is at most `0.03` absolute and recall degradation for every class is at most `0.05` absolute. Improvement is allowed. FAS-00 gates cover the 512-event union and its context-term-3 and entity-term-7 slices. S01 gates cover the complete 19,732-event factorial test set. A failed gate yields `SAE_NOT_FAITHFUL_FOR_COMPATIBILITY_ANALYSIS`; do not compute feature ranks, inspect feature activations, run ablations, or attempt another SAE setting inside S07.

## Sparse compatibility analysis (only after the gate passes)

For every seed, report all dictionary features by numeric seed-local ID. Do not assign semantic names. On training, held-out S01, and external FAS-00 populations, report activation frequency, zero mass, mean, variance, nonzero mean, and nearest-rank 50th/90th/99th percentiles. Report conditioning by target, observed state, context term, and entity term; compute coactivation partners using the 256 features with highest training activation frequency (ties by feature ID).

For each native readout and each class pair, compute decoder-feature coupling `kappa[j,a,b] = (w[a]-w[b]) dot d[j]`. Report the M/F activation and coupling differences separately, plus paired per-event sparse margin contributions. This preserves the distinction between a feature's activation and the observer's use of its decoder direction.

For each seed and class pair, select exactly 64 features using training rows only: rank by descending absolute signed mean of paired contribution difference `mean_i(C_F[i,j]-C_M[i,j])`, then feature ID. Construct one same-size matched control group from unselected features by greedy minimum standardized Euclidean distance on training activation frequency, mean nonzero activation, and decoder-column norm; resolve ties by feature ID and do not reuse controls. Freeze groups before held-out outcomes are read.

On held-out S01 and external FAS-00, ablate each selected group and its matched control by setting its sparse activations to zero, decode, and score through the unchanged native probe. Report accuracy, balanced accuracy, class recall, confusion matrix, target and pairwise margins, and prediction transitions relative to the faithful SAE reconstruction. These are interventions in the SAE reconstruction, not claims of transformer-circuit causality.

For coupling-swap attribution, keep each sparse code fixed and score its SAE reconstruction through both native probes. Report M codes under M/F readouts and F codes under M/F readouts. This is attribution over fixed readouts, not a trained classifier comparison.

## Sealing and stopping

Seal the protocol before preflight. Seal the three final SAE states and training receipts before opening held-out feature values for analysis. Seal all gate outputs before any feature analysis. After the gate passes, complete and seal the full S01 training/test sparse analysis first. The FAS-00 external transfer stage must verify that S01 seal before it opens FAS-00 feature values or sparse codes for characterization; it re-encodes its 512 rows through the same fixed seed dictionaries and requires exact parity with the gate codes. Seal FAS-00 transfer separately, then seal the combined result tree. Do not run layerwise analysis, inspect maximally activating examples, or start a follow-on experiment under S07.

Terminal flags are machine-readable. S07 cannot revise FAS-00, authorize online adaptation, or authorize layerwise/model-contact work.
