# E013 episode factory construction contract v0.1

Status: construction draft. This is the first E013 contract in this branch. A presumed sealed `v0.2` predecessor was searched for and not found; the user confirmed that it never existed here. No prior E013 seal is claimed.

## Scope and boundary

Build fresh, executable Rust/local-commit action-selection banks from generated task instances. Public benchmarks supply construction ideas only; released evaluation rows, gold patches, and privileged test data are not bank instances. Construction and adjudication are permitted. E013 small/large observer contact, trust-signal scoring, fit, and confirmation opening are closed.

`E013_MODEL_CONTACT_AUTHORIZED=false`

## Bank identities

| Bank | Repository identities | Families per repository | Tasks per cell | Total tasks | Empty-valid-set tasks |
| --- | ---: | ---: | ---: | ---: | ---: |
| E013-D | 6 | 8 | 12 | 576 | 48 (one per cell) |
| E013-C | 4 new repositories | 8 new families | 16 | 512 | 32 (one per cell) |

The two banks must have disjoint repository identities, family identities, task identities, candidate pools, seeds, and fixture bytes. Any claim of disjointness from E009/E010/E012 requires an actual inventory of those prior artifacts; a namespace comparison alone is insufficient.

## Episode object

Each episode binds a frozen repository snapshot or commit, task state, candidate patch identities, observer-safe presentation order, visible screening evidence, hidden completion fixture identity, metadata, and provenance. The hidden valid set is derived by independently applying and running every candidate after a reset. Multiple valid candidates are permitted. Exactly one task in each repository/family cell has no valid offered candidate.

Every candidate must apply and compile. Invalid candidates should fail task behavior, not parser hygiene. Candidate provenance and style must be audited so correctness cannot be read off a producer marker, patch formatting, or presentation position. If independent generator-model candidates are used, record model/prompt/version/seed; no such source is assumed by this contract.

## Visible and hidden firewall

Visible screening fixtures and hidden completion fixtures have distinct roots and manifests. The observer-facing projection may include task text, ordered candidate patches, and declared visible screening results. It must exclude hidden fixture paths, IDs, expected outputs, labels, valid-set size, gold patch, and any deterministic answer-bearing encoding. Projection is audited as bytes and as parsed fields.

The hidden adjudicator remains available to construction audit only. C payloads are sealed before D observer outcomes exist and remain inaccessible to the D selection path beyond C's root and summary counts.

## Replay and quality gates

1. Freeze repository snapshots and task/family definitions before candidate adjudication.
2. Freeze generator source hashes and namespaced seeds.
3. Apply each candidate to a fresh reset of its bound task state.
4. Record apply, compile, visible, and hidden outcomes separately, including failed attempts.
5. Confirm exact bank counts and empty-valid-set distribution.
6. Confirm candidate order is frozen independently of semantic candidate identity.
7. Check fixture disjointness, D/C disjointness, provenance, and observer-frame leakage.
8. Replay a prescribed subset from only sealed inputs, then seal each bank with per-file hashes and a root.

No task may be replaced based on an E013 observer's later behavior. Construction defects get preserved attempts and new versioned bank identities. A bank is `CONSTRUCTION_READY` only after every gate has a receipt. Construction readiness never authorizes model contact.

## Deferred decisions to bind before release

- Exact canonical JSON schema and binary/patch encoding.
- Exact repository set and pinned snapshot commits.
- Exact hidden/visible fixture policy and replay command.
- Whether every task includes a truth-changing sibling; if not, report supported count.
- Prior E009/E010/E012 inventory and overlap audit.
- Build target path: the supplied AGENTS guidance requests `G:` for compilation and links on `C:`, but `G:` is absent on this host. Do not silently claim this layout was used.
