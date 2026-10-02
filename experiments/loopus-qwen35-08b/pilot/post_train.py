"""Stage B/C: frozen-loop probes and LoopUS-style post-training variants on the toy model.

Variants (all start from the same pretrained toy weights; same data order, steps, lr):
  frozen_nogate            no training, plain re-application of the block (the 0.8B failure setting)
  frozen_gate_loopus       LoopUS gate at init, no training
  frozen_gate_sigmoid      sigmoid gate (g0=0.05) at init, no training
  control_noloop           continued LM training, no loop (N=1)  <- 'more training' control
  loopus_gate              faithful LoopUS gate, deep supervision, beta=1
  sigmoid_gate             sigmoid gate, deep supervision, beta=1
  sigmoid_nomono           sigmoid gate, beta=0 (ablate monotonicity loss)
  nogate                   no gate, deep supervision (plain recurrence trained)
  sigmoid_gateonly         sigmoid gate, block+decoder frozen (does damping alone help?)
"""
import argparse
import json
import time

import torch

from common import ROOT, SPLIT, load_windows, new_pretrained
from src import data as D
from src.eval_depth import evaluate_adaptive, evaluate_depths
from src.looped import LoopedQwen35
from src.train_loopus import ConfidenceHead, TrainCfg, save_trainable, train

VARIANTS = {
    "frozen_nogate": dict(gate="none", train=False),
    "frozen_gate_loopus": dict(gate="loopus", train=False),
    "frozen_gate_sigmoid": dict(gate="sigmoid", train=False),
    "control_noloop": dict(gate="none", train=True, N=1, n_sup=1),
    "loopus_gate": dict(gate="loopus", train=True),
    "sigmoid_gate": dict(gate="sigmoid", train=True),
    "sigmoid_nomono": dict(gate="sigmoid", train=True, beta=0.0),
    "nogate": dict(gate="none", train=True),
    "sigmoid_gateonly": dict(gate="sigmoid", train=True, scope="gate"),
}
DEPTHS = (1, 2, 3, 4, 6, 8, 12, 16)

ap = argparse.ArgumentParser()
ap.add_argument("--variant", required=True, choices=VARIANTS)
ap.add_argument("--pretrained", required=True)
ap.add_argument("--ckpt-dir", required=True)
ap.add_argument("--steps", type=int, default=400)
ap.add_argument("--batch", type=int, default=16)
ap.add_argument("--lr", type=float, default=3e-4)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--N", type=int, default=8)
ap.add_argument("--n-sup", type=int, default=3)
a = ap.parse_args()
v = VARIANTS[a.variant]

torch.set_num_threads(4)
torch.manual_seed(a.seed)
train_w, held_w = load_windows()
held_w = held_w[:512]
hf = new_pretrained(a.pretrained).eval()
gate_kw = dict(g0=0.05) if v["gate"] == "sigmoid" else {}
model = LoopedQwen35(hf, gate=v["gate"], gate_kwargs=gate_kw, **SPLIT)
conf = ConfidenceHead(hf.config.hidden_size)
res = {"variant": a.variant, "seed": a.seed, "spec": v, "steps": a.steps if v["train"] else 0}
if model.gate is not None:
    res["gate_mean_init"] = model.gate.mean_gate()

t0 = time.time()
if v["train"]:
    cfg = TrainCfg(n_reasoning_steps=v.get("N", a.N), n_supervision=v.get("n_sup", a.n_sup), lr=a.lr,
                   beta=v.get("beta", 1.0), scope=v.get("scope", "block+dec"), seed=a.seed, log_every=50)
    hist = train(model, conf, D.batches(train_w, a.batch, seed=a.seed, epochs=None), a.steps, cfg)
    res["train_secs"] = time.time() - t0
    tail = hist[-50:]
    per = {}
    for h in tail:
        for d in h["per_depth"]:
            per.setdefault(d["depth"], []).append(d)
    res["train_tail_per_depth"] = {k: {m: sum(x[m] for x in xs) / len(xs) for m in ("ce", "acc", "mono", "conf")}
                                   for k, xs in sorted(per.items())}
    res["loss_curve"] = [sum(h["loss"] for h in hist[i:i + 25]) / len(hist[i:i + 25]) for i in range(0, len(hist), 25)]
    save_trainable(model, conf, f"{a.ckpt_dir}/{a.variant}_s{a.seed}.pt")
    if model.gate is not None:
        res["gate_mean_trained"] = model.gate.mean_gate()

ev = evaluate_depths(model, held_w, DEPTHS, batch_size=32, loopcd=True, omegas=(0.25, 0.5, 1.0), w_max=1.0)
res["eval"] = ev
if v["train"]:
    res["adaptive"] = evaluate_adaptive(model, conf, held_w, max_R=8, thresholds=(0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01),
                                        batch_size=32)
(ROOT / "results").mkdir(exist_ok=True)
out = ROOT / "results" / f"pilot_{a.variant}_s{a.seed}.json"
out.write_text(json.dumps(res, indent=1))
print(a.variant, "done in %.0fs" % (time.time() - t0))
for d, r in ev["depths"].items():
    print(f"  R={d:>2}: nll={r['nll']:.4f} top1={r['top1']:.3f} drift={r['rel_drift_vs_h1']:.3f} norm={r['state_norm']:.1f}")
