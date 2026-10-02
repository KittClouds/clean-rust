"""Minimal LoRA for the shared reasoning block.

Why LoRA here: full fine-tuning the 21-layer block (~436M params) needs fp32 master weights plus
Adam state (~7 GB) on top of everything else, which does not fit a 12 GB card. LoRA keeps the
frozen bf16 base, trains small fp32 adapters, and because the adapter lives *inside* the layer
module it is shared by every loop iteration exactly like the base weights are.

``B`` is zero-initialised, so a freshly wrapped model is bit-identical to the base model.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

# Tiny per-head projections of the gated-delta layers (hidden -> num_heads); not worth adapting.
DEFAULT_SKIP = ("in_proj_a", "in_proj_b")


class LoRALinear(nn.Module):
    """``n_passes > 1`` gives one adapter per recursion pass (the base weight stays shared);
    ``cur`` selects the pass (clamped to the last adapter). ``n_passes == 1`` keeps the plain
    ``A`` / ``B`` parameter names so older checkpoints still load."""

    def __init__(self, base: nn.Linear, rank: int, alpha: float, n_passes: int = 1):
        super().__init__()
        self.base = base
        self.rank = rank
        self.scale = alpha / rank
        self.n_passes = n_passes
        self.cur = 0
        dev = base.weight.device

        def mk_a():
            a = nn.Parameter(torch.empty(rank, base.in_features, dtype=torch.float32, device=dev))
            nn.init.kaiming_uniform_(a, a=math.sqrt(5))
            return a

        def mk_b():
            return nn.Parameter(torch.zeros(base.out_features, rank, dtype=torch.float32, device=dev))

        if n_passes == 1:
            self.A, self.B = mk_a(), mk_b()
        else:
            self.A = nn.ParameterList([mk_a() for _ in range(n_passes)])
            self.B = nn.ParameterList([mk_b() for _ in range(n_passes)])

    def _ab(self):
        if self.n_passes == 1:
            return self.A, self.B
        i = min(self.cur, self.n_passes - 1)
        return self.A[i], self.B[i]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.base(x)
        A, B = self._ab()
        delta = F.linear(F.linear(x.float(), A), B) * self.scale
        return y + delta.to(y.dtype)


def apply_lora(model, layer_idx, rank: int = 32, alpha: float | None = None,
               skip=DEFAULT_SKIP, n_passes: int = 1) -> int:
    """Wrap every ``nn.Linear`` inside ``model.text.layers[i]`` (i in layer_idx). Returns count."""
    alpha = float(rank) if alpha is None else alpha
    n = 0
    for i in layer_idx:
        targets = []
        for _, parent in model.text.layers[i].named_modules():
            for cname, child in parent.named_children():
                if isinstance(child, nn.Linear) and cname not in skip:
                    targets.append((parent, cname, child))
        for parent, cname, child in targets:
            setattr(parent, cname, LoRALinear(child, rank, alpha, n_passes))
            n += 1
    return n


def lora_parameters(model):
    for m in model.modules():
        if isinstance(m, LoRALinear):
            yield from ([m.A, m.B] if m.n_passes == 1 else [*m.A, *m.B])
