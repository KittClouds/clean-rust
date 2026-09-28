# Phase 3 acceptance gates

Phase 3 turns the Phase 2 components into the live serving topology. It adds no new semantics.

- **Boundary:** journal and CAS are authority. Ladybug is a disposable projection, owned by a
  supervised child process.
- **Status values:** each gate is `OPEN` until its proof passes, then `PASS` with the evidence
  below.
- **Frozen:** 2026-09-28.

| Gate | Requirement | Proof |
| --- | --- | --- |
| G1 | `kammi-projector` runs as a child supervised by `kammi-ledgerd` | `tools/supervision_test.py` starts the daemon; `/v1/status.projection.process` is `RUNNING` with a pid |
| G2 | Projector death never stops authority | The same test kills the projector. Custody writes keep committing, the supervisor restarts it with backoff, and it resumes from its stored position when its database is intact. A kill that tore Ladybug's WAL (which cannot be repaired safely: dropping it crashes the engine) is quarantined and bulk-rebuilt in seconds. Lag returns to 0 and search answers again |
| G3 | Projection position, lag and health visible | `/v1/status.projection`: process state, pid, restarts, `projection_seq/head`, `memory_seq/head`, `journal_head`, `lag`, `last_verify`, `last_quarantine` |
| G4 | A corrupt projection is quarantined, rebuilt and resumed without authority interruption | `tools/supervision_test.py` corrupts the live DB and restarts the daemon. The corruption can surface as an open error, a deep-verify mismatch, or an engine crash (observed: 0xc0000005 on open). The last is caught by two crash-loop breakers: the supervisor after 3 fast crashes (`--reset`), and the projector after 3 starts that never became healthy. `last_quarantine` is set, the projection is rebuilt and deep-verified, and writes are never refused |
| G5 | Memory graph rows match Python | `tools/projection_parity.py` over the memory tables (Memory, CustodyRef, Cites, About, Supersedes) after the differential workflow. Memory tags live in `MemoryTag` instead of Python's shared custody `Entity` table; that mapping is the one declared difference |
| G6 | Lexical search parity | `tools/memory_differential.py`: `fts` mode, identical ids, order, `fused` and `fts` scores, across the Python FTS rebuild-on-doubling state machine and a daemon restart |
| G7 | Vector search parity | Same harness, `vector` mode. The embedder is bge (byte-identical to Python's fastembed), so ids and order are identical and scores agree to ≤ 1e-6 |
| G8 | Hybrid search parity | Same harness, `hybrid` mode, including `grounded_only`, `exclude_kinds`, `include_superseded` and `limit` variations |
| G9 | Graph/neighbour parity | Same harness, `graph` mode with seeds, and `GET /v1/memory/{id}/neighbors` |
| G10 | Trace/evidence parity | Same harness, `GET /v1/memory/{id}/trace` and `GET /v1/memory/{id}` for every memory |
| G11 | Supersession parity | Same harness: supersede chains, cycle refusal, and superseded memories excluded or included per flag |
| G12 | Rebuild from an empty projection is exact | `kammi-projector project` into an empty DB, then `verify --deep` and row parity against Python |
| G13 | The live follower catches up across writes | `tools/supervision_test.py`: writes while the projector runs; searches carry the daemon's memory seq and see their own writes |
| G14 | Restart and resume are exact | Kill at `projection.mid_transaction`, restart, then parity (custody and memory tables) |
| G15 | Bulk rebuild preserves row parity | `kammi-projector project --bulk` into an empty DB, then row parity with the statement path and with Python, plus `verify --deep` |
| G16 | Artifact-verification acceleration preserves the authority result | A replay with the checkpoint equals a replay without it (27 views, 0 differences). Tampering with the object, its size or its file ID invalidates the entry and forces a rehash; a deliberately corrupted object is still refused |
| G17 | The full HTTP differential still passes | `tools/http_differential.py` with the projector supervised: PASS |
| G18 | Python export and replay still accept Rust history | Part of G17: `independent_verify` and a Python `Ledger` replay of `export-v1`. With bge, the memory journal is included |

`PHASE_3_STATUS = COMPLETE` only when every gate is `PASS`. After that comes Phase 4 (stress,
shadow-follow, cutover).
