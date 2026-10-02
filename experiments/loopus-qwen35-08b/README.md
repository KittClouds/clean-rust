# loopus-qwen35-08b — looped `Qwen/Qwen3.5-0.8B-Base` (LoopUS + LoopCD ideas)

Isolated experiment. It does **not** touch the parked encoder lineage and is not folded into System 1.5.
Model: `D:\phoenix-models\qwen3.5-0.8b-base` (text backbone, 24 layers = 18 gated-delta + 6 full-attention,
752,393,024 params). All runs: one RTX 3080 (12 GB), bf16 base, `transformers 5.17`, Triton `fla` kernels.

## One-paragraph result

A frozen pretrained block cannot be looped, so LoopCD has no weak→strong trajectory to extrapolate. LoopUS-style
post-training (decay gate + LoRA + random deep supervision + monotonicity/confidence losses) **does not make depth
useful**: the objective is satisfied by making iterations ≥ 2 idempotent, on natural-language NLL *and* on a serial
multi-hop task. Supervising depth *t* only on examples that need ≤ c·*t* serial steps ("depth-matched") does produce real
depth use (R=2 beats R=1 by +4 pts overall and +9…17 pts on k=5–9, the hop counts assigned to depth 2–3) and therefore a genuine
weak→strong trajectory. LoopCD on that trajectory is at best marginal (≤ +0.8 pt overall, NLL ≤ −0.02, with per-k effects of both
signs). But **in no regime tested did the loop beat a one-pass control fine-tuned on the same stream**: 62.3 % vs 49.4 % (10 nodes,
k ≤ 12) and, in the pre-registered warm-start test on a task where one pass genuinely runs out (26 nodes), −14.9 pts on k=5–8
against a +5 criterion. Everything is LoRA r=32, ≤ 2,000 steps, one seed — see "What this does and does not establish".

## Provenance (read this before trusting any commit)

The experiment was started locally, then continued in a CPU-only cloud session that had no model access. That
session rebuilt the trainable stack and pushed it as `e3ef2e74` onto **`origin/freeze/phoenix-2026-09-27`** (a frozen
branch — it does not belong there). This branch (`loopus-qwen35-08b-2026-10-02`) merges that code with the
locally verified frozen construction and is the only place with real-checkpoint results.

## Layout

