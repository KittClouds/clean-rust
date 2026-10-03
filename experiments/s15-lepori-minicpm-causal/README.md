# Lepori — causal lane, MiniCPM5-1B-Base

Second causal substrate, paired with Lexi (`LFM2.5-230M` causal). The bidirectional encoder
lineage is **parked and preserved, not rescued**.

```
Lexi    = LFM2.5-230M causal
Lepori  = MiniCPM5-1B-Base causal      <- this lane
Encoder = PARKED / preserved lineage
```

## Status

| step | state | receipt |
|---|---|---|
| substrate qualification | **SUBSTRATE_QUALIFIED** | `substrate-qualification.json` |
| frozen contract | written | `substrate-contract.json` |
| BANK-v1 primitives | **20,000 TRAIN / 2,000 DEV canonical**, joinable at `m_cap=28` | `primitives/*-receipt.json` |
| Phase 0 gate | **9/9, engineering only, no accuracy threshold** | `phase0-gate.json` |
| Phase 1 baseline | complete; candidate legality 0.7495, global dead, endpoint degenerate | `phase1-receipt.json` |
| integrity / sufficiency audit | complete | `joint-surface-ablation.json`, `gold-action-sufficiency.json` |
| Phase 1B acquisition test | complete; goal-relative target not acquired by shallow readout or isolated supervision; legality held | `PHASE1B.md` |

Read `CORRECTIONS.md` before quoting anything from this lane. It records corrections to earlier
claims; later entries supersede stale interpretations retained for historical context.

**Historical-reference status:** the Qwen preparation audit found harness defects
documented in C13. The user chose to repair Qwen only and retain MiniCPM's existing
results. Numerical receipts are preserved; isolation/representation causal claims
are qualified. The new trial is in `../s15-lepori-qwen-two-run/README.md`.

## Headline

**Candidate legality is accessible; the candidate state is not yet action-sufficient.** A
parameter-free gold-state ladder gives legality-only state an overall determinism ceiling of
**0.7605** and a MOVE-conditional ceiling of **0.9335**. Its MOVE 1-NN accuracy is **0.3699**;
that is an estimator result, not an information ceiling. Adding the *already-existing*
`candidate_satisfies_goal` channel raises the overall ceiling to **0.9925** and the MOVE ceiling to
**0.9942**, while MOVE 1-NN reaches **0.9306**. The ladder shows a large learnability gap from
legality-only state, not that MOVE is impossible from it. Full tables in `PHASE1.md` and the C11
correction in `CORRECTIONS.md`.

## Why MiniCPM and not K2-Horizon

MiniCPM is a plain `LlamaForCausalLM` and exposes a **full internal hidden-state stack**. K2's
custom `K2HorizonModel.forward` absorbs `output_hidden_states` into `**kwargs`, never appends to
`all_hidden_states`, and returns only `last_hidden_state` — so it is final-layer-only. For a
program doing grafts over latent states, that is an integration risk rather than an interesting
scientific question. K2 remains available later.

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

### Scale varies with depth — and the number is smaller than I first said

Row-level pooled standard deviation, measured on real BANK data:

```
lt@24 3.85   mf@24 2.84   ms@24 2.95   mf@18 4.50   mf@12 2.03   mf@6 1.38
```

A spread of **1.58×** relative to the final surface, 3.3× between shallowest and `mf@18`. Earlier
I justified per-surface standardisation with a "6× smaller final layer" figure; that was a
**token-level** standard deviation across sequence positions, which is the wrong statistic for a
pooled per-row surface. Standardisation is still correct and still applied — the honest
justification is a 1.6–3.3× spread. See `CORRECTIONS.md` C10.

Standardisation statistics are fitted on **TRAIN canonical rows only** and frozen; `data.py`
applies that one file to every split. Post-normalisation per-surface std is exactly 1.0 on TRAIN and
0.9928–1.0047 on DEV, which is only possible if DEV never contributed.

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

**Caveat worth carrying:** the trained graft does **not** rely on this depth diversity. Removing
all six surfaces at once changes candidate legality by −0.0004, and zeroing `s` inside the
candidate path changes it by −0.0004. The earned capability lives entirely in the candidate-local
branch. Do not design a depth-diversity mechanism on the assumption that this lane uses one.

