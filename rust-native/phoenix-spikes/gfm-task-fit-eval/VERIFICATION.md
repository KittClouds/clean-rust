# GFM task-fit verification

Date: 2026-07-17

## Boundary

- Evaluation is read-only over an immutable asserted graph projection.
- Oracle start nodes isolate graph retrieval from NER/entity-linking quality.
- No Phoenix store, graph truth, desktop code, or paused experiment was changed.
- Cargo artifacts, packed bundles, hot caches, logs, and the JSON receipt live under
  `D:\phoenix-target-gfm-task-fit`.
- The standalone Cargo lockfile is generated locally and ignored because the workspace
  rejects files above 800 lines; the evaluated binary remains preserved on `D:`.
- The suite is controlled task-fit evidence, not a claim of benchmark parity with the
  model-card datasets.

## Supported task shapes exercised

- Direct and paraphrased supporting-document retrieval.
- Two-hop and four-hop supporting-document retrieval.
- Causal and temporal supporting-document retrieval.
- Near-name distractors and rare relations.
- True/false, multiple-choice, and open-ended query forms.
- Typed entity targets for G-reasoner.
- Hierarchical chapter targets for G-reasoner.

## Results

### Document retrieval: equal 12-case comparison

| Model | Recall@1 | Recall@3 | Recall@5 | MRR | Full support@5 | First query | Warm median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GFM-RAG-8M | 43.06% | 86.11% | 86.11% | 0.8750 | 66.67% | 2,490.1 ms | 1,176.9 ms |
| G-reasoner-34M | 34.72% | 86.11% | 97.22% | 0.8333 | 91.67% | 5,254.5 ms | 762.8 ms |

Bundle construction was 14,896.8 ms for GFM-RAG-8M and 77,302.6 ms for
G-reasoner-34M.

### G-reasoner typed targets

| Target family | Cases | Recall@1 | Recall@3 | Recall@5 | Full support@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hierarchical chapter | 2 | 100% | 100% | 100% | 100% |
| Typed entity | 3 | 0% | 66.67% | 100% | 100% |

### Family signals

- Both models achieved full support@5 on direct-document retrieval.
- G-reasoner achieved full support@5 on both causal/temporal cases; GFM-RAG
  achieved 50%.
- G-reasoner achieved full support@5 on all three multi-hop cases; GFM-RAG
  achieved 66.67%.
- G-reasoner missed one support document inside the top five on the three-part
  open-ended query. Top-five retrieval should therefore remain measured, not assumed.

## Fit decision

- **GFM-RAG-8M:** use as the compact document-retrieval lane when cheap rebuilds,
  strong early ranking, and a document-only result contract matter.
- **G-reasoner-34M:** use as the high-recall retrieval lane for complete evidence
  sets, causal/temporal or longer-hop queries, and hierarchical targets.
- **Typed entity retrieval:** G-reasoner is a good top-five candidate generator in
  this suite, but not a top-one authority without a deterministic or learned reranker.
- **Revision impact ordering:** keep rejected as a direct model task. It asks these
  retrieval models to predict propagation/impact semantics that their cards do not
  establish.

## Verification commands

```powershell
$env:CARGO_TARGET_DIR='D:\phoenix-target-gfm-task-fit\cargo'
cargo fmt --manifest-path 'rust-native\phoenix-spikes\gfm-task-fit-eval\Cargo.toml' -- --check
cargo test --manifest-path 'rust-native\phoenix-spikes\gfm-task-fit-eval\Cargo.toml'
cargo run --release --manifest-path 'rust-native\phoenix-spikes\gfm-task-fit-eval\Cargo.toml'
```

Observed gates:

- `cargo fmt --check`: passed.
- `cargo test`: 2 passed, 0 failed.
- Native release evaluation: passed and emitted
  `D:\phoenix-target-gfm-task-fit\receipts\task-fit-v1.json`.
