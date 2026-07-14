# Canonical Hyper-Relational Link Prediction Task v1

## Outcome

This slice freezes exact head and tail completion over the immutable WD50K
artifact. A statement is one primary triple plus its complete ordered qualifier
range. Official train, validation, and test partitions are preserved; qualifier
pairs never become independent examples.

Schema: `phoenix-canonical-hyper-relational-link-prediction-task/v1`.

The model-facing query contains source, directed relation, borrowed qualifier
offset/count, split, direction, and required target role. It does not expose the
positive entity or source statement index. The evaluator owns those fields and
uses them only for exact ranking and certificate composition.

## Frozen truth

The source remains the authoritative storage for all 236,507 primary facts and
46,645 qualifier pairs. The task binary does not duplicate qualifiers. Each
evaluation query borrows its source artifact's qualifier offset/count, and task
opening rebinds every query to the exact source fact before exposing mmap views.

The task stores only:

1. a checked little-endian header;
2. one 32-byte record per validation/test direction;
3. sorted truth groups keyed by `(source, directed relation, qualifier context)`;
4. one deduplicated flat truth-target array;
5. one eight-byte borrowed-range record per unique ordered qualifier context;
6. one byte per entity and relation for primary/qualifier roles.

Split, inverse direction, and target role are not serialized redundantly. Split
is implied by the contiguous validation/test partition. Direction and target
role are implied by the directed relation ID. A query and truth group carry one
interned `u32` qualifier-context ID; the context table points to one exact
representative range in the source mmap and never copies its pairs.

Opening fails before query access on source identity drift, task BLAKE3 drift,
layout/count overflow, invalid statement binding, invalid qualifier ranges,
incorrect split or direction, missing positive truth, unsorted truth groups,
invalid role bits, or truth-role mismatch.

## Leakage audit

The builder certifies both the original qualifier order and a sorted canonical
order. Complete-statement duplicate detection uses the canonical qualifier set,
so reordered qualifiers cannot evade the audit. The source's original order is
retained for zero-copy encoders; permutation invariance remains a model proof,
not an artifact assumption.

