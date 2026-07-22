# Phoenix Native Decision Surface Audit v1

Date: 2026-07-14
Mode: audit-only
Dataset implementation: not started
Model implementation: not started

## Verdict

No Phoenix-native research task currently passes the launch gate.

The preferred first task remains **Canonical Episode Assignment**, but it is not yet safe to open. Phoenix has strong *types* for proposal receipts, authoritative graph commits, evidence references, temporal availability, and revision lineage. The live desktop corpus does not currently populate those research-authority surfaces, and the episode/story-continuity lane is explicitly candidate-only.

The first missing boundary is not model capability. It is an append-only, time-indexed decision authority that can reconstruct the exact pre-decision state and candidate set.

## Audit method

The live desktop store was not opened by a second database process. Its active WAL was exclusively held by the running app.

The audit used two separately verified copies because the desktop links two store authorities:

- the primary runtime row store from `rust/phoenix`;
- the newer graph research/durability store from `rust-native/phoenix`.

For each copy:

1. All unlocked source files were hashed before and after the copy.
2. Copied unlocked files matched byte-for-byte.
3. The live WAL remained exactly eight bytes for the entire copy.
4. The eight-byte copy WAL was reconstructed from Overgraph 0.4.1's authoritative empty header: `OVGR` plus little-endian version `3`.
5. Audit binaries invoked read methods only; no init, append, checkpoint, or mutation method was called.

The physical manifest contains three immutable segments and 8,362 physical node records. Physical records are not treated as live examples because segments include updates and tombstones.

Generated measurement evidence is under `target/decision-surface-audit/` and is intentionally not a committed dataset.

## Live authority counts

### Primary desktop runtime

| Durable surface | Count | Authority interpretation |
| --- | ---: | --- |
| Registry entities | 167 | Current inventory, not historical graph truth |
| Entity cards | 36 | Current presentation records |
| Notes | 2 | Current documents |
| Runtime sessions | 146 | All `active`; all revision `0` |
| Ingest-log rows | 9 | Nine documents total; all `commitRequested=false` |
| Runtime commits | 0 | No authoritative decision labels |
| Evidence-ledger rows | 0 | No accepted/rejected evidence history |
| Scoped graph documents | 0 | No durable graph snapshot, run receipt, or operator journal in this store |

The 146 sessions are activity records, not training decisions. They have no revisions, no terminal dispositions, and no resulting commits.

### New graph research authority

| Durable surface | Count |
| --- | ---: |
| Kernel checkpoint | 0 |
| Kernel journal entries | 0 |
| Live kernel vertices | 0 |
| Asserted kernel edges | 0 |
| Candidate kernel edges | 0 |
| Graph-truth commits | 0 |
| Proposal batch receipts | 0 |
| Proposal observations | 0 |
| Projected outcomes | 0 |
| Latest document archives visible to this authority | 0 |
| Scoped documents visible to this authority | 0 |

The new reader seeing zero does **not** mean the desktop has zero content. The primary runtime reader sees the 167 entities and two notes above. It proves that the current live corpus and the research-authority surface are separate persistence domains even though the desktop links both crates.

The dependency seam is visible in `src-tauri/Cargo.toml`: `phoenix-native` and `phoenix-types` come from `rust/phoenix`, while the graph kernel and graph store come from `rust-native/phoenix`.

## Authority trace

### Current graph state

The app can persist a current graph rebuild snapshot through the `phoenix_graph_rebuild_v1/snapshot` scoped document. The document ID is deterministic for `(namespace, scope, document key)`, and relation upsert replaces the row with that ID.

Content sections use immutable hash-derived document keys. They make unchanged payloads reusable, but the current snapshot manifest still points to only one current composition. Immutable section blobs are therefore not, by themselves, an ordered history of decisions.

Live count: zero scoped graph documents in the audited store.

### Operator decisions

`graph-operator-mutation-journal.ts` retains action kind, previous and requested state, source snapshot identity, source receipt IDs, intent status, canonical commit ID, and timestamps.

Its persistence key is one deterministic `operator-mutation-journal` document per scope. That is a durable current journal, not a proven append-only historical ledger. No such document exists in the audited live store.

Live count: zero durable operator intents and zero durable operator receipts discoverable from the store.

### Episode and continuity decisions

`graph-story-continuity.ts` defines episodes, boundary receipts, temporal candidates, causal candidates, conflicts, review-required rows, and actions such as split, merge, ordering confirmation, causal confirmation, and conflict resolution.

