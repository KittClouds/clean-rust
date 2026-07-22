# Canonical External Dataset Import v1

## Status

Complete on 2026-07-13.

This slice creates a Rust-owned, content-addressed boundary between externally acquired graph datasets and Phoenix research runtimes. It imports the official `tkgl-smallpedia` v1 archive and the StarE WD50K statement partitions without Python, NumPy, PyTorch, Candle, or Burn in the artifact path.

## Source authority

### `tkgl-smallpedia`

- Dataset: TGB 2.0 temporal knowledge graph benchmark.
- Upstream archive: <https://object-arbutus.cloud.computecanada.ca/tgb/tkgl-smallpedia.zip>
- TGB source audited at commit `23349c34df077665c0309790e681444c19efe65a`.
- Archive version: `tgb-2.2.0/tkgl-smallpedia-v1`.
- Downloaded archive bytes: `10,565,876`.
- Downloaded archive SHA-256: `13df6e59fe9ba305dce8e981ee4afca3712b033070d469be57a2ed3bd5d71248`.
- TGB dataset documentation: <https://tgb.complexdatalab.com/docs/tkg/>.
- TGB software repository: <https://github.com/shenyangHuang/TGB>.

The official loader adds inverse quadruples and then creates a temporal 70/15/15 split using timestamp quantiles. Phoenix computes the same quantiles over a logical doubled timestamp view without allocating inverse rows. The immutable artifact retains the 550,376 source-direction temporal facts. A later task/evaluator view may derive inverse facts without changing source identity.

The static Wikidata rows have no timestamps. They remain `unsplit`, `is_static = true`, and `observed_at = None`; they are not assigned fabricated years.

The official validation and test negative-sample pickle files are included in the source receipt byte-for-byte but remain opaque in v1. No Python pickle decoder or unverified negative regeneration was admitted into this slice.

### WD50K

- Dataset: StarE WD50K hyper-relational statement corpus.
- Source: <https://github.com/migalkin/StarE/tree/master/data/clean/wd50k>.
- Source commit: `b294b9e2cde97ab9e81d2736b7f1f0959c9fd98b`.
- Dataset description: <https://github.com/migalkin/StarE/blob/master/data/clean/README.md>.
- StarE paper: <https://arxiv.org/abs/2009.10847>.

WD50K provides official random train, validation, and test partitions and no temporal evidence. Phoenix preserves those partitions as `OfficialFixed`. Every WD50K fact and qualifier has `observed_at = None`. The temporal evaluator cannot consume this artifact accidentally.

The raw files contain 47,155 entity identifiers and 531 relation identifiers. StarE's loader prepends `__na__`, explaining the published 47,156/532 counts. Phoenix does not create synthetic padding identifiers in the canonical source artifact.

The StarE repository is MIT, while its dataset README does not separately declare dataset licensing. That caveat is retained in the immutable manifest rather than silently promoted to a stronger claim.

## Artifact contract

Schema: `phoenix-external-graph-dataset/v1`.

The binary is a fixed-width, little-endian, mmap-ready file with:

1. a checked header;
2. entity string references;
3. relation string references;
4. fact records;
5. qualifier records;
6. one deduplicated UTF-8 arena.

Fact records encode subject, predicate, object, qualifier range, optional observed time, split, and static/time flags. Absence of time is represented by a flag, not a sentinel with temporal meaning.

The manifest binds:

- dataset name and kind;
- upstream URL and pinned version/commit;
- license notice;
- exact split authority;
- every source filename, role, byte count, and BLAKE3 digest;
- source identity;
- binary filename, byte count, and BLAKE3 digest;
- entity, relation, fact, temporal, static, and qualifier counts.

`dataset_id = BLAKE3(schema, source_identity, binary_blake3)`. Changing source bytes, source metadata, licensing notice, split policy, or canonical binary changes the dataset identity.

Installation order is immutable binary write plus `sync_all`, followed by immutable manifest write plus `sync_all`. Open verifies manifest identity, safe local binary naming, exact layout, exact byte count, and the full binary digest before exposing zero-copy slices.

## Implementation

