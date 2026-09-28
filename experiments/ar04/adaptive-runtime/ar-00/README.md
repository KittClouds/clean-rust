# AR-00 — Optimizer Interposer

This is the first isolated engineering arm of the adaptive-authority program.
It does not model a fly and it does not produce evidence for Drosophila Heresy.

The experiment keeps a tiny XOR MLP and its backpropagated gradient. The
baseline lets AdamW mutate parameters directly. The experimental arm routes the
same gradient through a fixed local action vocabulary:

```text
gradient proposal
  -> candidate actions {-step, no-op, +step}
  -> authority and bounds gate
  -> per-parameter utility ranking
  -> simultaneous commit
```

The hot path uses fixed-size arrays, no allocation, and no locks. The dataset
is written once as a compact binary artifact, then read through a read-only
memory map and zero-copy typed views. SIMD is used for the evaluation metric,
not smuggled into the action semantics.

## Run

From this directory:

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench ar00
```

`cargo run` writes `artifacts/xor-dataset.bin` and
`artifacts/ar-00-report.json`. These are engineering measurements only.

## AR-00 gate

The interposer passes the first gate if it learns the four-point XOR task from
the same initialization as AdamW, while reporting selected actions and blocked
actions. This does not establish usefulness, continual-learning protection,
or biological correspondence. It only establishes that the interposed action
interface can optimize a tiny network at all.
