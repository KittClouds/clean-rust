# Graph Run Freight Removal Execution Plan

Status: active implementation contract

Last verified checkpoint: 2026-07-12

## Mission

Remove representation, crossing, and persistence overhead around the deterministic graph arm without changing graph semantics.

The target is one decode, borrowed native processing, and one compact UI projection. Full certificates remain in an immutable native run arena and move across the WebView boundary only as explicitly requested pages.

This is not permission to rewrite graph algorithms. Every cut must preserve exact graph identity, authority, counts, stable IDs, promotion behavior, and candidate-only topology rules.

## Verified Starting Point

The current implementation already has:

- A typed native snapshot-analysis command.
- An immutable native `GraphRunCoordinator` arena.
- A run handle plus compact first-page projection.
- Native read-page and close-run RPCs.
- Full certificate and proof rows retained in the native arena.
- Generation-checked note-body residency.
- Native document text retained by content hash after discovery.
- Batched mention scanning with interned dictionaries and numeric mention tuples.

Release-style two-document evidence is stored in:

- `target/graph-build-baselines/two-shortrun-resident-tuple-mentions.json`

Current verified results:

| Gate | Result |
|---|---:|
| Warm response p50 | 456,051 bytes |
| Delta response p50 | 456,050 bytes |
| Warm crossings p50 | 10 |
| Warm written blobs | 0 |
| Delta written blobs | 0 |
| Warm reused blobs | 100 across 10 runs |
| Delta reused blobs | 100 across 10 runs |
| Exact identity parity | pass |
| Exact authority parity | pass |
| Exact count parity | pass |
| Candidate-only topology writes | zero |
| Graph suite | 214 passed, 1 skipped |

The response-freight target is met. The latency target is not. Before Cut 1, debug measurements were also contaminated by production `JSON.stringify` calls used only to estimate typed RPC byte counts.

## Execution Ledger

| Cut | Status | Evidence |
|---|---|---|
| 1. Remove measurement stringification | complete | `target/graph-build-baselines/two-shortrun-no-audit-stringify.json` |
| 2. Collapse to three data crossings | complete | `target/graph-build-baselines/two-shortrun-three-crossing-native-mentions-final.json` |
| 3. Native durable section persistence | complete | `target/graph-build-baselines/two-shortrun-native-durable-sections-final.json` |
| 4. Content-addressed arena handles and reuse | complete | `target/graph-build-baselines/two-shortrun-content-addressed-arena-final.json` |
| 5. Atlas proof paging in the UI | complete | `target/graph-build-baselines/two-shortrun-atlas-proof-paging-final.json` |
| 6. Shared semantic derivation context | complete | `target/graph-build-baselines/two-shortrun-shared-semantic-context-final.json` |
| 6A. Whole-run unchanged identity termination | complete | `target/graph-build-baselines/two-shortrun-one-second-identity-reuse-final.json` |
| 7-8 | pending | not started |

Cut 1 established that TauRPC's JavaScript proxy does not expose the serialized Tauri frame. Typed request bytes, response bytes, encode time, and decode time are therefore recorded as unavailable unless a real codec owner supplies them. The audit does not estimate them with a second payload traversal. JSON commands still report exact string bytes because they already own their encoded strings.

Cut 2 established `open_graph_run` as the native discovery boundary. Raw mention spans, interned kinds, entity references, and resident text remain in the arena; TypeScript receives grouped discovery candidates only. Warm graph execution uses `open_graph_run` and `analyze_graph_snapshot`, with the asynchronous durable receipt as the third complete-run crossing. Siegel projection is folded into analysis and cannot fall back to a standalone native crossing.

Cut 3 established immutable BLAKE3-addressed certificate sections with zstd content blobs, mmap-backed restart reads, section-specific dependency identities, and blob -> immutable manifest -> current manifest -> durable receipt publication ordering. The final 21-run gate recorded warm persistence at 27 ms p50 / 32 ms p95 and delta persistence at 27 ms p50 / 31 ms p95. Both lanes reused 70/70 sections with zero section encoding or compression. The arena-eviction smoke reopened the durable handle as a native v1 page with `noTopologyWrites: true`.

