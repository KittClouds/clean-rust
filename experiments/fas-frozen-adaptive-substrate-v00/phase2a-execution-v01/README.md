# FAS-00 Phase 2A execution v01

This sidecar implements only the sealed `phase2a-v01` feature extraction packet. It is separately hashed and sealed before model loading. Its corpus parser decodes only the four permitted fields and skips every other JSON value without decoding it.

The execution order is fixed:

1. `seal-execution.ps1` verifies the Phase 0, Phase 1, Phase 2A paperwork seals and this executor source seal.
2. `extract_fas_features.py --preflight` rechecks corpus identities, projects the permitted fields, verifies row counts and writes a no-model-contact preflight receipt.
3. `extract_fas_features.py --extract` downloads only the pinned revision to new FAS-only paths, validates the revision and shape, runs the frozen deterministic repeat sample, then writes the complete feature cache.
4. `extract_fas_features.py --validate-cache` independently checks serialized row identities, token IDs, per-row feature hashes, tensor shape/size, model snapshot hashes and the no-learning disposition.
5. `seal-cache.ps1` hashes and seals the output tree after validation.

No probe, arm, baseline, or evaluation code is present in this execution sidecar. A failed identity, dimension, determinism, tensor, or parameter-integrity check stops the run. Partial files remain diagnostic and are not a ready cache.
