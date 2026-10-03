# Swift Bonsai 2 27B (PQ2_0) frozen candidate — 2026-09-25

## Result

Swift Bonsai 2 PQ2_0 is frozen as a sandbox local candidate for Phoenix. The
pack is downloaded, size-matched, and SHA-256 fingerprinted. It has **not**
been loaded or probed, and it is **not** promoted into any Phoenix settings.

No Phoenix source code was changed. No saved Kammi settings were changed.
MiniCPM remains the active local trial; Ternary Bonsai 2 PTQ1_0 remains a
probed sandbox candidate.

## Frozen artifacts

- Hugging Face repository:
  `ukisai/Swift-Bonsai-2-GGUF`
- Model revision:
  `a3bdac086bbb6b04d87d0108d18943b5f63868f7`
- License: Apache-2.0
- Selected pack:
  `C:\phoenix-models\candidates\swift-bonsai-2-27b\a3bdac086bbb6b04d87d0108d18943b5f63868f7\Swift-Bonsai-2-PQ2_0.gguf`
- Selected pack size: `7,206,168,928` bytes (matches upstream `totalFileSize`)
- Selected pack SHA-256:
  `5912bb739217cf25b4283a098c7b893d9baff36bdf2e72d3dbf4cb999d5633d5`
- Candidate manifest:
  `C:\phoenix-models\candidates\swift-bonsai-2-27b\a3bdac086bbb6b04d87d0108d18943b5f63868f7\phoenix-candidate-manifest.json`
- Manifest status: `frozen_unprobed`

### Placement note

`D:\phoenix-models\candidates` had only ~3.1 GiB free, so the 7.2 GiB pack
lives on C: instead of following the D: convention. Kammi settings take an
absolute model path, so this is supported, but future docs and scripts must
not assume the D: prefix for this candidate.

### Pack selection

PQ2_0 (2-bit, 7.206 GB) was selected over PTQ1_0 (1-bit, 5.947 GB) because the
publisher states PQ2_0 contains the updated merged Swift weights, while
PTQ1_0 is the earlier release. Both files are complete standalone models:
the Swift correction is merged into the ternary weights, so no adapter file,
patch, or extra flag is needed. This costs ~1.26 GB of extra VRAM versus the
probed Ternary PTQ1_0 pack, which matters on the 12 GiB card (see below).

## What Swift claims to be

Swift Bonsai 2 is UkisAI's reasoning-efficient derivative of Prism ML's
Ternary Bonsai 2 27B (the already-frozen `prism-ml/Ternary-Bonsai-2-27B-gguf`
base). The publisher fine-tuned against reasoning-marker tokens that trigger
overthinking, and reports **39.8% fewer thinking tokens at 0.19% higher
score** than the base.

Publisher-reported scores (their protocols, their hardware — not Phoenix
measurements):

| Benchmark | Base | Swift |
|---|---:|---:|
| GPQA-Diamond | 84.18% | 84.34% |
| C-Eval | 81.37% | 81.47% |
| IFBench | 82.13% | 82.60% |
| AIME 2025 | 92.00% | 93.33% |

The publisher's own card carries two warnings that apply directly to Phoenix
use:

1. This is an **experimental research release**, not a production-ready model.
2. In their testing, benchmark scores did **not** consistently translate into
   reliable general-purpose behavior; instruction following, tool use, and
   open-ended coding or agent tasks remain uneven.

That second warning is load-bearing for Kammi, whose contract leans on
structured extraction and instruction adherence. Swift must pass the same
Phoenix probe suite as the base model before any promotion discussion — its
benchmark deltas alone promote nothing.

## Phoenix integration boundary

