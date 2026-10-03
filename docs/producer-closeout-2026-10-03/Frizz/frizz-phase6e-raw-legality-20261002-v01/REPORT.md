# Phase6E — raw Qwen legality access and earned micro-LoRA

MICRO_LORA_NO_GAIN_AT_THIS_BOUNDARY

Raw panel: no arm qualified precise grounding. No adapter earned. One rank4 final-block q/v pilot; no rank/layer sweep.

| View/readout | Readout-init BA | Trained BA | Full exact | Same-type exact | Precision | Recall | FP/root | FN/root | Retention |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| E_e-linear | 0.6319 | 0.7980 | 0.0000 | 0.0120 | 0.2355 | 0.7384 | 8.39 | 0.92 | 0.7658 |
| E_e-mlp | 0.5105 | 0.7954 | 0.0000 | 0.0150 | 0.2367 | 0.7307 | 8.25 | 0.94 | 0.7568 |
| local-linear | 0.5147 | 0.7948 | 0.0000 | 0.0120 | 0.2277 | 0.7384 | 8.77 | 0.92 | 0.7628 |
| local-mlp | 0.4482 | 0.7975 | 0.0000 | 0.0030 | 0.2425 | 0.7307 | 7.99 | 0.94 | 0.7477 |
| local_mf18-linear | 0.5302 | 0.7830 | 0.0000 | 0.0180 | 0.1970 | 0.7470 | 10.66 | 0.89 | 0.7508 |
| local_mf18-mlp | 0.5778 | 0.7888 | 0.0000 | 0.0150 | 0.2039 | 0.7521 | 10.28 | 0.87 | 0.7718 |
| local_mf24-linear | 0.5112 | 0.7843 | 0.0000 | 0.0120 | 0.2176 | 0.7230 | 9.10 | 0.97 | 0.7297 |
| local_mf24-mlp | 0.5773 | 0.7907 | 0.0000 | 0.0120 | 0.2100 | 0.7487 | 9.86 | 0.88 | 0.7658 |
| local_ms24-linear | 0.5230 | 0.7835 | 0.0000 | 0.0090 | 0.1917 | 0.7564 | 11.17 | 0.85 | 0.7778 |
| local_ms24-mlp | 0.5823 | 0.7962 | 0.0000 | 0.0090 | 0.2253 | 0.7444 | 8.96 | 0.89 | 0.7748 |

Phase6D gate: BA 0.7783; exact 0.0000; FP/root 11.37.

Localization: local and contextual frozen Qwen views improve some candidate-level metrics but do not supply precise legal sets. Matched E references also recover no exact sets. This is bounded interface/dose evidence, not a Qwen information ceiling.

Candidate contract: nine types; four deterministic positional arguments with observable role one-hots; final-depth first-mention means; missing observable bindings stay zero. No canonical binding repair or ID input. Qualified contexts mf24/ms24/mf18; no surface search.

Population: 1333 TRAIN /333 DEV canonical EXECUTE-eligible roots, both renderings grouped; all candidate types retained. TRAIN 84636 candidates,4690 legal; DEV20789,1166 legal (primary rendering). Rendering pairs are not independent samples.

Readout initialization is random diagnostic-head initialization on the same frozen substrate/state, not an untrained Qwen or E checkpoint. All fixed readouts, init/trained logits, legal-set Jaccard, root FP/FN, separate selected/optimal ranks/top3/top5/MRR, renderer and candidate/legal-count slices are in raw-results.json and panel/. ACTION-SUPPORTS.json adds typed candidate and selected-root supports. Supports below200 are descriptive.

TRAIN-error-families.json diagnoses action type, argument roles/binding availability, positive/negative preconditions, missing predicates, permission, candidate count and legal size. Canonical latent truth is diagnostic only. No target other than binary legality enters any fit.

## Earned adaptation

Rank4/alpha4 at language_model.layers.23.self_attn.q_proj/v_proj. Qwen q_proj includes query and output-gate coordinates; both receive the low-rank delta. All original parameters, prefix, norm and already-trained local_mf24 MLP head remain frozen.

The prefix cache is adaptation plumbing, not an additional raw readout surface. Full untruncated text, same mention/binding contract and frozen TRAIN context normalization. Zero-delta late-block parity is qualified in prefix-extraction.json.

| Pilot endpoint | Zero-delta adapter, trained head | Epoch8 |
|---|---:|---:|
| BA | 0.790276 | 0.785028 |
| precision | 0.209868 | 0.203573 |
| recall | 0.747856 | 0.742710 |
| full_exact_set_recovery | 0.000000 | 0.000000 |
| root_mean_Jaccard | 0.211393 | 0.206485 |
| false_positives_per_root | 9.858859 | 10.174174 |
| false_negatives_per_root | 0.882883 | 0.900901 |
| selected_retention | 0.762763 | 0.750751 |

| Filter | Full top1 | Full MRR | Same-type top1 | Same-type MRR |
|---|---:|---:|---:|---:|
| raw local_mf24 MLP | 0.003003 | 0.173070 | 0.108108 | 0.273694 |
| pilot zero-delta | 0.003003 | 0.171998 | 0.108108 | 0.272092 |
| pilot epoch8 | 0.003003 | 0.170186 | 0.111111 | 0.273980 |

TRAIN fixed mf24-MLP false positives involving absent AT: 11818/12430 (95.08%). Predicate strata overlap; this is a likely entity/location grounding target, not a causal proof.

TRAIN-OBSERVABILITY-CAVEAT.json separately records truth-present preconditions absent from visible/report channels and missing AT subjects lacking mentioned locations. Legality targets canonical truth, not permission or supported knowledge. Coverage is diagnostic: it does not prove nonidentifiability and was never used to alter the pilot.

Pilot cost: {'DEV_seconds': 36.46212069998728, 'fit_seconds': 742.0973353000009, 'init_DEV_seconds': 10.371970299980603, 'peak_cuda_bytes': 1856755712, 'steps': 1336, 'trainable_parameters': 26624}. Pilot fit_seconds is elapsed from fit start through final scoring/integrity checks; DEV_seconds measures tail plus cached-prefix I/O, not end-to-end Qwen latency. Per-arm raw costs: panel/*-cost.json (process-cumulative allocation peaks). Prefix extraction cost and disk identity: prefix-extraction.json; immutable prefix caches on D:. No paid/cloud workload.

Gate rejection remains a scoring error; no eligibility exclusions or fallback on empty predicted sets. Logged selection and optimal-set membership remain separate. Frozen consequence is never retrained. Its gold-legality benefit remains SAME-TYPE only; full-set gold-gate top1 is0.30%.

Preservation: original Qwen/head tensors checked byte-for-byte in pilot-frozen-parameter-receipt.json; all bridge/E/goal/consequence/gate/corpus inputs hash-locked. Existing goal/binding/globalization/renderer production panel remains unchanged, not a newly fitted probe.

Controls: known-solvable linear/MLP exact sets=1; zero-delta projection parity and frozen-weight gradient guards pass. Fresh processes replay every raw arm and both pilot endpoints exactly; metrics independently replayed. Every prefix cache hash/binding verified; first16 rows per split re-extracted exactly from original Qwen, not an exhaustive prefix recomputation. Protected evaluation unopened.

Final disposition applies only to this bounded panel and one constructed pilot. No rank/layer rescue, recurrence, comparator, F or consequence retraining was run.
