# Hyper Learning Gates v1

## Contract

WD50K optimization remains locked until three deterministic fixtures pass:

1. A generic positive/filtered-negative pair must be overfit by the triple control.
2. A value-symmetric fixture must be solved by Value-only and Full StarE, while CompGCN, Role-only, and `QualifierGradientNull` remain unable to distinguish both contexts.
3. A role-symmetric fixture must be solved only by Full StarE; CompGCN, Value-only, and `QualifierGradientNull` remain unable by construction.

`Detached v1` remains a historical matrix arm. `QualifierGradientNull` is a distinct causal control and is never independently trained. It aliases the exact CompGCN training outcome, evaluates the StarE surface, retains checkpoint-zero qualifier parameters, and records the CompGCN checkpoint model identity as its base.

## Optimizer correction

The legacy recipe performs one full-epoch mean-reduced update with coupled L2. On the frozen WD50K matrix this reduced qualifier gradients to approximately `1e-12`, below meaningful `f32` update scale, while decay dominated movement.

The functional gates use a deliberately narrow wake-up recipe:

- deterministic source order;
- one positive/filtered-negative pair per batch;
- sum reduction;
- `2^8` global loss scale;
- global norm clipping at `1.0`;
- no weight decay;
- 512 epochs, or 512/1024 updates for the one/two-pair fixtures;
- zero allocations inside the epoch/update loop.

The fixture initialization is controlled and symmetric. Embeddings begin equal, transforms begin as identity matrices, and the non-varied side of the multiplicative role/value composition is initialized to the multiplicative identity. Therefore a successful margin must be learned through the varied qualifier slot.

## Durable evidence

Every trained arm is written through the existing content-addressed hyper-encoder model format, reopened through the mmap loader, and rescored bit-exactly. The gate receipt binds source, task, optimizer, initialization, score, parameter-delta, checkpoint, manifest, and restart identities. Receipt corruption fails before use.

The launch condition is conjunctive: all three fixtures, immutable receipt replay, mmap score replay, null-control aliasing, and checkpoint-zero qualifier-block equality must pass.

## Real-data boundary

The overlap boundary is now closed by `phoenix-role-scoped-qualifier-null-composition/v1`. The null evaluator owns two independently verified mmap artifacts and routes reads by semantic role:

- primary entity, primary relation, shared transforms, direction matrices, and decoder bias read the trained CompGCN checkpoint;
- qualifier value, qualifier role, and qualifier projection read the checkpoint-zero StarE snapshot;
- one numeric entity or relation ID may be read from both parents during the same statement without restoring or copying shared rows;
- the composition manifest references both immutable parents and writes zero redundant weight bytes;
- a deterministic routing receipt binds every `(parameter class, semantic role, ID, source model)` tuple used by the audit surface.

The correctness fixture uses the same entity and relation IDs in primary and qualifier positions inside one statement. Mutating either source changes only its semantic channel. Qualifier-free routed scoring collapses bit-for-bit to CompGCN. Corruption of either parent fails before scoring. The WD50K optimization envelope is therefore unlocked at the evaluator boundary; no real WD50K envelope run was executed by this cut.

## Loss-scale identity

`LossScaleSemantics` is now a frozen optimizer identity axis:

- `UnscaleBeforeClip` treats the global scale as a numerical device and removes it before norm measurement, clipping, and update.
- `ClipScaledGradient` preserves the historical wake-up algorithm in which clipping observes the scaled gradient.

Every checkpoint economics receipt includes the final clip coefficient, final-step activation flag, and aggregate clip activation rate across optimizer steps. Power-of-two scaling under `UnscaleBeforeClip` reproduces the unscaled weights and optimizer digest bit-for-bit.

## Verification

- Phoenix graph research library: 56 passed.
- Candle baseline trainer: 15 passed across unit and integration suites.
- Historical functional learning gates remain deterministic, restart exact, and passing.
