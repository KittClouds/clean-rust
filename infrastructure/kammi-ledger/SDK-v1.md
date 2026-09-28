# Service clients v1

Python: ledgerd.client.KammiClient; client.py imports no Ledger or Ladybug.
Rust: sdk/rust, blocking reqwest with a reused client, streamed artifact upload,
borrowed JSON views, bytes buffers and compact header maps. Cargo.lock pins resolution.
Build targets on G:\kammi-ledger-target; C: test path uses a directory junction.

CLI: python -m ledgerd.cli. `call METHOD /v1/endpoint --body request.json`
exercises the same stable service contract; it never opens a database.
Every retryable write needs an explicit request_id. Reuse only for identical intent.
The SDK performs no local policy decision. Actor credentials and master credentials
have different roles. See schemas/wire-v1.json and schemas/openapi-v1.json.

Phoenix/external harness fixture starts a distinct daemon/client process and uses HTTP
for artifact registration, scoped historical fact, grounded memory, retrieval and trace.
