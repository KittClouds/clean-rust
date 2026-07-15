# Atlas Graph Hot Path and Regression Playbook v1

Status: frozen implementation contract

Frozen from: `5f16b875` plus the graph hot-path, manifold-switch, and legacy rich-scan quarantine cut

Performance target: an ordinary graph open or manifold switch completes in **1 second or less** without changing graph truth, layouts, colors, or rendering behavior

## The invariant

The graph is content-addressed state, not a command to rebuild the world.

When the graph receipt is unchanged, Atlas must reuse the already installed scene. An unchanged receipt is expected to cause:

- zero durable rehydration after the snapshot is resident;
- zero inventory reconstruction;
- zero layout or manifold compilation;
- zero scene compilation;
- zero GPU scene installation;
- zero native manifold crossings;
- only a draw when an actual camera or visual-state change requires one.

Optimization must never be purchased by changing exact graph geometry, topology, node colors, node modes, selection behavior, guide geometry, or the authority represented by the receipt.

## The one supported path

The supported path is:

```text
durable graph receipt
  -> GraphRebuildService.loadPersistedSnapshot(scope)
  -> coalesced durable read, only when the receipt is not already resident
  -> graph render identity comparison
  -> graph canvas inventory cache
  -> frozen graph-rebuild embedding atlas
  -> exact manifold projection cache
  -> active lens/filter slice
  -> compiled scene cache or changed-scene worker
  -> compact worker geometry
  -> original entity rebind on the UI thread
  -> exact-sized renderer buffers
  -> one scene install, one upload, one draw
```

The concrete ownership boundaries are:

1. `GraphRebuildService.loadPersistedSnapshot` coalesces concurrent reads of the same scope and retains the resulting snapshot.
2. `graph-render-identity.ts` compares receipt-backed graph authority before signals or component inputs are replaced.
3. `GraphAtlasPreviewComponent` terminates immediately when the incoming receipt identity is already installed.
4. `buildGraphCanvasInventory` converts the persisted Atlas packet into render inventory once per graph authority. Registry color changes explicitly invalidate this cache.
5. `cachedGraphRebuildEmbeddingAtlas` builds the exact embedding source once for the frozen graph.
6. `loadManifoldProjection` derives every manifold from that frozen source. A warm switch must not invoke a native graph or manifold RPC.
7. Lens and filter changes slice the cached inventory; they do not reconstruct the persisted graph.
8. `compileGalaxyScene` or the changed-scene worker compiles only a new scene identity.
9. The worker returns compact geometry rather than cloning full entity payloads. The UI thread rebinds the original immutable entities.
10. The renderer installs exact-sized node, edge, guide, and picking buffers atomically.

## The retired path must remain impossible

The former rich-scan route could enumerate documents and rebuild Atlas outside the certified graph-rebuild pipeline:

```text
UI
  -> AtlasScanCoordinatorService
  -> PhoenixUiApiService.atlasRichScan
  -> PhoenixBackendService
  -> TauRPC bridge
  -> atlas_rich_scan_json
```

Every boundary now fails closed through `atlas-rich-scan-quarantine.ts`. The route must not be re-enabled to fix missing data or a slow graph. The only supported producer is the receipt-bearing `GraphRebuildPipelineService` path.

If a future replacement is necessary, it must be designed as a new content-addressed producer with explicit authority, persistence, identity, and performance certificates. It must not reuse the retired method name or silently fall back to document enumeration.

See `docs/atlas-rich-scan-quarantine-v1.md` for the quarantine contract.

## Performance contract

### User-visible gates

| Operation | Green | Warning | Regression |
| --- | ---: | ---: | ---: |
| Cold open of the current 5,119-target / 987-edge corpus | <= 1,000 ms | 1,001-3,000 ms | > 3,000 ms |
| Warm reopen of an unchanged resident receipt | <= 250 ms | 251-500 ms | > 500 ms |
| Any manifold switch on an unchanged graph | <= 1,000 ms | 1,001-2,000 ms | > 2,000 ms |
| Reapplying the already active graph receipt | zero render work | any measured work | any native/rebuild work |

Anything above five seconds is treated as a wrong-path incident, not normal load variance.

### Frozen component evidence

