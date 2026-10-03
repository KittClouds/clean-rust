# System 1.5 Semantic Graft — Causal Phase 4A

This source implements the single causal Phase 4A intervention: one shared-weight recurrent block applied four times over the frozen P2-CONSIST typed state. The output graft and backbone remain frozen; only recurrence and its two output projections train. P3-BALANCED is retained as a separately hash-bound reference.

The script reads only the frozen BANK-v1 TRAIN and DEV cache on C: and writes a new run to `C:\phoenix-target-overgraph\semantic-graft-phase4a-causal-20261001-v02`. It refuses to overwrite an existing output identity. Protected TEST truth and BANK-v2 are outside this run. A prior preflight-only attempt is preserved separately at the original unversioned output path; it failed before freezing a Phase 4A spec or starting training.

Run from this directory with `python run.py`. Verify a completed artifact with `python verify.py`. The run freezes `PHASE4A-SPEC.json` before training, writes per-depth DEV metrics and estimates, and finishes with `PHASE4A-RECEIPT.json` plus a hash-binding `FINAL-SEAL.json`.

No depth, width, surface, objective, or architecture search is implemented. DEV selects the best epoch using the inherited P2-CONSIST objective evaluated on Z4; it never selects among recurrent depths.
