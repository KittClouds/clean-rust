# Causal semantic graft — Phase 2

Objective-only intervention on frozen causal Base + Phase 0 late graft (s=64,
e=64, 460,662 parameters). This wrapper imports all architecture, prepared data,
target provenance, availability masks and scoring from the immutable Phase 0/1 lane.

Two identities start from the same saved untrained Phase 0 seed initialization and
TRAIN-only normalization. Same 20k TRAIN / 2k DEV populations, complete candidates,
20 epochs, AdamW, cosine schedule, batch 128, deterministic FP32 CUDA, identical
TRAIN order and eight sampled existing renderer pairs per batch. Each arm selects
its lowest exact DEV objective. No coefficient or variance-floor tuning occurs.

P2-BASE reproduces Phase 1: `S + .1E + .25A + CF + .1R`.
P2-CONSIST uses `S + E + .5A + .5CF + .25pair + .05var`.
The latter removes raw latent renderer matching completely. CF is masked dormant.

Prediction consistency averages Bernoulli JS over shared supervised global channels,
and over sourceable targets then valid identity-aligned candidates. Categorical JS
compares complete action distributions when candidate identities align. Misaligned
pairs omit candidate/action consistency instead of guessing. Existing renderer
pairs alone are used. The 0/1 count-regression proxy is clipped into a Bernoulli
probability for JS; its supervised loss and evaluation semantics stay unchanged.

The variance floor is half the per-coordinate population std from the untrained
graft over all TRAIN rows. Variance uses correction=0 with variance clamped at 1e-12
for finite gradients. No named-coordinate or covariance constraint is added.
DEV selection averages variance penalties over fixed sequential DEV minibatches;
DEV never constructs or tunes the reference.

All new output:
`C:\phoenix-target-overgraph\semantic-graft-phase2-causal-20261001`.

Run:

```powershell
python test_phase2.py
python run.py
python verify.py
```

The runnable package freezes before BANK optimization. Architecture, initialization,
data, objective, provenance, reference, selected checkpoints and reports are hashed.
All earlier freezes remain unchanged. No protected TEST, BANK-v2, VCS, new surface,
backbone tuning, architecture rescue or cross-lane winner.

The variance-floor inspiration is deliberately limited to the component described
in [VICReg](https://arxiv.org/abs/2105.04906); this is not a full VICReg implementation.