These are implementation-test measurements, not substitutes for an end-to-end desktop trace:

| Gate | Frozen evidence |
| --- | ---: |
| Build 5,119-target canvas inventory | 301 ms isolated; 415 ms in the broad suite |
| Compile 5,119 nodes plus 987 edges in Siegel mode | 136 ms isolated; 406 ms in the broad suite |
| Compile all five manifold projections for 1,500 targets | 443 ms isolated; about 670 ms in the broad suite |
| Install, pick, and draw a 10,000-node renderer fixture | 26 ms in the verbose renderer gate |
| Changed-scene worker response size | less than 35% of the old full-scene payload |
| Full graph and graph-rebuild suite | 478 passed, 1 skipped, 15.21 seconds |

An end-to-end regression should be decomposed against these stages. Do not guess that layout is slow when the durable snapshot was loaded twice, or blame the GPU when the worker cloned the entire entity graph.

## Expected trace shape

On the first open of a new receipt, the console may contain one pair:

```text
[GraphCollapseTrace] ... persisted_snapshot
[GraphCollapseTrace] ... rendered_inventory
```

The same receipt must not emit a second pair because a parent and child both requested the graph, because Angular replaced an equal object, or because a concurrent consumer missed an in-flight load.

The renderer meter is available in development builds:

```js
window.__PHOENIX_GALAXY_METER__?.snapshot()
```

Read the meter by stage, especially:

- scene compile time;
- scene conversion time;
- renderer `setScene` time;
- draw time;
- compiler source and cache result;
- node, edge, guide, and buffer counts.

The trace is evidence. A generic elapsed time shown in the UI is not enough to select a repair.

## Regression audit order

Stop at the first boundary that violates its invariant. Repair that boundary and rerun the same receipt before moving downstream.

### 1. Duplicate `persisted_snapshot` or `rendered_inventory`

Likely causes:

- parent and child both load the persisted graph;
- equal receipts are represented by new objects and bypass identity termination;
- concurrent durable reads are not coalesced;
- graph scope changes accidentally during open.

Repair:

- restore one owner for graph hydration;
- compare `GraphRenderIdentity`, not object reference;
- keep the in-flight `loadPersistedSnapshot` promise shared per scope;
- prove the second subscriber receives the exact same resolved snapshot object.

Verify with `graph-rebuild-load-coalescing.spec.ts`, `graph-render-identity` tests, and the lens workspace tests.

### 2. Manifold switching crosses 1 second

Likely causes:

- switch code calls a native manifold RPC even though the frozen graph snapshot exists;
- embedding atlas or projection identity includes transient UI state;
- the graph receipt changes on a presentation-only event;
- all modes are rebuilt after every selection or camera change.

Repair:

- route the switch through `loadManifoldProjection`;
- key projections only by graph authority, mode, and layout context;
- preserve the frozen embedding atlas across presentation changes;
- keep the native path only for a genuinely absent graph source.

Verify with `graph-manifold-projection-loader.spec.ts`. The warm path must report zero native calls and preserve exact coordinates.

### 3. Inventory construction is slow or repeats

Likely causes:

- packet-to-entity adaptation moved into a component getter or effect;
- cache identity uses mutable view state;
- registry palette changes are handled by disabling the cache;
- an equal graph snapshot is cloned before inventory lookup.

Repair:

- cache by receipt-backed graph authority;
- keep view state out of the content identity;
- invalidate specifically when registry colors change;
- retain immutable entity references.

Verify with `graph-canvas-inventory.spec.ts`, including the 5,119-target performance fixture and color invalidation.

### 4. Scene compilation or worker transfer dominates

Likely causes:

- scene identity includes hover, camera, or unrelated panel state;
- a worker response carries full entities or graph metadata;
- unchanged scenes bypass the compiled-scene cache;
- entity payloads are cloned rather than rebound.

Repair:

- keep identity limited to graph, projection, and render-affecting settings;
- return only compact geometry from the worker;
- rebind original entities after the worker returns;
- preserve exact operation order in layout and geometry calculations.

Verify with `graph-galaxy-scene-compiler.spec.ts` and the compact worker payload gate.

### 5. Renderer installation or interaction dominates

Likely causes:

