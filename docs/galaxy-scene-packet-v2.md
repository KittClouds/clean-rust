# GalaxyScenePacketV2 Compatibility Port

Status: active current-graph transport boundary with a bounded browser residency authority. Native spatial tile transport is not wired yet. Packed renderer authority is not established yet.

`GalaxyScenePacketV2` replaces the worker-to-main-thread compact JavaScript object graph. The worker still builds the exact established galaxy layout, converts it to the established `GalaxySceneV2`, and then transfers packed binary pages. The main thread verifies the page receipts and rehydrates the same renderer contract.

## Active path

```text
current entities and edges
  -> existing galaxy layout worker
  -> existing GalaxySceneV2 conversion
  -> GalaxyScenePacketV2 pack
  -> transferable ArrayBuffer pages
  -> receipt and hash validation
  -> GalaxySceneV2 compatibility adapter
  -> unchanged ThreeGalaxyRenderer
```

The current compatibility producer still emits `tileId: full` at LOD zero. That tile now enters the same bounded residency manager used by future native tile manifests rather than installing directly into the renderer.

## Deletion gate

Further compatibility deletion is closed while the active renderer port still accepts `GalaxySceneV2`.

The gate opens only when all of these are true:

- The renderer installs a verified V2 manifest and packed resident pages directly.
- The active scene compiler no longer calls `unpackGalaxyScenePacketV2` to materialize a whole renderer scene.
- Renderer ownership, picking, focus, selection, and overlays operate on packed numeric identity and topology pages.
- Labels, external IDs, and cold metadata remain on-demand rather than becoming renderer-facing corpus arrays.
- Hybrid, Hopf, CAPS, Transit, and Siegel pass before/after live golden visual parity with the same graph, viewport, camera reset, render settings, and edge mode.
- The before/after run records one canvas, one WebGL context, nonzero expected node and edge counts, and no browser exceptions for every manifold.
- Focused packet, compiler, canvas, renderer, interaction, and authority tests pass with the production build and unused-code gate.

Until that certificate exists, the compatibility adapter and its `GalaxySceneV2` renderer seam are required code, not dead code.

## Browser residency authority

`GalaxyTsResidencyManager` owns the browser-side tile cache and request lifecycle:

- Frustum and screen-space-error request planning.
- Near-camera coarse coverage before progressive refinement.
- Abortable requests carrying generation tokens.
- Front/back buffers for manifold transitions.
- Incremental GPU install, activation, and eviction ports.
- Device-class byte, node, edge, tile, request, and draw budgets.
- Explicit corpus, resident, visible, drawn, and aggregated counters.

The manager and compatibility bridge are dynamically loaded only when the galaxy surface becomes active, keeping the application bootstrap bundle outside the hard production budget. The existing whole-scene renderer is represented as one compatibility tile; native pages can replace that provider without moving corpus collections into Angular state.

## Manifest contract

The structured-clone envelope contains only:

- Schema, generation, tile, LOD, authority receipt, layout, and source mode.
- Node and edge counts.
- String-slab ranges.
- Page descriptors and content hashes.
- A map of transferable `ArrayBuffer` pages.

It contains no node labels, external IDs, edge IDs, geometry arrays, or base64 payloads.

Every page descriptor repeats its generation, tile, LOD, content hash, and authority receipt. The receiver rejects missing pages, byte-length drift, content drift, ownership drift, authority drift, and manifest-hash drift.

## Page ownership

Shared pages:

- Stable dual-32-bit numeric node identities.
- Stable dual-32-bit numeric edge identities.
- Edge endpoint pairs.
- Exact collision records and member indexes.

Manifold pages:

- Tile-local float32 positions.
- Radii.
- RGBA8 node and edge colors.
- Scalar node and edge flags.
- Edge alpha.
- Optional hierarchy and hybrid coordinate buffers.

Detail pages:

- UTF-8 string offsets and slab bytes.
- Cold scene extras encoded into a transferable UTF-8 slab.

Detail pages are marked `on-demand`. The compatibility adapter currently materializes them immediately because the unchanged renderer still consumes string arrays. A later renderer port may defer them without changing the packet schema.

## Stable identity and collisions

External identities are represented in hot pages by a stable 64-bit numeric key stored as two `u32` words. The current algorithm is dual-seeded FNV-1a 32. External strings remain in the detail slab.

Hash collisions do not change identity. Collision pages record the numeric key and the exact indexes of every distinct external identity sharing it. Duplicate occurrences of the same external identity are not treated as a collision.

## Cross-manifold reuse

The packet generation is the immutable graph authority identity, not the full manifold scene identity. The full scene identity remains the authority receipt.

The main-thread shared-page pool retains one page per shared page role for the active generation. When another manifold returns the same identity or topology page hash, the new scene reuses the retained buffer while accepting new manifold pages. A new graph generation clears the pool.

## Native transport shield

The existing Rust `graph-scene-packet/v1` endpoint remains isolated and unchanged. It uses a JSON TauRPC method and base64 geometry. The generated TauRPC binding also represents `Vec<u8>` as `number[]`, so returning V2 pages through that method would turn binary freight into JSON number arrays.

V2 must not be wired through that surface. A future Rust producer requires a genuine binary IPC or custom-protocol response that delivers `ArrayBuffer` bytes while keeping only the manifest in JSON.

## Verification

- Packed scene round-trip parity for all current renderer arrays and cold scene data.
- RGBA8 color parity for the current integer-derived color contract.
- Page receipt and corruption rejection.
- Exact collision membership.
- Transfer-list ownership detachment.
- Shared-page reuse across manifold receipts.
- Existing 5,119-node and 987-edge one-second compilation gate.
- Full graph-atlas-preview regression suite.
- Production Angular build.
- Live native desktop rendering across Hybrid, Hopf, CAPS, Transit, and Siegel.
