# Temporal R-GCN Link Predictor v1

## Outcome

`phoenix-temporal-rgcn-link-predictor/v1` is the first learned model over the canonical Smallpedia temporal link-prediction task. It trains exclusively from frozen train facts, evaluates every validation query against all 47,433 dynamic entities, strictly beats a certified train-only structural baseline, restarts from an mmap weight artifact without Candle or retraining, and never opens the locked test split.

The final predictor is deliberately a structural-prior R-GCN rather than a pure neural score. The exact train relation/destination frequency is the strong baseline. A learned one-layer R-GCN residual breaks its large tie groups. This is both faster and materially stronger than asking a 16-dimensional model to relearn exact counts that are already present in authoritative train topology.

## Authority and leakage boundary

The trainer opens two immutable sources:

- `phoenix-external-graph-dataset/v1` Smallpedia mmap facts;
- `phoenix-canonical-link-prediction-task/v1` validation/test query authority.

Source dataset ID, source binary BLAKE3, task ID, task binary BLAKE3, candidate universe, and base/directed relation counts must agree before staging.

Only temporal facts marked `Train` become messages or optimizer examples. Validation and test facts are bounds-checked but never enter the encoder, structural prior, collision set, negative sampler, or optimizer. Static Smallpedia facts are excluded from v1 because the canonical candidate universe contains only dynamic entities.

Every train fact produces:

- one forward and one inverse degree-normalized message;
- one forward and one inverse positive example;
- one deterministic collision-free negative per direction by default.

The topology digest covers timestamp, source, base relation, and destination for every train fact in canonical source order. It is stored in both staging and training receipts and rederived before restart inference.

## Model

The Candle CPU model contains:

1. one 16-wide embedding per dynamic entity;
2. one 16x16 self transform;
3. one 16x16 transform for each of 566 directed message relations;
4. one 16-wide DistMult decoder vector and bias per directed relation.

One full-batch R-GCN layer applies degree-normalized train-only messages and ReLU. Training uses deterministic full-batch SGD with binary cross-entropy, L2 regularization, and a certified SplitMix64 seed.

Canonical score:

`train_relation_destination_frequency + 0.01 * RGCN_DistMult_logit`

The prior is not persisted as a 107 MB dense sidecar. Restart derives sorted sparse frequency rows from the already staged train message batches. Candidate scoring uses two `f32x8` products per entity, reuses the evaluator's fixed score buffer, and performs no per-query allocation.

## Frozen artifact

The 3,654,880-byte weight file is fixed-width, little-endian, BLAKE3-addressed, and mmap-backed. Its checked sections are entity embeddings, self transform, directed relation transforms, decoder relations, and decoder biases.

The model ID binds source/task identities, candidate and relation dimensions, hyperparameters, runtime, training receipt, optimizer receipt, topology digest, weight digest, and byte count.

The separate manifest ID binds the model ID to both validation certificates. This removes the score/model circularity while making certificate substitution detectable. A future locked test certificate can create a new manifest identity without changing the selected model or weight digest.

Open verifies both identities, safe local weight naming, exact byte count, full weight BLAKE3, header/version/dimensions, and every section offset before exposing mmap slices.

## Baseline gate

The certified baseline is exact train-only relation/destination frequency under the same canonical evaluator:

| Metric | Structural baseline | Temporal R-GCN | Delta |
| --- | ---: | ---: | ---: |
| Filtered MRR | 0.0579259492 | 0.0581034200 | +0.0001774708 |
| Hits@1 | 0.0380277171 | 0.0383053818 | +0.0002776647 |
| Hits@3 | 0.0541569484 | 0.0544407834 | +0.0002838350 |
| Hits@10 | 0.0949057791 | 0.0955166414 | +0.0006108622 |

The trainer fails before artifact installation unless learned MRR is strictly higher. The gain is modest and should not be oversold, but it is real across 101,243 unique validation queries, 162,066 positives, and 4,802,259,219 candidate scores.

## Final real-corpus certificate

Compilation used `CARGO_TARGET_DIR=D:\phoenix-target-overgraph`; the D: executable installed the final immutable artifact on C:.

- Manifest ID: `b3-105197893c14d869f710c17bc8f486f2c5f468ac6b13bef313f652018699af1b`.
- Model ID: `b3-7ce42c9d329eebbe593c2043106c79314269903a1fbebae142db21f6f3d62c30`.
- Weight BLAKE3: `b3-c67202ed551ad800deec58c7da06eaf7f74b635b06249e00257acb10178c2bcd`.
- Validation certificate: `b3-9613f3ebfad57ead7b094bcae023907fc70f273210855dc62442b870815404f5`.
- Baseline certificate: `b3-cdd74fc99b50ff7070eb51dd8f2f3e6a7998cf987a68a9bc971e77f8519174eb`.
- Artifact: `target/graph-research-models/temporal-rgcn-v1-certified-final`.

| Resource | Final measurement |
| --- | ---: |
| Train facts | 387,757 |
| Directed messages | 775,514 |
| Training examples | 1,551,028 |
| Exact staged bytes | 29,659,264 |
| Staging | 176.947 ms |
| Four-epoch training | 10.798 s |
| Canonical encoding | 93.320 ms |
| Canonical learned validation | 47.926 s |
| Restart mmap open plus encoding | 90.079 ms |
| Peak working set | 4,959,789,056 bytes |
| Allocation volume | 40,302,295,450 bytes |
| Weight mmap | 3,654,880 bytes |

The one-epoch probe trained in 4.515 seconds and produced nearly identical metrics. Four epochs therefore are not the current quality limiter. Exact all-entity validation is the dominant runtime, while autograd allocation volume and 4.96 GB peak memory are the trainer's main optimization targets.

## Proof gates

- Same source, task, seed, and configuration reproduce model ID, weights, and validation certificate across independent output roots.
- A different certified seed produces different weight and model identities.
- Synthetic validation requires the learned residual to beat the structural prior.
- Train-only message/example counts are exact.
- Negative targets cannot collide with any observed train triple in the same directed query.
- Weight corruption fails before mmap values are exposed.
- Source/task/topology drift fails before inference.
- Restart score bits are exact over the full canonical candidate universe.
- The real validation artifact contains no test certificate and creates no test claim.

## Implementation map

- `temporal_rgcn_model.rs`: architecture, receipts, identities, profiles, and errors.
- `temporal_rgcn_artifact.rs`: immutable weights, manifest identity, mmap loading, and corruption checks.
- `temporal_rgcn.rs`: train-only staging, sparse structural prior, SIMD encoding/scoring, and baseline evaluator.
- `candle-baseline-trainer/src/temporal_rgcn.rs`: deterministic Candle training, authoritative validation, baseline gate, artifact installation, and restart proof.
- `candle-baseline-trainer/src/temporal_rgcn_main.rs`: release execution surface.
- `candle-baseline-trainer/tests/temporal_rgcn.rs`: end-to-end determinism, seed separation, corruption, baseline, leakage, and restart test.

## Next research pressure point

Completed in [Temporal R-GCN Trainer Memory v2](temporal-rgcn-trainer-memory-v2.md). The fused allocation-free epoch kernel reduced training to 0.717 seconds, total allocation volume to 138.468 MB, and peak working set to 136.233 MB while preserving the frozen artifact/evaluator boundary. Exact canonical validation is now the dominant pressure point.
