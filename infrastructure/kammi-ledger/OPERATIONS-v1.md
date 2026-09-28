# Kammi Ledger operations v1

One daemon owns one store. Run `python -m ledgerd.api` from the qualified environment.
Set KAMMI_ROOT, KAMMI_TOKEN, KAMMI_PORT (default 8765), KAMMI_SIGNING_KEY_FILE
(32 raw Ed25519 private bytes), KAMMI_EMBEDDING_CACHE, KAMMI_LBUG_DLL,
KAMMI_OPENSSL_DLL_DIR, and KAMMI_EXTENSION_DIR. Native/model/extension paths
are the hash-qualified copies under vendor/runtime-v1, not mutable global installs.

Bind only 127.0.0.1. Keep credentials and signing keys outside CAS, source manifests,
and backups intended for ordinary lab access. Generate high entropy credentials.
Do not enable KAMMI_ACCEPTANCE_FAULTS in ordinary operation.

GET /v1/status reports journal/projection heads and lag, leases, denials, exposures,
remote bundles, memory health, and flight status. Diagnostic logs do not confer authority.
Only the acceptance artifact registered in the journal can open the infrastructure gate.
Opening infrastructure never replaces a lab's scientific authorization.

For a large local artifact, an administrator may call `POST /v1/artifacts/import-local`
with an absolute file path, expected SHA-256 identity, expected byte count, kind,
actor, and request ID. The daemon streams the file into CAS, checks its identity,
then journals registration. This is custody intake only: protected panel access
still requires a separate stage authorization and `open_panel` exposure event.
The endpoint accepts at most 8 GiB and never gives the worker a Ledger credential.

Stop the full owned process tree on Windows: virtualenv launchers may have children.
An OS-held byte lock, not a PID file or timestamp, controls writer ownership.
Archive immutable authority before maintenance. Never delete a live projection.

The supported initial deployment is local Windows x86-64 / CPython 3.13.
Other hosts require qualification against their own pinned native runtime.