- hidden edges still allocate or upload storage;
- focus reuploads positions instead of updating visibility/style state;
- nodes leave the batched render path;
- pointer handling scans every node;
- unchanged guides are rebuilt.

Repair:

- restore exact-sized static edge buffers;
- keep positions immutable during focus;
- batch every node mode while preserving textures, color, size, glow, and selection;
- use indexed picking and hierarchy focus;
- retain guide geometry unless an endpoint changed.

Verify with the renderer performance, picking, hierarchy-focus, edge-buffer, node-mode parity, and guide-retention tests.

### 6. The app is slow but renderer stages are fast

The delay is upstream. Inspect:

- durable receipt lookup and mmap-backed snapshot loading;
- repeated JSON parsing or structured cloning;
- graph receipt churn;
- duplicate Angular effects;
- a legacy rich-scan rejection being caught and retried;
- a background producer blocking the UI thread.

Do not tune shaders or layouts until the first slow upstream stage is named.

### 7. Visual or topology parity changes

Stop the optimization. Treat any missing node, edge, guide, label, color, selection state, or coordinate change as a correctness failure.

Restore parity first. Never downsample graph truth, approximate a certified layout, hide edges to meet timing, or weaken authority identity.

## Symptom-to-fix table

| Symptom | First boundary to inspect | Correct repair |
| --- | --- | --- |
| Two identical collapse-trace pairs | Graph hydration ownership | Identity termination plus in-flight load coalescing |
| Manifold switch invokes native code | Projection loader | Reuse frozen embedding atlas and cached exact projection |
| Colors remain stale | Inventory invalidation | Invalidate on registry color authority only |
| Selection recompiles the graph | Scene identity | Remove presentation-only state from compile identity |
| Worker time rises with entity metadata | Worker payload | Transfer compact geometry and rebind entities |
| Focus causes position uploads | Renderer focus path | Update focus buffers/state without position upload |
| Hidden edges consume buffers | Edge builder | Allocate exact visible edge capacity |
| Pointer latency grows linearly | Picking | Restore spatial/indexed picking |
| Five-second open with fast renderer meter | Snapshot/Angular path | Find duplicate hydration, parse, clone, or legacy retry |
| Missing graph data tempts rich scan | Producer authority | Fix the certified graph-rebuild producer; keep rich scan quarantined |

## Verification commands

Run the narrowest failing gate first, then the broad contract:

```powershell
npx vitest run src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-canvas-inventory.spec.ts --reporter=verbose
npx vitest run src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-manifold-projection-loader.spec.ts --reporter=verbose
npx vitest run src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-scene-compiler.spec.ts --reporter=verbose
npx vitest run src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/three-galaxy-renderer.spec.ts --reporter=verbose
npm test -- --run src/app/components/blueprint-hub/tabs/graph-tab src/app/graph-rebuild
```

Verify the quarantine separately:

```powershell
npm test -- --run src/app/services/atlas-scan-coordinator.service.spec.ts src/app/services/atlas-capability-runtime.service.spec.ts src/app/services/phoenix-backend.service.spec.ts src/app/components/search-panel/atlas-command-status.model.spec.ts
```

Then run the production gate:

```powershell
npm run build
```

Rust and desktop compilation must use the dedicated target drive:

```powershell
cargo check --manifest-path src-tauri/Cargo.toml --target-dir D:\phoenix-target-overgraph
```

Execution and artifact installation remain on the C: workspace. Do not install build outputs from the target drive as application truth.

## Freeze checklist

Before accepting a graph performance change:

- exact node, edge, guide, coordinate, color, texture, selection, and topology parity passes;
- same receipt performs zero render work;
- a cold current-corpus open is at or below one second;
- every warm manifold switch is at or below one second with zero native calls;
- the first load emits at most one snapshot/inventory trace pair;
- worker transfer remains compact;
- renderer buffers are exact-sized;
- broad graph tests and the production build pass;
- the retired rich-scan path still fails closed at every boundary;
- the measured stage certificate is preserved with the change.

The repair philosophy is simple: a multi-second graph interaction means Phoenix crossed the wrong boundary or repeated certified work. Find that boundary, restore identity and reuse, and keep the graph exact.
