# Phase 6 inference verification

Verified on 2026-07-16 using isolated Cargo targets on `D:`. The active Phoenix
application target was not modified.

## Final authoritative gate

Receipt:
`D:\phoenix-target-revision-inference\receipts\phase6-b07a08af1d9a5cbe-1784259664584-22548.json`

The run consumed the `docs/shortrun.md` authoritative snapshot and created new
immutable bundles for both models.

| Measurement | GFM-RAG-8M | G-reasoner-34M |
| --- | ---: | ---: |
| fresh bundle build | 1.087 s | 11.828 s |
| build peak resident memory | 796.9 MiB | 1,845.6 MiB |
| complete inference | 1.077 s | 0.557 s |

The 34M build comprises 4.752 s encoder/session load, 7.039 s embedding
compute, and 0.038 s artifact write. Its inference reused both the process
resident `qwen_onnx_fp32` session and the zero-copy two-file hot bundle.

Authority checks:

- source snapshot unchanged;
- 6 candidate edges excluded;
- 0 candidate edges admitted;
- 0 Phoenix persistence writes;
- stable requested-type ranking returned the expected document ID.

## Cache and memory behavior

The 2.38 GB external-data file is materialized once into the NVMe hot tier.
The ONNX model directory is assembled with same-volume NTFS hard links, so the
runtime receives the exact `model.onnx` / `model.onnx.data` names without a
second copy. Reuse validation reads bounded probes and does not require the
source volume.

Naive 8-row and 16-row ONNX batches were rejected after measurement. They
increased embedding compute to 9.03 s and 19.29 s respectively. Four ordered
rows remained the fastest measured policy while holding build memory below
1.9 GiB.

## Verification gates

- production unit and integration tests passed;
- real Phoenix snapshot projection passed;
- immutable bundle round-trip passed;
- candidate-truth leakage test passed;
- strict all-target Clippy passed with warnings denied;
- no crate-local `target/` directory exists;
- all authored Rust files remain below 800 lines.

## Phase 7/8 revision-impact model duel

Final warm receipt:
`D:\phoenix-target-revision-impact-duel\receipts\phase7-8-e8a76d5a8ad0bd9e-1784263194354-35072.json`

The duel projected all seven gold mutations into one generation-73 inference
snapshot containing 133 nodes and 182 admitted edges. Seven candidate-edge
leak traps were excluded, no candidate edge was admitted, the source digest
remained unchanged, and Phoenix received no persistence write.

| Arm | recall@1 | recall@3 | recall@5 | first broken rank | mean latency/case |
| --- | ---: | ---: | ---: | ---: | ---: |
| deterministic | 46.66% | 100% | 100% | 1.000 | 0.09 ms |
| 8M | 6.66% | 20% | 33.33% | 17.714 | 1,116.87 ms |
| 34M | 26.66% | 33.33% | 40% | 8.857 | 694.31 ms |
| deterministic + 8M | 40% | 93.33% | 100% | 2.428 | 1,116.96 ms |
| deterministic + 8M -> 34M | 46.66% | 93.33% | 100% | 2.285 | 1,811.27 ms |

Both combined arms retained the complete deterministic impact set. Every
dynamic ranking repeated identically, and a separate warm process reproduced
the same snapshot, stable IDs, raw scores, ranks, arm metrics, query-quality
metrics, and authoritative report digests.

The 49 `MutationKind x TargetNodeType` Qwen query embeddings were precomputed
in 31.069 s outside the interactive measurement. Cached Spotlight then ran 49
queries in 15.121 s total (308.59 ms/query) with zero encoder misses. Cached
scene recall@5 was 46.66% versus 40% dynamically; cached repair usefulness was
28.57%/85.71% at top-1/top-3 versus 57.14%/57.14% dynamically. The quality
trade is therefore mixed rather than an unconditional cached-query win.

The reported model-arm peak memory is the conservative full-process peak of a
single committee harness with both resident models loaded. It is not an
isolated per-model attribution; the committee peak was 2,610.4 MiB.

The technical integration candidate is false: neither model improved the
deterministic review ordering, and both combined arms reduced recall@3. The
formal gate remains `provisional_pending_author_review` because all seven gold
cases still carry `pending_author_review`; proxy review-time, suspiciousness,
and repair metrics cannot earn integration until those labels are accepted.

## Post-duel review gate

Model attachment now requires an explicit isolated-harness capability token.
Every untouched detector report records `modelIntegrationState: disabled`; the
duel may change that only to `experimental_presentation_only`. The API exposes
no production-enabled state, and attachment still cannot change authoritative
membership, order, severity, paths, or the deterministic report digest.

The digest-bound author packet is:
`D:\phoenix-target-revision-impact-duel\reviews\gold-review-v2-8bbdd2ad6cd25a44.md`

Its token is `gold-review-v2:8bbdd2ad6cd25a44`. All seven deterministic,
coverage, evidence-presence, and unranked-repair machine checks pass, but all
author decisions remain pending. Each case proposes a mutation-preserving
preferred repair; those preferences are proposals rather than accepted labels.

The next duel receipt will add focused evidence recall, evidence MRR, source
prefetch precision, reasonable-repair recall, repair MRR, and cross-case repair
contamination. Preferred-repair scoring remains unavailable until the packet
is accepted. No post-review model rerun has been claimed or executed yet.
