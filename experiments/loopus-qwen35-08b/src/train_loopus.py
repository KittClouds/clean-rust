"""LoopUS-style post-training for the looped Qwen3.5 stack.

Follows the structure of Thrillcrazyer/LoopUS (training_runtime.py):
  * encoder frozen / run under no_grad, one trajectory of N recursion steps per batch
  * random deep supervision: ``n_sup`` of the N depths are supervised, the rest are
    run under no_grad; the state is detached after every supervised step
    (one-step gradients, no BPTT)
  * loss at a supervised depth t:
        CE_t + beta * SiLU(CE_t - CE_{t-1}) + conf_weight * BCE(conf_t, top1_correct)
    ``CE_{t-1}`` is the (no-grad) CE of the previous iterate, so the monotonicity
    term only penalises a step that makes the LM worse.

Deliberate differences from the reference (all isolated to this experiment):
  * gradients of the n_sup losses are accumulated and applied in ONE optimizer
    step per batch, so one trajectory is produced by one set of weights
  * the first pass is never gated, so ``R=1`` stays the pretrained forward
  * the confidence head is per-token (predicts "argmax is correct") on the
    detached state; sequence confidence = mean over valid tokens
  * the LM readout is chunked + checkpointed (248k vocab)
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, asdict, field
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

from . import data as D
from .looped import LoopedQwen35
from .readout import mean_ce, shift


class ConfidenceHead(nn.Module):
    """Per-token logit that the top-1 prediction at this state is correct."""

    def __init__(self, hidden_size: int):
        super().__init__()
        self.net = nn.Sequential(nn.LayerNorm(hidden_size), nn.Linear(hidden_size, 1))

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        return self.net(h.to(self.net[1].weight.dtype)).squeeze(-1)


@dataclass
class TrainCfg:
    n_reasoning_steps: int = 8          # N: trajectory length
    n_supervision: int = 3              # supervised depths sampled per batch
    min_supervised_depth: int = 1
    lr: float = 5e-5
    gate_lr_mult: float = 10.0
    weight_decay: float = 0.0
    beta: float = 1.0                   # monotonicity weight
    conf_weight: float = 1.0
    grad_clip: float = 1.0
    scope: str = "block+dec"            # gate | block | block+dec
    ce_chunk: int = 1024
    seed: int = 0
    log_every: int = 10
    extra: dict = field(default_factory=dict)


def set_trainable(model: LoopedQwen35, scope: str) -> list[nn.Parameter]:
    for p in model.parameters():
        p.requires_grad_(False)
    groups: list[nn.Module] = []
    if model.gate is not None:
        groups.append(model.gate)
    if scope in ("block", "block+dec"):
        groups += [model.text.layers[i] for i in model.rea_idx]
    if scope == "block+dec":
        groups += [model.text.layers[i] for i in model.dec_idx] + [model.text.norm]
    if scope not in ("gate", "block", "block+dec"):
        raise ValueError(scope)
    params = []
    for g in groups:
        for p in g.parameters():
            p.requires_grad_(True)
            params.append(p)
    return params


def supervision_loss(model: LoopedQwen35, conf_head: ConfidenceHead, ctx, h_old: torch.Tensor, t: int,
                     labels: torch.Tensor, mask: torch.Tensor, cfg: TrainCfg):
    """One supervised recursion step from a detached state. Returns (loss, new_state, metrics)."""
    w = model.lm_head.weight
    h = model.step(h_old, ctx, first=(t == 1))
    hh, yy = shift(model.decode(h, ctx), labels, mask)
    ce, correct = mean_ce(hh, w, yy, cfg.ce_chunk, grad=True)

    mono = torch.zeros((), device=ce.device)
    if t > 1:
        with torch.no_grad():
            hp, _ = shift(model.decode(h_old, ctx), labels, mask)
            ce_prev, _ = mean_ce(hp, w, yy, cfg.ce_chunk)
        mono = F.silu(ce - ce_prev)

    valid = (yy != -100)
    conf_logit = conf_head(h.detach()[:, :-1, :].reshape(-1, h.shape[-1]))
    conf_bce = F.binary_cross_entropy_with_logits(conf_logit[valid].float(), correct[valid].float())

    loss = ce + cfg.beta * mono + cfg.conf_weight * conf_bce
    n = max(int(valid.sum()), 1)
    metrics = dict(depth=t, ce=float(ce.detach()), mono=float(mono.detach()), conf_bce=float(conf_bce.detach()),
                   acc=float(correct.sum()) / n, conf=float(torch.sigmoid(conf_logit[valid].detach()).mean()))
    return loss, h, metrics


def train(model: LoopedQwen35, conf_head: ConfidenceHead, batch_iter, steps: int, cfg: TrainCfg,
          log=print) -> list[dict]:
    rng = random.Random(cfg.seed)
    params = set_trainable(model, cfg.scope)
    gate_params = list(model.gate.parameters()) if model.gate is not None else []
    gate_ids = {id(p) for p in gate_params}
    other = [p for p in params if id(p) not in gate_ids]
    groups = [{"params": other, "lr": cfg.lr}]
    if gate_params:
        groups.append({"params": gate_params, "lr": cfg.lr * cfg.gate_lr_mult})
    groups.append({"params": list(conf_head.parameters()), "lr": cfg.lr * cfg.gate_lr_mult})
    opt = torch.optim.AdamW(groups, weight_decay=cfg.weight_decay)
    history: list[dict] = []

    model.train()
    conf_head.train()
    lo = max(1, cfg.min_supervised_depth)
    for step, (x, m, y) in zip(range(steps), batch_iter):
        with torch.no_grad():
            ctx = model.prepare(x, m)
            h = model.encode(ctx)
        sup = set(rng.sample(range(lo, cfg.n_reasoning_steps + 1), cfg.n_supervision))
        opt.zero_grad(set_to_none=True)
        per_depth = []
        for t in range(1, cfg.n_reasoning_steps + 1):
            if t in sup:
                loss, h_next, met = supervision_loss(model, conf_head, ctx, h.detach(), t, y, m, cfg)
                (loss / cfg.n_supervision).backward()
                met["loss"] = float(loss.detach())
                per_depth.append(met)
                h = h_next.detach()
            else:
                with torch.no_grad():
                    h = model.step(h, ctx, first=(t == 1))
        gn = torch.nn.utils.clip_grad_norm_(params + list(conf_head.parameters()), cfg.grad_clip)
        opt.step()
        rec = {"step": step, "grad_norm": float(gn), "supervised": sorted(sup), "per_depth": per_depth,
               "loss": sum(d["loss"] for d in per_depth) / len(per_depth)}
        history.append(rec)
        if cfg.log_every and step % cfg.log_every == 0:
            log(f"[train] step {step} loss={rec['loss']:.4f} gn={rec['grad_norm']:.2f} "
                + " ".join(f"d{d['depth']}:ce={d['ce']:.3f}" for d in per_depth))
    model.eval()
    conf_head.eval()
    return history


@torch.no_grad()
def adaptive_exit(model: LoopedQwen35, conf_head: ConfidenceHead, input_ids: torch.Tensor,
                  attention_mask: torch.Tensor | None, max_R: int, threshold: float):
    """Per-sequence confidence early exit (no cache, so freezing a sequence is safe).

    Returns ``(normed_hidden, exit_depth, ctx)``; ``exit_depth`` is 1-indexed.
    A sequence exits at the first depth whose mean valid-token confidence >= threshold.
    """
    ctx = model.prepare(input_ids, attention_mask)
    h = model.encode(ctx)
    b = input_ids.shape[0]
    mask = (attention_mask if attention_mask is not None else torch.ones_like(input_ids)).bool()
    active = torch.ones(b, dtype=torch.bool, device=h.device)
    exit_depth = torch.full((b,), max_R, dtype=torch.long, device=h.device)
    for t in range(1, max_R + 1):
        h_new = model.step(h, ctx, first=(t == 1))
        h = torch.where(active.view(-1, 1, 1), h_new, h)
        conf = torch.sigmoid(conf_head(h).float())
        seq_conf = (conf * mask).sum(1) / mask.sum(1).clamp(min=1)
        newly = active & (seq_conf >= threshold)
        exit_depth[newly] = t
        active = active & ~newly
        if not bool(active.any()):
            break
    return model.decode(h, ctx), exit_depth, ctx


def save_trainable(model: LoopedQwen35, conf_head: ConfidenceHead, path: str) -> None:
    """Save only what training changed (``requires_grad`` params + confidence head)."""
    sd = {f"model.{n}": p.detach().cpu() for n, p in model.named_parameters() if p.requires_grad}
    sd.update({f"conf.{k}": v.detach().cpu() for k, v in conf_head.state_dict().items()})
    torch.save(sd, path)


def load_trainable(model: LoopedQwen35, conf_head: ConfidenceHead | None, path: str, map_location="cpu") -> None:
    sd = torch.load(path, map_location=map_location)
    own = dict(model.named_parameters())
    for k, v in sd.items():
        if k.startswith("model."):
            own[k[len("model."):]].data.copy_(v)
    if conf_head is not None:
        conf_head.load_state_dict({k[len("conf."):]: v for k, v in sd.items() if k.startswith("conf.")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--gate", default="sigmoid", choices=["loopus", "sigmoid"])
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--seq-len", type=int, default=256)
    ap.add_argument("--max-docs", type=int, default=2000, help="keep identical to eval_depth.py")
    ap.add_argument("--N", type=int, default=8)
    ap.add_argument("--n-sup", type=int, default=3)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--scope", default="block+dec", choices=["gate", "block", "block+dec"])
    ap.add_argument("--grad-checkpoint", action="store_true")
    ap.add_argument("--out", required=True, help="output dir")
    a = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dt = torch.bfloat16 if dev == "cuda" else torch.float32
    hf = AutoModelForCausalLM.from_pretrained(a.model, dtype=dt).to(dev)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = LoopedQwen35(hf, gate=a.gate, grad_checkpoint=a.grad_checkpoint).to(dev)
    conf = ConfidenceHead(hf.config.hidden_size).to(dev, dtype=dt)
    texts = D.read_texts(a.corpus, limit=a.max_docs)
    train_docs, held_docs = D.split_docs(texts, val_frac=0.2, seed=0)
    enc = lambda t: tok(t, add_special_tokens=False)["input_ids"]      # noqa: E731
    train_w, held = D.pack(train_docs, enc, a.seq_len), D.pack(held_docs, enc, a.seq_len)
    cfg = TrainCfg(n_reasoning_steps=a.N, n_supervision=a.n_sup, lr=a.lr, scope=a.scope)
    hist = train(model, conf, D.batches(train_w, a.batch_size, seed=cfg.seed, epochs=None, device=dev),
                 a.steps, cfg)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    save_trainable(model, conf, str(out / "trainable.pt"))
    (out / "history.json").write_text(json.dumps({"cfg": asdict(cfg), "history": hist}))
    torch.save(held, out / "heldout_windows.pt")


if __name__ == "__main__":
    main()