- **Prism fork is mandatory.** Like the base Bonsai 2 packs, these files use
  Prism's ternary tensor types. Stock llama.cpp cannot load them. The
  publisher tested at `PrismML-Eng/llama.cpp` revision `1a07bfa5f`; the local
  Prism runtime is `prism-b10685-7dffb15` (commit `7dffb158d`, SHA-256
  `e0ea4fd53e6f0c741cbd28093b427f333ada0eb03b83073e1f99c483793ea976`,
  re-verified 2026-09-25). Runtime compatibility with this Swift pack is
  **unverified** and is the first probing gate.
- **Context profile must be re-derived, not copied.** The publisher serves
  with `-c 32768`. The ternary qualification showed the smaller PTQ1_0 pack
  at 8k context already resident at ~11.1–11.4 GiB on the RTX 3080 12 GiB.
  PQ2_0 is ~1.26 GB heavier in weights alone, so even the 8k single-slot
  profile needs a fresh VRAM-headroom measurement before any server launch
  is trusted. The 32k publisher profile should be assumed not to fit.
- **One gap from the ternary qualification is now closed in-tree
  (uncommitted).** `LlamaServerManager` with the `SingleSlot` performance
  profile now passes `--parallel 1 --flash-attn on`
  (`phoenix-native/apps/phoenix-shell-proof/src/shell/kammi/provider/llama_cpp.rs:149-157`).
  Still open: an explicit reasoning policy for ternary models and any
  non-default sampler flags.
- **Intended sampler settings** (publisher launcher flags, to preserve on
  probing): temperature 1.0, top-p 0.95, top-k 20, min-p 0.0,
  repeat-penalty 1.0, `--jinja`, with
  `chat_template_kwargs: {"enable_thinking": true, "reasoning_effort": "xhigh"}`
  where the integration supports it. Phoenix's local provider intentionally
  omits reasoning fields today, so the first probes should run reasoning
  policy `off` exactly as the base model was probed, then revisit.
- **Suggested model alias** for server launch: `bonsai-2-swift` (the alias
  used in the publisher's API example). Phoenix derives the request alias
  from the file stem (`Swift-Bonsai-2-PQ2_0`); either is fine as long as the
  probe receipt records it.

## Promotion gates

Swift stays `frozen_unprobed` until all of these pass:

1. The local Prism runtime (`7dffb158d`) loads the PQ2_0 pack and reaches
   `/health`, or a revision-bound newer Prism runtime is qualified first.
2. A single-slot memory profile is measured (resident GPU GiB at the chosen
   context size) with safe headroom on the 12 GiB card.
3. The Phoenix probe suite (exact `PHOENIX_READY`, schema-fixed structured
   extraction, needle retrieval, Rust codegen) passes at parity with or
   better than the base Ternary Bonsai 2 results, with no reasoning-budget
   truncation.
4. A startup receipt proves runtime hash, model hash, flags, VRAM headroom,
   and schema-valid probe before the provider becomes selectable.
5. MiniCPM remains the active local trial until gates 1–4 pass under the
   packaged app.

## Receipts

| Artifact | SHA-256 |
|---|---|
| Swift PQ2_0 pack | `5912bb739217cf25b4283a098c7b893d9baff36bdf2e72d3dbf4cb999d5633d5` |
| Local Prism runtime (re-verified) | `e0ea4fd53e6f0c741cbd28093b427f333ada0eb03b83073e1f99c483793ea976` |

Upstream identity cross-check: repo `ukisai/Swift-Bonsai-2-GGUF` at revision
`a3bdac086bbb6b04d87d0108d18943b5f63868f7` (last modified 2026-09-24),
Apache-2.0, base model `prism-ml/Ternary-Bonsai-2-27B-gguf` (finetune
relation), native context 262,144.

## Sources

- Model card: https://huggingface.co/ukisai/Swift-Bonsai-2-GGUF
- Full benchmark table: https://huggingface.co/ukisai/Swift-Bonsai-2-GGUF/blob/main/benchmark_results.json
- Required runtime fork: https://github.com/PrismML-Eng/llama.cpp
- Base model qualification: `phoenix-native/docs/ternary-bonsai-qualification-20260917.md`
