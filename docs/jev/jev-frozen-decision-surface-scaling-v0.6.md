# Jev Frozen Decision Surface Scaling v0.6

Status: active narrow extension. This protocol does not reopen v0.4 and does not create a QLoRA gate.

## Lanes

`v0.6-S` scales the validated v0.5 closed-world compatibility head from the existing 100k reference to one 250k S100 point on MiniCPM5-1B, Qwen3-0.6B, and K2-Horizon-0.9B. The backbone, final-layer `mean_full` representation, `name_definition` candidate profile, source-typed L3 loss, three-epoch schedule, and protected evaluation bank remain fixed.

`v0.6-B` is a separate contradictory-binding evaluation. An opaque surface previously associated with one semantic candidate is paired with another candidate's definition; gold follows the exposed definition, not the opaque token's prior affinity.

`v0.6-O` is a parallel open-world extension. It adds an outside-candidate score and is not mixed into the closed-world scaling curve. The canonical distinction remains:

```text
closed world: sum(candidate probabilities) = 1
open world:   sum(candidate probabilities) + P(other) = 1
```

## Fixed boundaries

- no Phoenix data or production artifacts;
- no LoRA, QLoRA, SFT, PPO, RL, or backbone updates;
- v0.4 QLoRA gate is sealed and byte-protected;
- v0.5 reports and caches are read-only inputs;
- real-data mixture cells are not repeated in this slice;
- 250k is a scaling point, not a rescue point or adaptation authorization.

## Required measurements

For `v0.6-S`, retain exact-world accuracy, NLL, Brier, ECE, OOD behavior, intervention behavior, and marginal quality per added training group and GPU-hour against the v0.5 100k S100 reference.

For `v0.6-B`, report ordinary opaque-definition performance beside binding-adversary performance and retain episode IDs for identity-affinity failures.

For `v0.6-O`, report candidate-set conditional quality, outside-mass quality, and whether adding/removing candidates changes explicit-candidate probabilities only according to the declared open-world semantics.

This protocol deliberately keeps the fixed closed-world compiler and the open-world capability extension in separate lineages.
