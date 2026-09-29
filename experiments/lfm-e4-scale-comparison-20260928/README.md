# E4 capability surface: 230M versus 1.2B (2026-09-28)

This engineering comparison asks how much of the historical E4 five-head linear
observer surface survives when the frozen backbone changes from
LFM2.5-1.2B-Base to LFM2.5-230M-Base. It does not test lexical transport,
retrieval, serving, or the protected E4-0 panel.

## Fixed comparison

- Same E1 FIT-derived, whole-quartet TRAIN/DEV split for both arms. Historical
  E1 TEST is excluded from fitting and DEV evaluation.
- Same independently generated E4-shaped TEST: 18,667 quartets, variants
  A/C/E/P, 74,668 primary inputs. Namespace and seed are new. Both model arms
  receive identical input bytes in identical order. TEST truth remains unopened
  until both arm predictions are sealed.
- Same `V1_FINAL_POSITION`: frozen `AutoModel`, no generation or fine-tuning,
  fp32, CUDA:0, final hidden layer at the final non-padding token, batch one,
  little-endian fp32 cache. Each arm uses its pinned local model/tokenizer.
- Same train-only float64 chunked Welford normalization and five independent
  PyTorch LBFGS linear heads with the historical E3 hyperparameters and L2
  regularization. Context/entity ID use all TRAIN rows; relation/state/target
  fit only where both lexical terms are on the E1 training side.
- Same prediction and scoring code for both arms. Primary metrics are the eight
  historical endpoints (five capabilities with exact target split into four
  strata), plus paired whole-quartet bootstrap using E4's 10,000-replicate,
  0.00625 lower-tail diagnostic and integrated route/target
  summaries. Timings and cache sizes are engineering diagnostics.

The historical 1.2B E2 feature cache is reused for the E1 FIT rows only. A
fresh 256-row extraction using this experiment's extractor reproduced its
first 2,097,152 bytes exactly. Both arms' five heads are refit on the new
TRAIN split; historical E3 observer weights are not reused as the comparison
arm.

## Population provenance

`source/e4-population-v02` is a narrow fork of the original E4 model-free
population generator. `source/panel-generator-v04` and the JSON plans are
copied, fixed references. This fork changes only the population namespace,
render seed, independent engineering permit, and exact E4-0 receipt checks
that cannot apply to a new namespace. Its support floor and 18,667-quartet
prefix remain. The emitted file hashes are in `population-seal.json` on the
scratch volume. The protected E4-0 panel and its labels are not read.

Generated caches, model artifacts, and TEST labels live under
`D:\phoenix-evals\e4-scale-compare-20260928`. They are not Git source files.
The first population emission hit a Windows stack limit; its partial output
was retained as `test-v1-failed-stack`. The successful replay used a 16 MiB
worker stack and emitted the full fresh population.
An independent replay from this checkout reproduced all three emitted file
hashes byte-for-byte; see `receipts/source-replay.json`.

## Execution order

1. Build/test the copied Rust population generator with `CARGO_TARGET_DIR`
   on `D:` and run `e4-scale-population` once.
2. Run `prepare_fit.py` once. It emits label-free FIT inputs, a TRAIN/DEV row
   map, and a split seal.
3. Extract 230M E1 FIT features. Reuse the pinned historical 1.2B E1 cache
   after the exact 256-row parity check.
4. Fit each arm with `fit.py`; DEV predictions are only a sanity check.
5. Extract both arms on the same fresh TEST inputs with `extract.py`.
6. Run `predict.py` for both TEST arms and retain their prediction seals.
7. Only then run `score.py`, which checks both seals and opens the independent
   TEST labels.

If the run stops, the completed steps and partial feature cache are preserved.
`extract.py` resumes an aligned partial cache in the same row order. A sealed
output directory is never overwritten.

## Claim boundary

This is an E4-shaped synthetic capability parity experiment. A strong 230M
result would show linear accessibility of the old E4 capabilities under this
new population. It would not by itself prove safe lexical transport, natural
context compatibility, or authority-memory qualification.
