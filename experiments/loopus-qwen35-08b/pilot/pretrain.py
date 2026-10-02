"""Stage A: pretrain the toy hybrid LM (this plays the role of the 'pretrained base')."""
import argparse
import json
import math
import time

import torch

from common import ROOT, load_windows, new_pretrained
from src import data as D

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--steps", type=int, default=1500)
ap.add_argument("--batch", type=int, default=16)
ap.add_argument("--lr", type=float, default=3e-3)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()

torch.manual_seed(a.seed)
torch.set_num_threads(4)
train_w, held_w = load_windows()
held_w = held_w[:1024]
print(f"train windows {tuple(train_w.shape)}  held-out windows {tuple(held_w.shape)}", flush=True)
m = new_pretrained()
opt = torch.optim.AdamW(m.parameters(), lr=a.lr, betas=(0.9, 0.95), weight_decay=0.1)
warm = 50
sched = torch.optim.lr_scheduler.LambdaLR(
    opt, lambda s: min(1.0, (s + 1) / warm) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(s, a.steps) / a.steps))))


@torch.no_grad()
def heldout():
    m.eval()
    tot, n = 0.0, 0
    for x, _, y in D.batches(held_w, 32, epochs=1):
        tot += float(m(input_ids=x, labels=y).loss) * (x.shape[0] * (x.shape[1] - 1))
        n += x.shape[0] * (x.shape[1] - 1)
    m.train()
    return tot / n


log = []
m.train()
t0 = time.time()
it = D.batches(train_w, a.batch, seed=a.seed, epochs=None)
for step in range(a.steps + 1):
    if step % 250 == 0 or step == a.steps:
        ho = heldout()
        log.append({"step": step, "heldout_nll": ho, "heldout_bpc": ho / math.log(2), "secs": time.time() - t0})
        print(log[-1], flush=True)
    if step == a.steps:
        break
    x, _, y = next(it)
    loss = m(input_ids=x, labels=y).loss
    loss.backward()
    torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
    opt.step(); sched.step(); opt.zero_grad(set_to_none=True)

torch.save(m.state_dict(), a.out)
(ROOT / "results").mkdir(exist_ok=True)
(ROOT / "results" / "pilot_pretrain.json").write_text(json.dumps(
    {"steps": a.steps, "batch": a.batch, "seq": 128, "lr": a.lr, "params": sum(p.numel() for p in m.parameters()),
     "train_windows": int(train_w.shape[0]), "heldout_windows": int(held_w.shape[0]), "log": log}, indent=2))
print("saved", a.out)
