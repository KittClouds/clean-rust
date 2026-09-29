# kammi-ledger-rs

Rust port of the Kammi Library (`../kammi-ledger`, Python). The Python tree is never modified,
and this workspace must stay outside it: `kammi-ledger/ledgerd/release.py` hashes every
`.py/.rs/.toml/.lock/.md/.json/.txt` file under `kammi-ledger/`, so Rust code there would close
the live daemon's flight gate. Build output goes to `$CARGO_TARGET_DIR` (this machine:
`D:/codex-runs/jev-v08q-r3-rust-target/kammi-ledger-rs-target`); the harnesses read the same variable.

## Status: live since 2026-09-29; Vault Phase 0 delivered; Vault Phase 1 built (v4 off)

Vault Phase 1 is built and proven on sandboxes:

- workspaces, the journaled v4 activation, six-clock memory, the receipt stream;
- the `kammi` verbs and MCP tools, the Frozen Fabrique seed;
- the independent verifier `kammi-verify`;
- a resume gate that fresh Claude agents pass 3/3.

It ships with v4 off. Activation is a journaled step, not before 2026-10-06
([docs/VAULT-PHASE-1.md](docs/VAULT-PHASE-1.md)).

## Earlier status: Vault Phase 0 (contracts)

The Rust Library has served the live store since the Phase 4E cutover (2026-09-29). Releases go
through `tools/release.py` ([docs/RELEASE.md](docs/RELEASE.md)); the daemon is bound to a
per-release source snapshot, not to this tree. Vault Phase 0 froze the next contract, without
activating it ([docs/VAULT-PHASE-0.md](docs/VAULT-PHASE-0.md),
[amendment v4](ARCHITECTURE-AMENDMENT-v4-VAULT-WORKSPACE.md)):

- the six-clock memory record;
- the workspace events;
- the `kammi` verb list;
- the receipt stream;
- the conditions for closing the rollback window;
- the Rust shell (`kammi`, `kammi-mcp`).

## Phase 4 (4A-4D, then the 4E cutover)

Phase 4 asked whether Rust can live in production, take authority cleanly and give it back.
See [docs/PHASE-4-GATES.md](docs/PHASE-4-GATES.md) for each gate, the evidence and the
findings.

| Part | Result |
| --- | --- |
| 4A stress (Rust only) | A1-A7 PASS: 32 writers exactly once; 0 lease violations; 10 hard kills with 0 lost or duplicated writes; projector kill loop; read-your-writes; 1M-event scale; 30-minute soak. A7 was amended from an RSS ratio to a leak test, and the original run is kept as FAIL_BY_SPEC |
| 4B live shadow | 6 cycles: head, derived-state, projection and search parity with Python, live store read only |
| 4C cutover rehearsal | On a copy: fence, full verification, import, Rust `LibraryAcceptanceV2` over 32 gates with registered evidence, same-port switch; CLI, SDK, MCP and `/v1/authorize` work |
| 4D rollback rehearsal | Rust writes custody, lease, bge memory and vault, then is fenced. `export-v1` is accepted by Python's unmodified verifier and replay. Python is re-accepted by its own `accept_library`, serves on the same port, reads the Rust-written state and writes |

Open finding: daemon memory is O(events), about 1-1.7 KB per event (1.7 GB at 1M events)
because derived state keeps full payloads. It is negligible at live scale (2,940 events). It
will be fixed after cutover as its own qualified change (compact state plus checkpoints).

## Phase 3 (integrated serving system)

Phase 3 turned the Phase 2 components into the live topology without new semantics. The
daemon owns authority (journal and CAS) and supervises a disposable `kammi-projector` child.
That child serves memory retrieval from Ladybug and never blocks a custody write. All 18
gates are `PASS`; see [docs/PHASE-3-GATES.md](docs/PHASE-3-GATES.md) for the proof of each.

