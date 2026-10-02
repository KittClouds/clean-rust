"""Memory-safe readout over a large vocabulary (Qwen3.5: 248,320 tokens).

Never materialises ``(B, T, V)`` logits: tokens are processed in chunks, and for
training each chunk is wrapped in ``torch.utils.checkpoint`` so the chunk's
logits are recomputed in backward instead of stored.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint


def shift(normed: torch.Tensor, labels: torch.Tensor, valid: torch.Tensor | None = None):
    """Next-token alignment. Returns flat ``(N, D)`` hidden and ``(N,)`` labels (-100 = ignore)."""
    h = normed[:, :-1, :]
    y = labels[:, 1:].clone()
    if valid is not None:
        y[valid[:, 1:] == 0] = -100
    return h.reshape(-1, h.shape[-1]), y.reshape(-1)


def _chunk_ce(h: torch.Tensor, w: torch.Tensor, y: torch.Tensor):
    z = (h @ w.t()).float()
    ce = F.cross_entropy(z, y, ignore_index=-100, reduction="none")      # (n,)
    correct = (z.argmax(-1) == y) & (y != -100)
    return ce, correct


def per_token_ce(h: torch.Tensor, w: torch.Tensor, y: torch.Tensor, chunk: int = 2048,
                 grad: bool = False) -> tuple[torch.Tensor, torch.Tensor]:
    """Per-token CE (0 at ignored positions) and top-1-correct mask, both ``(N,)``."""
    ces, cors = [], []
    for i in range(0, h.shape[0], chunk):
        hc, yc = h[i:i + chunk], y[i:i + chunk]
        if grad and torch.is_grad_enabled():
            ce, cor = checkpoint(_chunk_ce, hc, w, yc, use_reentrant=False)
        else:
            ce, cor = _chunk_ce(hc, w, yc)
        ces.append(ce)
        cors.append(cor)
    return torch.cat(ces), torch.cat(cors)


def mean_ce(h: torch.Tensor, w: torch.Tensor, y: torch.Tensor, chunk: int = 2048, grad: bool = False):
    """Mean CE over valid tokens + top-1 correct mask."""
    ce, cor = per_token_ce(h, w, y, chunk, grad)
    n = (y != -100).sum().clamp(min=1)
    return ce.sum() / n, cor


def _new_stats() -> dict:
    return dict(nll=0.0, n=0, correct=0, p_margin=0.0, logit_margin=0.0, entropy=0.0)


def _acc_stats(s: dict, z: torch.Tensor, yy: torch.Tensor) -> None:
    """Accumulate statistics of logits ``z`` (n, V) against targets ``yy`` (n,) into ``s``."""
    lp = torch.log_softmax(z, -1)
    s["nll"] += float(-lp.gather(-1, yy[:, None]).sum())
    s["n"] += int(yy.numel())
    s["correct"] += int((z.argmax(-1) == yy).sum())
    top2p = lp.exp().topk(2, -1).values
    top2z = z.topk(2, -1).values
    s["p_margin"] += float((top2p[:, 0] - top2p[:, 1]).sum())
    s["logit_margin"] += float((top2z[:, 0] - top2z[:, 1]).sum())
    s["entropy"] += float(-(lp.exp() * lp).sum())


@torch.no_grad()
def token_stats(h: torch.Tensor, w: torch.Tensor, y: torch.Tensor, chunk: int = 2048) -> dict:
    """Evaluation statistics at one depth (sums, so batches can be merged exactly)."""
    s = _new_stats()
    for i in range(0, h.shape[0], chunk):
        hc, yc = h[i:i + chunk], y[i:i + chunk]
        m = yc != -100
        if m.any():
            _acc_stats(s, (hc[m] @ w.t()).float(), yc[m])
    return s


@torch.no_grad()
def contrast_logit_stats(h_first: torch.Tensor, h_last: torch.Tensor, w: torch.Tensor, y: torch.Tensor,
                         omega: float | None, w_max: float | None = None, chunk: int = 2048) -> dict:
    """LoopCD-Logits: z' = z_R + omega (z_R - z_1), computed chunk-wise.

    Pass ``omega=None`` and ``w_max`` for the adaptive strength w_max (1 - (p1 - p2)) of z_R.
    """
    s = _new_stats()
    for i in range(0, h_last.shape[0], chunk):
        yc = y[i:i + chunk]
        m = yc != -100
        if not m.any():
            continue
        z1 = (h_first[i:i + chunk][m] @ w.t()).float()
        zr = (h_last[i:i + chunk][m] @ w.t()).float()
        if omega is None:
            p = torch.softmax(zr, -1).topk(2, -1).values
            om = (w_max * (1.0 - (p[:, 0] - p[:, 1]))).unsqueeze(-1)
        else:
            om = omega
        _acc_stats(s, zr + om * (zr - z1), yc[m])
    return s


def merge_stats(a: dict | None, b: dict) -> dict:
    return dict(b) if a is None else {k: a[k] + b[k] for k in b}


def finalize_stats(s: dict) -> dict:
    n = max(s["n"], 1)
    return {"nll": s["nll"] / n, "ppl": float(torch.exp(torch.tensor(s["nll"] / n))),
            "top1": s["correct"] / n, "p1_minus_p2": s["p_margin"] / n,
            "logit_margin": s["logit_margin"] / n, "entropy": s["entropy"] / n, "tokens": s["n"]}
