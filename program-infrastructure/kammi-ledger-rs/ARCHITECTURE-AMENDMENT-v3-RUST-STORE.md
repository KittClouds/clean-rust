# Kammi Library architecture amendment v3: Rust store and projector split

Authority: the user's direction for the Rust port (plan approved 2026-09-28) and the Phase 4E
cutover go (2026-09-29). This is the architecture identity that the Rust flight gate binds
(`kammi-ledger-rs/ARCHITECTURE-AMENDMENT-v3-RUST-STORE`). It amends the physical store and the
process layout. It changes no identity, no event vocabulary and no scientific authority.

## What stays exactly as in v1 and v2

- Artifact identity is the SHA-256 of raw bytes. Object, event, seal and fact identities are
  domain-tagged SHA-256 over RFC 8785 JCS. The strict JSON rules are unchanged.
- The event envelope keys, the closed 47-type vocabulary, contiguous `seq`, `prev` chaining,
  the commit order (bytes durable, then the event, then state, then projection) and
  request-ID idempotency are unchanged.
- There is one OS-locked writer per store. Memory has its own journal and trust class. Phoenix
  vault events are in the main journal (amendment v2).
- `/v1` is served exactly: the same routes, fields, status codes and errors as the Python
  service, verified by differential tests.

## What changes

1. **Store v2 layout** (`docs/STORE-V2.md`). Journal segments carry each event's payload inline
   beside the unchanged event bytes, and small objects go into packs with mmap indexes. Large
   objects stay loose under the v1 path rule. Indexes, lookup tables and checkpoints are derived
   and rebuildable. `export-v1` reproduces the v1 layout byte for byte.
2. **Projector process.** Ladybug runs only inside `kammi-projector`, a child process the
   daemon supervises. It follows the journal read-only and serves fixed retrieval queries over
   a pipe. A projector crash, a torn WAL or a corrupt projection is quarantined and rebuilt from
   the journal. It never refuses or delays a custody write. Custody reads such as run history
   are answered from core state, not from the projection.
3. **Flight identity.** It is computed once at daemon start:
   - architecture: this amendment;
   - source root: a manifest of the `kammi-ledger-rs` tree, with the file-type rules of
     `release.py` plus `.wgsl`, excluding `target/`, `vendor/`, `.git/` and `tmp/`;
   - runtime identity: the SHA-256 of `kammi-ledgerd.exe` and the store format.

   The gate is `OPEN` only under a `LibraryAcceptanceV2` for exactly these identities, issued
   by `kammi-ledgerd accept` with registered evidence for all 32 gates (the 28 Python gates plus
   `v1_import_parity`, `shadow_zero_diff`, `projector_isolation`, `export_v1_rollback`). Any
   change to a hashed file, or a rebuilt daemon binary, needs a new acceptance
   (`docs/RELEASE.md`).
4. **Rollback.** While only v1 vocabulary is journaled, `export-v1` plus Python's own
   `accept_library` returns authority to the unchanged Python Library (rehearsed in Phase 4D).

## Qualification

Phases 1-4 (`docs/PHASE-3-GATES.md`, `docs/PHASE-4-GATES.md`): corpus and JCS parity, replay
parity, the crash and tamper matrix, the `/v1` differential, memory parity, supervision, stress
A1-A7, the live shadow, and the cutover and rollback rehearsal. The live cutover record is kept
beside the operational store (`kammi-ledger-rs-operational/CUTOVER-4E.md`).
