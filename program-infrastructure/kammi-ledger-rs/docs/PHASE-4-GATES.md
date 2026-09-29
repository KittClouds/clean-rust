# Phase 4 acceptance gates

Phase 4 asks whether Rust can live in production continuously, take authority cleanly and
give it back cleanly.

- **Deliberately asymmetric:** Rust is stressed until we learn where it bends. Python, the
  reference, is exercised only enough for shadow parity and rollback compatibility. There is
  no Python soak, no request storm through Python, and no dual writes.
- **Memory embedder:** bge during the rollback window. It is byte-identical to Python's
  fastembed, so memory rolls back too.
- **Frozen:** 2026-09-28.

## 4A: Rust-only stress (`tools/stress_test.py`)

| Gate | Requirement | Pass bar |
| --- | --- | --- |
| A1 | Concurrent writers | 32 clients of mixed custody writes. Every acknowledged request is in the journal exactly once. Store deep verification passes |
| A2 | Lease churn | Many actors contend on a few resources. Reconstructed from the journal: at most one live lease per resource at any time, fencing tokens strictly increasing, stale renew and release refused |
| A3 | Daemon hard kills under load | Repeated `taskkill /F` while writers run; clients retry with the same request ID. Zero lost acknowledgements, zero duplicates, the store verifies, and the projection converges |
| A4 | Projector kill loop under load | Kill every few seconds while writing and searching. Writes 100 % acknowledged, searches 200 or 503, final projection passes `verify --deep` |
| A5 | Memory traffic | Concurrent record and search: read-your-writes on every search, no 5xx except 503 during a projector outage. Markers are single alphabetic tokens (see findings) |
| A6 | Scale | Large synthetic journal: daemon open/replay time and memory, bulk projection rebuild, deep verification, live catch-up. Measured and recorded |
| A7 | Sustained-operation memory stability (v2, amended 2026-09-28; see below) | 30 min mixed load with periodic projector kills. Afterwards: restart on the exact final head and measure fresh-replay RSS; soak-final RSS ≤ 1.10× fresh-replay RSS; no residual growth (> 5 % of fresh RSS) after conditioning on event count; bytes/event reported separately. Final verification passes |

### 4A results (2026-09-28, release binaries, NVMe)

| Gate | Result | Measured |
| --- | --- | --- |
| A1 | PASS | 32 clients, 51,658 writes in 125 s (413/s), all 200, exactly once; store and projection deep verify |
| A2 | PASS | 2,859 grants, 46,624 denials, 0 lease violations, stale renew always refused |
| A3 | PASS | 10 hard kills, restarts 1.0-2.8 s, 43,338 acknowledged, 0 lost, 0 duplicated |
| A4 | PASS | 6 projector kills, 19,471 custody writes all 200, searches 200/503 only, deep verify passes |
| A5 | PASS | Own write seen in 113/113 checked searches. With a kill every 5 s the projector was down most of the time (2,488 searches answered 503) |
| A6 | PASS | 1,001,723 events: daemon replay 28.4 s, RSS 1.7 GB; projector bulk load 79 s, RSS 1.26 GB; 5,000 live writes in 11.8 s; store and projection deep verification pass |
| A7 (original spec) | **FAIL_BY_SPEC** | 30 min, 237,705 operations, 8 projector kills, final verifications pass. Daemon memory 250 to 442 MB (first to last third), bar 1.2×. **Not a leak:** a fresh daemon replaying the soak store (227,591 events) starts at 493 MB, which equals the soak peak. The growth is derived state at ~1.5 KB/event (see the open `State` finding below) |
| A7 (v2) | PASS_NO_LEAK | 30 min, 243,890 operations, 9 projector kills, final verifications pass. Soak-final RSS 400 MB vs fresh replay at the same head (233,461 events) 541 MB: ratio 0.74 (≤ 1.10). Residual growth after conditioning on event count: 2.6 MB (≤ 5 %). State ~1.0 KB/event. Original ratio on this run: 267 to 402 MB, FAIL_BY_SPEC again (kept in the report) |

On the USB HDD (D:), cold-cache incremental projection on a 1M-row database ran at 45 events/s
(random primary-key page reads, ~20 ms each). With a warm cache, or on NVMe, it runs at about
400 events/s. The live store is on NVMe.

### A7 amendment (2026-09-28)

