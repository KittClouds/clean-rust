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

The synthetic fixtures deliberately keep qualifier-only IDs out of primary-triple roles, so the CompGCN checkpoint cannot alter their shared embedding rows. WD50K may reuse an entity or relation in both primary and qualifier roles. Before the real optimization envelope is allowed to run, the evaluator must audit that overlap and provide a separate checkpoint-zero qualifier read view whenever overlap is nonzero. Restoring shared rows in the CompGCN backbone would violate the counterfactual; silently using trained shared rows would violate the checkpoint-zero qualifier source.