Cut 4 separated generation-checked UI leases from BLAKE3-addressed immutable analysis content. Identical requests now share one native allocation and one concurrent build slot while retaining lease-local snapshot and scope identities for durable receipts. Inactive content is bounded by an eight-entry LRU and a 256 MiB resident-byte budget; active leases and in-flight `Arc` references cannot be evicted. Promotion preview receipts were made semantic-content-addressed after the audit found that `builtAt` manufactured a different promotion section every run, and retrieval candidates plus promotion receipts were added to their previously incomplete section dependencies. The final 21-run gate reused the arena on 10/10 warm and 10/10 delta runs, reduced warm wall p50 from 11.88 seconds to 9.98 seconds and delta wall p50 from 11.92 seconds to 9.84 seconds, and recorded zero native analysis recomputation on every reuse. Both lanes reused 70/70 durable sections with zero encoding, compression, content writes, or topology writes. Durable paging after lease close still returned proof rows with `noTopologyWrites: true`.

Cut 5 replaced per-certificate truncation with one deterministic global cursor across every detailed proof family. The compact analysis response now carries eight total proof rows out of 1,573 plus exact per-family aggregate counts; Atlas requests later pages only when a room is expanded or the operator explicitly asks for more. Page ownership is run-handle scoped, late pages from superseded runs are discarded, loaded rows are incrementally deduplicated, and view teardown releases each lease exactly once. The audit also removed a fourth warm scoped-snapshot lookup by retaining compact content manifests in a bounded 64-scope index. The final 21-run gate recorded 164 us warm / 159 us delta page projection p50, three crossings p50, 10/10 arena reuse in each lane, 70/70 section reuse in each lane, and zero encoding, compression, content writes, or topology writes. A 25-page live traversal returned all 1,573 rows exactly once, and paging after arena eviction reopened the durable mmap-backed page with `noTopologyWrites: true`.

Cut 6 profiled semantic tasks, candidates, manifold specialization, reranking, adjudication, and eval-ledger construction separately. The trace found adjudication rebuilding the complete anchor/entity/note indexes for individual candidates and mutations, while tasks, candidates, manifolds, reranking, and eval rebuilt the same target, event-chunk, contribution, and judgment indexes. `GraphSemanticDerivationContext` now builds seven narrow indexes once and lends them to the named consumers without changing semantic ordering or candidate-only boundaries. The final gate certifies 4,354 indexed entries, 378 avoided index builds, and 375,850 avoided entry insertions per run. Warm semantic-ledger p50 fell from the 60.65 ms pre-cut profile to 24.23 ms, with adjudication falling from 39.88 ms to 9.57 ms; delta finished at 23.81 ms total / 9.42 ms adjudication. All 20 unchanged runs retained three crossings, 70/70 section reuse per lane, zero encoding/compression/content writes, exact identity/authority/count parity, and zero topology writes. The benchmark harness now holds the store checkpoint pause across the complete gate so a delayed full-store `export_snapshot` cannot enter an interactive graph measurement.

Cut 6A moved unchanged-run termination ahead of NER, snapshot construction, semantic derivation, and native analysis. A canonical SHA-256 identity covers document bodies and metadata, scope, registry entities, model selection, embedding policy, calendar registry, and post-process mode. Reuse is allowed only while the exact snapshot authority and resident native lease still match; any mismatch fails closed to the complete build. A reused run still performs a fresh authority assertion, native durable persist, scoped receipt write, UI receipt, and layer projections. The final 21-run gate passed the explicit 1,000 ms p50 target and 3,000 ms p95 ceiling: warm measured 129.17 ms p50 / 156.63 ms p95 and delta measured 126.75 ms p50 / 158.10 ms p95. All 20 unchanged runs used one native crossing, reused 140/140 durable sections, performed zero snapshot/semantic/serialization/compression/blob work, and preserved exact identity, authority, counts, and zero topology writes. A complete proof traversal returned 1,573 unique rows, and durable paging remained native with `noTopologyWrites: true`.

## Non-Negotiable Invariants

Every phase must prove all of these before the next phase starts:

1. Exact node, edge, target, candidate, certificate, authority, and stable-ID parity.
2. Candidate-only semantic layers perform zero committed topology writes.
3. An unchanged warm run performs zero content encoding, compression, and blob writes.
4. Missing native state fails closed. It must not silently fall back to broad JSON graph transport.
5. A receipt exists for every successful run, including unchanged runs.
6. Closing or evicting an arena entry cannot invalidate a live UI page or persistence operation.
7. Paging changes presentation only. Aggregate counters always describe the complete native result.
8. Transport work and semantic algorithm changes never share the same implementation cut.
9. No gzip/base64 graph IPC revival.
10. No new optimization crate or unsafe path enters the hot lane without a benchmark showing its value and a parity test covering it.

