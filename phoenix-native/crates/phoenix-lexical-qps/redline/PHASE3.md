# REDLINE Phase 3: exact block-max WAND traversal

Date: 2026-09-18. Scope: literal single-expansion groups in bounded serving
mode. Transport and multi-expansion groups remain on the classic accumulator.

## What changed

- Added 64-row per-term block metadata: last document and maximum impact.
- Added standard WAND pivot ordering over live posting cursors.
- Added safe block jumps and bounded landing-block scans.
- Kept the coverage floor and evolving top-k threshold as strict proof gates;
  ties still evaluate.
- Kept full scoring in query-group order so surviving documents retain the
  classic lexical, coverage, and posting-choice semantics.
- Receipts expose posting rows available/visited, skipped blocks, coverage
  deaths, and score-bound deaths.

The pivot bound is the sum of each live cursor's quality-weighted suffix
maximum. For a document at the pivot, the score bound tightens to the exact
quality-weighted impact of the rows currently holding that document. A cursor
whose current document is before the pivot advances to the pivot; its skipped
documents are never materialized as candidates.

## Exactness gate

`block_max_matches_classic_candidate_set_and_top_k` compares the bounded WAND
path with the classic accumulator over 3 randomized 10k-document corpora,
2 coverage configurations, 45 query shapes, and top-k values 1/10/50. It
checks serving top-k equality, evidence-pool set and ordered equality, and
the posting-row accounting invariant. The REDLINE freeze, lazy-evidence,
relevance, and library suites are green.

## Mechanism gate

Release probe command:

```text
CARGO_TARGET_DIR=D:\phoenix-builds\phoenix-qps-redline
cargo run --release --manifest-path phoenix-native/Cargo.toml -p phoenix-lexical-qps --example perf_probe
```

Representative warm probe on the 10k x 96-token corpus with the predeclared
64-row blocks:

| workload | rows visited / available | skipped | score-bound deaths |
|---|---:|---:|---:|
| dense 3-term | 5,196 / 5,196 (100.0%) | 1 | 3,630 |
| high-frequency | 6,534 / 6,649 (98.3%) | 58 | 1,152 |
| skewed | 5,050 / 5,050 (100.0%) | 0 | 50 |

The dense and high-frequency arms do not clear the Phase 3 mechanism target
of at least 50% posting-row reduction. The score-bound deaths show that the
per-document bound is useful, but the 64-row block maxima are too loose to
skip unread rows on this uniform corpus. Smaller 16/4/1-row qualification
arms were measured; they increased metadata and hot-loop work without
producing a dense-arm latency win, so the predeclared 64-row contract remains
the correct sealed arm for now.

The normal release binary keeps WAND fail-closed. Its final warm probe before
Phase 3B was 101.6 us for the dense three-term arm and 150.6 us for the
high-frequency arm, with the same posting counts as the classic baseline.

## Phase 3B: fused literal candidate kernel

The repository contains an exact fused literal stream for bounded
all-single-expansion queries. It k-way merges ordered posting lists, finalizes each
document once, computes lexical and coverage score while the document is hot,
and feeds the result directly into a bounded heap using the existing
`RankedCandidate` comparator. Posting choices are stored in fixed-stride slots
only for heap survivors, then copied into the unchanged Phase-2 scratch
contract. Phase 3C demoted this path from serving: production literal queries
remain on the classic accumulator plus Phase 2. Classic is the serving path;
the fused stream is a test differential and diagnostic arm, while WAND remains
a test-only oracle.

The new `fused_literal_matches_classic_pool_and_receipts` gate compares the
fused and classic full evidence pools, coverage counts, posting-row counts,
and materialized-choice receipts. The REDLINE freeze, lazy-evidence,
relevance, and library suites remain green.

Three warm release probes on the frozen 10k x 96-token corpus were measured
against a separate classic build. Means were:

| workload | classic | fused literal | change | rows fused | docs finalized | scratch docs avoided | choices materialized |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense 3-term | 105.8 us | 106.6 us | +0.8% | 5,196 | 4,401 | 4,241 | 371 |
| high-frequency | 150.5 us | 164.4 us | +9.2% | 6,649 | 5,828 | 5,668 | 320 |
| skewed | 95.7 us | 94.7 us | -1.0% | 5,050 | 5,000 | 4,840 | 210 |

The receipt also reports `literal_scratch_documents_avoided`: finalized
documents which never enter corpus-indexed accumulation scratch. The exact
value varies with the configured candidate limit.

The fused path therefore clears semantic and allocation-shape goals but does
not clear the requested 15% latency improvement gate. It is retained as the
clean Phase 3B architecture, while the performance gate stays open for a
profile-guided follow-up rather than adding micro-optimizations without
evidence. No ranking, threshold, or transport behavior changed.

## Phase 3C: attribution-only decomposition

The serving path was left unchanged. A release-only probe now measures three
independent pieces: flat merge plus selection, classic accumulation plus the
bounded heap, and null k-way merge versus a null sequential posting scan. Three
warm runs on the same 10k-document corpus produced these approximate means
(nanoseconds per query):

| workload | flat merge | flat select | classic accum | classic heap | null merge | null scan |
|---|---:|---:|---:|---:|---:|---:|
| dense 3-term | 58,400 | 13,400 | 49,600 | 26,100 | 49,900 | 3,200 |
| high-frequency | 42,800 | 15,900 | 55,600 | 21,800 | 32,700 | 4,100 |
| skewed | 26,700 | 17,400 | 44,100 | 12,000 | 19,400 | 3,100 |

This closes the attribution question without another optimization round. The
merge has real control-flow cost over a sequential scan, while the bounded
heap and survivor bookkeeping are workload-dependent. Literal serving should
therefore remain on the classic accumulator plus Phase 2; the fused path is
an exact qualified diagnostic architecture. The next high-value experiment is
Phase 4 expansion-group collapse feeding the classic accumulator.

## Current performance reading

The WAND path is exact, but the first hot implementation is slower than the
classic accumulator on the frozen dense benchmark (Criterion median roughly
305 us versus the prior 163 us live baseline). It is therefore compiled as a
qualification arm only: unit tests enable it, while normal binaries fail
closed to the already-qualified classic accumulator. Sorting live cursors,
per-pivot bookkeeping, and loose block maxima are the measured reasons to
revisit in a future Phase 3B arm. The exact differential gate is complete;
the mechanism and latency gates are explicitly open.

## Boundaries

- No transport expansion behavior changed.
- The public `SearchReceipt` adds Phase 3B diagnostic counters for finalized
  literal documents and survivor choice records; existing ranking and hit
  semantics are unchanged.
- No model, graph, reader, or application files were touched by this phase.
- The existing dirty Phoenix worktree remains uncommitted and was preserved.