| Area | Result |
| --- | --- |
| Supervision (G1-G4, G13, G14) | Restart with backoff; `/v1/status.projection` shows the process, position, lag and health; read-your-writes. A projector kill or corrupt projection never refuses a write: it is quarantined and rebuilt. Two crash-loop breakers, one in the supervisor (`--reset`) and one in the projector, handle engine crashes |
| Memory parity (G5-G11) | `tools/memory_differential.py`: 656 steps byte-identical to Python (fts, vector, hybrid, graph, get, trace, neighbours, supersession, restart) and memory table row parity. Both daemons use a fixed clock, so even the memory journal's event IDs match |
| bge embedder | Dedicated runner reproducing fastembed exactly (numpy pairwise float32 norm): 191/191 vectors byte-identical to Python's embedder, and Python's identity formula. Memory recorded by Rust rolls back into Python |
| Bulk rebuild (G12, G15) | Pure-Rust row model plus `COPY FROM`: 1,785 events in 1.7 s (vs 17 s by statements); deep verify 0.8 s (was 18 s); rows identical to Python and to the statement path |
| Verification checkpoint (G16) | Live-store replay with the 1.2 GB custody reference: 4.6 s full, 0.47 s checkpointed, derived state identical. The metadata-trust boundary is declared and demonstrated |
| End to end (G17, G18) | HTTP differential 116/116. Python's verifier and replay accept Rust history, including the memory journal |

Things found and fixed on the way:
- empty CAS objects were misread as torn pack tails;
- two projectors could race on one database;
- `serde_json`'s default float parser lost the last bit of search scores on the RPC pipe;
- a Ladybug WAL torn by a kill cannot be dropped safely (the engine crashes), so the whole
  projection is rebuilt;
- corruption can crash the engine on open, hence the breakers;
- strict identity JSON rejected FILETIME-sized integers, which silently disabled the
  verification checkpoint.

ONNX Runtime is fetched by manifest, never committed: `vendor/onnxruntime-1.30.0/fetch.ps1`
or `fetch.sh`.

## Phase 2 (core, `/v1`, embedders, Ladybug projector)

| Crate | Role | Proof |
| --- | --- | --- |
| `kammi-jcs` | Canonical JSON and identities | Both real stores re-canonicalize byte-identical, and their seal, fact and memory IDs recompute. Over 1M random and adversarial inputs agree with the unmodified Python `ledgerd.identity` |
| `kammi-v1` | Read-only reader and follower of Python stores | Both real stores read and fully verify. Torn tails stay pending. Tamper, chain, vocabulary, duplicate-request and rewrite cases are refused |
| `kammi-store` | v2 authority store ([format](docs/STORE-V2.md)), plus a lock-free read-only `JournalFollower` | Exhaustive torn-tail sweeps, tamper and index-rebuild tests, a property model, a crash matrix over all 14 fault points, randomized multi-crash runs. The follower is tested against a live writer across rollovers, torn tails and committed corruption |
| `kammi-migrate` | v1 → v2 import (resumable), v2 → v1 export | Both real stores import to the exact v1 heads. The export is byte-identical and is accepted by the unmodified Python `EventJournal` and `ContentStore` |
| `kammi-core` | State machines replayed from the v2 journal and every command | Replay of the live store gives 0 differences across 27 derived views compared with the Python oracle (E4: equal except memory, which Python does not hold there) |
| `kammi-ledgerd` | The `/v1` daemon (axum), with the same `KAMMI_*` environment | Differential cleanroom against the Python daemon (below): 116 steps, every response equal |
| `kammi-embed` | Memory embedders over the Phoenix ONNX runners (EmbeddingGemma 300M, Jina v5, MDBR) behind a narrow `Embedder` trait | Four-layer qualification against an independent reference (below): both families pass every bar |
| `kammi-projector` | Disposable Ladybug projection (custody, entities, vault), separate process | Row-level parity with Python's own projection over all 20 tables. Crash mid-transaction resumes exactly. Corruption is quarantined and rebuilt |

### `/v1` differential cleanroom (`tools/http_differential.py`)

This is a port of `scripts/http_cleanroom.py`. The same workflow runs against the Python daemon
(on a v1 copy of E4) and the Rust daemon (on its v2 import):

- custody, grants, specs, a fenced lease, guarded exposure and the adapter;
- the remote bundle, including a real worker execution, return and receipt;
- memory with all four search modes, trace, neighbours and supersession;
- the vault plane: sources, streams, assets, a 2 MiB loose asset, reader, package export and import;
- 44 negative cases.

