# Kammi Library architecture amendment v4: Vault workspace, six-clock memory, shell ABI

Authority: the KAMMI Vault Gold Path Audit (2026-09-28), revised after the Rust cutover, and
the user's go for Phase 0 (2026-09-29). This is the Phase 0 contract: it **freezes** schemas
and the verb list. It does **not activate** them. No v4 event can be journaled until the
activation rule below is met, so the Python rollback path stays valid until then.

Machine-readable form: the `kammi-contract` crate (`crates/kammi-contract`). Its types are the
normative field lists, and its tests pin the invariants stated here.

## 1. One memory record: the six-clock envelope

Library memory adopts Phoenix's `TemporalEnvelopeRecordV1` clock model
(`phoenix-memory-contract`), carried as JSON in a new memory event, `MemoryRecordedV2`.
Existing `MemoryRecorded` events stay valid and are read as v2 records with every clock
unknown except `observed_at`.

| Clock | Field | Meaning | Who supplies it |
| --- | --- | --- | --- |
| Source time | `source_time` | Timestamp carried by the source or its container | Client |
| Asserted | `asserted_at` | When the speaker or author made the statement | Client |
| Occurred | `occurred.from`, `occurred.to` | The event instant or interval the statement describes | Client |
| Observed | `observed_at` | When the Library ingested it; equals the event's `utc` | Library (required) |
| Valid | `valid.from`, `valid.to` | When the statement may hold in the represented world | Client |
| System | derived | Journal sequence range in which the record is current | Library, derived from the journal; never in the payload |

Rules (mirroring `phoenix-memory-contract::temporal::validate_envelope_metadata`):

- A clock value is an RFC 3339 UTC string or the literal `"unknown"`. An interval end may also
  be `"open"` (unbounded). **Unknown is never the same as open**: a missing occurrence time
  cannot read as "always".
- `occurred` is complete or unknown as a whole: both ends known, or the single value
  `"unknown"`. It requires `from <= to`.
- For `valid`, `from <= to` when both ends are known. The default is `{"from": "unknown",
  "to": "open"}`.
- `precision` is one of `unknown instant minute hour day month year interval relative
  ordinal`, the same values and order as `TemporalPrecisionV1`.
- `timezone_offset_minutes` is an integer in `-1439..=1439` or `"unknown"`.
- `original_text` preserves the source's own temporal wording. An empty string means none.
- `confidence` is a finite number in `[0, 1]`.
- `flags` is a subset of `normalized` and `uncertain`.
- No artificial decay. Recency is a query signal computed from the clocks. Changed beliefs
  are handled by `valid` intervals and supersession, never by deleting or weakening memory.

The other `MemoryRecorded` fields are unchanged: kind, scope, text, author, custody
references, tags, confidence, and exact embedding bytes with the model identity. So is
supersession: `MemorySuperseded` closes the superseded record's system interval at the
superseding event's sequence.

## 2. The workspace domain

A workspace is a durable place where disposable agents resume work. Its events are in the
**main journal** (custody trust class), so one commit sequence orders workspace decisions with
the custody events they cite. Workspace state is a projection of those events. `status` and
`work` output must be rebuildable byte for byte by replay.

**HEAD and optimistic concurrency.** Each workspace has its own chain. Every workspace event
payload carries `workspace_id` and `expected_head`: the event ID of the workspace's previous
event, or `"genesis"` for `WorkspaceCreated`. The command is refused with `409 conflict` when
`expected_head` is not the current HEAD. The workspace HEAD is the ID of its latest event.
Request IDs are idempotent, as elsewhere. The request ID binds the intent hash, and reusing
it with a different intent is refused.

**References.** A `refs` list names what a line rests on: `event:`, `artifact:`, `seal:`,
`memory:`, `run:` or `workspace:` followed by an existing identity. Unknown references are
refused. A work packet line always cites the event that established it.

| Event | Payload beyond `workspace_id`, `expected_head` | Effect on the projection |
| --- | --- | --- |
| `WorkspaceCreated` | `title`, `lab`, `owners[]` | New workspace; the owners may write |
| `WorkspaceObjectiveSet` | `objective`, `refs[]` | Replaces the objective (the history stays) |
| `WorkspaceScopeSet` | `authorized[]`, `forbidden[]`, `refs[]` | Authorised scope and the do-not-do list |
| `WorkspaceNextStepSet` | `next_step`, `refs[]` | The single next step |
| `WorkspaceNoteRecorded` | `note_id`, `text`, `refs[]` | Appends a note |
| `WorkspaceDecisionRecorded` | `decision_id`, `text`, `rationale`, `refs[]`, `supersedes?` | Appends a decision; `supersedes` closes an earlier one |
| `WorkspaceQuestionOpened` | `question_id`, `text`, `refs[]` | Opens a question |
| `WorkspaceQuestionResolved` | `question_id`, `resolution`, `refs[]` | Closes it |
| `WorkspacePinned` / `WorkspaceUnpinned` | `ref`, `note?` | Maintains the pinned set |
| `WorkspaceHandoffSent` | `handoff_id`, `to`, `summary`, `next_step`, `refs[]` | A pending handoff |
| `WorkspaceHandoffReceived` | `handoff_id` | The handoff is no longer pending |
| `WorkspaceAgentAttached` / `WorkspaceAgentDetached` | `session_id`, `agent`, `tool` / `session_id`, `outcome` | Who is working now |
| `WorkspaceClosed` | `outcome`, `summary` | Read-only afterwards |