- **Original criterion:** last third ≤ 1.2× first third of daemon RSS during the soak.
- **First run:** FAIL_BY_SPEC, 250 to 442 MB. The report is kept as
  `evidence/stress-run1-original-a7.json`, and each new run still computes the original
  ratio and reports it as `original_criterion`.
- **Diagnosis:** a fresh daemon replaying the completed soak store reached the soak peak
  (493 MB). The criterion conflated retained derived state, which by design grows with the
  journal, with runtime leakage.
- **Amendment:** decided by the user. A7 now measures the intended failure mode, leakage.
  Retained state size is recorded separately, as the open scalability finding below.
  Unbounded growth with history is not a leak, but it is still debt, and it stays open.

### 4A findings

- **Quadratic projection ingest (fixed).** Relationship `MERGE` and key lookups inside
  `UNWIND` became whole-table joins in Ladybug 0.20.2, so each batch cost more than the one
  before. Incremental ingest now keeps in-memory key sets (16-byte hashes) of entities,
  artifacts and links, creates new rows with `UNWIND … CREATE`, and uses single-row
  primary-key statements for updates and new links. `COPY` into a rel table (or `COPY` mixed
  with statements in one transaction) segfaults in 0.20.2, so `COPY` is used only by the bulk
  load of an empty projection. After a bulk load, all three key sets are reloaded from the
  database.
- **Follower recursion (fixed).** An empty open segment was treated as a rollover and
  recursed until the stack overflowed (projector crash loop). A regression test now covers it.
- **Read-your-writes vs lexical rank (Python-compatible, not a divergence).** Ladybug's FTS
  tokenizer splits letter/digit runs, so markers like `qz1x7q` share subtokens and every
  stress memory matched lexically. A just-recorded memory is served from the recent-writes
  overlay with term-count score 1.0, which can rank below BM25 partial matches of older rows.
  Python has the same design. A5 now uses single alphabetic tokens, so it tests
  read-your-writes rather than tokenizer collisions.
- **Projector buffer pool at scale (fixed).** Python's fixed 256 MiB pool fills during the
  post-commit checkpoint at around 1M events, and the projector crash-looped. The pool is now
  4× the main journal bytes (floor 256 MiB, which matches Python on the live store; ceiling
  16 GiB; `KAMMI_PROJECTOR_BUFFER_MB` overrides). It is claimed lazily, and results do not
  depend on it (the thread count stays 2 for BM25 parity).
- **Crash-loop disk growth (fixed).** Each failed bulk load left its `bulk-<pid>` scratch
  directory, and each quarantine kept a full database copy: 33 GB after an hour. Stale scratch
  is now removed under the projection lock, and only the newest 3 quarantines are kept.
- **Derived state grows with every event (open).** `State.artifacts` keeps every artifact
  payload as a JSON value, and the other indexes hold hex strings (a direct port of Python's
  dicts). This costs ~1.5 KB of daemon memory per event: 1.7 GB at 1M events, and it is why A7
  fails. It is also why the daemon replays from genesis (no derived-state checkpoint yet).
  At live scale (2,940 events) it is negligible.
  - **Validated:** the ~228k-event soak store (~0.5 GB) and the 1M-event scale store (~1.7 GB).
  - **Until fixed:** monitor the journal event count and daemon RSS.
  - **Follow-up after cutover, as its own qualified change:** compact binary `State` (32-byte
    keys, payloads read back from the segments) plus state/replay checkpoints. It changes the
    runtime identity, so it is not folded into the build qualified here.

## 4B: gentle live shadow (`tools/shadow_follow.py`)

Python stays authority. Rust reads the live store only through the read-only v1 follower
(shared handles, positional reads, never mmap). No request goes to the live daemon: search
writes a receipt into Python's memory journal, so search comparisons run on copies only.

| Gate | Requirement | Pass bar |
| --- | --- | --- |
| B1 | Live follow | Every cycle, the shadow v2 head equals the live v1 head and every event is verified. Live files are only read |
| B2 | Derived-state parity | Every cycle, Rust `kammi-state-dump` of the shadow equals the Python oracle over `export-v1` of the shadow |
| B3 | Projection parity | Rust projector on the shadow vs a Python rebuild of the export: row parity |
| B4 | Search spot check | On copies of live history: identical responses for a fixed query set |

### 4B results (2026-09-28, release binaries)

