# Temporal R-GCN Trainer Memory v2

## Outcome

`phoenix-fused-temporal-rgcn16/v2` removes the physics-limiting Candle autograd tape from Temporal R-GCN training while preserving the frozen model format, train-only topology authority, canonical evaluator, structural-prior score, validation baseline gate, and mmap restart path.

The four-epoch Smallpedia training step fell from 10.798 seconds to 0.717 seconds. Process allocation volume fell from 40.302 GB to 138.468 MB and peak working set fell from 4.960 GB to 136.233 MB. The training kernel itself owns 3.655 MB of parameters plus a 9.726 MB exact-sized gradient arena, allocates 13.381 MB exactly, and performs zero heap allocations across all epochs.

This is a training-kernel replacement, not a new graph model. It computes the same one-layer, degree-normalized R-GCN, DistMult binary cross-entropy, L2 regularization, and full-batch SGD update. The operation order is now explicit and deterministic rather than delegated to an autograd graph.

## Pressure-point trace

The v1 model contains only 3.65 MB of frozen weights. Its memory did not come from model capacity.

The old training path retained:

- a 566-operation `index_add` encoder graph;
- source, target, and relation gathers of shape `1,551,028 x 16`;
- their elementwise products and binary-cross-entropy intermediates;
- reverse-mode state for every relation batch and query tensor;
- cloned graph and query arrays in Candle tensors.

That made a small model produce 40.3 GB of allocation traffic and a 4.96 GB peak working set.

## Fused design

The v2 trainer consumes the already staged relation and query arrays directly. It creates only:

1. five exact-sized parameter vectors;
2. encoded node rows;
3. encoded-node gradients;
4. node-embedding gradients;
5. self-transform gradients;
6. relation-transform gradients;
7. decoder and bias gradients.

Each epoch executes four allocation-free passes:

1. relation-batched R-GCN encoding with `f32x8` dot products;
2. streaming DistMult/BCE gradients over canonical examples without query gathers;
3. reverse relation traversal into the reusable gradient arena;
4. in-place deterministic SGD and L2 updates.

The trainer samples the allocator immediately before the epoch loop and fails closed if either allocated bytes or allocation count changes. It also records exact parameter bytes, gradient-arena bytes, training allocation volume/count, working set, and process-wide telemetry in the v2 report.

The runtime identity is intentionally honest: `phoenix-fused`, `temporal-rgcn-memory-v2`, `cpu-wide-f32x8`. Candle remains the proven baseline framework and crate host, but the temporal training receipt does not claim Candle executed gradients it no longer owns.

## Mathematical shields

- Central-difference checks cover node embeddings, self transforms, relation transforms, decoder relations, and decoder biases.
- Same source, task, seed, and configuration reproduce weight BLAKE3, model ID, validation scores, and validation certificate across independent real-corpus runs.
- Different seeds remain distinct certified identities.
- Exact train-only staging counts and topology identity are unchanged.
- Learned validation MRR must still strictly beat the certified structural baseline before artifact installation.
- Restart scoring remains bit exact from mmap weights.
- Weight corruption and source/task/topology drift still fail before scoring.
- The locked test split remains unopened and unclaimed.

## Certified real-corpus result

Compilation used `D:\phoenix-target-overgraph`; the release executable installed immutable artifacts under the C: workspace.

- Manifest ID: `b3-eb3b3b7ca9999403b440a87c1a310a4b08c30f579766bb524c064294781f3049`.
- Model ID: `b3-261c2935b5b80b6f999f7cb065c9bd53bab6a7f8436e8a8a08bf38e9de2b7e43`.
- Weight BLAKE3: `b3-f4d14dc5858e86d590fd39647018c6ee4a40c5f23662f9eb381afd30c61bfae3`.
- Validation certificate: `b3-84cc094b232ee3b0c645436689dd84fb3fa66c73f6b995438c0b855fa65d8519`.
- Performance certificate: `b3-152d403aa25cdc16833cc4112f6662bb4b00cb1e68d7eb9f41ef875dbff41ea3`.
- Artifact directory: `target/graph-research-models/temporal-rgcn-memory-v2-final`.

| Resource | v1 | Memory v2 | Change |
| --- | ---: | ---: | ---: |
| Four-epoch training | 10.798 s | 0.717 s | 15.1x faster |
| Process allocation volume | 40.302 GB | 138.468 MB | 291x lower |
| Peak working set | 4.960 GB | 136.233 MB | 36.4x lower |
| Training allocation volume | not isolated | 13.381 MB | exact parameters plus arena |
| Epoch allocation volume/count | not bounded | 0 bytes / 0 | fail-closed invariant |
| Training working set | not isolated | 108.835 MB | measured resident set |
| Canonical encoding | 93.320 ms | 74.339 ms | 1.26x faster |
| Restart open plus encoding | 90.079 ms | 92.125 ms | effectively unchanged |
| Canonical validation | 47.926 s | 49.763 s | dominant remaining cost |

The independent probe and final run produced the same model, weights, score digest, validation metrics, and certificate. Timing fields differ, as expected, and are isolated in content-addressed performance reports rather than model identity.

## Quality gate

| Metric | Structural baseline | Memory v2 | Delta |
| --- | ---: | ---: | ---: |
| Filtered MRR | 0.0579259492 | 0.0581752789 | +0.0002493296 |
| Hits@1 | 0.0380277171 | 0.0384041070 | +0.0003763899 |
| Hits@3 | 0.0541569484 | 0.0545950415 | +0.0004380931 |
| Hits@10 | 0.0949057791 | 0.0956030259 | +0.0006972468 |

The modest quality gain over v1 comes from the explicit fused floating-point operation order. It is certified but not treated as a model-capacity result.

## Remaining physics limit

The evaluator sequence is now complete through [Exact Tiled Query/Candidate Scorer v1](exact-tiled-query-candidate-scorer-v1.md). Exact validation of 4,802,259,219 candidates runs at a five-run p50 of 4.916 seconds and p95 of 4.999 seconds while preserving every score bit, rank, metric, digest, and certificate identity.
