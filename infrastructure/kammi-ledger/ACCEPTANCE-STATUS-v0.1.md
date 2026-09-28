# Kammi Ledger acceptance status v0.1

Date: 2026-09-27. Architecture is locked; implementation is a development slice. **New-flight gate: CLOSED.** This document is a status report, not an authorization or a scientific result.

## Built

- Single-process Ladybug custody projection behind a narrow FastAPI service and Python client/CLI. Service runs one Uvicorn worker on loopback; direct database writes are absent from the client API. Its current local HTTP token and filesystem permissions are development controls, not qualified production isolation.
- Streaming SHA-256 CAS, strict RFC 8785 canonicalization, framed hash-chained event journal, recovery of incomplete journal tails, typed graph tables, idempotent request IDs, Merkle seal creation/recursive verification, and replay after journal commit but before graph projection.
- Read-only generic flat-seal verifier plus an E4-specific fixture adapter outside the custody engine. It verified the frozen legacy E4-0 `v16-v09` seal's 447/447 entries and reproduced legacy root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`.
- Disposable E4 import produced base root `sha256:b7444f51049d53d5c5210498ae0c74ccb4f70dbe838ac5cf504ccb7bbc298e47` and successor root `sha256:234e568989f6c0e71fb69fa634b2e0bf085e7fb63336654202d3b221ef33f6fc`. The successor has two direct members and one parent. The 447 legacy entries resolve to 432 unique CAS objects; its successor closure has 433 unique objects after deduplication.
- A fresh Ladybug projection rebuilt from only the imported CAS and event journal reproduced the same event head, graph counts, and 433-object successor closure. Five focused unit/API tests pass.

## Acceptance gate status

| Gate | State | Current evidence / remaining requirement |
|---|---|---|
| 1. One-byte tamper | Prototype pass | Synthetic object alteration makes recursive seal verification fail. Repeat against frozen fixture and independent verifier. |
| 2. DB deletion/rebuild | Prototype pass | Disposable E4 projection rebuilt from CAS and journal with identical heads/counts/closure. Independent replay and backup/restore qualification remain. |
| 3. Crash recovery | Partial | Journal-to-DB replay and incomplete-tail recovery tested. CAS-publication crash, power-loss durability, and Windows filesystem semantics remain. |
| 4. GPU lease | Pending | Fencing tokens, host executor enforcement, and two-agent collision test are unimplemented. |
| 5. Exposure gate | Pending | Program-wide exposure events, guarded panel access, and terminal denial test are unimplemented. |
| 6. Adapter | Pending | Registry, immutable source identity, and gate-linked adapter receipt are unimplemented. |
| 7. Failure history | Pending | Legacy attempts are stored as raw objects, but typed failure/head projections and generic queries are unimplemented. |
| 8. Remote execution | Pending | Signed bundle, disposable worker, and return receipt verification are unimplemented. |
| 9. Memory retrieval | Pending | `memory.lbdb`, trust classes, search, and custody-ref tracing are unimplemented. |
| 10. Legacy Fabrique | Partial | 447/447 bytes and legacy root verified; disposable Merkle successor and rebuild pass. Complete typed history, failed-attempt/contact queries, and independent authoritative-head reconstruction remain. |

The `/v1/authorize` endpoint explicitly denies new flights while these gates remain open. This denial is only effective for clients routed through the service; program coordination has notified Frozen Fabrique, JEV, FAS-R1, and Kinetic Kammi of the hold. Existing authorized work retains its own contracts and lab ownership.

## Evidence and limitations

- [Architecture](ARCHITECTURE-v1.md) SHA-256 `c9e9d5bb54ee863ce99760ee26c0f0e912b952ff3e8a3b502cc23f2d78eb3524`.
- [Architecture lock](ARCHITECTURE-LOCK-v1.json) SHA-256 `94bcba258bd3658ccda3d917aaedf75aaf2a228edf8e9fda23f37159a9ccd364`.
- [Runtime qualification](runtime/QUALIFICATION-v1.json) SHA-256 `9466c05fc7351370173f0d0dcfd7dd9cc400d25c8d4655aa8cd00bf234e0f861`. The Python wheel required a separate native DLL; the current OpenSSL DLLs come from a local Git installation and are not yet a portable production lock.
- [Legacy 447/447 receipt](acceptance/e4-0/legacy-flat-verification-v1.json) SHA-256 `bd45cde3c3079c3d432e2253780b4c1cabf294842439773e7fb4e00f07faec97`.
- [Disposable Merkle import receipt](acceptance/e4-0/merkle-import-v1.json) SHA-256 `4a95cc7ccbd63cbf36e157f150e9a6a42227640679d472562eb5e06290b5c601`.
- [Projection rebuild receipt](acceptance/e4-0/projection-rebuild-v1.json) SHA-256 `c0ba6e3528dfad0e06c9483e7d0831a1a15eab6bfce9003963158533af1d43dd`.
- Source snapshot has 17 files, root `2f28022a8aca9c12fd1f6f00181b2043ae6610f559a319e7eab8b3b733116cb1`. See [source manifest](acceptance/source-manifest-v0.1.json).

Next implementation slice: import complete E4 attempt/supersession/head/contact semantics into generic custody events and queries; then implement policy, enforced leases, panel exposures, schema adapters, remote bundles, and the separate memory plane. Every gate needs an independent acceptance receipt before changing the flight state.