**Scope.** Memory scope may be the actor's lab (unchanged) or `workspace:<id>`, which the
workspace's owners and attached agents may read and write. This is how memory is shared across
labs, without weakening lab isolation.

## 3. Shell ABI (frozen verb list)

One meaning, three transports: the `kammi` CLI, MCP tools (`kammi_<verb>`) and the SDKs.
Text is for humans; `--json` gives the exact server object, sorted, for agents. Every write
carries an idempotency key (`--request-id`, generated when omitted) and, for workspace writes,
the expected HEAD (`--expect-head`; `kammi open` records the HEAD it read). Exit codes: `0` ok,
`1` refused by the Library, `2` usage, `3` conflict (stale HEAD), `4` Library unreachable.

| Verb | Meaning | Phase |
| --- | --- | --- |
| `status`, `call`, `artifact`, `run`, `seal`, `lineage`, `history` | The v1 commands, unchanged | 0 |
| `verbs` | List this ABI with each verb's phase and MCP tool | 0 |
| `open <workspace>` | Attach a session; prints the work packet | 1 |
| `work` | Work packet: objective, scope, do-not-do list, recent events, pending handoffs, open questions, next step; each line cites an event | 1 |
| `objective`, `scope`, `next`, `note`, `decide`, `ask`, `resolve`, `pin`, `unpin` | Workspace writes, one event each | 1 |
| `handoff`, `receive` | Send or acknowledge a handoff | 1 |
| `close` | Detach the session, or close the workspace (`--workspace`) | 1 |
| `remember`, `recall`, `trace` | Memory write, cited retrieval, evidence trace | 1 (recall quality: 3) |
| `find` | Custody lookup by name or identity | 1 |

Phase 0 ships the v1 commands in Rust (`kammi`, `kammi-mcp` in `crates/kammi-shell`) and the
full verb list as a typed contract. A reserved verb answers `not available until Phase 1` with
exit code 2. `tools/shell_conformance.py` holds the Rust shell to the frozen Python CLI and MCP:
reads are byte-identical and MCP sessions JSON-equal. The Python CLI and MCP stay frozen with
the rollback tree.

## 4. Receipt stream

The audit's open question is resolved: **receipts leave the memory state.**

- A third journal, `receipts` (trust class: receipt), holds `MemoryRetrieved` events for `/v2`
  recall. It is hash-chained and verified like the others, and replay skips it.
- Retry idempotency uses the segment index's request hash (`requests.tbl`), which is on disk,
  not in memory. A retried search returns the committed response, as today.
- `/v1` search keeps writing `MemoryRetrieved` to the memory journal while the rollback window
  is open (Python parity). When the window closes, `/v1` receipts move to the receipt stream
  too.
- Reason: daemon memory is O(events), at ~1 to 1.7 KB per event (Phase 4, A6/A7). Searches
  are the most frequent operation. They must cost disk, not permanent RAM.

## 5. The Python rollback window

The window closes only when all of the following hold:

1. At least 7 days after the cutover, so not before 2026-10-06.
2. The `rust_service.py monitor` history shows the flight gate `OPEN` throughout, no
   unexplained restarts, and daemon RSS consistent with ~1 to 1.7 KB per event.
3. No rollback predicate fired. The predicates are a verification failure, a divergence
   between `export-v1` and Python's verifier, or a client regression.
4. A final `export-v1` has been accepted by Python's `independent_verify` and archived.
5. The user's decision is recorded as a registered artifact (a closure receipt).

After closure the Python tree is archived read-only history. It is not deleted.

## 6. Activation

v4 vocabulary becomes journalable through an ordinary release (`docs/RELEASE.md`) that adds
the v4 types to the closed registry, and only after §5 is satisfied. Until then the registry
stays exactly v1's 47 types. A test pins this: no v4 type is accepted by `kammi-v1`.

Because Python cannot verify v4 events, the release that activates v4 must replace Python's
`independent_verify` as the audit's independent verifier. Its replacement is a Rust verifier
that shares no decision code with `kammi-core`, as in the plan's `kammi-qualify
verify-store`.

## 7. Compact state (scheduled, not Phase 0)

Before Phase 3 intake: compact binary state (32-byte keys, payloads read back from segments)
and derived-state checkpoints. It is qualified as its own release, with A6/A7 rerun.
