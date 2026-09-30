# Lexi specialization survival

This engineering lane measures how separate NER and NLI specialization changes the frozen LFM2.5-230M capability atlas. It does not search for new surfaces or train on BANK-v1.

`L-S0-lock.json` freezes the four Rung-0 surfaces and the first-token dead control, plus the Rung-1 `edge_existence` survivor as a separate sentinel. The Rung-1 sentinel is the DEV-selected `middle_plus_final` tiny MLP. Its source worlds are synthetic BANK-v1 worlds; it is a local-structure capability check, not a general graph or serving claim.

Each arm starts independently from the same pinned base model. First establish a frozen-backbone task-head control, then try bounded late-layer LoRA. Full fine-tuning stays out of the first pass. OpenNER and the NLI corpus must have separate source locks, train/dev/test paths, run outputs, and checkpoints. BANK-v1 is used only to measure old-head survival, refit recovery, movement across the four locked surfaces, and the edge-existence sentinel.

For each checkpoint, classify capability movement as `STABLE`, `ROTATED`, `REALLOCATED`, `BURIED`, `LOST`, or `IMPROVED`. Do not start attention-head masking until both specialization arms have completed their survival map.

Run the baseline receipt check from the repository root:

```powershell
python experiments/lexi-specialization-survival-20260929/verify_l_s0_lock.py
```

The base model and cached experiment outputs live on `D:`; the lock records their hashes. No BANK labels are used in either specialization training set.
