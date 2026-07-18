# Phoenix revision impact

Isolated native Rust lane for cross-revision identity, immutable
counterfactual overlays, and dual revision-analysis graph projections.

This crate is deliberately outside the active Phoenix workspace while its root
lockfile and application target are in use. It depends on the authoritative
`phoenix-types` contract by path, writes no graph state, and has its own
dedicated Cargo target:

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-revision-impact-duel'
cargo test --manifest-path `
  'C:\code land\clean-rust\rust-native\phoenix-spikes\phoenix-revision-impact\Cargo.toml'
```

The identity resolver treats offsets as weak supporting evidence only.
Ambiguous candidates remain explicit. The counterfactual view borrows its base
snapshot immutably and records the exact base and sidecar digests used.

Phase 3 projects typed constraints and model-facing inference topology from one
generation. Both views use contiguous CSR storage. The asserted graph-rebuild
adapter admits structural and accepted relations only; candidate and rejected
semantic relations are counted in the projection receipt but never enter the
GFM-facing arrays.

Phase 3.5 joins an explicit revision-requirement sidecar against the existing
generation-stamped temporal, memory, and causal sidecars. It fails closed on
generation skew, candidate truth, missing evidence, invalid intervals, or a
base fact/state that does not satisfy the declared requirement. The seven gold
mutations run through base snapshot, counterfactual overlay, authoritative
adapters, dual projection, and both real model CSR constructors without loading
MPNet or Qwen.

Phase 4 runs deterministic directed Causal Ripple propagation over the
constraint projection. Hard requirements are revalidated against the
counterfactual overlay and remain fully broken at any path depth. Defeasible
and weak support use typed fixed-point decay and can only produce suspicious
results. The engine condenses strongly connected components, deduplicates
shared evidence origins, combines independent support paths, retains bounded
representative paths, and records every traversal or receipt truncation.

Propagation paths use a compact sentinel-encoded arena-backed parent chain and
are materialized only for surviving impact receipts. Common one-signal,
one-contribution, and one-constraint cases remain inline; SCC reverse edges use
contiguous CSR storage. Evidence IDs are deduplicated while receipts are built
so returned vectors do not retain duplicate-path capacity. The
`revision_ripple_perf` binary measures traversal allocations, peak scratch plus
result memory, retained-result memory, and materialized path volume over 50,000
nodes and 99,999 edges.

Phase 5 wraps the authoritative ripple output in a serializable
`RevisionImpactReport`. Each impact carries typed constraint evidence with
document byte ranges and a ten-plane coverage certificate. Explicit local
coverage gaps produce deterministic `Unknown` abstentions; unavailable planes
cannot be promoted into broken or suspicious results. The durable receipt binds
the base and mutation digests, projection coverage, propagation configuration,
paths, classifications, ordering, and report digest. Model overlays are present
in the contract but remain empty and presentation-only at this phase.

The Phase 5 gate compares all seven planted mutation families against keyword
search and an optimistic current continuity-conflict baseline. A separate smoke
test memory-maps `docs/shortrun.md`, locates evidence with SIMD substring search,
validates source byte ranges, and runs the complete read-only detector without
touching graph truth.

Phase 9 adds deterministic repair generation and counterfactual simulation.
Repair templates compile into typed `ProposedEdit` operations; model output is
absent from the generation and validation path. Each candidate receives an
isolated overlay, a fresh authoritative constraint projection, and a complete
Causal Ripple rerun. A candidate is `ProvenFix` only when every claimed source
constraint disappears, coverage is complete, traversal is untruncated, and no
new violation is introduced. Partial, rejected, and unknown outcomes remain
explicit. Rollback candidates are marked separately from mutation-preserving
repairs, author locks fail closed, and every receipt binds the base, candidate,
overlay, and repaired-report digests while proving no truth writes occurred.

The workspace author reviewed and confirmed all seven gold cases on 2026-07-17.
Pre-repair impact labels remain intact because they describe the cracks the
detector must find. The separate author-directive fixture records the required
post-repair story truth, preferred compound template and rejected alternatives.

Phase 9.5 binds statement repairs to exact document byte ranges before they can
claim source validity. Each binding records the evidence, scene, operation,
range and expected span digest. Missing or ambiguous anchors, changed text,
invalid UTF-8 boundaries and overlapping edits fail closed. Shadow rewrites
reuse unchanged documents through shared immutable byte storage, allocate each
changed document once, reconstruct the candidate requirement sidecar and then
run the normal repair simulation. The real `docs/shortrun.md` smoke exercises
this complete source-to-sidecar-to-validator path without writing source truth.

The `revision_repair_review` harness emits an author decision packet plus a JSON
metrics receipt. Confirmed compound templates rank first. They carry a typed
`ApplyAuthorDirective` operation and intentionally return `Unknown` until a
shadow rebuild supplies the new belief, event, capability, travel, relationship
or possession evidence. Existing graph-only candidates remain separately
reported and cannot lend their `ProvenFix` status to an author-directed repair.

Shadow semantic executors now cover the confirmed delayed-reveal,
earlier-death, changed-witness, changed-power-limit, changed-travel,
removed-relationship and changed-possession repairs. Each compiles
its author directive into typed fact, graph-edge, requirement and relevant
sidecar deltas; materializes them in a candidate-only copy-on-write workspace;
and delegates final classification to the existing repair simulator. The power
executor adds a closed capability record that distinguishes an unaided safe
limit of two, a costly third-step overdraw requiring recovery, and an
artifact-assisted safe limit of exactly three. Capability coverage is resolved
only when those typed rules validate. The travel executor preserves the
authoritative eight-hour ordinary route and pursuit pressure while adding a
real portal with fixed endpoints, a consumed activation charge, a bounded
passenger count and a 24-hour cooldown. Location and capability coverage are
resolved only after both typed travel rules validate. Receipts bind the committed base digest,
shadow snapshot, compiled deltas, rebuilt planes, author outcomes and no-write
proof. The review harness persists the full shadow result bundle alongside its
packet and metrics receipt.

The relationship executor preserves that Hazel and Silas were never trusted
confidants. It rebuilds private-channel access as theft, records their public
alliance as a performance hiding mutual distrust, and replaces intimate
betrayal weight with public exposure plus objective sabotage. A typed state
transition records that Hazel's action destroys the alliance's usefulness.

The possession executor keeps the unique chronal key with Hazel, establishes
that Kai knows and trusts this arrangement before the vault, makes Hazel
present and responsible for operating the key, redirects Silas's
possession-based suspicion to Hazel, and certifies duplicate-key claims as a
contradicted rumor rather than unresolved object identity.