Its contract is explicit:

```text
commitPolicy = candidate_only
noTopologyCommit = true
noTopologyWrites = true
```

The episode projection is therefore a candidate/UI interpretation, not authoritative committed graph history. With no scoped snapshot present, the audited live corpus also provides no durable current episode candidate rows to count.

Live authoritative episode assignments: zero.

### Graph proposals and outcomes

The new graph kernel has the correct vocabulary:

- proposal statuses: generated, reviewed support, reviewed contradiction, deferred, rejected;
- outcome states: uncommitted, active, superseded, retracted, reverted;
- proposal evidence references, source generations, observed timestamps, and immutable batch receipts;
- authoritative commits with operation, predecessor IDs, reversal ID, receipt IDs, source generations, and commit timestamp.

`GraphStageApi::freeze_research_snapshot` already loads a checkpoint, graph-truth commits, and proposal receipts from one store generation. The frozen snapshot contract carries `availableAtMs`, `observedAtMs`, and `labelAvailableAtMs`, and treats `uncommitted` as censored rather than negative.

This is sufficient machinery when populated. The audited live store has zero receipts and zero graph-truth commits, so it supplies no native labels today.

### Temporal reconstruction

The graph-truth lineage can reconstruct active asserted atoms across assert, supersede, retract, and revert operations. It does not reconstruct app-level candidate overlays or episode alternatives that were never committed or appended as receipts.

The primary runtime has nine ingestion timestamps, but every ingest has `commitRequested=false`; there are no corresponding committed graph states. These rows cannot form temporal prediction labels.

## Native task census

Counts below are **usable authoritative examples**, not current entities or possible feature rows.

| Native task | Required historical signal | Usable examples | Gate result |
| --- | --- | ---: | --- |
| Canonical episode assignment | Event, candidate episodes, chosen episode/new episode, timestamp | 0 | Fail: no durable candidate set or authoritative choice |
| Delta adjudication | Proposed delta, disposition, evidence, resulting commit | 0 | Fail: zero receipts, evidence rows, and commits |
| Discrepancy classification | Conflicting assertions, assigned class, resolution | 0 | Fail: candidate continuity conflicts are not committed authority |
| Evidence ranking | Claim, candidate evidence, accepted evidence | 0 | Fail: zero evidence-ledger rows and no durable alternative set |
| Relation completion | Pre-state, later accepted relation, evidence | 0 | Fail: zero proposal outcomes and graph-truth commits |
| Graph repair | Malformed region, candidate corrections, accepted repair | 0 | Fail: no repair proposal/decision ledger exists |
| Temporal prediction | Historical states and subsequent transition | 0 | Fail: ingest timestamps exist, committed state sequence does not |

Action-family and relation-family sufficiency is therefore also zero. No frequency threshold can be evaluated yet.

## Required audit questions

### Can we reconstruct what was knowable then, or only current truth?

Only current app truth and current candidate projections are generally reconstructable. The new graph-truth lane can reconstruct committed lineage and temporally bounded proposal observations, but the live corpus contains none of those records.

Answer: **not for any live native task**.

### Are rejected and deferred proposals durable?

The graph proposal receipt type supports both states. The operator journal supports active, applied, conflicted, and undone intents. Neither surface is populated in the audited store, and the app journal is current-document persistence rather than a proven append-only history.

Answer: **representable, not currently evidenced as durable history**.

### Are candidate alternatives recorded, derivable, or lost?

Graph proposal batch receipts can record multiple observations. Episode continuity can derive alternatives inside a snapshot. There are zero receipt batches and zero scoped snapshots in the audited store. Reconstructing alternatives after the fact would introduce hindsight and hidden-answer bias.

Answer: **currently lost for research purposes**.

### Can the same graph state appear across train and validation?

Yes. Current snapshots and repeated decisions can share an identical pre-state. The existing train-topology derivation prevents edge leakage inside the established link-prediction task, but no Phoenix-native decision split certificate exists.

Required future rule: group by immutable pre-state identity and decision lineage before assigning a split.

### Can document, episode, or entity lineage cross a temporal split?

Yes. Stable entities and documents naturally recur, and future episodes may contain earlier entities or evidence. A timestamp-only row split would leak lineage.

Required future rule: certify document, episode, entity, and evidence overlap; select explicitly which overlaps are allowed by task semantics; block the rest at group level.

### Are labels produced by authoritative commits or inferred afterward?

