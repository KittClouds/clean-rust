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
import math
import random
from dataclasses import dataclass, asdict, field
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

from . import data as D
from .looped import LoopedQwen35
from .lora import LoRALinear, apply_lora, lora_parameters
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
    warmup: int = 0                     # linear LR warmup steps (0 = off)
    lr_min_frac: float = 1.0            # cosine-decay floor as a fraction of lr (1.0 = constant)
    scope: str = "block+dec"            # gate | block | block+dec
    ce_chunk: int = 1024
    seed: int = 0
    log_every: int = 10
    extra: dict = field(default_factory=dict)


def lr_factor(i: int, steps: int, warmup: int, lr_min_frac: float) -> float:
    """Multiplier on the base LR at optimizer step ``i``: linear warmup, then cosine to ``lr_min_frac``."""
    warm = min(1.0, (i + 1) / warmup) if warmup > 0 else 1.0
    prog = min(max(i - warmup, 0) / max(steps - warmup, 1), 1.0)
    return warm * (lr_min_frac + (1.0 - lr_min_frac) * 0.5 * (1.0 + math.cos(math.pi * prog)))


SCOPES = ("gate", "lora", "block", "block+dec")


def set_trainable(model: LoopedQwen35, scope: str) -> list[nn.Parameter]:
    """Freeze everything, then enable the scope. ``lora`` trains only the adapters (+ gate)."""
    if scope not in SCOPES:
        raise ValueError(scope)
    for p in model.parameters():
        p.requires_grad_(False)
    params: list[nn.Parameter] = []

    def enable(ps):
        for p in ps:
            p.requires_grad_(True)
            params.append(p)

    if model.gate is not None:
        enable(model.gate.parameters())
    if scope == "lora":
        enable(lora_parameters(model))
    if scope in ("block", "block+dec"):
        for i in model.rea_idx:
            enable(model.text.layers[i].parameters())
    if scope == "block+dec":
        for i in model.dec_idx:
            enable(model.text.layers[i].parameters())
        enable(model.text.norm.parameters())
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
          log=print, on_step=None, label_fn=None) -> list[dict]:
    """``batch_iter`` yields ``(x, mask, labels[, aux])``. If ``label_fn`` is given, the labels
    supervised at recursion depth ``t`` are ``label_fn(t, labels, aux)`` (e.g. depth-matched
    curricula that only ask depth ``t`` to solve examples needing <= c*t serial steps). A depth
    whose filtered labels are all ignored is run without a loss."""
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

    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda i: lr_factor(i, steps, cfg.warmup, cfg.lr_min_frac))
    history: list[dict] = []

    model.train()
    conf_head.train()
    lo = max(1, cfg.min_supervised_depth)
    for step, batch in zip(range(steps), batch_iter):
        x, m, y, *rest = batch
        aux = rest[0] if rest else None
        with torch.no_grad():
            ctx = model.prepare(x, m)
            h = model.encode(ctx)
        sup = set(rng.sample(range(lo, cfg.n_reasoning_steps + 1), cfg.n_supervision))
        opt.zero_grad(set_to_none=True)
        per_depth = []
        for t in range(1, cfg.n_reasoning_steps + 1):
            y_t = label_fn(t, y, aux) if label_fn is not None else y
            if t in sup and int(((y_t[:, 1:] != -100) & (m[:, 1:] == 1)).sum()) > 0:
                loss, h_next, met = supervision_loss(model, conf_head, ctx, h.detach(), t, y_t, m, cfg)
                (loss / cfg.n_supervision).backward()
                met["loss"] = float(loss.detach())
                per_depth.append(met)
                h = h_next.detach()
            else:
                with torch.no_grad():
                    h = model.step(h, ctx, first=(t == 1))
        gn = torch.nn.utils.clip_grad_norm_(params + list(conf_head.parameters()), cfg.grad_clip)
        opt.step()
        sched.step()
        rec = {"step": step, "grad_norm": float(gn), "supervised": sorted(sup), "per_depth": per_depth,
               "loss": sum(d["loss"] for d in per_depth) / max(len(per_depth), 1)}
        history.append(rec)
        if on_step is not None:
            on_step(step, rec)
            model.train()
            conf_head.train()
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


