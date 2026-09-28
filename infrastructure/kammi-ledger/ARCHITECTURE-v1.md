# Kammi Ledger architecture v1

Status: **locked for implementation**. This is program infrastructure, not a new laboratory protocol or authorization to run a model. Any change to these decisions requires a numbered architecture amendment and a new lock receipt. Existing lab seals and scientific claims retain their own authority.

## Purpose and flight gate

Kammi Ledger provides one program-wide custody service and a separate agent-memory service. Custody is authoritative evidence; memory is contextual and can only point to custody evidence. E4-1 and every other **new flight** wait for the acceptance gates below. Existing authorized work keeps its own lab ownership and contracts. The daemon's deployment must not silently modify them.

The first implementation slice is content-addressed storage (CAS), an immutable event journal, a custody graph, Merkle seals, and one writer daemon. The E4-0 legacy import is its first acceptance fixture. Policy, enforced leases, exposures, remote bundles, and memory follow in that order before the flight gate can pass. No “airspace reopens” claim is valid from a design lock alone.

## Trust and ownership

- One `kammi-ledgerd` process owns the read-write Ladybug `Database` object for `custody.lbdb` and, later, a separate read-write object for `memory.lbdb`. Clients use narrow Python/Rust SDK, CLI, and MCP APIs. They do not obtain database paths or arbitrary Cypher write access.
- The daemon authenticates actors and scopes each operation to a lab, run, and role. Local transport uses an ACL-protected named pipe; remote transport uses authenticated TLS. Audit events retain actor identity and request identity. A request ID is idempotent.
- Ladybug is a **rebuildable projection/index**, never the sole source of custody truth. CAS bytes and a durable, hash-chained event journal are authoritative. The two Ladybug files can be deleted and reconstructed from those bytes.
- Lab owners control scientific content, decisions, and claims. Chief Kammi coordinates identity, access, resources, exposure accounting, and the common gate vocabulary. Shared SDK code is not shared lab evidence.
- Memory queries may retrieve a claim and its `custody_ref`, but a memory record never satisfies an authorization predicate or becomes an observed result by changing its trust class.

Ladybug's documented concurrency pattern allows one read-write database object and concurrent connections from that object; it does not allow another database object to open the same file concurrently. The daemon therefore also owns read queries while live. Its transactions are serializable, atomic, and durable **within Ladybug**, but cannot atomically include filesystem CAS writes, journal appends, remote work, or process launches. The journal/replay protocol below covers those boundaries. [Concurrency](https://docs.ladybugdb.com/concurrency/), [transactions](https://docs.ladybugdb.com/cypher/transaction/).

## Identity and immutable bytes

```text
.kammi/
  objects/sha256/21/fc77...       # immutable raw bytes
  journal/                         # framed event segments and checkpoints
  custody.lbdb                     # rebuildable projection
  memory.lbdb                      # separate, non-authoritative projection
  locks/                           # daemon ownership and worker fencing
  cache/                           # disposable
```

An artifact ID is `sha256:` plus the SHA-256 of its **raw bytes**. A location is metadata and may change without changing identity. An artifact registration records digest, byte count, media type, schema ID, kind, producer, observed source path/URI, and custody scope. It reads the source once into a temporary CAS object, hashes while copying, flushes, then atomically publishes the digest path. Existing digest paths are verified before reuse. Source paths are never embedded in content identity.

Structured custody objects use RFC 8785 JSON Canonicalization Scheme (JCS) and SHA-256. The SDK rejects duplicate keys, invalid Unicode, non-finite numbers, and ambiguous or out-of-range numeric representations; large integers and decimal quantities use schema-defined strings. Required/missing/null semantics are explicit per schema. Identifiers are domain-separated and schema-versioned:

```text
object_id = SHA256("kammi-object-v1\0" || JCS(object))
event_id  = SHA256("kammi-event-v1\0"  || JCS(event))
seal_root = SHA256("kammi-seal-v1\0"   || JCS(seal_payload))
```

Only content fields appear in these payloads. Timestamps, mutable locations, and display labels are excluded unless a schema explicitly makes them semantic. Members and parents are sorted by full typed ID; duplicates are rejected. A cross-language conformance corpus must give the same bytes and IDs in Python and Rust. [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html).

## Event journal and crash protocol

Every accepted operation creates an immutable event. The daemon assigns a monotonically increasing sequence, a previous-event digest, actor/request IDs, scope, event type, payload object reference, and UTC event time. The journal is framed with length and checksum; each committed frame links to the previous digest. Incomplete tails are recognizable. Records are appended only by the daemon.

Commit order is:

1. Validate policy and canonical payload; stage all referenced immutable CAS objects.
2. Flush and publish CAS objects. An unreferenced object after a crash is an orphan, never a false committed event.
3. Append and durably flush the event frame. This is the custody commit point. A retry with the same request ID returns the same event.
4. Apply the event to Ladybug in a transaction. On restart, replay committed events not yet projected. If the DB is missing or inconsistent, rebuild from the beginning.

Windows durable rename/flush behavior and journal-tail recovery must be demonstrated on the actual filesystem before deployment. A Ladybug WAL checkpoint does not substitute for the event journal. The verifier compares the event chain, CAS digests, projection sequence, and projected heads.

Events include `RunCreated`, `ScientificSpecBound`, `ExecutionSpecBound`, `ToolchainBound`, `ArtifactRegistered`, `SealCreated`, `SealVerified`, `HeadPromoted`, `StageAuthorized`, `LeaseAcquired`, `LeaseReleased`, `ContactRecorded`, `ExposureRecorded`, `AttemptStopped`, `OutputsRegistered`, `ReplayVerified`, and `RunClosed`. New event types require a registered schema. Failed attempts stay in the journal; authoritative heads change only through an explicit, policy-valid promotion event.

## Custody graph and seals

The typed Ladybug custody schema starts with `Lab`, `Agent`, `Run`, `Stage`, `Artifact`, `Event`, `Seal`, `Authorization`, `Host`, `Resource`, and `Panel`. Scientific specs, execution specs, toolchains, manifests, and results initially use typed `Artifact.kind` values. Relationship tables include `BELONGS_TO`, `EXECUTED_BY`, `HAS_STAGE`, `HAS_EVENT`, `INPUT_TO`, `OUTPUT_OF`, `DERIVED_FROM`, `SUPERSEDES`, `SEALED_BY`, `PARENT_SEAL`, `VERIFIED_BY`, `AUTHORIZED_BY`, `RUNS_ON`, `USES_RESOURCE`, and `EXPOSES`. The daemon alone maps versioned event schemas into this graph; no lab writes its own synonyms. Ladybug's node and relationship tables are explicitly typed. [Schema documentation](https://docs.ladybugdb.com/cypher/data-definition/create-table/).

A v1 seal payload contains schema ID, sorted direct artifact IDs, and sorted parent seal roots. Parents must already exist and be verified; cycles and duplicate members are rejected. The root binds the complete transitive ancestry without serializing it into every successor. `kammi lineage` walks parent edges, validates every root and artifact byte, and can export a flat closure when an old verifier requires one. A contract binds an ancestor using its exact digest; a verifier loads that ancestor to check any property it needs.

`ScientificSpec`, `ExecutionSpec`, `Toolchain`, `Run`, and `Result` are distinct artifact kinds/relations. A verifier repair changes the toolchain identity and produces a new attempt/event, not a scientific revision. A hypothesis or task-contract change produces a new scientific spec. Importers preserve historical contract bytes and roots even if the new graph expresses them more compactly.

## Contacts, gates, leases, and exposures

Contact classes are `POPULATION_GENERATED`, `TOKENIZER`, `MODEL`, `CUDA`, `TRUTH_LABEL`, `EVAL_PANEL`, `SCORING`, and `HUMAN_INSPECTION`. A contact event binds run, class, target artifact/panel, actor, time, and authorization. `contact-status` is a projection over events. **No recorded contact** is only a complete negative claim when all relevant contact-capable access paths are mediated and their coverage is attested; unmanaged shell, process, or file access cannot be disproved by an empty ledger.

Stage policies are declarative, versioned artifacts with a policy-engine implementation hash. `authorize` evaluates sealed scientific/execution specs, verified roots, contact and exposure histories, resource leases, and stage-specific predicates. It returns an event-backed authorization or a structured denial. An adapter or policy update may alter future gate results; it cannot rewrite existing event history or a lab's sealed protocol.

Resources have leases with owner, run, host, purpose, start, expiry, and a monotonic fencing token. The host executor checks the token immediately before launch and during long jobs; a lease record alone is advisory. Unmanaged GPU users must be detected and treated as an occupancy conflict or an explicit unknown. Expiry/restart reconciliation cannot cause two valid executors to own the same GPU simultaneously.

Panel exposures use the program-wide purpose vocabulary `generation`, `fit`, `selection`, `thresholding`, `diagnostic`, and `terminal`. Every mediated open records lab, run, actor, purpose, date/time, and decision. Reports show the vector of counts and sequence of decisions across labs. Terminal-panel access is denied before its authorization. File ACLs or a guarded panel gateway must make this an actual access control, not just a logging convention.

Remote workers receive a signed, immutable RunBundle containing run/spec/root identities, clean git state, input roots, environment lock, device requirements, seeds, command, expected outputs, and authorization. The worker returns environment, execution, and output receipts plus artifacts; the daemon verifies and ingests them. Worker evidence cannot promote a head by itself.

## Memory plane

