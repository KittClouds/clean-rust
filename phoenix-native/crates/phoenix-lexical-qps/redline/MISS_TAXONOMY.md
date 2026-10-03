# REDLINE miss taxonomy

Date: 2026-09-18. This is a read-only autopsy of the frozen literal quality
frontier. It does not change serving behavior, thresholds, ranking weights, or
transport policy.

The evaluator uses the same literal QPS configuration as the quality frontier,
including QpsConfig::default().coverage_floor = 0.2. For every judged
relevant document absent from Phoenix top-100, it compares:

1. exact token presence in the indexed title/body;
2. the bounded literal result;
3. the exhaustive literal oracle;
4. whether the independent BM25 baseline found the document in top-100.

stem_overlap_with_literal_absence is a deliberately small heuristic using
suffix stripping. It is a clue for future morphology work, not evidence that
a stemmer is correct.

## Results

| dataset | judged relevant docs | Phoenix top-100 | missed | literal absent | coverage filtered | ranked below top-100 | ranked misses BM25 found |
|---|---:|---:|---:|---:|---:|---:|---:|
| SciFact | 339 | 292 | 47 | 2 | 5 | 40 | 11 |
| FiQA | 1,706 | 628 | 1,078 | 40 | 82 | 956 | 178 |

Percentages are calculated over each dataset's Phoenix misses:

- SciFact: 4.3% literal absent, 10.6% below the 0.2 coverage floor, and
  85.1% present in the exhaustive literal result but ranked below top-100.
- FiQA: 3.7% literal absent, 7.6% below the coverage floor, and 88.7%
  present in the exhaustive literal result but ranked below top-100.

The exhaustive oracle produced no eligible-document omissions on either
dataset. That makes the result useful as a decomposition rather than a
candidate-generation guess.

## Rank depth

The exhaustive ranks of reachable relevant documents below top-100 are:

| dataset | 101-200 | 201-500 | 501-1,000 | 1,001-5,000 | over 5,000 |
|---|---:|---:|---:|---:|---:|
| SciFact | 9 | 15 | 11 | 5 | 0 |
| FiQA | 126 | 145 | 113 | 302 | 270 |

SciFact is mostly a near-boundary calibration problem. FiQA has a mixed
shape: 384 of 956 reachable misses are within rank 1,000, while 572 are
deeply misplaced below rank 1,000.

Among reachable misses, BM25 finds 11 SciFact documents and 178 FiQA
documents in its own top-100. Mean Phoenix literal evidence for those
BM25-recovered documents versus documents missed by both top-100 systems is:

| dataset / population | documents | lexical score | coverage |
|---|---:|---:|---:|
| SciFact / BM25 recovered | 11 | 10.522 | 0.285 |
| SciFact / both missed | 29 | 5.608 | 0.368 |
| FiQA / BM25 recovered | 178 | 15.831 | 0.468 |
| FiQA / both missed | 778 | 8.740 | 0.430 |

The BM25-recovered FiQA slice has materially higher Phoenix lexical score
and slightly higher coverage. That points toward term-frequency, rarity, and
length calibration as useful first V3 signals. The SciFact slice is too small
for a strong conclusion.

The expanded lexical census makes the FiQA signature more specific:

| FiQA population | max IDF | mean IDF | strongest term contribution | document length | contribution entropy |
|---|---:|---:|---:|---:|---:|
| BM25 recovered (178) | 5.058 | 2.562 | 7.148 | 130.0 | 0.748 |
| Both missed (778) | 3.292 | 1.542 | 4.091 | 173.8 | 0.737 |

BM25 is recovering shorter documents with substantially stronger rare-term
authority and a larger strongest single-term contribution. This is evidence
for a lexical calibration experiment around rarity, strongest-term impact,
and length normalization before adding positional or transport features.

## Decision

FiQA's recall loss is mostly rank placement under the current Phoenix lexical
score, not literal absence. Only 122 of 1,078 missed judged documents
(11.3%) are unavailable to the literal oracle because they have no exact
match or fall below the coverage floor. The remaining 956 are reachable by
literal retrieval and require better ranking discrimination, term weighting,
or learned evidence.

Transport and morphology remain valid research directions for the 122
unavailable FiQA documents, but they should not be treated as the sole
explanation for the FiQA frontier. The next isolated experiment should train
a revision-bound V3 ranker over the existing literal candidate set. A real
expansion artifact should be evaluated separately afterward, with recall
change reported independently.

The follow-on reranking experiment is recorded in V3_R1.md.

## Reproduction

    $env:CARGO_TARGET_DIR = 'D:\phoenix-builds\phoenix-qps-miss-taxonomy'
    cargo build --release -p phoenix-memory-lock --bin qps_miss_taxonomy
    & 'D:\phoenix-builds\phoenix-qps-miss-taxonomy\release\qps_miss_taxonomy.exe' 'D:\phoenix-evals\beir\scifact' 'D:\phoenix-evals\beir\receipts\scifact-miss-taxonomy.json'
    & 'D:\phoenix-builds\phoenix-qps-miss-taxonomy\release\qps_miss_taxonomy.exe' 'D:\phoenix-evals\beir\fiqa' 'D:\phoenix-evals\beir\receipts\fiqa-miss-taxonomy.json'
