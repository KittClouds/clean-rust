# Security boundary v1

Qualified scope: cooperating local agents on a trusted Windows account/host, authenticated
loopback HTTP, pinned runtime, narrow write tools, exact grants and guarded executors.
Protect filesystem permissions, credentials, signing keys and backups with OS administration.

The daemon refuses a second writable owner using an OS byte lock; Ladybug also locks its
database. Direct writable database access by clients is forbidden. A user controlling the
OS account can bypass filesystem/API controls and is outside this threat model.
Do not expose loopback service directly to an untrusted network. Remote use requires an
authenticated TLS tunnel/proxy and separate deployment qualification.

Master credentials authorize infrastructure administration and can inspect protected bytes.
Ordinary agents use actor credentials plus grants. Raw secrets are not journal artifacts.
Remote worker signatures establish origin/integrity; they do not prove honest computation.
Memory is contextual and may be false, contradictory or superseded.
Acceptance fault hooks are explicitly opt-in; enabling them invalidates ordinary operation.

CAS + journal integrity is hash-based, with OS protection as the append-only enforcement
boundary. A hostile administrator can rewrite/re-sign local state; external anchoring is
not implemented in v1. This release does not claim hostile multi-user or physical security.
