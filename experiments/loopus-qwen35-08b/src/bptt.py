"""Full-backprop looped training (no detach between passes).

LoopUS detaches the state between supervised depths, so pass 1 is only ever trained to be good at
ITS OWN answer. Here the loss is taken at the FINAL depth only and gradients flow through every
pass: the loop is trained as a (weight-tied or per-pass-adapter) deeper network. Used for the depth
test: arm A (separate adapter per pass), arm B (shared weights), vs the one-pass control.
"""
from __future__ import annotations

import torch

from .readout import mean_ce, shift
from .train_loopus import SCOPES, TrainCfg, lr_factor, set_trainable


def bptt_loss(model, ctx, x_h0, N: int, labels, mask, chunk: int = 1024):
    """CE at depth N with gradients through all N passes. Returns (loss, accuracy)."""
    h = x_h0
    for t in range(1, N + 1):
        h = model.step(h, ctx, first=(t == 1))
    hh, yy = shift(model.decode(h, ctx), labels, mask)
    ce, correct = mean_ce(hh, model.lm_head.weight, yy, chunk, grad=True)
    return ce, float(correct.sum()) / max(int((yy != -100).sum()), 1)


def train_bptt(model, batch_iter, steps: int, cfg: TrainCfg, log=print, on_step=None):
    params = set_trainable(model, cfg.scope)
    gate_ids = {id(p) for p in (model.gate.parameters() if model.gate is not None else [])}
    groups = [{"params": [p for p in params if id(p) not in gate_ids], "lr": cfg.lr}]
    if gate_ids:
        groups.append({"params": [p for p in params if id(p) in gate_ids], "lr": cfg.lr * cfg.gate_lr_mult})
    opt = torch.optim.AdamW(groups, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda i: lr_factor(i, steps, cfg.warmup, cfg.lr_min_frac))
    hist = []
    model.train()
    for step, (x, m, y) in zip(range(steps), batch_iter):
        with torch.no_grad():
            ctx = model.prepare(x, m)
            h0 = model.encode(ctx)
        opt.zero_grad(set_to_none=True)
        loss, acc = bptt_loss(model, ctx, h0, cfg.n_reasoning_steps, y, m, cfg.ce_chunk)
        loss.backward()
        gn = torch.nn.utils.clip_grad_norm_(params, cfg.grad_clip)
        opt.step()
        sched.step()
        rec = {"step": step, "loss": float(loss.detach()), "acc": acc, "grad_norm": float(gn)}
        hist.append(rec)
        if on_step is not None:
            on_step(step, rec)
            model.train()
        if cfg.log_every and step % cfg.log_every == 0:
            log(f"[bptt] step {step} ce={rec['loss']:.4f} acc={acc:.3f} gn={rec['grad_norm']:.2f}")
    model.eval()
    return hist
