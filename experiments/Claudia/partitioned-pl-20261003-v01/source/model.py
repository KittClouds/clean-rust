"""One boring candidate-independent scorer, 365 -> 128 -> 64 -> 1, GELU. Frozen before any DEV scoring.

No candidate self-attention, recurrence, comparator, LoRA, access organ or legality head: a single scalar utility per
candidate. All three arms start from the SAME initial weights (``build(seed)`` is deterministic) so the only thing that
differs between them is the ranking likelihood.
"""
import torch
import torch.nn as nn

from data import TOKEN_DIM


class Scorer(nn.Module):
    def __init__(self, d_in=TOKEN_DIM, h1=128, h2=64):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d_in, h1), nn.GELU(), nn.Linear(h1, h2), nn.GELU(), nn.Linear(h2, 1))

    def forward(self, x, key_mask=None):
        return self.net(x).squeeze(-1)


def build(seed=0):
    torch.manual_seed(seed)
    return Scorer()


def count_params(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
