# App-native AI harness audit v1

Status: audit and research only
Date: 2026-07-14
Scope: AI chat page, AI side panel, Canvas, editor AI toolbar, note workspace, Phoenix chat/runtime, app command surfaces, retrieval, and research
Explicit exclusion: all active GNN/trainer work under `rust-native/phoenix-spikes/**`, including `candle-baseline-trainer` and `gfm-rag-8m-parity`

## Executive verdict

Phoenix does not need another chat UI. It needs one app-native agent runtime behind every existing AI surface.

The repository already has a credible skeleton: durable threads and messages, durable run/event/tool/approval rows, a Rust planner, scoped note and graph retrieval, workspace artifacts, revision-checked editor edits, and a Canvas UI. The problem is that these pieces do not form one harness:

- The AI page streams directly through `KammiChatUiService`.
- The side panel owns a separate durable planner/tool/approval loop.
- The editor toolbar owns a third direct streaming-edit loop.
- Canvas is a side-panel mode flag and selection shortcut, not a durable output contract.
- The note is an editable target, but not yet a file-like transactional workspace for an agent.
- The app exposes many useful APIs, but there is no governed command bus that turns them into a coherent model-facing environment.
- Deep research is not implemented. The current planner is a four-tool-round retrieval helper with no web research tools, citation ledger, gap loop, or context compaction.

This should be treated as a control-plane rebuild around reusable parts, not a visual chat rewrite and not a ground-up replacement of Phoenix persistence.

## Definition of the product

An app-native AI harness is the runtime that lets a model perceive, reason about, and safely act on Phoenix as if Phoenix were an IDE whose primary files are notes.

When the harness is enabled:

1. A note has a stable file-like identity, revision, readable content, addressable ranges/blocks, diff, checkpoint, and atomic commit contract.
2. The agent receives one governed command environment for notes, folders, navigation, search, indexing, embeddings, graph reads, research, and app state.
3. The agent loop is durable, resumable, cancellable, observable, provider-neutral, and independent of which UI surface launched it.
4. Chat and note output are explicit output targets of the same run protocol.
5. Every mutation has a policy decision, preview or trusted grant, expected revision, commit receipt, and real rollback/checkpoint path.
6. Deep research is a bounded evidence loop with source provenance, claim support, citation verification, and a final note or chat synthesis.

The existing chat page and side-panel chat can remain visually familiar. They should become two clients of the same harness session, not two implementations of AI behavior.

## Audit method and constraints

This audit used source inspection only. No implementation was started, no GNN file was touched, and no build or long-running test was launched while the trainer worktree was active.

Primary local seams inspected:

- UI and editor: the full chat page, side-panel chat, editor toolbar, AI sidebar mode, editor agent workspace, note snapshots, and note editor store.
- Angular runtime clients: Kammi chat UI, Phoenix chat, tool host, Phoenix UI/store APIs, and TauRPC bridge.
- Native runtime: Phoenix chat, planner, runtime command router, Tauri RPC boundary, and desktop Cargo dependency graph.