## Operating Rules

Each implementation cut must be narrow enough to answer four questions in one review:

1. Which allocation, traversal, crossing, or write was removed?
2. Which code path now owns the displaced responsibility?
3. Which certificate field proves the improvement?
4. Which test proves semantic identity was preserved?

For every cut:

1. Record the pre-cut certificate.
2. Add or update the smallest failing contract test.
3. Implement only the named boundary change.
4. Run focused tests.
5. Run the full graph suite and production Angular build.
6. Run the desktop cold + 10 warm + 10 delta gate.
7. Compare parity, writes, crossings, bytes, latency, and resource fields.
8. Stop and revert the cut if parity fails or an unchanged run writes content.

Build Rust artifacts under `D:\clean-rust-tauri-graph-run-arena`. Do not use the workspace or C: drive as the primary Cargo target.

## Execution Order

### Cut 1: Remove Measurement Stringification

Goal: make measured transport time represent transport and codec work, not audit-side serialization.

Current boundary:

- `src/app/services/phoenix-transport-audit.ts`
- `src/app/services/phoenix-taurpc-bridge.ts`
- generated TauRPC transport glue

Actions:

1. Add a transport-metrics envelope that accepts byte counts and codec duration from the actual codec boundary.
2. Stop calling `byteLengthOfJson` for typed graph requests and responses in production.
3. Keep explicit JSON command measurement only where the command already owns a JSON string.
4. Make unknown byte counts explicit rather than estimating them with a second serialization.
5. Add separate fields for request bytes, response bytes, encode time, decode time, and audit overhead.
6. Ensure the benchmark harness reads counters but does not create them by serializing graph values.

Proof:

- A test whose typed response contains a throwing `toJSON` must still complete measurement.
- No `JSON.stringify` or `byteLengthOfJson` executes on the typed graph-analysis path.
- Warm response byte accounting remains within 5% of an independently captured codec-boundary sample.
- Rerun the 21-run gate and establish a new latency baseline before making further performance claims.

Stop condition:

- Do not proceed if byte counts cannot be captured without a second full traversal. Mark them unavailable and continue timing the real boundary.

### Cut 2: Collapse the Warm Run to Three Data Crossings

Goal: one run-open/upload crossing, one analyze/project crossing, and one persist/receipt crossing. Page reads after user interaction are excluded.

Target flow:

1. `open_graph_run`: identify documents and upload only changed text.
2. `analyze_graph_run`: scan mentions, derive graph certificates, and return the compact first page.
3. `persist_graph_run`: compare section identities and return the durable receipt.

Actions:

1. Make `open_graph_run` accept document ID, content hash, optional changed text, resolver seed identity, and options.
2. Move mention scanning behind the run coordinator so mention rows do not cross into TypeScript and then return to Rust.
3. Retain mention spans and intern tables inside the arena.
4. Give TypeScript only the mention projection required by visible UI, if any.
5. Fold analysis inputs currently sent through separate RPCs into immutable run metadata or stable native references.
6. Remove superseded broad crossings only after the typed path has exact parity coverage.

Proof:

- Warm and delta runs use at most three data-bearing native crossings.
- Unchanged documents send hashes, not text.
- Discovery mention data does not make a Rust to TypeScript to Rust round trip.
- Complete warm response remains below 512 KB excluding requested pages.
- Exact parity and zero-write gates pass.

Stop condition:

- Do not hide extra graph crossings by renaming them control messages. A message carrying graph rows, document text, proof rows, or derived indexes is data-bearing.

### Cut 3: Native Durable Section Persistence

Goal: persist immutable native certificate sections without reconstructing or encoding unchanged TypeScript documents.

Actions:

1. Define a tagged, length-delimited section identity format with an explicit schema version and domain separator.
2. Compute section identities while native sections are built.
3. Store section identity, row count, raw byte estimate, and dependency identities in the arena.
4. Make `persist_graph_run` load the prior manifest and compare identities before encoding.
5. Encode and compress changed sections only.
6. Write a durable receipt for unchanged runs without rewriting content blobs.
7. Persist enough manifest state to reopen certificates after process restart.
8. Add crash tests around blob write, manifest commit, and receipt publication ordering.

