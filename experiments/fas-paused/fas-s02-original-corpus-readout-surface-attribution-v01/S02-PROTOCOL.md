# FAS-S02 Protocol: Original-Corpus Readout Surface Attribution

## Question

On the original FAS-00 Phase 1 v03 qualification corpus and the original grouped split, does replacing the final-layer global mean vector with the final model-visible position change exact-target transfer for the held-out context term?

The primary comparison is the held-out context term 3 slice. The held-out entity term 7 slice is the contracted comparator. Both use the original FAS-00 `HELDOUT_TERM_EXACT_TARGET` task and the same target labels.

This is a diagnostic attribution experiment. It does not repair, replace, or supersede the FAS-00 sensor disposition. It cannot authorize FAS-00 Phase 4 or any adaptive mechanism.

## Interpretation boundary

S01-3 showed strong target transfer from final-position features on its controlled counterfactual corpus. S02 asks whether that representation-surface effect reproduces on the original FAS-00 qualification corpus. S01-3 features, fitted probes, predictions, and metrics are motivation only and are not S02 inputs.

A difference between the views supports a bounded statement about the two frozen readout surfaces under this corpus, split, target task, and fixed linear probe. It does not establish a universal pooling cause or a general semantic capability.

## Immutable inputs

Use only the parent artifacts enumerated in `contracts/parent-binding-v01.json`:

- FAS-00 Phase 1 v03 events and seal;
- FAS-00 Phase 2A `FULL` rows from the sealed `mean_full` feature cache and its row receipts;
- the sealed FAS-00 Phase 3 target-transfer contract, result, score rows, and `HELDOUT_TERM_EXACT_TARGET` probe artifact;
- the pinned FAS-00 LFM snapshot identity for the new final-position extraction;
- the S01-3 result seal as lineage context only.

No labels or latent world fields may enter model inputs. No S01 corpus or feature cache may enter S02 execution.

## Fixed split and target transfer

Preserve the FAS-00 grouped split exactly:

- training worlds: seeds 0–15, templates 3 and 4;
- validation worlds: seeds 16–23, template 5;
- test worlds: seeds 24–31, template 5.

For the target-transfer fit, retain training events with a non-null observation and exclude both `context_term_id == 3` and `entity_term_id == 7`. Evaluate only the original test slices: `context_term_id == 3` and `entity_term_id == 7`, each with a non-null observation. Keep the exact serialized event order and row identities. Do not reassign groups or resample.

The context slice is primary. Report balanced accuracy, ordinary accuracy, per-class support/recall, and per-seed results for both views. Report event-paired prediction outcomes (both correct, mean-only correct, final-position-only correct, both incorrect) and the final-position minus mean-full metric differences. No composite score or post-result threshold is defined.

## Two representation views

1. `mean_full`: the existing sealed FAS-00 Phase 2A `FULL` final-layer arithmetic mean over all model-visible positions. Read the original sealed feature rows only.
2. `final_position`: newly extracted final-layer hidden state at the last model-visible position for the exact same `FULL` input token IDs.

No other feature view, layer, pooling rule, normalization, or model is in scope. The final-position extraction must use the sealed Phase 2A `FULL` token-ID sequences and verify their row, input, tokenizer, and sequence identities. The last selected position is `sequence_length - 1`; there is no padding.

## Phase boundary

### S02-0: construction packet

Complete and seal this protocol, parent binding, and execution contract. No model or tokenizer contact and no probe fitting.

### S02-1: final-position extraction

Requires a separate explicit model-contact authorization. If authorized, load the pinned model snapshot read-only, use only the 32,768 sealed `FULL` token sequences, extract only the final-position view, and write a fresh S02-only feature cache. The extractor reads only row index, event ID, rendered-input hash, token IDs, token-ID hash, and sequence length from the sealed feature receipts. It does not read labels or latent fields. Use one example per forward call, exact sequence length, no padding, final layer, float32 output, deterministic repeat checks, and before/after parameter identity checks. Do not fit probes or calculate scores during S02-1.

### S02-2: fixed linear readout comparison

Requires separate explicit analysis authorization after the S02-1 cache is sealed. Recompute predictions from the existing sealed FAS-00 mean-full transfer probe and verify they reproduce its sealed context/entity results. Fit one final-position probe using the exact FAS-00 probe family, train-fitted standardization, regularization, optimizer, class order, and transfer rows. Use the same test events for both views. Any solver or identity failure is recorded as a failure; no alternate solver or tuning is permitted.

## Explicit exclusions

No corpus regeneration, label or split changes, Phase 5 streams, probes on S01 data, query-only probe, nonlinear model, optimizer or threshold search, layer/pooling search, online update, episodic memory, snapshots, recurrent state, RTRL, JEPA, backbone modification, or FAS-00 revision is permitted.

## Expected construction disposition

```text
S02_PACKET_READY                    true
S02_FINAL_POSITION_EXTRACTION_AUTHORIZED false
S02_READOUT_ANALYSIS_AUTHORIZED     false
S02_MODEL_CONTACT_PERFORMED         false
S02_RESULT_READY                    false
```
