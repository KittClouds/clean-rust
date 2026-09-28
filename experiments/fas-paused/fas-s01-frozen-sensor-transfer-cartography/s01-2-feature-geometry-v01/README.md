# FAS-S01 S01-2 Feature Extraction and Geometry v01

This run identity executes the explicitly authorized frozen LFM feature extraction, seals the complete seven-view cache and repeat/parameter-identity receipts, then runs only the existing S01-2 geometry contract.

All rendered inputs, token IDs, offsets, span positions, and parent roots are bound to the sealed S01-2/S01-2A/S01-2B/S01-2C artifacts. Extraction is single-row, exact-length, and unpadded. No tokenizer is invoked; all span positions are consumed exactly from S01-2C. The model revision is pinned, remote code is disabled, and no model parameters are trainable.

Execution order:

1. Run `source/test_preflight.py` on synthetic vectors and the sealed corpus metadata. Then seal `inputs/extraction-execution-contract-v01.json`, `inputs/geometry-implementation-contract-v01.json`, the input binding, authorization packet, and source scripts with `source/seal_preflight.py`.
2. Verify parent trees and download only pinned config/safetensors into the isolated `model-assets` directory using `source/prepare_model.py`.
3. Run `source/run_extraction.py`; it loads the pinned model once, processes every event, repeats the first 256 rows exactly, and records parameter identity before/after.
4. Seal and verify the complete feature cache with `source/seal_feature_cache.py`.
5. Run `source/run_geometry.py` only after the feature-cache seal verifies.
6. Seal the complete extraction/geometry result tree with `source/seal_result.py`.

The run stops with S01-3 unauthorized. Probe fitting, nonlinear diagnostics, adaptation, feature/view search, and backbone writes are outside this authorization.
