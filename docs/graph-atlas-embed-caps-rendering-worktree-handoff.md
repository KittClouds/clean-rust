# Graph Atlas Embed Caps And Rendering Handoff

Date: 2026-06-18
Branch: `codex/calendar-temporal-registry-bridge`

This document records the work currently in the tree before pushing the branch.
The work is one continuous Graph Atlas pass: fix Embed/CAPS hierarchy semantics,
remove noisy sentence/paragraph targets from Embed views, and make the high-count
B-glass sphere renderer fast enough without giving up the visual contract.

## Scope

Touched areas:

- `graph-rebuild-embedding-atlas.ts`
- `graph-atlas-taxonomy-audit.ts`
- `graph-galaxy-hierarchy-caps.ts`
- `graph-galaxy-lorentz-layout.ts`
- `graph-galaxy-engine.ts`
- `graph-galaxy-objects.ts`
- `three-galaxy-renderer.ts`
- related specs for embedding atlas, hierarchy contract, object rendering, and renderer behavior

## Embed Target Curation

The Embed atlas now excludes sentence and paragraph targets more aggressively.
The exclusion covers not only display kind and document-unit profile text, but
also `styleKey` and `stateContextKind` values such as `sentence` and `paragraph`.

Why:

- Sentence and paragraph points were flooding Embed spaces.
- They were especially visible in Hybrid and Siegel as large pink/flat bands.
- The intended Embed contract keeps useful document structure, chunks, evidence,
  entities, facts, state, and context, but does not render every sentence and
  paragraph as first-class manifold targets.

Implementation notes:

- Shared sentence/paragraph taxonomy tokens were added.
- `isSentenceOrParagraphTarget(...)` checks taxonomy-style fields directly.
- The taxonomy audit now reports sentence/paragraph style-key exclusions.
- Specs cover styled sentence/paragraph exclusions and audit accounting.

## CAPS Hierarchy Contract

Embed CAPS hierarchy now follows the intended containment order:

1. document / note
2. document roots
3. chunks
4. evidence
5. entity
6. event
7. fact
8. memory/state/context

Why:

- Embed CAPS had drifted from the Graph tab hierarchy.
- Roots, chunks, evidence, entities, state, and context were not consistently
  nested in the same containment language.
- Some nodes collapsed into broad caps or appeared outside the expected shell.

Implementation notes:

- `HIERARCHY_SHELL_BANDS` and shell order are exported from
  `graph-galaxy-hierarchy-caps.ts`.
- Explicit `capsHierarchyRole` metadata is honored before heuristic text
  classification.
- `graph-rebuild-embedding-atlas.ts` synthesizes Lorentz/CAPS metadata even when
  post-process vectors are missing.
- Entity caps are nested under evidence caps when note/chunk support exists.
- Event, fact, and memory caps derive parent caps from entity/evidence/chunk
  containment instead of flattening.
- `graph-galaxy-lorentz-layout.ts` uses the shared hierarchy shell bands for
  guide shells and contract radii.
- Dense children are distributed around their hierarchy shell in Embed Caps
  instead of stacking into a tight clump.
- `graph-galaxy-engine.ts` skips relation control-plan expansion for embedding
  source mode so Embed node counts are not silently altered by graph-mode
  scaffolding.

## CAPS Count And Layout Fixes

The Embed CAPS view is protected against silently losing nodes from the scene.

Tests now assert:

- every graph rebuild embedding target becomes a scene point in Embed Caps
  unless explicitly excluded by the curated contract,
- dense graph-fact children stay on their shell and spread around the ring,
- explicit caps produce nested root-lane guides,
- missing vector/postprocess metadata still produces a usable hierarchy,
- guide shell radii match the shared shell contract.

## B-Glass Sphere Performance

The sphere + B-glass renderer was converted from per-node mesh/material work to
batched GPU-friendly paths.

What changed:

- B-glass sphere nodes use four focus-state `InstancedMesh` batches:
  `dimmed`, `normal`, `neighbor`, and `active`.
- Instance transforms and instance colors are updated in-place.
- Glows use a single `Points` shader layer rather than one sprite material per
  node.
- Hover and selection now use `applyFocusState()` instead of rebuilding the
  whole layout.
- Edge hover/focus updates rewrite edge colors without rewriting edge positions.
- Labels rebuild only when the selected/hovered label set actually changes.
- Large glass scenes skip the expensive fallback raycast against thousands of
  meshes and rely on screen-space picking.

Why:

- The B-glass sphere view became sluggish above roughly 3k nodes.
- The hot path was draw-call/material churn, glow sprite/material count, label
  rebuilding, edge geometry rebuilding, and high-count raycasting.

## B-Glass Visual Contract

The first batching pass made nodes too clear, then too milky/black. The final
path keeps the batching but moves the look into a named shader:
`BGlassInstancedMarble`.

Current shader intent:

- glassy colored marble,
- per-instance color,
- sharper rim and specular highlight,
- subtle internal vein variation,
- more solid alpha floor,
- no bloom contribution.

The glow batch shader is named `GalaxyGlowBatch`. It intentionally does not set
`vertexColors: true`, because the shader declares its own `color` attribute.
That avoids Three.js injecting a duplicate color attribute and producing shader
compile errors.

## Tests Added Or Updated

Important test coverage now includes:

- styled sentence/paragraph Embed exclusions,
- taxonomy audit exclusion reporting,
- generated CAPS hierarchy metadata and parent caps,
- cross-note entity support caps,
- dense Embed Caps child distribution,
- shell guide radii from the shared hierarchy contract,
- B-glass shader instance batching,
- no-bloom marble shader contract,
- glow batch shader compile guard,
- hover/selection focus refresh path.

## Verification

Commands run successfully during this pass:

```powershell
npm test -- --run src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-objects.spec.ts src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-product-renderer.spec.ts
npm run build
```

The focused renderer/object suite passed: 25 tests.

`npm run build` passed. The existing Angular initial bundle budget warning
remains: the initial bundle is about `6.04 MB`, roughly `36 kB` over the
configured `6.00 MB` budget.

## Known Caveats

- `gh` was not available in this shell, so publishing is handled with native
  `git commit` and `git push`, not the GitHub CLI PR helper.
- A plain localhost browser smoke cannot fully verify the Graph canvas because
  the Phoenix WASM path has been removed and the app expects the Tauri native
  backend for real graph data.
- The current B-glass marble design is functional, fast, and sharper than the
  first batch pass, but it remains a visual tuning surface for future design
  polish.

