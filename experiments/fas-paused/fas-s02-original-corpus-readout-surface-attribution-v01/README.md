# FAS-S02: Original-Corpus Readout Surface Attribution

S02 tests whether the original FAS-00 held-out-context target-transfer failure changes when the frozen representation is read at the final model-visible position instead of using `FAS_FEATURE_V1` global mean pooling.

The comparison uses the sealed FAS-00 Phase 1 v03 qualification corpus, its original grouped seed/template split, the existing sealed `mean_full` feature cache, and the pinned LFM revision. The new final-position features and all S02 results will have a separate identity and output tree.

## Current disposition

```text
S02 construction packet       READY
S02-1 model contact            NOT AUTHORIZED
S02-1 feature extraction       NOT AUTHORIZED
S02-2 probe fitting            NOT AUTHORIZED
S02 result                     NONE
FAS-00 disposition             SENSOR_FAIL_NO_SIGNAL (unchanged)
```

This packet is a prospective contract. It does not authorize tokenizer or model loading, forward passes, feature extraction, or probe fitting. Each execution stage requires a separate explicit authorization.

## Sealed files

- `S02-PROTOCOL.md`: scope, scientific question, and phase boundaries.
- `contracts/parent-binding-v01.json`: exact parent artifact identities and hashes.
- `contracts/two-view-attribution-contract-v01.json`: frozen extraction and linear readout procedure.
- `seals/construction-disposition-v01.json`: current status.
- `scripts/seal_construction.py`: deterministic construction-tree verifier and sealer.
- `seals/construction-seal-v01.json`: packet file hashes and canonical root.

No Phase 5 stream, adaptive mechanism, or additional representation view is part of S02.
