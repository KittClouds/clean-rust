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

## Results (2026-09-28)

| Gate | Status | Evidence |
| --- | --- | --- |
| G1 | PASS | `/v1/status.projection`: `RUNNING` with a pid |
| G2 | PASS | 40 writes during the outage, all 200; searches 200 or 503; restarted with a new pid, lag 0. The kill tore the WAL, so the projection was quarantined and bulk-rebuilt |
| G3 | PASS | process, pid, restarts, projection and memory seq/head/lag, journal head, `last_verify`, `last_quarantine`; lag reached 0 |
| G4 | PASS | Corruption crashed the engine on open (0xc0000005, three times). The supervisor breaker restarted with `--reset`: quarantined, bulk-rebuilt in 1.15 s. 20 writes during the rebuild, all 200; the healed projection passes `verify --deep` |
| G5 | PASS | Memory, CustodyRef, Cites, About, tags and Supersedes rows identical to Python's |
| G6-G11 | PASS | `tools/memory_differential.py`: 656 steps byte-identical, fixed clock, bge, including every event ID, across a restart of both daemons. By category: fts 67, vector 53, hybrid 132, graph 41, get 73, trace 72, neighbours 72, supersession 6, restart 48, records 82 |
| G12 | PASS | Empty projection rebuilt with bulk (1,785 events, 1.7 s): `verify --deep` passes, and all 20 custody tables match Python's rebuild |
| G13 | PASS | 12 of 12 searches returned their own just-committed record |
| G14 | PASS | Exit 91 at `projection.mid_transaction`; the resume reached the journal head; `verify --deep` passes |
| G15 | PASS | Bulk rows identical to Python and to a statement-built projection (deep verify re-derives through bulk) |
| G16 | PASS | Live-store replay with the 1.2 GB reference: full 4.6 s, first 1.4 s, checkpointed 0.47 s, derived state identical. Touch forces a re-hash, a flipped byte is refused, a corrupt checkpoint is ignored. The declared metadata-trust boundary is demonstrated, and full mode refuses it |
| G17 | PASS | HTTP differential with the supervised projector and bge: 116 steps, 0 mismatches, both crash retries exact |
| G18 | PASS | Python `independent_verify` and `Ledger` replay accept the Rust export at the same head (1,785 events). The memory journal is included (bge) |

Workspace tests: 57 passed, 0 failed.

`PHASE_3_STATUS = COMPLETE`
