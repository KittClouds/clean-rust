# BEND-AC-00 protocol v0.1

Status: `DRAFT_NOT_SEALED`; phase 1 is not authorized as complete until Bend runs and exact parity is verified.

## Objective

Evaluate whether Bend 2 can express and execute a deterministic byte-oriented Aho-Corasick automaton with exact behavioral parity to the matcher configuration used by Alex. This is a language and representation experiment, not an Alex or Phoenix change.

## Scope and boundaries

- Use only synthetic ASCII byte patterns and texts in phase 1.
- Keep all new files under `experiments/bend-ac-00/`.
- Read Alex only to establish oracle provenance and configuration. Do not edit, build through, or link the Alex or Phoenix crates for this fixture export.
- Do not copy production aliases, snapshots, caches, manifests, corpora, or evaluation data.
- Do not begin performance claims or the medium/ugly corpus phases before semantic parity passes.
- The experiment is not sealed, and no result or phase is promoted by this draft.

## Phase 1: semantic parity

Input is an ordered list of non-empty byte strings and an ordered list of byte texts. Pattern IDs are their zero-based registration positions. Match offsets are zero-based byte offsets with an exclusive end. The match stream is ordered as emitted by the oracle.

The behavioral oracle is Alex's exact-surface matcher configuration:

- `daachorse = 0.4.1`
- `DoubleArrayAhoCorasickBuilder`
- `MatchKind::LeftmostLongest`
- `leftmost_find_iter`

This is a non-overlapping leftmost-longest contract: choose the longest pattern at the earliest eligible start, then resume at that match's end. It is not the standard overlapping AC stream. Pattern order is preserved for IDs. The initial fixture has no empty or duplicate patterns; duplicate handling needs its own explicitly defined contract before inclusion.

The fixture exercises the `a/aa/aaa/aaaa`, `he/she/his/hers`, `abc/bc/c`, and `foo/foobar/bar` prefix/suffix families. It stores source bytes as hex and expected results as `(pattern_id, start_byte, end_byte)` tuples.

### Oracle observability limit

Alex constructs an opaque `daachorse::DoubleArrayAhoCorasick`; its use site exposes matching, not a public enumeration of trie states, failure links, or output lists. Exporting those internals from Alex would require changing Alex or relying on private implementation details, both outside this scope. Therefore phase 1 seals the ordered match stream and input fixture. Bend's own state/failure/output summary must be deterministic and satisfy its local construction invariants, but it cannot be called byte-for-byte Alex parity.

## Phase 1 exit gate

1. The Bend source builds and runs on a supported host with a pinned Bend version.
2. Every fixture input byte sequence is identical to the Rust oracle input.
3. Bend's ordered match tuples equal the checked-in oracle tuples exactly for every case.
4. Two clean Bend runs produce byte-identical canonical output.
5. Construction invariants pass: root failure is root; every non-root failure points to a proper suffix trie state; trie edges preserve prefix semantics; and output closure is direct outputs plus inherited failure outputs.
6. Source, tool versions, commands, fixture hashes, and failed attempts are recorded before any later phase.

## Later phases, not started

- Phase 2: measure construction and scan separately after phase 1 passes.
- Phase 3: add medium and adversarial synthetic corpora, including dense suffix inheritance.
- Phase 4: only after prior gates, evaluate a frozen compact representation and Rust interoperability.

Build-directory footprint and clean-build disk use are required phase 2 measurements.

## Host prerequisite

The current workstation is Windows and has no WSL distribution installed. The Bend project currently documents Windows as unsupported and WSL as the supported path. No WSL or other system-level setup is part of this draft. The oracle fixture can be generated on Windows; Bend execution cannot begin until a supported host is available.