Proof:

- Unchanged warm persistence performs zero section serialization and compression.
- Unchanged warm persistence is below 30 ms p50.
- Restart can load the last durable receipt and page its certificate rows.
- A simulated interrupted write exposes either the prior complete run or the new complete run, never a mixed manifest.
- Changed-section tests show that only dependent sections are replaced.

Stop condition:

- Never publish a receipt that references an uncommitted manifest or missing section blob.

### Cut 4: Content-Addressed Arena Handles and Reuse

Goal: identical immutable analyses safely reuse one arena entry.

Actions:

1. Derive an analysis identity from schema version, document identities, resolver seed identity, model/options identity, and stable section identities.
2. Separate the content identity from a lease token. UI callers receive leases; the coordinator owns shared content.
3. Add reference counting for UI pages, persistence work, and active analysis.
4. Deduplicate concurrent opens for the same analysis identity.
5. Define bounded eviction by resident bytes and least-recently-used inactive content.
6. Make stale, closed, or schema-mismatched leases fail explicitly.

Proof:

- Identical inputs share one immutable analysis allocation.
- Different resolver seeds, model versions, or options cannot collide.
- Closing one lease cannot invalidate another lease for the same content.
- Eviction never removes active content.
- Hash collision and schema migration tests fail closed.

Stop condition:

- A raw digest is not a lifetime-safe handle. Do not remove lease generation checks.

### Cut 5: Atlas Proof Paging in the UI

Goal: keep detailed proof rows native until a user asks to inspect them.

Actions:

1. Identify every Atlas panel that reads complete certificate arrays.
2. Give the view model aggregate counters plus the first page only.
3. Request subsequent pages through `read_graph_run_page` on expansion, scrolling, or explicit navigation.
4. Cancel stale page requests when the selected run changes.
5. Close leases when the owning view and any persistence reference are released.
6. Add loading, end-of-results, expired-run, and retry states without manufacturing empty proof.

Proof:

- Opening Atlas does not request all proof rows.
- Page concatenation is stable, ordered, duplicate-free, and complete.
- Counters remain exact before all pages are loaded.
- Switching runs cannot display a late page from the prior run.
- UI teardown closes the lease exactly once.

Stop condition:

- Do not cache full proof arrays in another TypeScript service; that recreates the freight under a different owner.

### Cut 6: Shared Native Semantic Derivation Context

Goal: remove repeated maps, sets, filters, and sorts without moving or changing semantic algorithms.

Entry requirement:

- Cuts 1 through 5 are green and a native internal profile identifies the repeated work by subphase.

Actions:

1. Add internal timings and allocation counters for semantic tasks, candidates, manifolds, reranking, adjudication, and ledgers.
2. Introduce `GraphSemanticDerivationContext` containing only indexes used by at least two measured phases.
3. Use interned IDs and borrowed slices where lifetimes remain clear.
4. Replace repeated sorting with stable precomputed order only when all consumers require the same order.
5. Keep candidate-only relations isolated from committed topology indexes.
6. Move one consumer at a time and run exact parity after each move.

Proof:

- Each shared index has at least two named consumers and a measured avoided cost.
- Semantic-ledger time has per-subphase evidence.
- Exact candidate, adjudication, ledger, and promotion outputs remain unchanged.
- Candidate-only layers still produce zero topology writes.

Stop condition:

- Do not create a universal context bag. If an index has one consumer or no measured cost, keep it local.

### Cut 7: Digest Reuse for Authority and Persistence

Goal: compute canonical section identities once and reuse them for authority sealing, persistence comparison, and receipts.

Actions:

1. Inventory every authority field and its canonical ordering rule.
2. Prove the new incremental digest is domain-separated and length-delimited.
3. Build digests alongside stable native section construction.
4. Store child section identities in the authority root rather than recursively normalizing rows again.
5. Keep a compatibility verifier until old and new authority outputs prove equivalent under the versioned contract.
6. Remove recursive sort/stringify sealing only after equivalence tests cover reordered, empty, Unicode, and delimiter-ambiguous inputs.

Proof:

