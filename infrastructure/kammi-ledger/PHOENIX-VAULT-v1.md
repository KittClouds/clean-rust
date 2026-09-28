# Phoenix vault product extension

This is an extension of the existing Kammi Library service. Phoenix does not
open Ladybug and does not create another database. The one service owns CAS,
the hash-chained journal, a single Ladybug projection, replay, and the HTTP
boundary. Phoenix remains the owner of note/document meaning, accepted graph
facts, UI decisions, generation eligibility, and Reader behavior.

The extension is introduced by
[architecture amendment v2](ARCHITECTURE-AMENDMENT-v2-PHOENIX-VAULT.md).
It is a product API. It grants no scientific stage or model contact.

## Identity and commit flow

Register a Phoenix **service actor** with its own credential. Generate a stable
vault ID once. Source IDs are stable across renames; source revisions are
optimistic and append-only. A source commit increments the vault source epoch.

Phoenix writes graph/index/scene bytes as immutable assets, then writes a
canonical JSON manifest:

```json
{"schema":"PHOENIX_VAULT_GENERATION_V1","vault_id":"phoenix.example","source_epoch":1,"generation_id":1,"asset_ids":["sha256:..."]}
```

It stages the manifest as a vault asset and selects the generation with that
manifest's ID, the asset IDs, and the exact current source epoch. Selection
fails if a source changed meanwhile. A subsequent edit marks the generation
stale; it does not erase existing assets or the Reader's source revision.

## HTTP surface

All calls require the service actor's bearer credential. Write calls also
require a currently accepted Library source/runtime unless the caller is an
isolated acceptance fixture. The JSON body includes `actor_id` and
`request_id`.

| Operation | Route | Result |
| --- | --- | --- |
| Create vault | `POST /v1/vaults` | Stable vault ID |
| Commit source bytes | `POST /v1/vaults/source` | Revision, epoch, CAS ID |
| Stream source bytes through 16 MiB | `POST /v1/vaults/source-stream` | Revision, epoch, CAS ID; headers carry actor, vault, source, base revision, request ID |
| Stage small asset | `POST /v1/vaults/asset` | CAS ID |
| Stream large asset | `POST /v1/vaults/asset-stream` | CAS ID; headers carry actor, vault, kind, request ID |
| Select generation | `POST /v1/vaults/generation` | Generation receipt |
| Save Reader locator | `POST /v1/vaults/reader` | Source ID, revision, byte offset |
| Select Library as product primary | `POST /v1/vaults/product-primary` | One-way authority event bound to the source epoch and cutover receipt |
| Read vault and source | `GET /v1/vaults/{id}` and `/sources/{source_id}` | Current view/content |
| Stream source bytes | `GET /v1/vaults/{id}/sources/{source_id}/bytes` | Verified bytes, revision and CAS identity headers |
| Read asset | `GET /v1/vaults/{id}/assets/{sha256_id}` | Verified byte stream |
| Export portable package | `GET /v1/vaults/{id}/package` | ZIP64 stream and `X-Vault-Package-Root` |
| Import portable package | `POST /v1/vaults/package` | Verified semantic replay |

The Rust `kammi-client` offers the same narrow calls. It streams asset upload,
asset download, export, and import instead of loading large files into memory.
The package root must be preserved separately from the package bytes; import
requires that expected root. This checks integrity but is not an origin
signature.

The JSON source route is suitable for sources up to 8 MiB before base64
expansion. The streaming route accepts an exact 16 MiB document and rejects
larger content before a journal commit. Phoenix's 16 MiB document limit can
therefore be preserved. The Rust client exposes file-backed source upload and
streamed source download.

## Provisioning and pinned client

The Library administrator registers one actor per Phoenix installation with
`POST /v1/actors`: `kind=service`, `lab=phoenix`, and
`credential_sha256=SHA256(random 256-bit bearer token)`. Generate the token
locally with the operating system CSPRNG. Store the token in an ACL-restricted
Phoenix installation secret file; send only the hash to the administrative
endpoint. Phoenix loads the token at runtime and sends it only over loopback
HTTP or authenticated HTTPS. Do not place it in source, logs, vault packages,
memory, or chat. The Library administrative credential never enters Phoenix.

The versioned Rust client is distributed as a `.crate` package with an exact
SHA-256 and accepted Library source root in `dist/SDK-HANDOFF-v1.json`. Product
builds pin both the package digest and service API major version. The SDK is
an HTTP client; it never opens Ladybug. Credential rotation is not yet an
online endpoint; coordinate a versioned actor migration through Library Lab.

## One-way product cutover and recovery

New vaults begin in `LEGACY_MIRROR` mode. While Phoenix's current local save
is authoritative, the adapter commits locally first and writes an outbox
entry keyed by stable source ID, local revision, content digest, and an
idempotent Library request ID. It then mirrors the same bytes to Library in
revision order. A crash before mirroring leaves an outbox item to replay. A
lost Library response is resolved by retrying the same request ID and bytes.
The UI must not describe an unmirrored edit as current in Library.

For cutover, Phoenix pauses edits, drains the outbox, compares stable IDs,
revisions, digests, and the Reader locator against the Library view, and
performs a product-level cold-open from an independently copied package.
Phoenix stages a canonical `PHOENIX_VAULT_CUTOVER_V1` receipt as a vault asset
of kind `cutover-receipt`. The receipt binds `vault_id`, `source_epoch`,
`legacy_snapshot_id`, and `cold_open_root`; the last two are SHA-256 IDs of
the product's exact legacy snapshot and cold-open proof. It then calls
`POST /v1/vaults/product-primary` with that asset ID and exact source epoch.
The Library event is the durable one-way authority selector. A source change
before the call rejects the transition; Phoenix rechecks before retrying.

After the selector commits, Library is primary. A save is acknowledged only
after its vault source commit is confirmed. Phoenix may update its local files
afterward as a disposable cache. If the process dies between vault commit and
local cache update, the next launch reads the Library vault view and refreshes
the cache. If the Library service is unavailable, Phoenix cannot silently
accept a local authoritative edit. Divergent revisions or digests stop
reconciliation for explicit product repair; no last-writer-wins merge.

The Library records the selected mode and receipt but does not certify
Phoenix's cold-open semantics. That qualification belongs to Phoenix product.

## Phoenix migration boundary

Phoenix's existing workspace saves, revision-bound document commits, memory
generations, and scene publications remain its product semantics. The product
adapter should map those existing commit points to the Library calls above.
Only the service credential crosses into Phoenix. It must never receive the
Library administrative credential or a direct Ladybug handle.

Cold-open qualification requires a copied package to import into another
Library host and recover source bytes, active generation assets, and Reader
locator. Existing Phoenix-native UI/storage migration and end-to-end app
qualification are separate product work; the Library acceptance suite qualifies
the service boundary.