def build_model(hf, gate: str = "sigmoid", scope: str = "lora", lora_rank: int = 32,
                lora_alpha: float | None = None, grad_checkpoint: bool = False,
                gate_kwargs: dict | None = None, split: dict | None = None,
                lora_passes: int = 1) -> LoopedQwen35:
    """Wrap an HF Qwen3.5 in the looped stack; ``scope='lora'`` also adapts the block + decoder.
    ``split`` = dict(enc=, reasoning=, dec=) inclusive ranges; default is the measured 0-1/2-22/23."""
    m = LoopedQwen35(hf, gate=gate, gate_kwargs=gate_kwargs, grad_checkpoint=grad_checkpoint, **(split or {}))
    if scope == "lora":
        # per-pass adapters only inside the looped block; the decoder runs once, so it keeps one adapter
        apply_lora(m, m.rea_idx, lora_rank, lora_alpha, n_passes=lora_passes)
        apply_lora(m, m.dec_idx, lora_rank, lora_alpha)
    dev = next(hf.parameters()).device
    return m.to(dev)


def save_trainable(model: LoopedQwen35, conf_head: ConfidenceHead, path: str, meta: dict | None = None) -> None:
    """Save only what training changed (``requires_grad`` params + confidence head) and a ``meta``
    dict that is enough to rebuild the wrapper (gate kind, LoRA rank, ...)."""
    sd = {f"model.{n}": p.detach().cpu() for n, p in model.named_parameters() if p.requires_grad}
    sd.update({f"conf.{k}": v.detach().cpu() for k, v in conf_head.state_dict().items()})
    if meta is not None:
        sd["__meta__"] = meta
    torch.save(sd, path)


def load_trainable(model: LoopedQwen35, conf_head: ConfidenceHead | None, path: str, map_location="cpu") -> None:
    sd = torch.load(path, map_location=map_location)
    own = dict(model.named_parameters())
    for k, v in sd.items():
        if k.startswith("model."):
            name = k[len("model."):]
            if name in own:
                own[name].data.copy_(v)
            else:                                # warm-start a per-pass model from a single-adapter checkpoint
                targets = [own[f"{name}.{i}"] for i in range(64) if f"{name}.{i}" in own]
                if not targets:
                    raise KeyError(name)
                for t in targets:
                    t.data.copy_(v)
    if conf_head is not None:
        conf_head.load_state_dict({k[len("conf."):]: v for k, v in sd.items() if k.startswith("conf.")})


def load_checkpoint(hf, path: str, device: str = "cuda"):
    """Rebuild wrapper + confidence head from a checkpoint written by ``save_trainable(meta=...)``."""
    sd = torch.load(path, map_location=device)
    meta = sd["__meta__"]
    model = build_model(hf, gate=meta["gate"], scope=meta["scope"], lora_rank=meta.get("lora_rank", 32),
                        lora_alpha=meta.get("lora_alpha"), gate_kwargs=meta.get("gate_kwargs"),
                        split=meta.get("split"), lora_passes=meta.get("lora_passes", 1))
    conf = ConfidenceHead(hf.config.hidden_size).to(device)
    load_trainable(model, conf, path, map_location=device)
    return model.eval(), conf.eval(), meta


