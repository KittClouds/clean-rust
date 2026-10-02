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


@torch.no_grad()
def evaluate_adaptive(model: LoopedQwen35, conf_head, windows: torch.Tensor, max_R: int, thresholds,
                      batch_size: int = 2, device="cpu", chunk: int = 2048, max_batches: int | None = None) -> dict:
    """Quality vs compute for confidence early exit: one entry per threshold.

    ``mean_exit_depth`` is the compute proxy (reasoning-block applications per sequence).
    """
    from .train_loopus import adaptive_exit
    model.eval()
    w = model.lm_head.weight
    out = {}
    for thr in thresholds:
        stats, depth_sum, n_seq, nb = None, 0.0, 0, 0
        for x, m, y in D.batches(windows, batch_size, seed=0, epochs=1, device=device):
            if max_batches and nb >= max_batches:
                break
            nb += 1
            normed, depth, _ = adaptive_exit(model, conf_head, x, m, max_R, thr)
            hh, yy = shift(normed, y, m)
            stats = merge_stats(stats, token_stats(hh, w, yy, chunk))
            depth_sum += float(depth.sum())
            n_seq += x.shape[0]
        r = finalize_stats(stats)
        r["mean_exit_depth"] = depth_sum / max(n_seq, 1)
        out[float(thr)] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="local HF directory of Qwen3.5-0.8B-Base")
    ap.add_argument("--corpus", required=True, help=".jsonl (input_text) / .txt / .md / directory")
    ap.add_argument("--depths", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--seq-len", type=int, default=256)
    ap.add_argument("--max-docs", type=int, default=2000, help="keep identical to train_loopus.py")
    ap.add_argument("--max-batches", type=int, default=64)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--loopcd", action="store_true")
    ap.add_argument("--adaptive", action="store_true", help="confidence early-exit curve (needs --checkpoint)")
    ap.add_argument("--max-R", type=int, default=8)
    ap.add_argument("--checkpoint", help="trained LoopUS state (from train_loopus.py)")
    ap.add_argument("--gate", default="none", choices=["none", "loopus", "sigmoid"])
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dt = getattr(torch, a.dtype) if dev == "cuda" else torch.float32
    hf = AutoModelForCausalLM.from_pretrained(a.model, dtype=dt).to(dev)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = LoopedQwen35(hf, gate=a.gate).to(dev)
    from .train_loopus import ConfidenceHead, load_trainable
    conf = ConfidenceHead(hf.config.hidden_size).to(dev, dtype=dt)
    if a.checkpoint:
        load_trainable(model, conf, a.checkpoint, map_location=dev)
    texts = D.read_texts(a.corpus, limit=a.max_docs)
    _, held_docs = D.split_docs(texts, val_frac=0.2, seed=0)       # same split as train_loopus.py
    held = D.pack(held_docs, lambda t: tok(t, add_special_tokens=False)["input_ids"], a.seq_len)
    res = evaluate_depths(model, held, a.depths, a.batch_size, dev, loopcd=a.loopcd, max_batches=a.max_batches)
    if a.adaptive:
        res["adaptive"] = evaluate_adaptive(model, conf, held, a.max_R, (0.3, 0.5, 0.7, 0.8, 0.9, 1.01),
                                            a.batch_size, dev, max_batches=a.max_batches)
    res["meta"] = {"model": a.model, "corpus": a.corpus, "seq_len": a.seq_len, "windows": int(held.shape[0]),
                   "gate": a.gate, "split": model.split_summary()}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2))
    for d, r in res["depths"].items():
        print(f"R={d}: nll={r['nll']:.4f} top1={r['top1']:.3f} drift={r['rel_drift_vs_h1']:.3f} "
              f"cos={r['cos_vs_h1']:.3f} norm={r['state_norm']:.1f} t={r['seconds_cumulative']:.2f}s")


if __name__ == "__main__":
    main()
