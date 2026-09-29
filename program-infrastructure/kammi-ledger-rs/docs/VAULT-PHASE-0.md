# Vault Phase 0: decide the contracts

The first phase of the KAMMI Vault gold path (the audit's roadmap), revised after the Rust
cutover. Its gate is **schemas locked**: one memory model, the verb list and the workspace
events, all frozen before any of them can be journaled.

| # | Item | Delivered |
| --- | --- | --- |
| 1 | Adopt the six-clock envelope as the one memory record | Amendment v4 §1; `kammi-contract::time`. It uses the same rules as `phoenix-memory-contract`, and a test pins parity with `TemporalPrecisionV1` |
| 2 | Freeze the verbs and the workspace event schema | Amendment v4 §2-3 (v4, because v3 is the Rust store the flight identity already cites; that document is now `ARCHITECTURE-AMENDMENT-v3-RUST-STORE.md`); `kammi-contract::workspace` and `::verbs` |
| 3 | Move `MemoryRetrieved` out of the main memory state | Decided in amendment v4 §4: a `receipts` journal, retry lookup on disk, and `/v1` moves when the rollback window closes. Implementation is part of activation |
| 4 | Set the end of the Python rollback window | Amendment v4 §5: five conditions, not before 2026-10-06, closure recorded as a registered decision |
| 5 | Script the release routine | `tools/release.py`, `docs/RELEASE.md`. The daemon hashes a per-release source snapshot, never the working tree |
| 6 | Start `kammi` and its MCP server as Rust crates | `crates/kammi-shell`: `kammi` (the v1 commands plus the verb list) and `kammi-mcp` (port of `mcp.py`) |
| 7 | Compact state and checkpoints | Scheduled before Phase 3 intake (amendment v4 §7), as its own release |

## Gate evidence

- `cargo test -p kammi-contract` (8 tests):
  - envelope rules fail closed;
  - unknown is never open;
  - v1 records read as v2;
  - workspace payloads are exact;
  - the verb list is unique;
  - Phoenix clock parity;
  - **no v4 type is journalable yet** (the rollback-safety pin).
- `tools/shell_conformance.py` (19 checks) against the frozen Python CLI and MCP on one daemon:
  - CLI reads are byte-identical;
  - writes agree, and idempotent replays are identical;
  - a 14-message MCP session is JSON-equal reply by reply, including every error path;
  - the 1 MiB frame cap holds;
  - an unreachable Library is an `isError` reply (where Python's process dies).
- The Phase 0 tree reaches production through the scripted release itself. That run proves
  the routine end to end and binds the live daemon to a tree that contains the frozen
  contract. Its record is `kammi-ledger-rs-operational/releases/<commit>/release-report.json`.

## Not done in Phase 0 (by design)

- **Nothing is activated.** No workspace or `MemoryRecordedV2` event can be journaled, and the
  daemon binary does not link `kammi-contract`. Activation is a release after the rollback
  window closes.
- **No retrieval changes.** `/v1` memory search stays at Ladybug parity.
