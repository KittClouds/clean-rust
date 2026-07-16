# Atlas Rich Scan Quarantine v1

Status: active and fail closed.

## Reason

The retired `atlas_rich_scan_json` route advertised `dirty-only` execution but treated every supplied
document as dirty. It could rebuild dynamic NER, evidence rows, embeddings, and candidate edges for
an unchanged global corpus outside the content-addressed graph-run pipeline.

## Safety boundary

- Graph canvas and Search Panel do not inject or call the retired coordinator.
- Atlas capability recipes that depend on the route report `blocked` and are not runnable.
- The compatibility coordinator owns no runtime, model, database, or graph dependencies and throws
  the stable quarantine error on every call.
- `PhoenixUiApiService`, `PhoenixBackendService`, and the TauRPC bridge independently reject calls.
- The desktop RPC returns an error without parsing the payload, locking runtime state, or invoking
  `PhoenixRuntime::atlas_rich_scan`.

The supported graph path remains `GraphRebuildPipelineService`, including whole-run input identity,
resident native lease validation, immutable section persistence, and unchanged-run termination.

## Reactivation gate

The retired route must not be reconnected. Any replacement requires a separately reviewed design
with durable content-addressed manifests, restart-safe unchanged termination before model work,
exact parity tests, and a performance certificate at least as strict as the graph-run gate.
