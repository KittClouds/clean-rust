# Canonical Link Prediction Task v1

## Outcome

This slice installs an exact, content-addressed temporal link-prediction task over the frozen `tkgl-smallpedia` source artifact. The production path is Rust-only: source facts and the task are mmap-backed; the official TGB protocol-5 negative files are decoded by a restricted, non-executing parser; official parity is mandatory before installation; filtered ranking uses SIMD; and test access is fail-closed behind one durable task-wide claim.

Schema: `phoenix-canonical-link-prediction-task/v1`.

## Official semantics

The contract was audited against the pinned TGB source and its temporal knowledge-graph documentation:

- TGB groups split facts by `(timestamp, source, relation)` and records every observed destination for that query.
- Candidate negatives are every dynamic entity ID except that query's observed destination set.
- Inverse queries are appended after original queries. Their source and destination are exchanged and their relation is `base_relation + relation`.
- Ranking uses the average tie rank: `0.5 * (count(score > positive) + count(score >= positive)) + 1` after all filtered destinations are excluded.
- Certified metrics are filtered MRR and Hits at 1, 3, and 10.

Phoenix regenerates both official conflict dictionaries directly from the frozen split facts. It independently decodes the pinned validation and test pickle receipts and requires complete ordered equality: query order, timestamp, source, directed relation, destination order, and every destination value. Any difference fails before task serialization.

The pickle parser recognizes only the small opcode and NumPy-value surface found in the pinned official receipts. It does not import Python, execute globals, construct arbitrary objects, or accept unaudited opcodes.

## Compact mmap task

The binary stores:

1. a checked little-endian header;
2. fixed-width query records;
3. one flat destination-conflict array.

Each query record contains timestamp, source, directed relation, conflict offset/count, split, and inverse flag. Validation records are contiguous before test records. The candidate universe is implicit `0..candidate_universe`; billions of negative pairs are never materialized.

Open verifies the manifest identity, full binary BLAKE3, exact file layout, every query's split/direction/range contract, all manifest-derived counts, and every conflict destination before exposing zero-copy slices. A forged validation/test boundary cannot change which records are visible.

`task_id` binds the schema, frozen source dataset and binary identities, both official pickle identities, both full parity identities, and the canonical task binary identity.

## Evaluation surface

The evaluator allocates exactly two candidate-sized buffers once:

- immutable destination IDs;
- mutable model scores.

The caller scores one unique query into the reusable score buffer. Ranking scans that buffer with eight-lane `wide::f32x8` comparisons. All observed destinations for the query are filtered for every positive, including ties. Non-finite scores fail immediately.

Score certificates bind task ID, model ID, split, the canonical BLAKE3 stream of every score in query/candidate order, metrics, query count, positive count, and candidates scored. On little-endian targets, score buffers enter BLAKE3 in one bulk operation per query; this preserves the certificate identity while removing billions of tiny hasher calls.

## Test lock

Validation is directly evaluable. Test records are private to the evaluator and require an immutable lock receipt binding:

- task ID;
- frozen model-selection ledger ID;
- selected model ID;
- validation certificate ID.

Before any test query reaches a scorer, Phoenix atomically creates and syncs a claim named by the task ID. The claim is task-wide, not lock-wide: a second lock cannot reopen the same test. If scoring fails, the claim remains burned. A successful score certificate is written immutably only after evaluation. This is intentionally fail-closed; operators must create a new task identity to perform a new test campaign.

No real Smallpedia test evaluation was executed during this slice. The test partition remains unclaimed because no selected learned model exists yet.

## Real-corpus certificate

Release compilation used `CARGO_TARGET_DIR=D:\phoenix-target-overgraph`; executables on `D:` read the frozen source and installed the final task on `C:`.

Final task:

- task ID: `b3-4a89c46f19d4636e5669d84ba1795eb89fe082c4185506e297e9a0ffbe21db5d`;
- manifest: `target/graph-research-datasets/canonical-link-prediction-v1-final/b3-4a89c46f19d4636e5669d84ba1795eb89fe082c4185506e297e9a0ffbe21db5d.manifest.json`;
- binary bytes: 7,850,552;
- dynamic candidate entities: 47,433;
- base relations: 283;
- derived directed relations: 566;
- validation: 101,243 unique queries and 162,066 positives;
- test: 103,430 unique queries and 163,172 positives;
- inverse queries: 76,986.

Release task construction, including two full pickle decodes and complete parity comparison, took 341.656 ms. The final hardened cold-process mmap open, including full BLAKE3 and every record/count contract, took 6.501 ms.

The authoritative full-validation evaluator gate scores 4,802,259,219 candidates and 162,066 positives. The original per-float certificate hashing path took 97,551.189 ms. Bulk canonical hashing reduced it to 20,799.111 ms with the identical score certificate `b3-fcec089dc4399787994a3bb5bfa68c7c8a3c2050f813b0d22151fdbd3303996f`, a 4.69x reduction with exact output parity. The scorer in this throughput gate is a deterministic candidate-ID fixture, not a research baseline.

## Verification gates

- Exact regenerated-vs-official conflict parity passes for the real validation and test receipts.
- Same frozen source and official bytes produce the same task identity.
- Restricted pickle parsing rejects an executable global.
- Official-parity drift fails before task installation.
- SIMD average-tie filtered ranking matches a hand-computed tie/filter case.
- Test claims are durable and task-wide before scoring.
- A scorer failure burns the claim; retry cannot expose test records.
- Binary corruption fails before mmap query access.
- The debug performance test evaluates 5.12 million candidates under a five-second guardrail.
- Focused task tests pass.
- Strict crate-scoped Clippy with all targets and `-D warnings` passes.

## Implementation map

- `link_prediction_model.rs`: schemas, public receipts, metrics, and errors.
- `tgb_pickle.rs`: restricted official negative-file decoder.
- `link_prediction_build.rs`: temporal-domain derivation, inverse-query generation, and exact official parity.
- `link_prediction_artifact.rs`: immutable binary/manifest installation and validated mmap opening.
- `link_prediction_eval.rs`: SIMD filtered metrics, deterministic score certificates, and test lock/claim.
- `build_link_prediction_task.rs`: real release build and parity harness.
- `inspect_link_prediction_task.rs`: cold-process restart proof.
- `benchmark_link_prediction_validation.rs`: complete validation evaluator throughput/certificate gate.

## Next boundary

The next learned-model slice can consume this task without copying topology or materializing negatives. The most useful next ticket is **Temporal R-GCN Link Predictor v1**: train only on train facts, score this task's directed validation queries in candidate batches, select without test access, then exercise the task-wide lock exactly once for the frozen winner. A relation-batch sidecar should be added only if profiling proves the existing typed adjacency layout forces meaningful copying.
