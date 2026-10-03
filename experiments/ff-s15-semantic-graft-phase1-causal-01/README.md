# Causal semantic graft, Phase 1

This wrapper trains the exact frozen Phase 0 causal Base graft. It imports the
unchanged model, objective, supervision ABI, prepared populations and cache identities.
The user-authorized candidate cap is 28; no candidate or action endpoint is dropped.

The run uses 20,000 TRAIN rows and 2,000 DEV rows, deterministic FP32 CUDA, AdamW,
twenty maximum epochs, cosine scheduling, and six-epoch early stopping. Every epoch
visits the complete TRAIN population and saves a checkpoint. The minimum exact DEV
five-term aggregate selects the checkpoint; no architecture or target search occurs.

Global and candidate states retain the Phase 0 dimensions 64/64. Unavailable targets
remain masked; the counterfactual support loss remains inactive. No representation
extraction, backbone update, protected TEST, BANK-v2, VCS or System 1.5 change occurs.

New artifacts live on C: NVMe:
`C:\phoenix-target-overgraph\semantic-graft-phase1-causal-20261001`.

From this directory:

```powershell
python test_phase1.py
python run.py
```

The harness tests are synthetic engineering checks, not Phase 1 learning evidence.
The run freezes the wrapper and training spec before optimizing BANK. Completed
artifacts include all checkpoints, optimization history, a selected graft with its
TRAIN normalizer, per-target DEV metrics and trivial controls, candidate-conditioning
and renderer diagnostics, runtime MODEL_ESTIMATE envelopes, and a hash-bound receipt.

Phase 0 world semantics do not imply evidence-supported epistemic justification.
Candidate legality and legal one-step goal satisfaction are the only sourceable
candidate targets. Count supervision is a restricted 0/1 annotation proxy.

Only causal Base is trained here. NER-LoRA, NLI-LoRA and encoder remain unchanged;
there is no cross-lane winner or hidden-coordinate alignment.