| path | what |
|---|---|
| `src/frozen_loop.py` | independent frozen-weights loop (produced `premise.json`); reads disk safetensors for the weight-identity gate |
| `src/looped.py` | trainable `LoopedQwen35`: shared HF modules, per-layer mask dispatch on `config.layer_types[abs_idx]`, no cache, first pass never gated (R=1 ≡ pretrained) |
| `src/gate.py` | `LoopUSGate` (faithful port of the repo's `SelectiveGate`) and `SigmoidGate` (explicit identity init) |
| `src/loopcd.py`, `src/readout.py` | LoopCD hidden/logit/adaptive contrast; chunked, checkpointed 248,320-vocab readout |
| `src/lora.py` | LoRA on the shared block + decoder (full FT of ~436 M block params needs ~7 GB of fp32 state; does not fit 12 GB) |
| `src/train_loopus.py` | LoopUS-style trainer (random supervised depths, one-step detached gradients, mono + confidence losses, warmup/cosine, per-sequence early exit, optional `label_fn` for depth-matched supervision) |
| `src/eval_depth.py`, `src/train_loopus.py` CLI | WikiText/BANK depth sweeps (+LoopCD) |
| `src/hops.py`, `src/train_hops.py` | serial k-hop pointer-following task, evaluator, LoopCD evaluator, CLI for every arm |
| `src/validate_real.py`, `validate_real.json` | real-checkpoint gates |
| `results/` | per-run eval logs, args, histories; `final_*` = large-n final evals |
| `run_*.sh` | exact commands for each experiment |
| `tests/` | 46 tests (toy hybrid Qwen3.5 config; CPU routes to the reference gated-delta kernel) |

## Gates (real checkpoint, `validate_real.json`)

weights **EXACT** vs safetensors · R=1 logits **bit-identical** to HF (max diff 0.0) · states **bit-identical** to the
independent frozen reference at R=1/2/4/8 · LoRA gradients through the Triton gated-delta kernel match the
pure-PyTorch reference (cosine 0.9993, norm ratio 0.997).

Split (measured from depth geometry, `geometry.json`): encoder = layers 0–1, reasoning block = 2–22 (21 layers), decoder = 23.

## Results

### 1. Frozen loop diverges; training-free LoopCD is unavailable
WikiText-103 validation (40 batches × 4 × 512 tokens), NLL at R = 1 / 2 / 4 / 8: **2.899 / 3.366 / 5.196 / 8.410**
(BANK-v1 TRAIN, `premise.json`: 2.630 / 3.035 / 4.480 / 7.652). Every LoopCD variant (hidden / logits, ω ∈ {0.25, 0.5, 1}, adaptive) is worse than plain `h_R`, which
is itself worse than `h_1` (`results/frozen_wikival.json`).

### 2. LoopUS-style training on WikiText-103 NLL (LoRA r=32, lr 1e-5, warmup 100)
Reference (full val, 480 windows): pretrained R=1 **2.8943**; no-loop control R=1 **2.6220**.

| run | what happened |
|---|---|
| lr 2e-4, no warmup | **control CE rose 2.56 → 4.49 in 10 steps** (a no-loop run, so not a looping effect) — full-size Adam sign-steps over ~19 M adapter params. |
| lr 1e-4, 100-step warmup | still wrong: held-out NLL 3.30 at step 100 vs 2.91 untouched. Gradients were verified correct (Triton vs reference cosine 0.9993), so this was step scale. LR sweep on the control (3e-6 / 1e-5 / 3e-5 → **2.789 / 2.682 / 2.694** at 200 steps) → lr 1e-5. |
| N=8, gate g₀=0.05 (stopped at step 600) | R=1/2/4/8 all **2.658** (control at 600: 2.643). Gate never opened: mean g = 0.0494. Depth inert. |
| N=4, gate forced open g₀=0.5 (stopped after the step-200 eval) | step 0 R=1/2/4/8 = 2.913 / 3.033 / 3.738 / 5.781 (diverging, as frozen); step 200: **2.690 / 2.690 / 2.691 / 2.696** — LoRA made the block idempotent in ~100 steps; gate bias unmoved (g = 0.495). |

Reading: next-token loss is not a testbed where depth can pay — the one-pass state is already good, and "do nothing after pass 1" minimises every supervised depth.

### 3. Serial k-hop pointer following (random permutation of letters; answer = node after k steps; chance 10 % at 10 nodes)
`C>F K>A …\nStart C, 3 steps ->` → ` K`. Loss on the single answer token. A random *function* was measured first and
rejected: long walks fall into short cycles, giving a ~50 % floor from shortcuts; permutations remove that.
Same seeded stream, LoRA r=32 and optimizer for every arm; zero-shot is ~0 % (format unseen).

| exp | arm | result (accuracy %, n = 1000/k for exp 1, 500/k for exp 3) |
|---|---|---|
| 1, k≤6 | control N=1 | R=1 **77.6** overall; k=1..6 = 99.9/99.8/99.9/99.4/97.9/81.1; unseen k=7,8 = 20.1/20.9 |
| 1, k≤6 | loop N=4, 2 sup. depths, g₀=0.5 | R=1/2/4/8 = **74.9 / 75.1 / 75.0 / 74.2** — iterations inert; worse than control at R=1 |
| 2, k≤12 | loop N=3 (stopped at step ~525) | depth-flat at both evals (R=1…6 within ±1.5 pts) |
| 3, k≤12 | **depth-matched** loop N=3, c=4 | R=1/2/3/4 = **44.9 / 48.8 / 49.2 / 49.4**; k=5: 12→25–27, k=6: 20→35–37, k=7: 19→36–37, k=8: 28→37–38 |
| 3, k≤12 | control N=1 (the exp-2 control; same stream, 2000 steps) | R=1 **62.3** overall; k=5/6/7/8 = 79.9/65.9/54.1/55.8 |

**LoopCD on the depth-matched model** (reference `h_1`; `results/final_h3_dm4_N3/loopcd_R*.json`), R=2, overall accuracy / NLL:
base `z_R` 48.8 / 1.585 · hidden ω=0.25 48.9 / 1.566 · hidden ω=0.5 48.5 · hidden adaptive 48.0 · logits ω=0.25 47.1 · logits ω=0.5 45.6 · logits ω=1 43.2 · logits adaptive 44.5.
Per-k effects are large and of both signs (logits ω=0.25: k=5 24.7→36.8, k=12 41.0→24.2) and net out to ~0.

### 4. Shortcut-resistant task (26 nodes): where does one pass run out?
Same task with all 26 letters (long cycles; chance 3.8 %). Control (N=1, 1500 steps, batch 16, n=100/k): k=1…6 =
100/100/99.0/96.0/56.2/33.3, k≥7 ≈ 7–20 % — so one pass handles **k ≤ 4**, a real ceiling with room above it.
The depth-matching constant was set **prospectively** from this by script (largest contiguous k with ≥ 90 % → **c = 4**; `results/h4_control_N1/prospective_c.txt`).
The from-scratch depth-matched loop arm (N=4, 2 supervised depths) **failed to train** — at step 1000 even k=2 was at chance (5 %) while the control had
100 % — because depth 1 only receives the ~5 examples/batch with k ≤ 4, on half the steps. That is an optimisation failure, not a capacity result; stopped at step ~1100 and reported as inconclusive (`results/h4_dm_N4/`).

### 5. Post-train a capable one-pass model into a loop (what LoopUS does) — pre-registered
Both arms warm-start from the exp-4 control and train 1000 more steps on the same stream (seed 1, lr 5e-5). A: control continued (N=1).
B: depth-matched loop, c=4, N=3, gate g₀=0.5. **Criterion (fixed before running): loop best-R accuracy exceeds continued-control R=1 by ≥ 5 pts averaged over k=5…8.**
Final, n=300/k (`results/final_h5_*`):

| k | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | all |
|---|---|---|---|---|---|---|---|---|---|
| control continued, R=1 | 100 | 100 | 99.7 | 99.6 | **68.7** | **42.0** | 17.4 | 14.7 | 40.3 |
| loop R=1 | 100 | 100 | 99.0 | 89.3 | 14.6 | 8.9 | 7.9 | 11.5 | 33.3 |
| loop R=2 | 100 | 100 | 99.0 | 87.9 | 39.6 | 20.7 | 10.8 | 11.9 | 35.9 |
| loop R=3 | 100 | 100 | 98.7 | 89.0 | 39.6 | 19.3 | 10.8 | 13.6 | 36.1 |

Mean over k=5…8: control 35.7 vs loop best (R=3) 20.8 → **−14.9 pts. Criterion not met.** Depth does help the loop (R=1→R=2 on k=5: 14.6→39.6), but
depth-matching also *removes* the one-pass handling of k=5–6 (loop R=1 fell from the warm-start's 70.7/39.6 to 14.6/8.9), and R≥2 does not recover it.
LoopCD at R=2 (`loopcd_R2.json`): base 35.9 / NLL 2.196; logits ω=0.25 **36.7** / 2.179 (best); hidden ω=0.5 36.5; adaptive 36.0–36.2. It is consistently positive on the band where
h₂ > h₁ (k=5/6/7, logits ω=0.25: 39.6→45.2, 20.7→25.2, 10.8→17.1; SE ≈ 2.8 each) and negative on k=4 (87.9→85.3 at ω=0.25, 76.5 at ω=0.5), netting +0.3…+0.8 overall.

## What this does and does not establish

* **Established (measured, gated):** the construction is correct; frozen looping diverges on this backbone; the LoopUS-style objective
  collapses to idempotent iterations at this budget on both tasks; depth-matched supervision yields real depth use; LoopCD gains are marginal
  (positive only on the band where the reference is weak, negative elsewhere); a one-pass control matches or beats the looped model in every
  comparison made, including the pre-registered one.
* **Not established:** anything at LoopUS's actual scale (they post-train far longer, full-parameter). Everything here is LoRA r=32, ≤ 2,000
  steps of ~1–3 k tokens, **one seed**, and the hop task is synthetic. The depth-matched loop was run once per setting (no seed variance). The
  failure of the from-scratch 26-node loop arm (exp 4) is an optimisation failure and says nothing about capacity.
* The k=9…12 rows of the 10-node task carry cycle shortcuts (composite k lets "answer = start" score ~50 %); they inflate every arm equally and are not evidence of multi-hop composition.
* Pilots 1 and 2, exp 2's loop arm and exp 4's loop arm were **stopped early by decision** (reasons above); they are reported at the step reached, not as completed runs.
* Where a loop could still win (untested): much longer / full-parameter post-training; a loop that is *initialised from* depth-aware weights; supervising depth 1 on the full distribution while letting later depths refine; larger models where one pass genuinely cannot reach the answer.

## Reproduce
```
pip install triton-windows<3.8 pyarrow pytest        # fla kernels need Triton; WikiText parquet; tests
python src/validate_real.py                            # real-checkpoint gates
python src/prep_corpus.py                              # corpus/ from the downloaded WikiText-103 shards + BANK-v1 TRAIN
python -m pytest tests -q
bash run_pilot1.sh | run_pilot2.sh | run_hops1.sh | run_hops2.sh | run_hops3.sh | run_hops4.sh | run_hops5.sh   # hops* need --n-nodes/--init-from as in the scripts
```
Always train with `--grad-checkpoint` on LM runs (≈ 11 GB without it → shared-memory thrash on Windows; 5 GB with).
