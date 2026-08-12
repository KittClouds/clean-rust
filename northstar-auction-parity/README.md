# Northstar Auction Parity

An isolated, read-only bridge from the sealed MT5 research corpus to Northstar.

This workspace deliberately has no dependency edge into `index-fund-prototype`.
MT5 remains the behavioral oracle; this workspace verifies and reconstructs its
sealed ledgers before any later Northstar wiring.

## Proven scope

- Stable Rust representations for RG2 / dataset schema 7 semantics.
- Exact decimal and MT5-server-time preservation.
- Memory-mapped, zero-copy TSV traversal.
- SHA-256 verification of every sealed run payload.
- Canonical corpus hash reproduction.
- Relational validation of the seven auction datasets.
- Independent reconstruction of all Phase 10.5 view and target cardinalities.
- Independent auction grammar for all 16 golden scenarios in both directions.
- Exact reproduction of all 32 frozen MQL5 event-ID hashes.
- Threshold, idempotence, mirror, and episode-gap boundary proofs.

No UI, TradeLocker, order, macro, ledger, or live-stream integration exists here.

## Build

Cargo output is written to `D:\northstar-auction-parity-target`.

```powershell
cargo test --workspace
cargo run -p northstar-parity-cli -- verify `
  --corpus "C:\Users\shuga\OneDrive\Documents\ChatGPT\eas\furnace\corpus" `
  --seal "C:\Users\shuga\OneDrive\Documents\ChatGPT\eas\phase10\seal\corpus_seal.json"

cargo run -p northstar-parity-cli -- verify-interface `
  --workspace "C:\Users\shuga\OneDrive\Documents\ChatGPT\eas"

cargo run -p northstar-parity-cli -- verify-golden
```

## Deliberate stop line

The workspace is not wired into Northstar. Full MQL5 ledger serialization and
terminal-accumulator hashes remain to be reproduced before the verified data is
packed into a stable mmap artifact. Only that artifact will become a candidate
dependency for a later Northstar adapter crate.