PASS: 6 cycles, 10 minutes apart. B1 and B2 passed in every cycle, B3 in cycles 1 and 6, and
B4 in cycle 6 (30 steps, 0 mismatches). The live store stayed at 2,940 events for the whole
window (no agent wrote to it), so the follower was not exercised on new live events during
this window.

## 4C: cutover rehearsal (`tools/cutover_rehearsal.py`, on a copy)

Sequence: fence writes, settle the journal, full artifact verification
(`KAMMI_OBJECT_VERIFY=full`), record the Python head, import, open Rust, projection deep
verification, issue the Rust acceptance, run acceptance probes, switch the endpoint.

| Gate | Requirement | Pass bar |
| --- | --- | --- |
| C1 | Operational sequence | Every step scripted, timed and verified; the Rust head after import equals the fenced Python head |
| C2 | Full verification | Every object hashed with no checkpoint trust |
| C3 | Rust acceptance | `LibraryAcceptanceV2` issued with registered evidence for all 32 gates; flight gate `OPEN` for the Rust source and runtime identity |
| C4 | Endpoint switch | Rust serves on the same port. The unchanged Python client, MCP and SDK probes work, including an ordinary `/v1/authorize` |

## 4D: rollback rehearsal (continues on the 4C copy)

| Gate | Requirement | Pass bar |
| --- | --- | --- |
| D1 | Real Rust writes | Custody, lease, bge memory, search and vault writes while Rust is authority. Then the projection (bulk-loaded history plus incremental writes) passes `verify --deep` |
| D2 | Fence and export | Rust fenced; `export-v1` of the full history |
| D3 | Python accepts Rust history | Unmodified `independent_verify` and `Ledger` replay accept the export at the same head, memory included |
| D4 | Python re-accepted | A new `LibraryAccepted` for the unchanged Python source and runtime, re-binding its existing qualified evidence through Python's own `accept_library`; Python flight gate `OPEN` |
| D5 | Endpoint switched back | Python serves on the same port and reads the Rust-written custody, memory and vault state; a Python write succeeds |

### 4C/4D results (2026-09-28, `tools/cutover_rehearsal.py`, copy of the live store)

PASS, C1-C4 and D1-D5, in a single run on the same port with acceptance mode off (real flight
gates):

- **Before the switch (Python on the copy):** Python served the copy (2,940 → 2,942 events,
  memory 5 → 6) and was fenced. Its `independent_verify` passed in 14.5 s.
- **Import and verification:**
  - Import took 3.8 s: 934 objects (1.34 GB), 2,359 payloads inlined, heads equal.
  - Deep verify took 1.3 s.
  - The backup (`export-v1`) is byte-identical to the Python store, and the restored state is
    identical.
  - The full-hash replay passed without trusting the checkpoint.
- **Rust acceptance:** `LibraryAcceptanceV2` `sha256:080b2d2d…` was issued with 8 evidence
  files covering all 32 gates. Flight gate `OPEN`.
- **Rust serving:** Rust started on the same port in 0.5 s. The Python CLI, Rust SDK, MCP,
  a trace and search of the memory recorded under Python, and `/v1/authorize` all passed.
- **Rust tenure:** Rust wrote an artifact, a lease grant and release, a bge memory and
  search, and a vault with a source. The projection (bulk-loaded history plus these
  incremental writes) passed `verify --deep` afterwards.
- **Rollback:**
  - Rust was fenced, and `export-v1` reproduced the Rust head.
  - Python's unmodified verifier and `Ledger` replay accepted it (memory 6 records,
    including the Rust one).
  - `py_reaccept.py` re-accepted Python through its own `accept_library` (flight `OPEN`,
    `sha256:b9d59056…`). This works only because the Python source and runtime are unchanged.
  - Python served on the same port, read the Rust memory, trace and vault, wrote, and
    authorized.

The acceptance is bound to the source and binaries at rehearsal time. At 4E, `kammi-ledgerd
accept` must run again with the final committed tree, against the import of the live store.

## 4E: real cutover

This is not started without an explicit go from the user at the time (other agents write to
the live Python daemon). It follows the rehearsed 4C sequence. Python is then kept as the
rollback target, not as a writer, with low-rate compatibility probes over a defined window.
If a rollback predicate fires, Rust is fenced and authority returns through the rehearsed 4D
path.

`PHASE_4_STATUS` covers 4A-4D; 4E is reported separately.
