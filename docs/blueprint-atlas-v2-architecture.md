# Blueprint Atlas V2 Architecture

This checkpoint turns Blueprint Hub from a graph dashboard into an inspectable operating room. The goal is not just to show counts, clusters, and manifolds; every visible object should have lineage, evidence, review state, and a reversible path toward durable graph mutation.

## Pipeline Intent

The pipeline is deliberately layered.

1. Sidecar schema
   - Machine-derived document units, regions, rhetorical units, retrieval units, graph fact candidates, evidence spans, confidence records, and lineage are typed sidecar data.
   - Sidecar objects never automatically become user anchors.

2. Chunker lenses
   - Fast adaptive leaf chunks remain the low-latency indexing substrate.
   - Additional lenses model structure, hierarchy, rhetoric, graph-bearing facts, and cross-document packets without pretending there is only one correct chunk.

3. Review and promotion
   - Machine objects are review-stateful: proposed, accepted, rejected, muted, promoted_to_anchor, compiled_to_graph, or ledger_only.
   - Counts in the UI should open the rows underneath them.
   - Review receipts are reversible and do not directly mutate topology.

4. Graph compilation
   - Reviewed or high-confidence sidecar facts compile into entity mentions, relation candidates, hyperedges, evidence-backed edges, structure edges, retrieval overlays, and cross-doc bridges.
   - Durable topology commits require compiler receipts and provenance.
   - Ambiguous facts stay visible instead of silently disappearing.

5. Blueprint Hub UI V2
   - The main operating rooms are Entities, Structure, Facts, Review, Discourse, and Metrics.
   - Rows expose source preview, lineage, detector reason, confidence, graph impact, and actions.

6. Graph canvas interaction
   - The canvas is an inspection surface: nodes, edges, clusters, wormholes, search results, and lens toggles all resolve to source-backed records.
   - Visual styling remains separate from semantic state, but the canvas must expose provenance and review affordances.

7. Evaluation dashboard
   - Chunk health, hierarchy depth, orphan chunks, evidence density, entity-prior noise, review ratios, graph mutation count, retrieval quality, cross-doc bridge quality, and indexing cost are surfaced as health signals.
   - The UI should explain why an indexing run is healthy or suspicious.

8. Document-type adaptation
   - Document profiles change detector weighting, not ontology.
   - Fiction may weight chapter, scene, dialogue, and action higher; research may weight method, result, claim, and evidence higher; technical docs may weight procedure, code_block, constraint, and instruction higher.

## Operator Mutation Journal

Review actions are now recorded as operator intents before they are replayed into review state. This gives the app a path that is distinct from the scanning delta pipeline:

- Core graph rebuild builds the current machine snapshot.
- Operator mutation journal records human intent against source fingerprints.
- Replay applies compatible intents onto fresh snapshots.
- Stale or changed source rows become conflicted instead of being blindly re-applied.
- Compiler receipts remain responsible for topology commits.

The important invariant is:

```text
operator intent -> replayed review state -> compiler diff/receipt -> durable graph commit
```

This keeps user decisions durable without letting arbitrary buttons bypass graph compilation and provenance.

## Verification Contract

This checkpoint was verified with:

- `npm test -- --run src/app/graph-rebuild`
- `npm run build`
- `git diff --check`

The Angular build still reports the existing initial bundle budget warning; it is not a functional failure of this checkpoint.
