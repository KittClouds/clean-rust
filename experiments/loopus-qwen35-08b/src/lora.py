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
    def __init__(self, base: nn.Linear, rank: int, alpha: float):
        super().__init__()
        self.base = base
        self.rank = rank
        self.scale = alpha / rank
        dev = base.weight.device
        self.A = nn.Parameter(torch.empty(rank, base.in_features, dtype=torch.float32, device=dev))
        self.B = nn.Parameter(torch.zeros(base.out_features, rank, dtype=torch.float32, device=dev))
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.base(x)
        delta = F.linear(F.linear(x.float(), self.A), self.B) * self.scale
        return y + delta.to(y.dtype)


def apply_lora(model, layer_idx, rank: int = 32, alpha: float | None = None,
               skip=DEFAULT_SKIP) -> int:
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
            setattr(parent, cname, LoRALinear(child, rank, alpha))
            n += 1
    return n


def lora_parameters(model):
    for m in model.modules():
        if isinstance(m, LoRALinear):
            yield m.A
            yield m.B