- Authority sealing is below 15 ms p50.
- Persistence and authority consume the same section identities.
- Equivalent inputs yield stable identities across restart.
- Non-equivalent tagged inputs cannot collide through concatenation ambiguity.

Stop condition:

- If the authority algorithm changes, version it explicitly. Never silently reinterpret an existing authority hash.

### Cut 8: Resource Certificates and Release Gate

Goal: make regressions in copying and residency visible before release.

Required certificate fields:

- Native encode and decode microseconds.
- Codec request and response bytes.
- Native allocation count and allocated bytes for the run where supported.
- Estimated or measured copied bytes at named boundaries.
- Arena resident bytes before and after the run.
- Arena peak resident bytes.
- Process peak resident memory sampled with its platform and precision stated.
- Sections encoded, compressed, reused, and written.
- Data-bearing and control crossing counts reported separately.
- Page rows retained, returned, and requested later.

Actions:

1. Define measurement ownership for every field.
2. Record unavailable metrics as unavailable, never zero.
3. Keep instrumentation allocation-free or bounded on the hot path.
4. Add thresholds to the benchmark report only after two stable local baselines.
5. Make the cold + 10 warm + 10 delta certificate the release gate.

Final release thresholds:

| Metric | Warm target | Delta target |
|---|---:|---:|
| Wall p50 | <=1,000 ms | <=1,000 ms |
| Wall p95 hard ceiling | <=3,000 ms | <=3,000 ms |
| Response traffic | <512 KB | <512 KB |
| Data-bearing crossings | <=3 | <=3 |
| Native boundary overhead | <15% of Rust compute | <15% of Rust compute |
| Authority sealing | <15 ms | <15 ms |
| Unchanged persistence | <30 ms | <30 ms |
| Encoded/compressed/written unchanged sections | 0 | 0 |

## Verification Ladder

Run this ladder for every completed cut:

1. Touched unit and contract tests.
2. `npx tsc --noEmit -p tsconfig.app.json`
3. Relevant native unit tests using `--target-dir D:\clean-rust-tauri-graph-run-arena`.
4. `npx vitest run src/app/graph-rebuild --reporter=dot`
5. `npm run build`
6. `cargo fmt --manifest-path src-tauri/Cargo.toml -- --check`
7. `git diff --check`
8. Build and relaunch the exact D:-target desktop binary.
9. Run one cold + ten warm + ten delta builds over two copies of `docs/shortrun.md`.
10. Save the certificate under `target/graph-build-baselines/` with a cut-specific name.
11. Compare against the immediately previous certificate, not an aspirational historical run.

The desktop gate must report:

- exact identity, authority, and count parity;
- no topology writes;
- zero unchanged content writes;
- section encoding/compression counts;
- request and response bytes;
- crossing counts;
- p50 and p95 wall/codec/native/persistence/authority timings;
- resource certificate fields available at that phase.

## Failure Protocol

Stop at the first failed boundary.

| Failure | Required response |
|---|---|
| Identity or authority mismatch | Stop; find the first divergent section identity. |
| Count mismatch | Stop; compare native aggregate counts before inspecting UI pages. |
| Topology write from candidate layer | Stop; restore the promotion boundary before performance work continues. |
| Warm content write | Stop; trace manifest identity comparison before inspecting compression. |
| Response bytes increase >10% | Explain the new projection field or revert it. |
| Latency regression >10% over two gates | Profile the named phase; do not attribute it to noise without a repeat. |
| Memory increase >10% | Report retained arena sections and lease counts; verify close/eviction behavior. |
| Missing metric | Mark unavailable and identify the correct measurement owner. |
| Desktop-only failure | Preserve the failing certificate and inspect the live native boundary before changing algorithms. |

## Definition of Complete

This plan is complete only when:

- The final release thresholds pass in one cold + ten warm + ten delta desktop gate.
- Restart recovery can serve a durable certificate page without rebuilding unchanged graph content.
- Atlas loads proof incrementally and releases its run lease.
- The complete graph-analysis hot path contains no generic `serde_json::Value` or full `JSON.stringify` traversal.
- All large graph data remains native except explicitly requested compact pages.
- Resource and codec fields are present in durable run receipts.
- The full verification ladder is green.

Until those conditions hold, report each finished cut as a verified checkpoint, not as completion of the overall performance program.