- [`external_dataset_model.rs`](../rust-native/phoenix/crates/phoenix-graph-research/src/external_dataset_model.rs) defines source, split, fact, qualifier, manifest, and error contracts.
- [`external_dataset_import.rs`](../rust-native/phoenix/crates/phoenix-graph-research/src/external_dataset_import.rs) performs allocation-conscious mmap parsing with `memchr` line scanning and `hashbrown` dictionaries.
- [`external_dataset_artifact.rs`](../rust-native/phoenix/crates/phoenix-graph-research/src/external_dataset_artifact.rs) owns immutable encoding, BLAKE3 identities, crash-safe installation, mmap opening, and zero-copy record access.
- [`import_external_dataset.rs`](../rust-native/phoenix/crates/phoenix-graph-research/examples/import_external_dataset.rs) is the release smoke/performance harness.
- [`inspect_external_dataset.rs`](../rust-native/phoenix/crates/phoenix-graph-research/examples/inspect_external_dataset.rs) proves cold-process restart from only the manifest and mmap binary.

No download client is embedded in the research crate. Acquisition is an explicit operator step; the importer certifies the acquired bytes and cannot silently replace them from the network.

## Real-corpus certificate

Release compilation used `CARGO_TARGET_DIR=D:\phoenix-target-overgraph`. Final artifacts are under `target/graph-research-datasets/canonical-external-v1-final` on `C:`.

| Measure | `tkgl-smallpedia` | WD50K |
| --- | ---: | ---: |
| Import | 415.72 ms | 76.68 ms |
| Cold-process mmap open + full digest verification | 33.98 ms | 6.60 ms |
| Binary bytes | 53,517,393 | 8,675,744 |
| Entities | 309,794 | 47,155 |
| Relations | 762 | 531 |
| Facts | 1,528,398 | 236,507 |
| Temporal facts | 550,376 | 0 |
| Static unsplit facts | 978,022 | 0 |
| Qualifier pairs | 0 | 46,645 |
| Maximum qualifier pairs on one fact | 0 | 65 |

Smallpedia split counts are 387,757 train, 81,033 validation, 81,586 test, and 978,022 static/unsplit. The certified thresholds are year 1997 for train and year 2007 for validation.

WD50K split counts exactly match the upstream README: 166,435 train, 23,913 validation, and 46,159 test.

Final identities:

- Smallpedia dataset: `b3-81d8edf1ee6b88557ae555ed15696561d8bcc2740a73b21be1e6fa4f090d9eba`.
- Smallpedia source: `b3-5a3155c5acf36e0394c51d81242eae1a7e3019ac4d48c1e9d538d97499061c33`.
- WD50K dataset: `b3-763abdf62332cc7bda324be935a4756e759d64b700547c75a9580c67beaa76b2`.
- WD50K source: `b3-c2a766682266495a832cff28a3ad7c2cb3ae410a9627a9ba52ad05833257ee01`.

## Verification gates

- Deterministic same-byte import produces the same dataset identity.
- Mmap round-trip preserves optional time, split, static state, qualifier ranges, and dictionary lookup.
- Odd WD50K qualifier fields fail before artifact installation.
- Binary corruption fails before record access.
- Source receipt/metadata drift fails before mmap access.
- A debug test imports and installs 100,001 facts in 0.59 seconds, below the 5-second guardrail.
- Full `phoenix-graph-research` suite: 32 passed.
- Isolated no-default-feature library Clippy: clean with `-D warnings`.

Workspace-wide strict Clippy remains blocked by pre-existing new-lint failures in `phoenix-types` and `phoenix-hyperbolic`; those files were not changed by this slice.

## Deliberate next boundary

The next slice should be **Canonical Link Prediction Task v1**:

1. decode or independently regenerate TGB time-filtered validation/test negatives in Rust;
2. prove exact parity against the pinned pickle receipts before choosing either path as authority;
3. define query-direction and inverse-relation derivation without duplicating the source artifact;
4. add filtered MRR/Hits metrics and a test-lock boundary;
5. keep WD50K on its separate official-fixed hyper-relational task protocol.

This v1 importer does not weaken the existing Phoenix temporal evaluation protocol or pretend that WD50K has timestamps.