def main():
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from .eval_depth import evaluate_depths

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=r"D:\phoenix-models\qwen3.5-0.8b-base")
    ap.add_argument("--train-corpus", required=True)
    ap.add_argument("--val-corpus", required=True)
    ap.add_argument("--max-docs", type=int, default=4000)
    ap.add_argument("--gate", default="sigmoid", choices=["loopus", "sigmoid", "none"])
    ap.add_argument("--g0", type=float, default=0.05, help="sigmoid gate init")
    ap.add_argument("--scope", default="lora", choices=list(SCOPES))
    ap.add_argument("--lora-rank", type=int, default=32)
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--seq-len", type=int, default=512)
    ap.add_argument("--N", type=int, default=8, help="trajectory length")
    ap.add_argument("--n-sup", type=int, default=3)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--lr-min-frac", type=float, default=0.1)
    ap.add_argument("--gate-lr-mult", type=float, default=10.0)
    ap.add_argument("--beta", type=float, default=1.0, help="monotonicity weight")
    ap.add_argument("--conf-weight", type=float, default=1.0)
    ap.add_argument("--eval-every", type=int, default=100)
    ap.add_argument("--eval-batches", type=int, default=8)
    ap.add_argument("--eval-depths", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--grad-checkpoint", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True, help="output dir")
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dt = torch.bfloat16 if dev == "cuda" else torch.float32
    hf = AutoModelForCausalLM.from_pretrained(a.model, dtype=dt).to(dev)
    tok = AutoTokenizer.from_pretrained(a.model)
    gate_kwargs = {"g0": a.g0} if a.gate == "sigmoid" else None
    model = build_model(hf, a.gate, a.scope, a.lora_rank, None, a.grad_checkpoint, gate_kwargs)
    conf = ConfidenceHead(hf.config.hidden_size).to(dev)
    cache = Path(a.out).parent / "_windows"
    train_w = D.load_windows(a.train_corpus, tok, a.seq_len, a.max_docs, cache, shuffle_docs_seed=a.seed)
    val_w = D.load_windows(a.val_corpus, tok, a.seq_len, None, cache)
    cfg = TrainCfg(n_reasoning_steps=a.N, n_supervision=min(a.n_sup, a.N), lr=a.lr,
                   gate_lr_mult=a.gate_lr_mult, warmup=a.warmup, lr_min_frac=a.lr_min_frac, beta=a.beta, conf_weight=a.conf_weight, seed=a.seed, log_every=10)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = dict(vars(a), gate_kwargs=gate_kwargs, lora_rank=a.lora_rank, lora_alpha=None, cfg=asdict(cfg),
                train_windows=int(train_w.shape[0]), val_windows=int(val_w.shape[0]))
    (out / "args.json").write_text(json.dumps(meta, indent=2))
    print(f"train windows {tuple(train_w.shape)}  val windows {tuple(val_w.shape)}", flush=True)
    n_train = sum(p.numel() for p in set_trainable(model, a.scope)) + sum(p.numel() for p in conf.parameters())
    print(f"trainable params: {n_train/1e6:.2f}M", flush=True)

    elog = (out / "eval_log.jsonl").open("a", encoding="utf-8")

    def on_step(step: int, rec: dict) -> None:
        if step % a.eval_every != 0 and step != a.steps - 1:
            return
        res = evaluate_depths(model, val_w, a.eval_depths, a.batch_size, dev, chunk=512, max_batches=a.eval_batches)
        row = {"step": step, "train_loss": rec["loss"],
               "val": {d: {k: round(r[k], 4) for k in ("nll", "top1", "state_norm", "cos_vs_h1")}
                       for d, r in res["depths"].items()}}
        elog.write(json.dumps(row) + "\n")
        elog.flush()
        print(f"[eval] step {step} " + " | ".join(f"R{d}: nll={r['nll']:.3f} top1={r['top1']:.3f} |h|={r['state_norm']:.0f}"
                                                  for d, r in res["depths"].items()), flush=True)
        save_trainable(model, conf, str(out / "trainable.pt"), meta)

    hist = train(model, conf, D.batches(train_w, a.batch_size, seed=cfg.seed, epochs=None, device=dev),
                 a.steps, cfg, on_step=on_step)
    save_trainable(model, conf, str(out / "trainable.pt"), meta)
    (out / "history.json").write_text(json.dumps({"cfg": asdict(cfg), "history": hist}))
    print("done ->", out, flush=True)


if __name__ == "__main__":
    main()