`memory.lbdb` has its own schema, migration stream, retention policy, and retrieval indexes. Nodes include `Memory`, `Decision`, `Hypothesis`, `Procedure`, `FailureMode`, `ResultSummary`, `Concept`, `Task`, `Agent`, `Lab`, and `Project`, with `ABOUT`, `DERIVED_FROM`, `SUPPORTS`, `CONTRADICTS`, `SUPERSEDES`, `APPLIES_TO`, `DISCOVERED_BY`, `USED_BY`, and `RELATED_TO` edges. Each record has a stable ID, trust class, scope, text, author/time, confidence, supersedes references, and optional custody refs.

Trust classes are `OBSERVED`, `DERIVED`, `INTERPRETIVE`, `HYPOTHESIS`, `PREFERENCE`, and `PROCEDURE`. Changes create a new record and supersession edge. `OBSERVED` requires verified custody refs and still does not become custody evidence. A memory write checks referenced custody IDs through the daemon; there is no cross-database atomic transaction, so replay marks unresolved references rather than inventing evidence. Retrieval combines graph neighborhood and full-text search first, then versioned embedding/vector search after the authoritative spine is qualified. Retrieval responses show trust class and evidence links. Ladybug supports FTS over node string properties and a disk-backed vector index over node vector properties; extension/version qualification is required on the deployed Windows build. [FTS](https://docs.ladybugdb.com/extensions/full-text-search/), [vector](https://docs.ladybugdb.com/extensions/vector/).

## Schema evolution and interfaces

Original object bytes remain immutable. A registered adapter has source schema, target schema, implementation artifact/hash, and deterministic output. `AdapterApplied` binds source and output IDs. Any adapter used for a gate or result is named in that event. Adapters never mutate an old ID.

The daemon exposes typed operations only: artifact registration/get/verify, run creation/status, lineage, seal create/verify, authorization request, contact status/record, lease acquire/release, exposure open/report, memory search/record/supersede, and import/replay. SDKs share wire schemas and JCS fixtures. The MCP façade exposes these same scoped operations; raw Ladybug MCP is restricted to offline read-only inspection, never a live second database object or write path.

## E4-0 acceptance fixture

The current frozen legacy fixture is the E4-0 `v16-v09` final contract and seal. At this architecture lock, the contract file SHA-256 is `21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f`; the seal-file SHA-256 is `0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c`; its recorded legacy root is `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`, with 447 declared and 447 present entries. These are fixture anchors, not proof that every referenced byte has already been independently reverified by Kammi Ledger.

The importer runs read-only over the complete E4-0 history, including failed attempts, contracts, receipts, seals, and lineage. It preserves original raw digests, legacy root algorithms, names, and statuses. It must reproduce the existing verifier's 447/447 closure and identify the same authoritative head without experiment-specific code in the custody engine. A separate new Merkle seal may bind the imported legacy seal; its root will be different and must never be presented as the legacy root. Future successors reference that root rather than copying 447 entries.

## Flight acceptance gates

Before new flights, independently demonstrate and retain receipts for:

1. One-byte CAS tamper detection and rejection.
2. Full deletion/rebuild of `custody.lbdb` with identical event head, graph heads, and seal roots.
3. Crash after CAS publication/before journal commit, and after journal commit/before DB projection; recovery is idempotent and preserves committed history.
4. Two simultaneous GPU lease requests: exactly one valid fencing token and one executable launch.
5. Pre-authorization terminal-panel open rejected by the mediated access path; exposure vectors and decisions reconstruct across labs.
6. Registered schema adapter changes a field view while source bytes and ID remain unchanged.
7. Failed execution remains queryable without scientific-spec revision or silent head promotion.
8. Signed bundle executes on a disposable worker and returns independently verified evidence.
9. Fresh agent retrieves a relevant historical failure through memory and follows its custody refs to verified evidence; memory cannot satisfy a custody gate.
10. Complete E4-0 legacy import identifies the authoritative head and reproduces the legacy 447/447 closure and root, then verifies a new successor using only direct members plus parent roots.

The acceptance report records implementation versions, source hashes, environment, test fixtures, failures, independent reviewer, and exact roots. Any failed gate keeps the new-flight hold in place. Individual labs seal their own instantiated inputs, splits, seeds, and results; Kammi stores those identities and custody relations without merging evidence across labs.

## Implementation qualifications

Pin a Ladybug release, Python runtime, FTS/vector extension builds, JCS library, Windows filesystem, and remote-worker signature implementation in an execution lock before coding against them. The locally available `py` is 3.13; the online Ladybug system-requirements page appears older than current PyPI wheels, so actual wheel and extension compatibility must be proved rather than inferred. Python/FastAPI is the initial daemon preference; the wire contract allows a later Rust daemon. No agent receives direct database write permissions.