The [pinned StarE evaluator](https://github.com/migalkin/StarE/blob/b294b9e2cde97ab9e81d2736b7f1f0959c9fd98b/loops/evaluation.py#L57-L94)
builds filtered labels from train, validation, and test using the full ordered
qualifier sequence when qualifier sampling is enabled. Phoenix matches that
contract exactly. It does not substitute a broader primary-only filter.

The leakage audit covers distinct primary-triple keys, direct same-relation inverse
keys, complete statement keys, reordered qualifier duplicates, and global
entity/relation role inventories. WD50K declares no semantic inverse map, so the
manifest records that absence rather than fabricating one.

The frozen corpus reports:

- train/validation primary overlap: 676;
- train/test primary overlap: 0;
- validation/test primary overlap: 0;
- train/validation complete-statement duplicates: 272;
- train/test and validation/test complete-statement duplicates: 0;
- reordered cross-split qualifier duplicates: 0;
- train/validation, train/test, and validation/test direct inverse overlap:
  730, 1,448, and 209 directional keys;
- 41,696 primary-position entities and 5,459 qualifier-only entities;
- 487 primary relations and 44 qualifier-only relations.

These values are evidence attached to the task identity. They are not silently
removed or re-split.

## Exact evaluator

Validation supports two distinct certified candidate policies:

- `FullEntity`: rank against all 47,155 entity IDs;
- `PrimaryRole`: retain only entities observed in the required subject or
  object role.

The scorer always receives the canonical candidate order and never receives
the positive target. The policy is applied by the authoritative ranker. Full
ranking uses eight-lane `wide::f32x8` comparisons. Role ranking uses the mmap
role bytes and preserves the same score stream, allowing the two certificates
to share a score digest while retaining different identities and ranks.

All true destinations across train, validation, and test are filtered for the
query's `(source, directed relation, ordered qualifier context)` key. Ties use
exact average rank:

`0.5 * (count(score > positive) + count(score >= positive)) + 1`

after filtered truths are removed. Certificates report MRR and Hits@1/3/5/10,
plus slices by qualifier presence, exact qualifier count, primary relation, and
target provenance (`primary-only`, `primary-and-qualifier`, and the certified
zero-query `qualifier-only` cohort).

The score digest binds internal statement identity, source, positive, directed
relation, borrowed qualifier range, split/direction/role, and every
`f32::to_bits()` value in query/candidate order. Certificate identities hash all
metric floating-point values by bits. Batch sizes one and three reproduce the
same certificate in tests.

## Locked test

Test queries are private to the evaluator. A lock binds task, model-selection
ledger, selected model, validation certificate, and candidate policy. Before a
test query reaches the scorer, the evaluator atomically creates and syncs one
task-wide claim. Scorer failure burns the claim; retry fails. A successful test
certificate is installed immutably after scoring.

No real WD50K test scoring was executed in this slice. The frozen test remains
unclaimed until a selected model exists.

## Real WD50K artifact

Release compilation used `CARGO_TARGET_DIR=D:\phoenix-target-overgraph`; the
binary on `D:` built and reopened artifacts on `C:`.

- source dataset: `b3-763abdf62332cc7bda324be935a4756e759d64b700547c75a9580c67beaa76b2`;
- task: `b3-fa0b90e1b17f716b22324e63936682c07f8a7d31887d9eb5b9c635b1ef7020e5`;
- manifest: `target/graph-research-tasks/canonical-hyper-relational-v1-final/b3-fa0b90e1b17f716b22324e63936682c07f8a7d31887d9eb5b9c635b1ef7020e5.manifest.json`;
- binary bytes: 10,805,334 versus 8,675,744 source bytes;
- train/validation/test statements: 166,435 / 23,913 / 46,159;
- validation/test directed queries: 47,826 / 92,318;
- filtered truth groups/targets: 213,308 / 472,470;
- unique ordered qualifier contexts: 14,610;
- qualifier-bearing train/validation/test statements: 22,890 / 3,235 /
  6,042;
- maximum qualifier pairs on one statement: 65;
- release build: 366.152 ms;
- full identity-checking mmap restart open: 20.976 ms.

The full-validation throughput gate ranked 2,255,235,030 candidates in
5,689.016 ms, or 396.419 million candidate ranks/second. A cold-process rerun
took 5,692.929 ms and reproduced both exact identities:

- score digest: `b3-5e6ebaca1a701d270be4e2499397e5f713047e73b4d9b1ae2e2f88bb7711be04`;
- certificate: `b3-9a5513130d91f07e02696db91c3f5dab2e2f64ace37d6770a094eec77c5b019f`.

The throughput scorer is a deterministic calibration fixture, not a research
baseline.

## Verification

- Deterministic build identity over the same source.
- Exact source-fact and qualifier-range rebinding.
- Exact pinned-StarE ordered qualifier-context filtering.
- No qualifier arena in the task binary.
- Full and role policy certificates remain distinct over the same score stream.
- Batch-size-independent score and certificate identities.
- Hits@5 and all required metric slices.
- Claim-before-test and burn-on-scorer-failure behavior.
- Binary corruption and source drift fail before query access.
- Focused tests: 3 passed.
- Real release build, cold reopen, and two complete validation throughput runs
  passed.

## Implementation map

- `hyper_relational_model.rs`: task, metric, certificate, lock, and error contracts.
- `hyper_relational_binary.rs`: fixed-width little-endian mmap records.
- `hyper_relational_build.rs`: WD50K authority checks, role inventory, truth
  grouping, qualifier-order hashes, and leakage audit.
- `hyper_relational_artifact.rs`: compact immutable binary and validated mmap open.
- `hyper_relational_eval.rs`: exact filtered ranking, slices, score identity, and
  one-shot test lock.
- `hyper_relational_tests.rs`: determinism, zero-copy, evaluator, lock, corruption,
  and drift proofs.
- `build_hyper_relational_task.rs`: real frozen-task build/restart harness.
- `benchmark_hyper_relational_validation.rs`: complete validation throughput and
  reproducibility gate.

## Next boundary

The task is ready for a qualifier-aware model without another data reshape. The
next model should consume the primary fact mmap plus borrowed qualifier ranges
directly, train on train statements only, and prove qualifier permutation
invariance. A StarE-style encoder is the clean first rung; CompGCN remains its
triple-only control under this same evaluator.
