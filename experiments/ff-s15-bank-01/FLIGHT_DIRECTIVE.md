# FF-S15-BANK-01 — flight directive (data-engineering only)

Isolated throwaway flight. Hard firewall from E4-0, E4-01, E5, R1, JEV, five-head work.

## Boundaries (top of directive, non-negotiable)

- NO frozen-LFM features, NO probe scores, NO adapter, NO downstream accuracy during construction.
- NO selecting generators because a model likes them. Fix generators from formal semantics.
- NO contamination from existing branches into bank examples or splits.
- External datasets are design seeds only (`seed-registry-v1.json`). Zero external rows in BANK-v1.
- Builders see only inputs after freeze; terminal truth opens once under a later evaluation contract.

## Build

- `python -m src.build_bank [--fast] [--seed 0]` → `releases/BANK-v1[-fast]/`
- `python -m src.seal --release <dir> --sample N` → 25 gates G01–G25.

## Layout

- `worlds/{SPLIT}.jsonl` — canonical truth (authoritative).
- `inputs/{TRAIN,DEV}.jsonl` — rendered inputs + development labels.
- `public/test-inputs/TEST-*.jsonl` — inputs only (no labels).
- `protected/test-truth/TEST-*.jsonl` — escrowed terminal truth.
- `manifests/release.json` — code hashes, seeds, budgets, row hashes, contact flags.

## Done when

`BANK_v1_SEALED=true`: generator/simulator/renderer replay PASS, split leakage PASS
(literal dups = 0; graph-iso collisions reported), metamorphic PASS, truth escrow PASS,
seed manifest COMPLETE, `frozen_fabric_contact=false`, `system_1_5_training=false`,
`terminal_truth_opened=false`, cleanroom reconstruction exact on samples.
