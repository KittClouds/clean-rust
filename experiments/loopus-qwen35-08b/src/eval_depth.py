"""Teacher-forced loop-depth evaluation (+ optional LoopCD sweep).

Per depth R: NLL / top-1 / p1-p2 / logit margin / entropy, hidden-state drift
against h_1 (relative L2 and cosine), state norm, and cumulative wall time.
One recursion trajectory per batch serves every requested depth.

LoopCD is only meaningful if h_R beats h_1, so the premise is checked per depth
(`premise_hR_beats_h1`) and the sweep is skipped when it fails unless
``force_loopcd=True``.

CLI (real model, on a GPU box):
  python -m src.eval_depth --model D:/phoenix-models/qwen3.5-0.8b-base \
      --corpus <path/to/TRAIN.jsonl> --depths 1 2 4 8 --out results/frozen_depth.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from . import data as D
from .looped import LoopedQwen35
from .readout import (contrast_logit_stats, finalize_stats, merge_stats, shift, token_stats)
from .loopcd import contrast_hidden, adaptive_strength


def _sync(dev):
    if torch.device(dev).type == "cuda":
        torch.cuda.synchronize()


@torch.no_grad()
def evaluate_depths(model: LoopedQwen35, windows: torch.Tensor, depths=(1, 2, 4, 8), batch_size: int = 2,
                    device="cpu", chunk: int = 2048, omegas=(0.25, 0.5, 1.0), w_max: float = 1.0,
                    loopcd: bool = False, force_loopcd: bool = False, max_batches: int | None = None) -> dict:
    model.eval()
    w = model.lm_head.weight
    depths = sorted(set(depths))
    dmax = depths[-1]
    stats = {d: None for d in depths}
    drift = {d: dict(rel=0.0, cos=0.0, norm=0.0, n=0) for d in depths}
    secs = {d: 0.0 for d in depths}
    cd_stats: dict[str, dict[int, dict | None]] = {}

    def cd_add(name, d, s):
        cd_stats.setdefault(name, {})
        cd_stats[name][d] = merge_stats(cd_stats[name].get(d), s)

    n_batches = 0
    for x, m, y in D.batches(windows, batch_size, seed=0, epochs=1, device=device):
        if max_batches and n_batches >= max_batches:
            break
        n_batches += 1
        ctx = model.prepare(x, m)
        _sync(device)
        t0 = time.perf_counter()
        h = model.encode(ctx)
        st = {}
        for t in range(1, dmax + 1):
            h = model.step(h, ctx, first=(t == 1))
            if t == 1 or t in depths:
                st[t] = h
            if t in depths:
                _sync(device)
                secs[t] += time.perf_counter() - t0
        h1 = st[1]
        valid = m.bool()
        normed = {}
        for d in depths:
            normed[d] = model.decode(st[d], ctx)
            hh, yy = shift(normed[d], y, m)
            stats[d] = merge_stats(stats[d], token_stats(hh, w, yy, chunk))
            hd, h1v = st[d][valid].float(), h1[valid].float()
            drift[d]["rel"] += float(((hd - h1v).norm(dim=-1) / h1v.norm(dim=-1).clamp(min=1e-6)).sum())
            drift[d]["cos"] += float(torch.nn.functional.cosine_similarity(hd, h1v, dim=-1).sum())
            drift[d]["norm"] += float(hd.norm(dim=-1).sum())
            drift[d]["n"] += int(valid.sum())

        if loopcd:
            n1 = normed[depths[0]] if depths[0] == 1 else model.decode(h1, ctx)
            hh1, _ = shift(n1, y, m)
            for d in depths:
                if d == 1:
                    continue
                for om in omegas:
                    hp = contrast_hidden(h1, st[d], om)
                    hp_n, yy = shift(model.decode(hp, ctx), y, m)
                    cd_add(f"hidden_w{om}", d, token_stats(hp_n, w, yy, chunk))
                    hh, yy = shift(normed[d], y, m)
                    cd_add(f"logits_w{om}", d, contrast_logit_stats(hh1, hh, w, yy, om, chunk=chunk))
                # adaptive strength: hidden variant uses per-token w from z_R's top-2 margin
                hh, yy = shift(normed[d], y, m)
                cd_add(f"logits_adaptive_wmax{w_max}", d,
                       contrast_logit_stats(hh1, hh, w, yy, None, w_max=w_max, chunk=chunk))
                zr_ref = model.logits(normed[d])
                hp = contrast_hidden(h1, st[d], adaptive_strength(zr_ref, w_max))
                del zr_ref
                hp_n, yy = shift(model.decode(hp, ctx), y, m)
                cd_add(f"hidden_adaptive_wmax{w_max}", d, token_stats(hp_n, w, yy, chunk))

    res = {"batches": n_batches, "depths": {}}
    for d in depths:
        r = finalize_stats(stats[d])
        n = max(drift[d]["n"], 1)
        r.update(rel_drift_vs_h1=drift[d]["rel"] / n, cos_vs_h1=drift[d]["cos"] / n,
                 state_norm=drift[d]["norm"] / n, seconds_cumulative=secs[d])
        res["depths"][d] = r
    if loopcd:
        res["loopcd"] = {}
        for name, per_d in cd_stats.items():
            res["loopcd"][name] = {}
            for d, s in per_d.items():
                r = finalize_stats(s)
                base = res["depths"][d]["nll"]
                r["delta_nll_vs_hR"] = r["nll"] - base
                r["delta_nll_vs_h1_baseline"] = r["nll"] - res["depths"][1]["nll"] if 1 in res["depths"] else None
                res["loopcd"][name][d] = r
        res["premise_hR_beats_h1"] = {d: res["depths"][d]["nll"] < res["depths"][1]["nll"]
                                      for d in depths if d > 1 and 1 in res["depths"]}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=r"D:\phoenix-models\qwen3.5-0.8b-base", help="local HF directory")
    ap.add_argument("--corpus", required=True, help="held-out .jsonl (every window is scored)")
    ap.add_argument("--depths", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--seq-len", type=int, default=512)
    ap.add_argument("--max-batches", type=int, default=None, help="default: all windows")
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--loopcd", action="store_true")
    ap.add_argument("--omegas", type=float, nargs="+", default=[0.25, 0.5, 1.0])
    ap.add_argument("--w-max", type=float, default=1.0)
    ap.add_argument("--checkpoint", help="trained state from train_loopus.py (self-describing)")
    ap.add_argument("--gate", default="none", choices=["none", "loopus", "sigmoid"],
                    help="only for a checkpoint-free gated model; checkpoints carry their own gate")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dt = getattr(torch, a.dtype) if dev == "cuda" else torch.float32
    hf = AutoModelForCausalLM.from_pretrained(a.model, dtype=dt).to(dev)
    tok = AutoTokenizer.from_pretrained(a.model)
    if a.checkpoint:
        from .train_loopus import load_checkpoint
        model, _, meta = load_checkpoint(hf, a.checkpoint, dev)
    else:
        model, meta = LoopedQwen35(hf, gate=a.gate).to(dev), {"gate": a.gate, "scope": "none"}
    for p in model.parameters():
        p.requires_grad_(False)
    windows = D.load_windows(a.corpus, tok, a.seq_len, None, Path(a.out).parent / "_windows")
    res = evaluate_depths(model, windows, a.depths, a.batch_size, dev, chunk=512, loopcd=a.loopcd,
                          omegas=tuple(a.omegas), w_max=a.w_max, max_batches=a.max_batches)
    res["meta"] = {"model": a.model, "corpus": a.corpus, "seq_len": a.seq_len, "windows": int(windows.shape[0]),
                   "checkpoint": a.checkpoint, "train_meta": {k: meta.get(k) for k in ("gate", "scope", "N", "n_sup", "steps")},
                   "split": model.split_summary()}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2))
    for d, r in res["depths"].items():
        print(f"R={d}: nll={r['nll']:.4f} top1={r['top1']:.3f} drift={r['rel_drift_vs_h1']:.3f} "
              f"cos={r['cos_vs_h1']:.3f} norm={r['state_norm']:.1f} t={r['seconds_cumulative']:.2f}s")
    if a.loopcd:
        print("premise h_R beats h_1:", res.get("premise_hR_beats_h1"))
        base1 = res["depths"][min(a.depths)]["nll"]
        for name, per in res["loopcd"].items():
            print(f"  {name}: " + "  ".join(f"R{d}={r['nll']:.4f}" for d, r in per.items()), f"(R1 baseline {base1:.4f})")


if __name__ == "__main__":
    main()
