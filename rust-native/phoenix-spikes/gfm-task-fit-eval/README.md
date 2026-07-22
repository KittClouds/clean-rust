# GFM task-fit evaluation

Isolated evaluation of the pinned native GFM-RAG-8M and G-reasoner-34M lanes
on tasks documented by their model cards. This crate does not modify Phoenix,
the parity crates, or the paused revision-impact experiment.

The evaluation isolates graph-model behavior by supplying oracle start nodes.
It measures supporting-document retrieval, multi-hop retrieval, query-form
robustness, typed-entity retrieval, and hierarchical-node retrieval. It does
not claim to evaluate NER, entity linking, answer generation, or fine-tuning.

All generated model bundles and receipts are written under the dedicated D:
target:

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-gfm-task-fit\cargo'
cargo run --locked --release --manifest-path `
  'C:\code land\clean-rust\rust-native\phoenix-spikes\gfm-task-fit-eval\Cargo.toml'
```

