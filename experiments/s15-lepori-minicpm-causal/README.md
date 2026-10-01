# Lepori — causal lane, MiniCPM5-1B-Base

Second causal substrate, paired with Lexi (`LFM2.5-230M` causal). The bidirectional encoder
lineage is **parked and preserved, not rescued**.

```
Lexi    = LFM2.5-230M causal
Lepori  = MiniCPM5-1B-Base causal      <- this lane
Encoder = PARKED / preserved lineage
```

## Status: substrate qualified, primitives frozen, lane ready to train

| step | state | receipt |
|---|---|---|
| substrate qualification | **SUBSTRATE_QUALIFIED** | `substrate-qualification.json` |
| frozen contract | written | `substrate-contract.json` |
| BANK-v1 primitives | **20,000 TRAIN / 2,000 DEV canonical**, joinable at `m_cap=28` | `primitives/*-receipt.json` |
| graft / training | not built yet | — |

## Why MiniCPM and not K2-Horizon

MiniCPM is a plain `LlamaForCausalLM` and exposes a **full internal hidden-state stack**. K2's
custom `K2HorizonModel.forward` absorbs `output_hidden_states` into `**kwargs`, never appends to
`all_hidden_states`, and returns only `last_hidden_state` — so it is final-layer-only. For a
program doing grafts over latent states, that is an integration risk rather than an interesting
scientific question, so K2 is not the choice today. K2 remains available later.

## Qualification results

```
parameters          1,080,632,832 (1.0806B)  bf16  frozen
architecture        LlamaForCausalLM, model_type llama, no trust_remote_code
hidden_size         1536          layers 24
hidden_states       tuple length 25, fully populated at every depth   <- decisive
validated depths    25/50/75/100% -> layers 6 / 12 / 18 / 24
weight identity     EXACT vs on-disk safetensors, worst max-abs-diff 0.0
padding             cosine >= 0.99998, relative RMS <= 0.006 at all four depths
entity spans        all mentions resolve to token spans
latency             ~48 ms/forward batch 1, ~54 ms batch 8, on CUDA
```

The weight-identity check exists because of the LFM2.5-Encoder-230M incident, where loading a
wrapper with bare `AutoModel` silently random-initialized every weight. A load is not trusted
here until it is compared against the checkpoint on disk.

### One substrate property worth knowing before designing anything

Hidden scale varies sharply with depth:

```
std   layer 6 = 22.21    layer 12 = 22.91    layer 18 = 23.59    layer 24 = 3.73
```

The final layer is ~6× smaller than mid-depth. So the six surfaces are stored **already
per-surface standardised**; otherwise shallow surfaces would dominate any cross-surface mixing,
and a variance floor is only comparable *within* a surface, never across depths.

## The six surfaces

| surface | layer | pooling |
|---|---|---|
| `lt@24` | 24 | last real token — the causal summary |
| `mf@24` | 24 | mean over all real tokens |
| `ms@24` | 24 | mean over last 16 real tokens |
| `mf@18` | 18 | mean over all real tokens |
| `mf@12` | 12 | mean over all real tokens |
| `mf@6` | 6 | mean over all real tokens |

All six verified mutually distinct (`lt@24` vs `mf@24` max-abs 5.13), no NaN, no duplicate rows.
Entity mentions are mean-pooled at final depth, where a causal mention representation is
context-complete.

## Inherited constraints — the contract, not the graft

The encoder's architecture is **not** being ported. These are program-level lessons, banked:

1. **Exhaustive candidates.** `m_cap = 28`, measured over 140,000 canonical worlds. The encoder's
   24 silently dropped 21,016 worlds (15% of the universe) and 567,254 candidates.
2. **No raw latent-matching loss.** `||s(x) - s(x̃)||²` is minimised at constant `s`; it drove
   `D_s` to 0.0007 while looking like success. Enforce consistency on *predictions* (JS).
3. **Diversity is not competence.** `D_s > 0` did not imply discrimination — the encoder reached
   `D_s` 1.84 with every global target still at 0.500.
4. **Paired correctness, not naked renderer agreement.** A constant predictor is perfectly
   renderer-stable for the wrong reason. Always report the 2×2 decomposition.
5. **No duplicate-source weighting.** 13 BANK heads resolve to **6 independent canonical
   sources**; weight over sources, `L_g = (1/|H_g|) Σ_h L_h`.
6. **Balanced objective, correct selection, pre-registered margins.** Class-imbalanced BCE is
   minimised by the prior; select on `J_select` over unique source groups.
7. **No generic global-token/candidate-token recurrent mixer.** Phase 4A moved state enormously
   while destroying candidate conditioning (6.53 → 1.53). Any future recurrent organ needs a
   different job, not more depth.
8. **Port the contract, not the graft.**

This lane joins at the current constructive frontier and does not replay those rungs.

## Layout

```
src/substrate_contract.py    frozen identity + inherited lessons (the thing not to change)
src/qualify_substrate.py    Phase 0 substrate qualification, writes the receipt
src/extract_primitives.py   BANK-v1 -> six surfaces + entity spans
src/topup_primitives.py     reach the exhaustive joinable contract; never overwrite the base
```

Artifacts: `D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm\`

Next: build a **causal-appropriate** Phase 0/1 interface over these surfaces under the inherited
constraints. The parked encoder's artifacts stay where they are, for a future encoder-specific
program.