The comparison works as follows:

- Status codes and error details must be equal.
- JSON shapes must be equal.
- IDs are compared through a one-to-one mapping, because event IDs embed `utc`.
- Base64 JSON payloads and zip packages are compared by content.

Then both daemons crash at `journal.after_fsync`. Both exit 91, restart at the committed head,
and repair the retried request without a duplicate event. Finally the Rust store is exported to
v1 and is accepted by Python's `independent_verify` and by a full Python `Ledger` replay.

Result: **PASS**. There are 3 labelled divergences:

| Step | Python | Rust | Why |
| --- | --- | --- | --- |
| `GET /v1/memory/<unknown>` | 500 | 404 | Deliberate fix of an unhandled `ValueError` |
| Malformed JSON body | 400, `json` module wording | 400, `kammi-jcs` wording | Parser diagnostic text only |
| Invalid zip package | 400, `zipfile` wording | 400, `zip` crate wording | Parser diagnostic text only |

Startup on E4 (1,723 events): Python 41–54 s, Rust 0.5–2.6 s. Workflow: Python about 8 s,
Rust about 0.5 s.

**Rollback boundary.** Python fixes memory vectors at 384 dimensions (bge-small; its verifier
requires 1,536-byte embeddings). A store whose memories come from a 768-d Phoenix runner
therefore rolls back to Python for **custody only**; the harness verifies that path explicitly.
With a 384-d embedder, the memory journal rolls back too.

### Embedder qualification (`kammi-embed-dump` + `tools/embed_qualify.py`)

The reference shares no code with the runner. It uses Python `tokenizers` on the same
`tokenizer.json`, and Python `onnxruntime` on the same graph with one input per run and no
padding. Pooling and normalisation are reimplemented in numpy. The frozen corpus is
`crates/kammi-embed/fixtures/qualification-corpus-v1.json` (130 documents, 41 queries, 10 edge
cases, sha256 `4a819759…`).

| Layer | Bar | Gemma 300M (q4, pad-free) | Jina v5 (q4f16, padded) |
| --- | --- | --- | --- |
| Tokens identical (incl. truncation at 2048 / 1024) | 100 % | 100 % | 100 % |
| Norm error | ≤ 1e-3 | 5.8e-7 | 6.4e-7 |
| Cosine vs reference, min / p50 | ≥ 0.999 / 0.9999 | 0.9999998 / 1.0 | 1.0 / 1.0 |
| Batch vs single cosine, min | ≥ 0.9999 | 0.9999998 | 1.0 |
| Repeat bitwise identical | 100 % | 100 % | 100 % |
| Top-10 identical / mean overlap | ≥ 95 % / 0.98 | 100 % / 1.0 | 100 % / 1.0 |
| Order flips / threshold flips outside ties (1e-3) | 0 / 0 | 0 / 0 | 0 / 0 |

Two findings are now encoded in the families:

- **ONNX Runtime version changes Gemma retrieval.** On ORT 1.20.1, which the Phoenix apps
  resolve from `node_modules`, only 88 % of queries kept the same top-10, with 14 order flips.
  The Library pins ORT 1.30, and the DLL hash is part of every embedder identity. The DLLs
  are fetched, never committed: `vendor/onnxruntime-1.30.0/fetch.ps1` (or `fetch.sh`) downloads
  the pinned PyPI wheel and refuses any wheel or DLL whose SHA-256 or size differs from
  `manifest.json` / `SHA256SUMS`. The embedder also refuses a mismatched DLL.
- **The Gemma q4 export is not padding-invariant** (a padded row drifts to cosine about 0.9997,
  in the reference runtime too). Gemma therefore batches only inputs of identical token length,
  which is also faster (15.3 s vs 21.6 s for the corpus). Jina measured padding-invariant and
  keeps padded batches.

### Ladybug projector

