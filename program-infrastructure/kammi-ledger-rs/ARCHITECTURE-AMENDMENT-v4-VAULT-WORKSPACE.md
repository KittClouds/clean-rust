# Kammi Library architecture amendment v4: Vault workspace, six-clock memory, shell ABI

Authority: the KAMMI Vault Gold Path Audit (2026-09-28), revised after the Rust cutover; the
user's go for Phase 0 (2026-09-29); and the user's Phase 1 decisions (2026-09-29), revision 2
below. Phase 0 froze these schemas. Phase 1 implements them in a binary that runs with v4 off.
The vocabulary becomes journalable on a store only through the journaled activation (§6). So
the Python rollback path stays valid until then.

Machine-readable form: the `kammi-contract` crate (`crates/kammi-contract`). Its types are the
normative field lists, and its tests pin the invariants stated here.

Revision 2 (Phase 1 decisions):

- **Activation:** a journaled action (`LibraryVocabularyActivated`), not a code release.
- **Closure:** accepted as one-way, and not before 2026-10-06.
- **Resume test:** runs through a provider-neutral function interface.
- **Ownership:** Chief Kammi owns the ledger and the Frozen Fabrique workspace.
- **Gate list:** changes at activation.

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

**Who may write.**

- **Admin:** the Library admin (the master token, held by Chief Kammi) may do anything,
  including creating workspaces.
- **Owners:** they own their workspace. Owners must be registered actors.
- **Handoff recipients:** an actor that a handoff in the workspace was sent to becomes a
  participant. It may attach, note, decide, ask, resolve, pin, hand off and receive. Handoffs
  are how access is delegated.
- **Owners only:** setting the objective or the scope, and closing the workspace.
- **Guidance, not enforcement:** the do-not-do list tells agents what not to do. Gated
  operations stay behind grants and policy.
- **Protected material:** work packets may name it by classification and location only, never
  by content.

**Commit safety.** A workspace command runs replay's own checks on a copy of the state before
the append. Anything replay would refuse never reaches the journal.

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
| `close` | Detach the session, or close the workspace (`--end`, owners only) | 1 |
| `log` | The workspace's events after a given event (the record behind the packet) | 1 |
| `create` | Create a workspace (Library admin only, so Chief Kammi) | 1 |
| `help` / `--help` | Usage for all verbs, or one verb's arguments | 1 |
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

## 6. Activation (journaled, one-way)

A store starts with only the v1 vocabulary active. The binary understands v4, but the core
refuses every v4 event, on the command path and on replay, until the journal contains
`LibraryVocabularyActivated`. That event is itself the first v4 event, so the active vocabulary
is derived from the journal like everything else. No side file can disagree with history.

**Payload:**

- `vocabulary` is `"v4"`, and `not_before` is `2026-10-06T00:00:00Z`.
- Three registered artifacts:
  - `closure_decision`: a `KAMMI_ROLLBACK_WINDOW_CLOSURE_V1` document deciding `CLOSE`,
    recording the user's decision;
  - `verification`: a Rust independent verification (`kammi-verify`) that PASSes at the head
    just before its own registration, and that registration must be the latest event, so
    nothing enters unverified;
  - `backup`: the manifest of the backup taken just before.

**Command rules:** admin only; refused before `not_before` by the Library clock; refused if v4
is already active.

**Replay rules:** v4 must not already be active, the fields must be exact, and the artifacts
must be registered.

**The one-way door:** after activation, `export-v1` rollback ends, and no pre-Phase-1 Rust
binary can read the journal either. Recovery is forward-fix only. Before activation, the
procedure is rehearsed on a current copy of the live store, and a backup is taken.

**Independent verifier:** Python cannot verify v4 events. From activation on, `kammi-verify`
(which shares nothing with `kammi-core` or `kammi-store` except the JCS canonicalizer)
replaces Python's `independent_verify` as the audit's independent verifier.

**Gate list:** `export_v1_rollback` stays in the acceptance through the rollback window. After
activation it is retired, and four gates are added: `rust_independent_verifier`,
`v4_replay_identity`, `resume_gate` and `activation_rehearsal`.

**Resume test (Phase 1 gate):** fresh agents work from `kammi` alone, through one
provider-neutral function interface (`kammi verbs --functions`; the same definitions are the
MCP tools). Runners:

- Claude app subagents;
- local llama.cpp and OpenRouter, both through the OpenAI-compatible tool-calling API;
- the Codex app.

A runner counts as a passing headless test only when its path has been verified end to end.

## 7. Compact state (scheduled, not Phase 0)

Before Phase 3 intake: compact binary state (32-byte keys, payloads read back from segments)
and derived-state checkpoints. It is qualified as its own release, with A6/A7 rerun.
