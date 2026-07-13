# Frozen Model Artifact v1

## Purpose

`phoenix-frozen-model/v1` is the immutable boundary between certified graph research
and a runtime that can perform inference. A model is not identified by a mutable name
or checkpoint directory. Its model id is BLAKE3-addressed over its source identities,
architecture, hyperparameters, seed receipt, runtime, training receipt, score
certificates, tensor directory, and weight-blob digest.

V1 freezes the exact MLP-16 architecture already used by the Baseline Ladder. It does
not introduce a second model design:

```text
16 features -> dense 16 + ReLU -> dense 1 + sigmoid
```

The four required tensors are row-major `hidden.weight [16,16]`, `hidden.bias [16]`,
`output.weight [16]`, and `output.bias [1]`.

## Identity chain

Every manifest binds:

- the content-addressed frozen dataset id and its checkpoint id/generation;
- the exact frozen tensor id;
- the train-topology derivation id and train-topology BLAKE3;
- the certified evaluation protocol id;
- all certified seeds and the selected repeat;
- framework, framework version, backend, and compilation target;
- deterministic architecture and hyperparameters;
- trainer, optimizer implementation, optimizer-state BLAKE3, completed steps and
  epochs, example counts, and the number of training executions;
- validation/test-lock assertions and score/metric certificates;
- the exact ordered tensor layout and mmap weight-blob BLAKE3.

Dataset, tensor, topology derivation, topology, evaluation protocol, optimizer state,
weights, scores, and metrics must carry valid lowercase `b3-` identities. Seed
certificates are recomputed from their little-endian seed bytes. The selected repeat
must exist in that certificate.

## Immutable storage

Weights use `phoenix-frozen-model-weights/v1`, a little-endian fixed-width binary with
a 32-byte header followed by four contiguous `f32` tensor sections. The manifest
holds every tensor's name, shape, element count, and byte offset.

Opening a model:

1. recomputes the complete model identity;
2. requires content-addressed manifest and weight filenames;
3. mmaps the weight file;
4. verifies file length and BLAKE3 before exposing bytes;
5. validates header version, tensor count, exact contiguous offsets, shapes, bounds,
   and absence of trailing bytes.

The write path is binary then manifest, with `create_new`, file sync, atomic rename,
and byte-identical reuse. An existing path with different bytes fails closed.

## Selection and score contract

Every frozen model must prove that selection used validation and that test stayed
locked during selection. At least one validation score certificate is mandatory.
Certificates bind task, evaluator schema, split, score count, `f32-le` score BLAKE3,
and serialized metric BLAKE3. Duplicate task/split certificates are rejected.

Adding a held-out test certificate after selection creates a new model artifact id,
while the content-addressed weight identity remains unchanged. This makes evaluation
provenance explicit without pretending that identical weights are different bytes.

## Restart guarantee

`FrozenModelMapped::score_mlp16` loads the four mapped tensors into fixed-size stack
arrays and performs SIMD reference inference. It has no trainer, optimizer, mutable
graph, or model-initialization input.

The restart test writes once, drops the training snapshot, reopens only the immutable
manifest and mmap weight blob, and requires bit-exact score and score-certificate
parity across two independent opens. A 20,000-row restart inference performance gate
also runs without any training execution.

## Failure shields

V1 rejects source identity drift, zero checkpoint generation, invalid seed digests,
non-finite weights or hyperparameters, tensor reordering or shape drift, missing
validation certificates, unlocked test selection, multiple training executions,
optimizer-state drift, manifest edits, weight corruption, renamed artifacts, section
gaps/overlaps, and trailing bytes.

## Scope guard

V1 stores final inference weights and an optimizer receipt; it does not store optimizer
state for training resume. It does not train a model, read live graph state, mutate
topology, unlock test data, or add Candle to the Phoenix workspace. Candle Baseline
Trainer v1 is the next ticket and must emit this artifact rather than inventing a
parallel checkpoint format.
