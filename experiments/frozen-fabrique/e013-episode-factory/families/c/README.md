# E013-C family bank

Status: construction material in progress under sealed `E013-TRUST-SIGNAL-DEVELOPMENT-v0.2` (protocol SHA-256 `840be748b8aed6b9b642c3c622f079a61c847c61d0e5c9842b04a2a229aa6bdc`). This is a new C-family identity; no task bank is sealed and no observer contact is authorized.

## Scope

E013-C contains four authored Rust repository templates and eight algorithm-centered task families per repository. Each repository/family cell has 16 task instances (512 total); exactly one task in each cell has no valid offered candidate (32 total). Candidate patches are Rust source diffs that must apply cleanly, compile, and be replayable from a reset template. No E013 observer, T1-T5 scoring, or GPU is part of construction.

The eight families are intentionally orthogonal to E013-D's cross-cutting reliability concerns:

| Family ID | Archetype | Core behavior under variation |
| --- | --- | --- |
| `c.token-cursor` | Incremental UTF-8 token cursor | Chunk boundaries, multibyte scalars, cursor advancement, and token spans |
| `c.interval-index` | Interval/segment index | Overlap, containment, adjacency, and query-boundary behavior |
| `c.graph-witness` | Graph witness paths | Reachability witnesses, path choice, and compact predecessor reconstruction |
| `c.delta-codec` | Delta codec | Round-trip encoding, reset points, signed deltas, and malformed streams |
| `c.parser-precedence` | Parser combinator precedence | Ambiguous prefixes, associativity, and nested grouping |
| `c.window-fold` | Streaming window fold | Sliding/rolling aggregation, expiration, and partial windows |
| `c.binary-frame` | Byte-slice binary framing | Header/payload slicing, tagged fields, and exact frame boundaries |
| `c.dependency-eval` | Memoized dependency evaluation | DAG scheduling, memo reuse, and invalidation scope |

## Identity and generation rules

- Repository and family IDs use the `e013-c/` namespace and must be disjoint from E013-D at the ID, source-tree, task, fixture, candidate, and seed levels.
- Repository snapshot commit and tree identities are injected by the core after materialization. No commit SHA is fabricated here.
- Each cell contains 16 tasks, with its empty-valid-set slot selected by a private deterministic bank seed. The slot and its ordinal are hidden from the observer projection. Task IDs and display order are independently permuted; candidate order uses its own seed and cannot encode correctness.
- Non-empty tasks offer multiple semantically distinct valid patches plus plausible compiling distractors. The empty-valid task still offers legal, compiling patches, each of which misses at least one hidden behavioral condition. Candidate identity and patch shape do not reveal adjudication labels.
- Every task has distinct visible and hidden fixture roots. Hidden fixture bytes, expected outputs, labels, valid-set size, and slot selection are construction-only and never appear in observer-facing fields.
- Sibling tasks are generated as truth-changing pairs when the cell's behavior variants permit it. Their IDs are opaque and the relationship is construction metadata only.
- Public benchmark material informs schema and verifier design only. No released evaluation row, gold patch, or protected fixture is imported.

## Replay and validation

The family plug-in implements the core `EpisodeFamily` API. Core replay must reset the bound template before applying each candidate, then record patch-apply, compile, visible-screen, and hidden-completion outcomes separately. Tests should exercise deterministic output under equal seeds, seed separation across cells, candidate-order independence from correctness, hidden/visible byte disjointness, and the exact 4 × 8 × 16 / 32-empty distribution.

Construction readiness is pending until the core's repository catalog is frozen, all candidate patches replay, the leakage audit passes, and the final bank is sealed. Readiness never authorizes model contact.
