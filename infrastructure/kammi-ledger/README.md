# Kammi Ledger

One local authority process serves custody, authorization, exposure, leases,
remote bundles and contextual agent memory through HTTP, Python, Rust and MCP.
Phoenix vaults use the same service. CAS plus the append-only journals are
authoritative; one Ladybug database is the disposable custody, memory, and
Phoenix product projection.

## Qualification and service

Run the complete immutable qualification with the offline cleanroom environment:

```powershell
.\.kammi-dev\cleanroom-env\Scripts\python.exe -m scripts.endstate_run
```

It preserves each attempt under acceptance/endstate, binds the current source and
runtime, independently audits every gate, then emits LibraryAcceptanceV1.
An ordinary test run cannot reopen the operational store.

After acceptance, start the local daemon:

```powershell
.\.kammi-dev\cleanroom-env\Scripts\python.exe -m scripts.service start
.\.kammi-dev\cleanroom-env\Scripts\python.exe -m scripts.service status
```

Credentials and signing keys reside in .kammi-dev/operational, outside CAS.
Provision lab actors and exact scope grants through the administrative service.
Never distribute the administrative credential to lab agents. The daemon listens
on loopback; remote deployments require an authenticated transport boundary.

See [operations](OPERATIONS-v1.md), [lab integration](LAB-INTEGRATION-v1.md),
[security boundary](SECURITY-BOUNDARY-v1.md), [runtime provenance](RUNTIME-PROVENANCE-v1.md)
and [backup/restore](BACKUP-RESTORE-v1.md). The Phoenix product extension is
described in [PHOENIX-VAULT-v1.md](PHOENIX-VAULT-v1.md). Public wire definitions
are in schemas.

## Qualified boundary

Windows, pinned CPython/runtime/native assets, one trusted OS account, guarded
service/executor paths. No hostile local administrator isolation, hardware
attestation or physical power-loss/reboot durability claim. GPU stress uses logical
GPU leases and CPU fixture commands. No scientific model or evaluation flight is
started by infrastructure acceptance. Memory never authorizes scientific actions.

Rebuilding projections replays exact stored vectors; it does not rerun embeddings.
Source or runtime changes close the flight gate and require a new qualification.