External comparisons used current primary project sources for [Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md), [T3 Code](https://github.com/pingdotgg/t3code/blob/main/docs/architecture/overview.md), [Cline](https://github.com/cline/cline), and [OpenCode](https://opencode.ai/docs/server/).

## Current reality map

### 1. The three AI entry points are not one execution system

| Surface | Current execution path | Durable harness run? | Note mutation path |
|---|---|---:|---|
| Full AI chat page | `AiChatPageComponent -> KammiChatUiService.sendMessage -> handleStreamingChat` | No | None |
| AI side panel, Chat mode | `AiChatPanelComponent -> PhoenixChatService.startRun -> Rust planner/tool loop -> final stream` | Sometimes; planner requires workspace/index mode and OpenRouter configuration | No by default |
| AI side panel, Canvas mode | Same side-panel run with `mutationsEnabled: true` | Yes | TypeScript tool host proposals, with one selection-specific auto-apply shortcut |
| Editor AI toolbar | Direct `PhoenixChatService.streamChat` into a streaming editor session | No | Immediate live-editor replacement/insertion |

Evidence:

- The full page injects `KammiChatUiService` and delegates its send at `src/app/pages/ai-chat/ai-chat-page.component.ts:42,721,908`.
- `KammiChatUiService.sendMessage` starts at `src/app/lib/services/kammi-chat-ui.service.ts:312` and goes directly to its provider streaming path at lines 375 and 694. It does not start a `ChatRun`.
- The side panel starts a durable run at `src/app/components/right-sidebar/ai-chat-panel/ai-chat-panel.component.ts:1677-1678`, drives planner/tool state in `waitForRunReady` at line 1893, and invokes planner processing at line 1932.
- The toolbar dispatches its own AI workflow at `src/app/components/editor/plugins/toolbar/toolbar.component.ts:288`; direct streaming starts at line 356 after opening a live stream edit at lines 335-336.

Conclusion: shared persistence and shared model settings are not enough to call these one system. The unit that must be shared is the run protocol, tool environment, policy engine, event stream, and output contract.

### 2. Canvas is a mode flag, not yet a workspace contract

`AiSidebarModeService` stores only `chat | canvas`, a focus ticket, and an optional selection with a one-use `autoApplyEligible` flag. Canvas adds UI context and exposes proposal tools, but it does not define:

- a durable target note for the lifetime of a run;
- what happens when the user switches notes;
- a base revision and transaction boundary;
- a staged patch set;
- atomic commit/abort;
- a checkpoint that can restore the original note;
- whether final output belongs in chat, the active note, a new note, or both;
- recovery after app restart or WebView reload.

The screenshot also exposes a product issue: opening the side panel can squeeze the note into a very narrow column. A true Canvas mode should treat the note as the primary output surface and the chat/run trace as a resizable inspector, not reduce the output surface to a sliver.

### 3. The durable run skeleton is worth preserving

`PhoenixChat` already persists:

- threads and messages;
- `ChatRun` state;
- ordered run events;
- tool-call rows;
- approval rows;
- evidence JSON;
- planner messages;
- final response and error state.

The TypeScript model mirrors these as `ChatRun`, `ChatRunEvent`, `ChatToolCall`, `ChatApprovalRequest`, and `ChatRunSnapshot` in `src/app/lib/services/phoenix-chat.service.ts:88-301`.

Useful current states include queued, gathering, planning, executing tools, waiting for a tool host, waiting for approval, ready to answer, streaming, completed, degraded, failed, and cancelled.

This is the correct seed for the new harness event store. It should be generalized, not discarded.

### 4. The current planner is an RLM helper, not a full agent harness

The Rust planner currently offers:

- scope description;
- note list/get/read-span;
- lexical search;
- graph search;
- session state/stats;
- workspace artifact put/list/pin;
- active note snapshot and selection reads through the TypeScript host;
- highlight range;
- replace/rewrite/insert/save proposals.

The planner hard-caps itself at four tool rounds and 24 artifacts (`rust/phoenix/crates/phoenix-runtime/src/planner.rs:16-17,313`). The side panel gives the whole run an 8,000 ms deadline (`ai-chat-panel.component.ts:1856`). This is suitable for a small retrieval pass, not for IDE-style work or deep research.

The initial contributor layer is also a stub: `ContributorCoordinator::gather` returns an empty default contribution in `rust/phoenix/crates/phoenix-chat/src/lib.rs:76-86`. Retrieval happens only if the optional planner path is enabled.

### 5. Provider behavior is component-owned and inconsistent

The side panel enables the planner only when workspace mode is on and an OpenRouter key is configured. The final response may then use Google, NVIDIA NIM, or OpenRouter, but the planner transport still depends on OpenRouter. The full page can use any configured provider but bypasses the planner entirely.

Consequences:

- capability changes when the same thread is opened in another surface;
- Canvas silently depends on an OpenRouter planner even if another provider is selected for final output;
- run lifecycle and provider streaming are interleaved inside a 2,226-line Angular component;
- closing or reloading the component can strand UI-host work;
- there is no single provider-neutral model-event protocol.

### 6. Note edits have optimistic checks, but not transactions

`EditorAgentWorkspaceService` provides a useful live editor adapter:

- snapshot with note ID, Markdown, plain text, selection, blocks, and a document hash revision (`editor-agent-workspace.service.ts:129-145`);
- revision-checked replace/insert/delete/rewrite;
- streaming replace/insert;
- highlight and focus;
- immediate persistence through `NoteEditorStore.saveContentNow`.

But it is not a safe agent filesystem:

- edits mutate the live editor before or as they are persisted;
- a proposal's `rollbackToken` is only a string such as `noteId:revision`; no restore operation consumes it (`chat-tool-host.service.ts:137,159,192,209`);
- a partial streaming edit is deliberately preserved once any text arrived, so cancellation is not a true rollback (`editor-agent-workspace.service.ts:308-357`);
- edits are range-based against a ProseMirror position hash, not a durable note version/transaction;
- only one active note can be addressed through the editor host;
- multi-note edits cannot be committed atomically;
- note snapshots are manual/safety copies and `restoreAsCopy` creates another note rather than restoring a transaction (`note-snapshot.service.ts:24-68`).

### 7. The permission model is declared but not enforced

`RunOptions.mutationPolicy` declares `confirm | trusted_auto_edit | full_autonomy`, but repository search finds no runtime enforcement of those values. The side panel always supplies `confirm` at `ai-chat-panel.component.ts:1857`.

Current behavior is instead encoded by tool names and UI shortcuts:

- read tools run automatically;
- proposal tools create approvals;
- Canvas selection edits can auto-apply once when positions match;
- toolbar actions bypass the proposal/approval run entirely.

This is not a policy engine. A complete harness needs policy decisions based on capability, resource, command arguments, run profile, user grant, and risk.

### 8. Phoenix already exposes a broad app API surface

Reusable app operations already include:

- note/folder/entity/edge CRUD in `PhoenixStoreService`;
- note hydration and indexing in `PhoenixUiApiService.indexNote` (`phoenix-ui-api.service.ts:623`);
- line, scoped, semantic, lexical, and graph retrieval (`phoenix-ui-api.service.ts:632-720` and planner tools);
- graph node/edge reads and writes (`phoenix-ui-api.service.ts:850-884`);
- session state and statistics;
- document index reads;
- semantic vector materialization and candidate refresh commands;
- persistent chat, OM memory, workspace artifacts, and graph/store diagnostics;
- application state for the active note, sidebars, routes, and editor selection.

The runtime command surface already contains families such as `note:*`, `relation:*`, `session:*`, `chat:*`, `semantic:*`, `graph:*`, `persistence:*`, `documentGraph:*`, `entityCards:*`, `folderSchema:*`, and `networkView:*`.

These APIs should sit behind an agent capability registry. The model must not receive raw `storeCommand` or unrestricted relation mutation access.

### 9. There are two Phoenix source trees in the desktop dependency graph

`src-tauri/Cargo.toml:20-29` mixes `rust/phoenix` and `rust-native/phoenix` dependencies. The desktop's `phoenix-native` and `phoenix-types` come from `rust/phoenix`, while several graph rebuild, store, Overgraph, document-index, and relation crates come from `rust-native/phoenix`.

The chat and type files in the two trees have already diverged. The complete harness must name one authoritative runtime/type source or define a deliberate, generated compatibility boundary. Otherwise new agent tools will keep landing on ambiguous or incompatible app APIs.

### 10. Test coverage proves the skeleton, not the product contract

There are Rust tests for basic chat lifecycle and planner flows. However, the two most relevant end-to-end planner tests—scoped artifact promotion and Canvas TypeScript-host approval—are gated by `#[cfg(feature = "legacy-cozo-graph")]` at `rust/phoenix/crates/phoenix-runtime/src/lib.rs:15856-15858` and `16061-16063`. That feature is not in the runtime's default feature set.

Repository search found no focused Angular specs for `ChatToolHostService`, `EditorAgentWorkspaceService`, `AiSidebarModeService`, or the side-panel run loop. There is no cross-surface parity test proving that the full page and side panel produce the same run behavior.

## Open-source harness research

### Pi: minimal core, durable session tree, radical extensibility

Pi separates a unified multi-provider API, an agent runtime, and a coding-agent application. Its coding agent exposes a small built-in tool set (`read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`), programmatic SDK use, and a JSONL RPC mode. Sessions are JSONL trees with parent IDs, branch navigation, forking, and automatic/manual compaction while full history remains on disk. Extensions can register or replace tools, intercept lifecycle events, implement permission gates, customize compaction, and replace remote execution operations. Pi explicitly requires tool-output truncation so large results do not consume the context window.

Sources: [Pi coding agent README](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md), [extension contract](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md), and [RPC contract](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md).

Borrow:

- keep the core loop small;
- treat tools and lifecycle interception as registries;
- preserve full durable history separately from compacted model context;
- make headless/RPC use a first-class client, not an afterthought;
- cap and externalize large tool outputs;
- allow app-specific tools to replace generic implementations cleanly.

Do not copy:

- Pi intentionally ships without a built-in permission system and runs with the launching user's permissions. Phoenix controls valuable user content and should default to a governed policy engine.
- Pi's generic filesystem/bash environment should become a Phoenix note/app command environment, not unrestricted OS access.

### T3 Code: thin clients, provider runtimes, typed ordered events

T3 Code is primarily a GUI/orchestration layer around coding-agent providers, not the agent intelligence itself. Its current architecture uses a browser client, WebSocket transport, a server-side orchestration engine, provider services, queue-backed workers, ordered push events, checkpoint processing, and runtime receipts. Provider-native events are normalized into domain events before they reach the UI. Async completion is signaled by receipts rather than polling incidental state.

Source: [T3 Code architecture overview](https://github.com/pingdotgg/t3code/blob/main/docs/architecture/overview.md).

Borrow:

- every Phoenix AI UI is a thin client of one runtime protocol;
- normalize provider-specific messages and tool events once;
- use monotonically ordered domain events;
- serialize side-effect workers where order matters;
- publish explicit `turn_quiescent`, checkpoint, commit, and index completion receipts;
- test by awaiting receipts, not timers or component internals.

Do not copy:

- Phoenix should not merely wrap Codex/Cline/OpenCode as an opaque subprocess. It has unique note, graph, index, embedding, and app-state semantics that belong in its own capability runtime.
- A WebSocket server is not required inside a Tauri app; the lesson is the protocol boundary, not the transport choice.

### Cline: task harness, approvals, checkpoints, command/browser tools

Cline treats a task as a durable unit containing conversation, tool use, code changes, command executions, token/cost data, and resumable state. Its runtime supplies file, shell, search, browser, MCP, approval, and plugin facilities. It supports plan/act behavior, conditional tool policies, long-running command observation, context compression, and checkpoints. Cline checkpoints use a shadow Git repository and let users restore files, task context, or both.

Sources: [Cline repository](https://github.com/cline/cline), [task model](https://docs.cline.bot/core-workflows/task-management), [checkpoints](https://docs.cline.bot/core-workflows/checkpoints), [permission handling](https://docs.cline.bot/sdk/guides/permission-handling), and [ClineCore](https://docs.cline.bot/sdk/clinecore).

Borrow:

- one durable task/run owns messages, actions, approvals, budgets, checkpoints, and receipts;
- distinguish read, mutation, command, network, and external-resource permissions;
- let a rejection become a tool result so the model can adapt;
- support long-running work and notify when attention is required;
- separate restoring output state from rewinding conversation state;
- expose browser/research as tools with the same audit trail as note mutations.

Do not copy:

- a shadow Git repository is the wrong primitive for notes stored across IndexedDB/native rows and graph/index projections. Phoenix needs application transactions and note checkpoints.
- Cline's generic terminal is broader than necessary. Phoenix should expose an app command language first and optional OS shell only as a separately sandboxed capability.

### OpenCode: headless server, event stream, typed custom tools, granular permissions

OpenCode runs a server behind its TUI and exposes an OpenAPI contract, SDK, and server-sent event stream. Built-in and custom tools share a common registry. Permissions resolve to `allow`, `ask`, or `deny`, can match command/path patterns, can differ by agent, and include guards for external directories and repeated identical calls. Plan/build and subagent profiles are capability configurations rather than separate chat implementations.

Sources: [OpenCode server](https://opencode.ai/docs/server/), [tools](https://opencode.ai/docs/tools/), [permissions](https://opencode.ai/docs/permissions/), [agents](https://opencode.ai/docs/agents/), and [custom tools](https://opencode.ai/docs/custom-tools/).

Borrow:

- publish one typed headless API and event stream for every UI surface;
- use a single tool registry for built-in, app-native, plugin, and future connector tools;
- evaluate `allow | ask | deny` against the actual command/resource pattern;
- keep plan/read-only behavior as a permission profile;
- add loop detection for repeated identical failing calls;
- give every tool a session/run/resource context.

Do not copy:

- OpenCode's default is intentionally permissive for most operations. Phoenix should default reads to scoped allow, note writes to ask, destructive actions to deny, and sensitive/external access to ask or deny.
- Phoenix must preserve asserted graph truth boundaries; a generic graph mutation tool must never be exposed as a convenience shortcut.

## Synthesis: what Phoenix should build

The best fit is:

- Pi's small, extensible loop;
- T3 Code's normalized ordered runtime protocol and receipts;
- Cline's durable task/checkpoint/approval semantics;
- OpenCode's headless tool registry and granular policy model;
- Phoenix's existing native store, note editor, retrieval, graph, embedding, and app-state APIs.

It should not embed one of these products wholesale. The unique value is an agent environment whose filesystem is the user's Phoenix workspace and whose commands understand notes, scopes, graph truth, indexes, and research provenance.

## Target architecture

### Architectural rule

Angular components render and submit intent. They do not own agent loops.

The native Phoenix runtime is the durable control plane. A provider adapter may live natively or behind a formal host protocol, but component lifecycle must never define run lifecycle. Live-editor-only presentation actions such as focusing or highlighting may remain in a TypeScript UI host. Content mutation should go through the native note transaction boundary so it survives UI reloads and can address unopened notes.

```text
AI page -----------\
AI side panel ------> Agent Client Service ---> Phoenix Agent Runtime
Editor toolbar ----/        |                        |
                             | ordered events         +-- Run/event store
                             | approvals              +-- Model adapters
                             | diffs/receipts         +-- Capability registry
                             v                        +-- Policy engine
                       UI projections                 +-- Context/research engine
                                                      +-- Note workspace/VFS
                                                      +-- App command bus
                                                      +-- Phoenix store/search/graph/index APIs
```

### 1. One run envelope

Every invocation creates or continues the same `AgentRun` contract, regardless of surface:

```text
AgentRun
  id, session_id, parent_run_id
  initiator_surface
  output_target
  strategy
  capability_profile
  provider/model configuration
  scope snapshot
  budgets and deadline policy
  status and current step
  context checkpoint
  transaction/checkpoint IDs
  created/updated/completed timestamps
```

Recommended durable states:

```text
created -> preparing -> model_running -> tool_running
        -> waiting_permission -> model_running
        -> waiting_user -> model_running
        -> compacting -> model_running
        -> committing -> verifying -> completed
        -> interrupted | cancelled | failed
```

`interrupted` means recoverable after process/UI loss. `failed` means the run reached a terminal error with a durable failure receipt. `cancelled` must stop model transport, tool work, and uncommitted transactions.

Each transition appends an event with a per-run sequence number. Polling may exist for compatibility, but the primary UI path should subscribe to ordered events.

### 2. Keep mode dimensions orthogonal

Do not replace the current boolean collection with a larger boolean collection. Define three independent choices:

| Dimension | Values | Meaning |
|---|---|---|
| Output target | `chat`, `active_note`, `new_note`, `named_note` | Where the final authored result belongs |
| Strategy | `direct`, `agent`, `deep_research` | How much iterative work the runtime performs |
| Capability profile | `read_only`, `propose`, `act_scoped`, `autonomous_sandbox` | What actions may execute and under which policy |

Examples:

- Normal AI chat: `chat + direct + read_only`.
- Indexed question: `chat + agent + read_only`.
- Canvas rewrite: `active_note + agent + propose`.
- Trusted note drafting: `active_note + agent + act_scoped`.
- Research report: `new_note + deep_research + propose`.

Plan versus act is a capability/policy profile, not a separate chat implementation. Canvas is a note output target, not merely a tab.

### 3. Note workspace as a virtual filesystem

Define a canonical note URI and revision contract:

```text
note://<narrative-id>/<note-id>
note://<narrative-id>/<folder-id>/<note-id>#block=<block-id>
```

Required operations:

- list and stat notes/folders;
- read full note, block, line, or character range;
- search within one note or scope;
- create/open/rename/move notes;
- stage exact edits or structured block edits;
- diff staged state against the base revision;
- checkpoint before the first mutation;
- atomically commit one or more notes;
- abort and restore the checkpoint;
- refresh the active editor projection after commit;
- emit index/embedding invalidation and completion receipts.

Every write takes `expected_revision`. Every successful commit returns a new durable revision, content hash, changed ranges/blocks, checkpoint ID, affected projection IDs, and timing.

The editor adapter should translate durable note patches into ProseMirror updates when that note is open. It must not be the only place where a note can be changed.

### 4. Bash-like app command environment

Expose one model-facing `app_exec` tool backed by a typed parser and command registry. It should feel shell-like but must not evaluate through PowerShell, Bash, or `cmd.exe`.

Example command vocabulary:

```text
phx pwd
phx app status
phx app open note://nar/note-1
phx app select --from 120 --to 240

phx note ls note://nar/folder-1
phx note stat note://nar/note-1
phx note cat note://nar/note-1 --block block-7
phx note grep "harbor" --scope narrative:nar
phx note patch note://nar/note-1 --expected-rev 42 --patch artifact://patch-9
phx note diff tx://run-8
phx note commit tx://run-8
phx note abort tx://run-8

phx index status --scope narrative:nar
phx index ensure note://nar/note-1
phx embed ensure --scope narrative:nar
phx search lexical "Ryan harbor" --scope narrative:nar --limit 10
phx search semantic "who waited by the water" --scope narrative:nar --limit 10
phx graph neighbors entity://ryan --depth 2 --asserted-only
phx graph path entity://ryan entity://new-rome --asserted-only

phx research search "query"
phx research fetch https://example.org/source
phx research claims artifact://source-12
phx run status
phx run cancel
```

The parser produces typed `argv`, validates schemas, resolves scopes, asks the policy engine, executes one registered handler, and returns a structured result. Pipes can be added later only as typed artifact flow, not arbitrary shell text. For example, a search result artifact may feed a claim extractor without copying its full body into model context.

Raw `storeCommand`, arbitrary relation writes, candidate graph promotion, destructive persistence commands, and OS shell access must not be model-facing commands.

### 5. Capability registry

Each command/tool descriptor must declare:

```text
name and version
description and JSON schema
resource kinds touched
read | propose | mutate | destructive class
scope resolver
default policy
idempotency behavior
timeout and output budget
whether cancellation is supported
receipt schema
renderer hints
```

The runtime should discover core Phoenix capabilities statically and allow plugins/connectors to register additional capabilities through the same interface. Tool visibility is computed per run; the model should never see tools that policy will always deny.

### 6. Policy engine

Replace `mutationPolicy` as an informational string with evaluated policy.

Minimum decision vocabulary:

- `allow`: execute immediately;
- `ask`: create a permission request with preview and resource patterns;
- `deny`: hide or reject the capability;
- `sandbox`: execute only in an isolated workspace/transaction.

Decision inputs:

- capability and action class;
- exact command arguments;
- note/folder/narrative scope;
- active versus external note;
- destructive or truth-promoting behavior;
- run capability profile;
- temporary user grants (`once`, `for_run`, `for_pattern`);
- credential/network sensitivity;
- repeated-call/doom-loop guard;
- current transaction/checkpoint state.

Safe default profile:

| Action | Default |
|---|---|
| Scoped note/app/status reads | Allow |
| Lexical/semantic/asserted-graph reads | Allow |
| Index/embed ensure for already-scoped content | Allow with resource budget |
| Web search/fetch | Ask once per run or configured allow |
| Stage note patch | Allow in transaction |
| Commit note changes | Ask |
| Create a new research note | Ask or scoped allow |
| Delete/move/overwrite notes | Ask, with checkpoint |
| Asserted graph mutation/promotion | Deny to normal agents |
| Candidate semantic relation creation | Proposal-only |
| Persistence cleanup/reset | Deny |
| Raw OS shell | Deny unless separately sandboxed |

This preserves the existing contract that semantic relations remain candidate-only unless an explicit promotion step exists.

### 7. Tool result, artifact, and receipt contract

Every tool result should be small, typed, and durable:

```text
ToolResult
  run_id, step_id, call_id, sequence
  capability, status
  summary
  inline_payload
  artifact_refs[]
  policy_decision_id
  mutation_receipt_id
  stdout/stderr refs when applicable
  truncated, total_bytes
  latency_ms
  started_at, completed_at
```

Large note bodies, search results, web pages, graph neighborhoods, model traces, and command logs become artifacts. The model receives a bounded summary plus artifact handles and can read precise slices later. This applies Pi's output-budget lesson to Phoenix's existing workspace artifact concept.

Every run still receives a durable receipt, including cancelled, interrupted, degraded, and failed runs.

### 8. Deep research engine

Deep research is a strategy implemented by the same runtime, not a separate chat app.

Required loop:

```text
goal and scope
  -> research plan and explicit questions
  -> parallel/batched discovery queries where safe
  -> source fetch and immutable source artifacts
  -> claim extraction with source spans
  -> Phoenix note/index/graph retrieval
  -> evidence comparison and contradiction tracking
  -> gap analysis
  -> repeat within time/query/token/source budgets
  -> synthesis draft
  -> citation and claim-support verification
  -> note transaction or chat answer
  -> completion receipt
```

Required research records:

- query ledger: query, provider, time, result count, selected result IDs;
- source artifact: URL/document/note ID, title, retrieved time, content hash, relevant spans;
- claim: normalized statement, supporting and contradicting evidence refs, confidence/status;
- citation: target note range/block, source ref, source span, verification state;
- gap: unanswered question and stop reason;
- research budget: elapsed time, model tokens, fetches, bytes, sources, iterations;
- synthesis receipt: included/excluded claims and citation coverage.

The final note must distinguish web sources, user notes, graph-derived context, and model inference. Candidate semantic graph relations stay candidate-only; research never silently commits model-derived relations into asserted graph truth.

### 9. Context manager

The current ten-message history and four-round planner are not sufficient. The harness needs:

- durable full event history;
- a model-context projection separate from stored history;
- automatic compaction with a structured summary;
- pinned artifacts that survive compaction;
- explicit active goal, decisions, open questions, changed notes, pending permissions, and verification state;
- retrieval of old event/artifact slices by ID;
- model-specific token accounting and reserve budgets;
- duplicate and low-value context suppression.

Compaction must never discard transaction state, checkpoint IDs, policy grants, unresolved approvals, cited source spans, or the active definition of done.

### 10. Provider adapter protocol

Model providers should implement one event vocabulary:

```text
model.requested
model.reasoning.delta
model.output.delta
model.tool_calls
model.usage
model.completed
model.failed
```

Adapters normalize model IDs, reasoning controls, structured tool calls, usage, errors, cancellation, and retry semantics. The run must behave the same in the page and panel for the same provider/capability profile.

If a provider must remain hosted in TypeScript, the native runtime should issue a durable `model.requested` work item and accept correlated provider events. The Angular component must not be the work owner.

### 11. UI contract

Preserve the existing chat visual language, but make all surfaces projections of the same run:

- AI page: full task history, research artifacts, run controls, and optional note split view;
- side panel: compact run trace, approvals, current step, and quick commands;
- Canvas: note is primary; the panel becomes an agent inspector with diff/approve/cancel, not a second output canvas;
- toolbar: creates a prefilled harness run against the current selection; it never streams directly into the document outside the run/transaction protocol;
- reopening the same run in another surface shows identical messages, steps, permissions, and output target;
- closing a surface does not cancel a run unless the user explicitly chooses cancel;
- attention states are visible when a run needs permission, input, or conflict resolution.

## Gap matrix

| Priority | Gap | Current evidence | Required contract |
|---|---|---|---|
| P0 | Three execution paths | Page direct stream; panel durable run; toolbar direct edit | One client/runtime protocol |
| P0 | Note is not a transactional workspace | Immediate editor mutation; inert rollback token | Note VFS, checkpoint, staged diff, atomic commit/abort |
| P0 | Policy enum is not enforced | `mutationPolicy` has no runtime consumers | Capability/resource-aware `allow/ask/deny/sandbox` |
| P0 | Component owns active loop | Side panel polling and provider streaming | Runtime-owned durable work and ordered events |
| P0 | No governed app command bus | Many raw services/store commands | Typed `app_exec` registry with schemas and receipts |
| P0 | Mixed Phoenix authorities | Desktop mixes `rust/phoenix` and `rust-native/phoenix` | One authority or generated compatibility boundary |
| P1 | No deep research | No web tools, claims, citations, or gap loop | Bounded research engine and evidence ledger |
| P1 | Weak context lifecycle | Ten-message page history; no harness compaction | Full history plus compacted context projection |
| P1 | Provider-dependent capability | Planner requires OpenRouter in side panel | Provider-neutral run/tool protocol |
| P1 | UI-hosted note tools | Active editor required for most mutations | Native note store transaction; TS only for presentation |
| P1 | Inadequate recovery | Planner session cache and TS host state are transient | Resume from durable step/tool/transaction state |
| P1 | Missing parity and safety tests | Key planner tests legacy-feature-gated; no Angular host specs | Contract, restart, conflict, rollback, and parity suites |
| P2 | Canvas layout harms output surface | Side panel can squeeze note severely | Note-first responsive workspace |
| P2 | Stale naming/contracts | “Go” names remain around Rust runtime | Provider/runtime-neutral naming during migration |

## Definition of done

### A. One system across every surface

- [ ] The full AI page, side panel Chat, side panel Canvas, and toolbar submit through one `AgentClient` API.
- [ ] The same prompt, scope, provider, and capability profile produce the same run events and available tools from every surface.
- [ ] A run started in one surface can be opened and controlled in another without losing state.
- [ ] No Angular component contains a provider/tool polling loop or directly mutates note content from model tokens.
- [ ] Closing/reloading a UI surface leaves the run resumable.

### B. Note-as-file workspace

- [ ] Every note has a canonical URI and durable monotonic revision.
- [ ] The agent can list, stat, read, search, create, rename, move, and patch notes without requiring them to be open in the editor.
- [ ] Edits are staged against `expected_revision` and previewed as a structured diff.
- [ ] One run can atomically commit changes to multiple notes or abort all of them.
- [ ] A checkpoint exists before the first mutation and can restore the exact prior note state.
- [ ] Conflict detection stops commit when the user edits a touched note after the agent's base revision.
- [ ] Editor state refreshes from the committed store without cursor corruption or duplicate save races.
- [ ] Index, embedding, and graph projections receive explicit invalidation/completion receipts after note commits.

### C. App command harness

- [ ] `app_exec` uses a typed parser and registry, never a system shell evaluator.
- [ ] Commands exist for app status/navigation, note workspace, lexical/semantic search, asserted graph reads, index/embed ensure, research, artifacts, and run control.
- [ ] Each command declares schema, action class, scope, policy, timeout, cancellation, output budget, and receipt type.
- [ ] Raw store/relation commands and asserted graph mutation are unavailable to normal model profiles.
- [ ] Large outputs are truncated in context and retained as slice-readable artifacts.
- [ ] Repeated identical failing calls trigger a loop guard and a visible recovery event.

### D. Policy and safety

- [ ] Every tool call has a durable policy decision.
- [ ] `allow`, `ask`, `deny`, and `sandbox` are enforced in the runtime.
- [ ] Approvals support once, for-run, and constrained pattern grants.
- [ ] Rejection returns a structured result to the model and does not strand the run.
- [ ] Destructive note operations require checkpoint plus approval.
- [ ] Sensitive credentials never enter model context, event payloads, or exported run logs.
- [ ] Web/network access is independently governable.
- [ ] Candidate semantic relations cannot leak into asserted graph truth without explicit promotion authority.

### E. Durable agent lifecycle

- [ ] Run and step events use monotonic per-run sequence numbers.
- [ ] Model requests, tool calls, permissions, artifacts, transactions, and receipts survive app restart.
- [ ] Cancel aborts provider streaming, cancellable tools, and uncommitted note transactions.
- [ ] Interrupted runs resume from the last durable boundary without repeating committed mutations.
- [ ] Tool calls use stable idempotency keys.
- [ ] Every terminal state emits one durable final receipt with status, work summary, mutations, verification, usage, timing, and errors.

### F. Deep research

- [ ] Research supports web discovery/fetch plus Phoenix note, index, embedding, and asserted graph retrieval.
- [ ] Every source has immutable provenance, access time, content hash, and relevant spans.
- [ ] Every synthesized factual claim links to support, contradiction, or an explicit inference marker.
- [ ] The loop performs gap analysis and stops on a declared budget or evidence-sufficiency rule.
- [ ] Final note citations resolve to retained source artifacts and pass a citation verification step.
- [ ] The report distinguishes external sources, user-authored notes, asserted graph facts, candidate relations, and model inference.
- [ ] Research can target chat, an active note, a named note, or a new note through the same run protocol.

### G. Context and model support

- [ ] Full durable history is separate from the bounded model-context projection.
- [ ] Automatic compaction preserves active goal, decisions, open questions, transaction state, grants, citations, and definition of done.
- [ ] Pinned artifacts survive compaction and are addressable by ID and slice.
- [ ] Provider adapters normalize tool calls, streaming, reasoning, usage, cancellation, retry, and errors.
- [ ] Planner/agent capability does not depend on also configuring a specific final-answer provider.

### H. Observability and performance

- [ ] The UI shows current phase, active tool, elapsed time, permissions needed, budgets, and output target.
- [ ] Every model/tool/index/embed/research/commit step records latency and byte/token counts.
- [ ] Long-running work publishes heartbeats or progress without polling component internals.
- [ ] Tool result inline payloads stay below a documented byte/token budget; full data is artifact-backed.
- [ ] `Shortrun B` is a reproducible smoke fixture for selection rewrite, note drafting, search, and research-to-note flows.
- [ ] Performance tests report p50/p95 time to first event, first model token, read tool result, staged diff, commit receipt, and cancellation quiescence.
- [ ] Memory tests cover long note reads, large search results, and 100+ step runs without unbounded UI or context growth.

### I. Verification suite

- [ ] Unit tests: parser, tool schemas, policy matcher, revision conflicts, patch application, rollback, truncation, context compaction, citations, and loop guard.
- [ ] Native integration tests: run state machine, model-host protocol, note transaction, app restart/resume, cancellation, idempotency, index/embed receipts, and research artifacts.
- [ ] Angular integration tests: page/panel parity, approval UX, note-first Canvas layout, surface handoff, editor refresh, and conflict handling.
- [ ] End-to-end desktop tests: toolbar-to-run, Canvas rewrite approve/reject, multi-note commit/rollback, deep research to new note, crash/relaunch/resume, and disabled/denied capabilities.
- [ ] Relevant planner tests run under the native desktop feature set rather than only the non-default legacy graph feature.
- [ ] No verification step requires touching or rebuilding the active GNN trainer lane.

### J. Migration completion

- [ ] Existing thread/message history remains readable.
- [ ] Existing durable runs are either migrated or clearly marked legacy/read-only.
- [ ] `KammiChatUiService.sendMessage` no longer owns a direct execution path.
- [ ] Toolbar direct streaming edits are removed after parity is proven.
- [ ] Side-panel component orchestration/polling is removed after the runtime event client lands.
- [ ] The old Canvas auto-apply shortcut is removed or expressed as a real scoped policy grant.
- [ ] One Phoenix runtime/type authority is documented and enforced by dependency checks.

## What to preserve, replace, and retire

Preserve and harden:

- Phoenix thread/message/run/event/tool/approval persistence;
- the Tauri/TauRPC boundary;
- scoped note and graph retrieval;
- workspace artifacts as the seed of the artifact store;
- the note editor, existing chat visual shells, and right-sidebar shell;
- active selection/highlight adapter;
- note snapshots as raw material for real checkpoints;
- index, embedding, graph, and store APIs behind governed commands.

Replace behind compatibility adapters:

- component-owned send/orchestration paths;
- `ChatPlannerRunner` as the only loop implementation;
- editor-only note mutation host;
- informational `mutationPolicy`;
- polling-first run updates;
- provider-specific planner gating;
- consumptive one-shot highlighted context as the only selection attachment model.

Retire after migration:

- full-page direct streaming through `KammiChatUiService.sendMessage`;
- toolbar direct model-to-editor streaming;
- rollback tokens with no rollback implementation;
- raw `storeCommand` access as an internal pseudo-tool boundary;
- stale “Go chat/tool host” naming where the runtime is Rust/Phoenix;
- duplicated settings/run logic in the page and 2,226-line side-panel component.

## Recommended delivery sequence

This is not an implementation plan approval; it is the lowest-risk sequence implied by the audit.

### Slice 1: one real Canvas transaction

Goal: prove the note is an agent file and all surfaces use one run.

Flow:

1. Toolbar or Canvas launches a durable run against one selected note range.
2. Runtime reads the note by URI and base revision.
3. Model proposes one replacement through the command registry.
4. Runtime stages a patch and produces a real diff.
5. User approves or rejects.
6. Approval atomically commits through the note store or rejection aborts.
7. Editor refreshes, index invalidation runs, and a durable receipt is shown.
8. The same run can be opened in page or panel with identical state.

Verification: exact before/after content, conflict rejection, rollback, relaunch recovery, page/panel parity, and timing receipt on `Shortrun B`.

### Slice 2: read-only app IDE

Add typed note/app/search/index/graph-read commands with a real policy registry, artifacts, output budgets, ordered events, and context compaction. No asserted graph writes.

### Slice 3: multi-note transactional agent

Add create/rename/move/multi-note patch, atomic commit, checkpoints, conflict UI, cancellation, and trusted scoped grants.

### Slice 4: deep research to note

Add web tools, source/claim/citation ledgers, gap loop, synthesis, citation verification, and note output.

### Slice 5: extensibility and optional sandboxed shell

Add plugin/connector registration, exported headless API, and, only if a concrete use case requires it, an isolated OS-shell capability separate from `phx` app commands.

## Audit answer

Phoenix already has enough parts that this is not a huge rebuild of storage, chat UI, search, graph, or editor technology. It is a substantial rebuild of ownership and contracts:

- move ownership of the agent loop out of Angular components;
- make the note store a transactional agent workspace;
- turn existing app APIs into a governed command environment;
- unify every surface on one durable event protocol;
- add real policy, recovery, compaction, research provenance, and verification.

The first implementation should not begin until the team accepts the P0 boundaries in the gap matrix, especially the authoritative Phoenix source tree, note transaction contract, runtime/UI ownership boundary, and graph mutation restrictions.