## Architecture

```
MiniCPM hidden stack
   -> 6 typed surface projections   u_i = P_i(x_i)     one per surface, NOT shared
   -> global semantic state         s   = rho_s([u_1..u_6])
   -> candidate-conditioned states  e_j = rho_e([c_j ; s])
   -> typed heads + action endpoint
```

The six `u_i` are returned as an explicit **surface memory bank** so a later intervention can
reread them without reworking the base interface. No recurrence, no IHA, no LoRA, no stochasticity,
no cross-surface attention, no backbone adaptation.

**Action endpoint semantics:** one logit per candidate, `[B, m]`, masked CE over the candidates a
world actually has, padded slots masked so they can never be selected. Chance is
`1/15.69 = 0.0637`, not `1/28`. An earlier version of this lane inherited the encoder's mis-shaped
`m × m_cap` head; see `CORRECTIONS.md` C9 for the three-lane lineage audit.

## Inherited constraints — the contract, not the graft

The encoder's architecture is **not** being ported. These are program-level lessons, banked:

1. **Exhaustive candidates.** `m_cap = 28`, measured over 140,000 canonical worlds. The encoder's
   24 silently dropped 21,016 worlds (15% of the universe) and 567,254 candidates.
2. **No raw latent-matching loss.** `||s(x) - s(x̃)||²` is minimised at constant `s`; it drove
   `D_s` to 0.0007 while looking like success. Enforce consistency on *predictions* (JS).
3. **Diversity is not competence.** `D_s > 0` did not imply discrimination — the encoder reached
   `D_s` 1.84 with every global target still at 0.500, and this lane sits at 0.496 with the same
   result.
4. **Paired correctness, not naked renderer agreement.** A constant predictor is perfectly
   renderer-stable for the wrong reason. Always report the 2×2 decomposition. On this lane it
   dissociates cleanly: global sources are *unstable* (70–89 disagreements of 188) and below
   trivial, while `candidate_legal` has **zero** disagreements at 0.7553.
5. **No duplicate-source weighting.** 13 BANK heads resolve to **6 independent canonical
   sources**; weight over sources, `L_g = (1/|H_g|) Σ_h L_h`.
6. **Balanced objective, correct selection, pre-registered margins.** Class-imbalanced BCE is
   minimised by the prior; select on `J_select` over unique source groups.
7. **No generic global-token/candidate-token recurrent mixer.** Encoder Phase 4A moved state
   enormously while destroying candidate conditioning (6.53 → 1.53).
8. **Aggregate metrics can be majority-class artifacts.** This lane's endpoint is 0.4672, which is
   *exactly* the NOOP share. Action-type breakdowns are mandatory, not optional.
9. **Port the contract, not the graft.**

## Layout

```
src/substrate_contract.py   frozen identity + inherited lessons (the thing not to change)
src/qualify_substrate.py   Phase 0 substrate qualification
src/fit_surface_stats.py   TRAIN-only frozen surface statistics
src/extract_primitives.py  BANK-v1 -> six RAW surfaces + entity spans
src/topup_primitives.py    reach the exhaustive joinable contract; never overwrite the base
src/data.py                population, candidates, canonical supervision
src/ontology.py            13 targets, 6 independent sources, alias map
src/objective.py           inherited five-term contract; raw latent L_R absent and forbidden
src/graft.py               six projections, surface memory bank, typed heads
src/pairs.py               renderer pairs + simulator-verified truth-changing pairs
src/gate.py                Phase 0 engineering exit gate
src/phase1.py              Phase 1 baseline + surface-contribution diagnostic
src/joint_ablation.py      joint all-u-zero / s-zero ablations
src/gold_sufficiency.py    parameter-free gold action-sufficiency ladder
```

Artifacts: `D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm\`
Docs: `PHASE1.md` (results), `CORRECTIONS.md` (corrections, read first).

Protected/test truth unopened, BANK-v2 unused, canonical splits unchanged, backbone frozen,
cross-agent alignment forbidden and asserted.
