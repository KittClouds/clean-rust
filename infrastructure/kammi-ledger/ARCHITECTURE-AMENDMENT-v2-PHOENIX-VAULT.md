# Kammi Library architecture amendment v2: Phoenix vault

Authority: user direction in Chief Kammi, 2026-09-27. This amends the physical
projection layout and adds a Phoenix product domain. It does not amend any
scientific protocol or grant model contact.

## One service, one database, distinct authority domains

`kammi-ledgerd` owns one writable Ladybug database object. Custody, contextual
agent memory, and Phoenix vault tables share that object and have separate
schemas and APIs. No client writes Ladybug directly. The old `memory.lbdb`
projection remains preserved as a historical file; memory journal replay builds
its tables in `custody.lbdb`. No memory claim becomes product or custody truth.

The CAS and hash-chained journals remain durable authority. Ladybug remains a
rebuildable projection, including for Phoenix vault state. Phoenix vault events
are part of the main Library journal so one commit sequence decides the active
source revision, generation, and Reader locator. Memory retains its separate
contextual journal and trust class.

## Phoenix ownership

Phoenix owns note content, stable entry IDs, human decisions, Reader locators,
generation qualification, and product semantics. Library owns immutable byte
identity, event commit, replay, physical transaction, authentication, and
single-writer arbitration. A vault is scoped to a Phoenix service actor. It is
not a scientific run and needs no lab-stage authorization for ordinary editing.

`VaultCreated`, `VaultSourceCommitted`, `VaultGenerationSelected`, and
`VaultReaderPositionSet`, and `VaultProductPrimarySelected` events describe the
product state. Source commits use
an expected revision and increment a vault source epoch. A derived generation
may become active only against the exact current source epoch. A later source
commit makes it stale without erasing the generation. Readers can retain the
immutable asset identities returned by the active-generation view. A rename
changes the workspace source object, not its
stable entry IDs.

The vault starts in legacy-mirror mode. The product can select Library as its
one-way primary authority only with a scoped cutover receipt and exact source
epoch. Phoenix owns the proof that its old local state and cold-open behavior
are ready; Library records the declaration and enforces its ordering.

The Phoenix-facing API is narrow and owner-scoped. It never exposes arbitrary
Cypher, Library administrative credentials, or scientific stage controls.
Source bytes and generation manifests enter CAS before a journal event can
select them. A crash before event commit leaves an unreferenced object. A crash
after journal commit is repaired by replaying the Ladybug projection.

## Portability

The vault's stable ID is generated once and stored in the authoritative event.
Filesystem paths are locations. A portable export must include the vault's
referenced CAS objects and its event slice plus a verifier manifest. Copying
only the Ladybug projection is not a portable vault. Import verifies bytes
and source/generation lineage before replaying semantic events on another
Library host. The package root is an integrity identity supplied out of band;
v2 does not assert origin authenticity if an attacker can replace both package
and expected root.

This amendment requires successor Library qualification. Existing accepted
scientific receipts remain valid; new service source bytes close the flight gate
until the successor acceptance passes.