Graph-truth commit outcomes are authoritative. Episode continuity classes and projections are currently compiler candidates. Operator review signals represent a human preference unless followed by an authoritative commit.

Live authoritative labels: zero.

### Are there enough examples per action and relation family?

No. Every candidate task has zero usable authoritative examples.

### Which signals are genuine outcomes versus operator preference?

| Signal | Class |
| --- | --- |
| Active/superseded/retracted/reverted graph-truth lineage | Genuine authoritative graph outcome |
| Resulting immutable commit and its atoms | Genuine authoritative graph outcome |
| Reviewed support/contradiction | Operator judgment |
| Deferred/rejected proposal without later commit | Operator/process disposition, not world outcome |
| Story-continuity candidate class | Compiler inference |
| Operator journal intent | Operator preference until committed |
| Later evidence or revision | Outcome only when independently timestamped and committed |

## Leakage verdict

The existing frozen research snapshot and train-only topology feature derivation are strong leakage controls for the established link-prediction pipeline. They do not certify a Phoenix-native decision dataset that does not yet have immutable pre-states, candidate groups, and labels.

The following native leakage certificate is still required:

```text
decision observed_at
pre_state_identity
candidate_set_identity
label_available_at
resulting_commit_identity
document overlap
episode overlap
entity overlap
evidence overlap
lineage-group split identity
future-reference rejection count
```

## Exit-gate decision

| Gate | Episode assignment | Result |
| --- | --- | --- |
| Pre-decision state reconstructable | No | Fail |
| Explicit label authority | No committed episode assignment | Fail |
| Future information excludable | No immutable decision-time snapshot | Fail |
| Candidate group includes correct answer | No durable candidate set | Fail |
| Split leakage certifiable | No native decision split identity | Fail |

**Canonical Episode Assignment is preferred but remains locked. No first task is selected.**

## Smallest next authority cut

The next cut should be **Phoenix Native Decision Receipt v1**, not a dataset and not a model.

It should append one immutable receipt at the decision boundary with:

```text
decision_id
task_family
scope and lineage IDs
observed_at
pre_state_snapshot_id
candidate_set_id and ordered candidates
chosen candidate or explicit new/none action
rejected and deferred candidates
operator/compiler authority class
evidence anchors available at decision time
resulting graph-truth commit ID
label_available_at
later outcome/revision links
```

Required design constraints:

1. Bridge the primary runtime corpus into the graph research authority or define one explicit migration boundary. The two readers must not silently claim the same store while seeing different typed universes.
2. Append receipts; never overwrite decision history.
3. Freeze the exact pre-state and candidate set before applying the action.
4. Keep compiler proposals, operator preferences, and authoritative graph outcomes as distinct label classes.
5. Backfill nothing unless an existing authoritative timestamped record proves the label. Unknown history remains censored.
6. Add the native leakage certificate before exporting the first dataset row.

After those receipts accumulate, rerun this audit. If episode assignments have sufficient action-family counts and pass all five exit gates, the existing link-ranking workhorse can consume them without opening a model-zoo lane.

## Audit instrumentation

- `rust/phoenix/crates/phoenix-store-overgraph/src/bin/phoenix-runtime-decision-row-audit.rs`
- `rust-native/phoenix/crates/phoenix-api/src/bin/phoenix-native-decision-surface-audit.rs`

Both are read-only audit binaries. Neither creates a dataset, trains a model, writes a checkpoint, or mutates the audited live store.

## Implementation follow-up

Phoenix Native Decision/Outcome Receipt v1 and its first real producer are now
implemented and documented in
[`phoenix-native-decision-outcome-receipt-v1.md`](phoenix-native-decision-outcome-receipt-v1.md).
New Atlas Control operator-review actions append their decision receipt before
the UI mutation and a censored execution observation after durable application.
This changes future capture, not the historical counts above: no operator row,
graph commit, or candidate projection was backfilled. Reward-complete research
rows remain locked until genuine later outcomes are observed.

Canonical Episode Assignment now has its first end-to-end producer. Exact, unambiguous continuity
event memberships can be accepted in Atlas Control; the native runtime freezes the complete episode
candidate group, appends the operator decision and outcome, commits the asserted membership, and
opens the canonical reward horizon. See
[`canonical-episode-assignment-producer-v1.md`](canonical-episode-assignment-producer-v1.md).
This opens future task capture only. The frozen dataset gate still depends on a nonzero live census
and certified chronological/leakage coverage.