| Check | Result |
| --- | --- |
| Row parity vs the Python projection rebuilt from the same events (Rust store → `export-v1` → Python `Ledger`) | 20/20 tables identical, 1,785 events |
| Kill at `projection.mid_transaction` | Exit 91 after 2 committed batches (512 events). Resume projects the remaining 1,273. Parity holds |
| 40 random corrupted pages | 38 harmless (stale pages), 1 caught at open, **1 silently changed `Link` rows**; Ladybug's own checksums missed it |
| `verify --deep` (in-memory re-derivation and a full row compare) | Detects the silent case. `project --verify` quarantines, rebuilds and re-verifies clean. A projection that only lags is kept |
| Rebuild time for 1,785 events | Rust 17 s, Python 37 s |

### Run it

```powershell
# daemon (v2 store); memory via a Phoenix runner
$env:KAMMI_ROOT = "<v2 store>"; $env:KAMMI_TOKEN_FILE = "<token file>"
$env:KAMMI_EMBEDDER = "gemma300"          # or jina-v5[:<model dir>], mdbr[:<dir>], hashing:384
kammi-ledgerd

# projector (needs kammi-ledger/vendor/runtime-v1/native on PATH)
kammi-projector project --store <v2 store> --db <custody.lbdb> --follow --verify
kammi-projector verify  --store <v2 store> --db <custody.lbdb> --deep

# qualification harnesses (kammi-ledger venv)
python tools/http_differential.py <work dir> --embedder gemma300
kammi-embed-dump gemma300 crates/kammi-embed/fixtures/qualification-corpus-v1.json <dump.json>
python tools/embed_qualify.py <dump.json>
python tools/projection_parity.py <python custody.lbdb> <rust custody.lbdb>
```

## Full acceptance run

```powershell
$L = "C:\code land\clean-rust\program-infrastructure\kammi-ledger"
$env:KAMMI_V1_CORPUS = "$L\.kammi-dev\operational\store-v1-fenced-20260928;$L\.kammi-dev\e4-import"
$env:KAMMI_JCS_PYTHON = "$L\.venv\Scripts\python.exe"
$env:KAMMI_LEDGER_PY = $L
$env:KAMMI_JCS_ORACLE_CASES = "1000000"
$env:KAMMI_CRASH_RANDOM = "300"
$env:KAMMI_WORK_DIR = "G:\kammi-ledger-rs-target\acceptance-work"
cargo test --release --workspace -- --nocapture
```

Real stores are only read, with shared handles, and are never memory-mapped. Python runs with
`PYTHONDONTWRITEBYTECODE=1` and only ever opens disposable exported copies. Without the
variables, the corpus and oracle tests report that they were skipped.

## Manual migration commands

```powershell
kammi-migrate import    --v1 <python store> --v2 <rust store>
kammi-migrate verify    --v2 <rust store>
kammi-migrate export-v1 --v2 <rust store> --out <new dir>
kammi-migrate compare   --v1 <original> --v1 <exported>
```

## Measured on the live operational store (this machine; descriptive, not a benchmark)

- Journal read and full validation: 2,940 events in 65 ms.
- Opening ~2,945 tiny loose payload files took 22 s (about 7.6 ms per file). v2 carries those
  payloads inline in one segment file.
- Import of the whole store (1.34 GB, of which one artifact is 1.2 GB): about 69 s, dominated by
  copying the large artifact. Re-sync with nothing new: 0.24 s.
- SHA-256 in memory runs at 1,584 MiB/s (SHA-NI). Verifying the loose v1 store from disk runs at
  88 MiB/s, so it is I/O-bound.
- Replay of the live store in `kammi-core`: 20 s (Python 145 s), dominated by re-hashing the
  1.2 GB custody reference.

## Next

Phase 4: the stress and soak program, then shadow-follow of the live Python store, cutover and
rehearsed `export-v1` rollback. Items carried into it:
- Memory events are applied one per transaction to match Python's FTS scores bit for bit.
  Large memory journals will want a bulk path for them too, once parity is re-proven on it.
- The deep verification at every projector start is cheap now (0.8 s on E4). Measure it at
  scale and decide on periodic versus per-start.
- The declared checkpoint trust boundary (metadata-identified files) should be revisited if
  the object store ever becomes writable by anything but the daemon.
