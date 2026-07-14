# Qualifier Signal Isolation Matrix v1

Status: implemented and certified on frozen WD50K.

This experiment preserves the paired four-epoch CompGCN/StarE result as an immutable reference specimen. It does not reinterpret that result as an architectural rejection. It isolates where qualifier information enters the existing fused encoder under one initialization, one filtered negative schedule, one candidate universe, and the authoritative full-candidate evaluator.

## Frozen interventions

The ordered matrix is part of the experiment identity:

1. `compgcnTriple`: qualifier roles and values are masked.
2. `stareQualifiers`: real qualifier roles and values enter messages and decoder queries.
3. `roleOnly`: qualifier values are masked; role embeddings remain.
4. `valueOnly`: qualifier roles are collapsed; value embeddings remain.
5. `shuffled`: qualifier contexts are rotated within the same split and primary relation.
6. `detached`: real qualifier messages are used in the forward path; qualifier-specific gradients are blocked.
7. `queryOnly`: qualifiers condition decoder queries but not graph messages.
8. `messageOnly`: qualifiers condition graph messages but not decoder queries.

All arms start from the same bit-identical weights and consume the same deterministic positive/filtered-negative example schedule. Test access is prohibited. The shuffled reference digest, intervention order, resulting model IDs, validation certificate IDs, and gradient-economics digests are bound into the matrix identity.

## Gradient economics

The final epoch records mean binary cross-entropy and, for each parameter block:

- L2 gradient norm;
- parameter norm;
- optimizer update norm;
- update-to-weight ratio;
- exactly-zero gradient count.

The blocks are entity embeddings, relation embeddings, relation projection, qualifier projection, direction matrices, and decoder bias. Measurements are taken after complete backward propagation and before the SGD update. They introduce no epoch allocation.

## Durability contract

Each arm is written as an immutable content-addressed model artifact. Every model is then reopened through mmap and rescored with the authoritative evaluator. The restart certificate must equal the live certificate exactly. The immutable matrix manifest recomputes its own identity when opened; model manifest IDs are excluded from the circular matrix identity while model IDs, score certificates, and economics remain bound.

## Certified WD50K result

Matrix:

`b3-808fb05beaf1fde0c82a3fa7de92f009d3dd5859e5914457f7ee21a925a57fb6`

Artifact:

`target/graph-research-models/qualifier-signal-isolation-matrix-v1`

| Arm | Validation MRR | Qualified MRR | Qualifier gradient L2 |
| --- | ---: | ---: | ---: |
| CompGCN | 0.0017855040 | 0.0016541088 | 0 |
| StarE | 0.0017832635 | 0.0016559782 | 8.087e-12 |
| Role-only | 0.0017614094 | 0.0011922498 | 1.508e-9 |
| Value-only | 0.0018958765 | 0.0020440533 | 2.035e-10 |
| Shuffled | 0.0017852623 | 0.0016427490 | 8.557e-12 |
| Detached | 0.0017832635 | 0.0016559782 | 0 |
| Query-only | 0.0017833816 | 0.0016384194 | 7.461e-12 |
| Message-only | 0.0017830315 | 0.0016542632 | 3.311e-12 |

Value-only improves overall MRR by 6.18% and qualified-query MRR by 23.57% over the triple-only control at this checkpoint. Role-only is harmful. Real and shuffled qualifiers are nearly tied to the control.

The decisive finding is optimization scale: all final losses remain effectively `ln(2)`, full StarE and detached StarE have the exact same score digest, and qualifier gradients are many orders of magnitude below the L2 component of the update. This run proves active forward qualifier semantics but does not prove useful learned qualifier propagation. The next experiment must be an optimization envelope, not another architecture.

## Verification gates

- eight distinct content-addressed model identities;
- deterministic matrix identity and scientific outputs across repeated fixture runs;
- detached qualifier projection has exactly zero raw gradients;
- all eight live/restart certificates are exact;
- immutable matrix identity validates on reopen;
- no test partition access;
- zero allocations inside every fused training epoch;
- all source, task, shuffled-reference, schedule, model, score, and economics identities are BLAKE3-addressed.
