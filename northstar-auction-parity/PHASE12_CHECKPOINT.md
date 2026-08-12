# Phase 12 checkpoint

Status: `PARITY FOUNDATION PASS / NORTHSTAR INTEGRATION DEFERRED`

## Isolation

- Standalone sibling workspace: `northstar-auction-parity`.
- No dependency on `index-fund-prototype`.
- No UI, TradeLocker, order, ledger, macro, or live-stream code changed.
- Cargo artifacts reside on `D:\northstar-auction-parity-target` through the
  workspace-local `target` junction.

## Passing evidence

- RG2 corpus: 20 runs, 320 sealed files, 3,915,010,108 bytes.
- Canonical corpus SHA-256 reproduced exactly:
  `9cbad8545db23cba7ccea2bd062aeba700597deb4be19cecbb74647f65ef8413`.
- Relational reconstruction: 38,957 events; 7,764 attempts; 1,462 episodes;
  49,281 contributor rows; 7,764 feature rows; 628 transits.
- Phase 10.5 parity: all five canonical view cardinalities and all five target
  eligible/observed/censored counts match the sealed Python registry.
- Golden grammar: 16 scenarios, two directions, 32 directional ledgers,
  128 semantic/identity assertions, and 56 boundary assertions.
- Exact event identity: all 32 MQL5 event-ID hashes match.
- Unit suite, doc tests, formatting, and strict Clippy all pass.
- Same-length sealed-file mutation is rejected.

Machine-readable receipts live in `proof/`.

## Remaining before any Northstar wiring

1. Reproduce the full MQL5 golden ledger serialization hashes.
2. Reproduce the MQL5 terminal accumulator hashes.
3. Pack verified rows into a versioned, checksummed, zero-copy mmap artifact.
4. Reopen the artifact and prove row/key/view parity from the packed bytes.
5. Expose a tiny read-only adapter crate; keep Northstar integration a separate,
   explicitly approved cut.
