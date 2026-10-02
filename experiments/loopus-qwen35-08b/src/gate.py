"""Recurrence gates for the looped reasoning block.

Both gates map ``(h_new, h_old) -> h_next`` where ``h_new = f(h_old)`` is one
application of the shared reasoning block. They are *damped fixed-point
updates*: ``h_next = h_old + g * (h_new - h_old)`` with ``g`` in (0, 1).

``LoopUSGate`` is a faithful port of ``SelectiveGate`` in Thrillcrazyer/LoopUS
(``models/modeling_lds.py``). Note: its docstring talks about re-injecting
``x_init`` but the code gates between the new and the *previous* iterate; that
is what is ported here.

``SigmoidGate`` is an alternative with an explicit, controllable identity
init (``g ~= g0`` everywhere at init, input-dependent after training).
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class LoopUSGate(nn.Module):
    """ZOH-discretised selective decay (Mamba-style), as in LoopUS.

    A_bar = exp(delta * A),  A = -exp(A_log) < 0,  delta = softplus(W_dt(W_in(h_new - h_old)))
    h_next = A_bar * h_new + (1 - A_bar) * h_old

    Init (copied from LoopUS): A_log = log(1..D) (S4D-real), dt log-uniform in
    [1e-3, 1e-1]. Low-index channels therefore accept the block update, high
    index channels (|A| large) keep the old state: the map is close to the
    identity for most channels at init.
    """

    def __init__(self, hidden_size: int, dt_rank: int | None = None,
                 dt_min: float = 1e-3, dt_max: float = 1e-1,
                 dt_scale: float = 1.0, dt_init_floor: float = 1e-4):
        super().__init__()
        if dt_rank is None:
            dt_rank = math.ceil(hidden_size / 16)
        self.dt_rank = dt_rank
        self.delta_proj = nn.Linear(dt_rank, hidden_size, bias=True)
        self.dt_input_proj = nn.Linear(hidden_size, dt_rank, bias=False)
        self.A_log = nn.Parameter(torch.log(torch.arange(1, hidden_size + 1, dtype=torch.float32)))

        dt_init_std = dt_rank ** -0.5 * dt_scale
        nn.init.uniform_(self.delta_proj.weight, -dt_init_std, dt_init_std)
        dt = torch.exp(
            torch.rand(hidden_size) * (math.log(dt_max) - math.log(dt_min)) + math.log(dt_min)
        ).clamp(min=dt_init_floor)
        inv_dt = dt + torch.log(-torch.expm1(-dt))  # softplus inverse
        with torch.no_grad():
            self.delta_proj.bias.copy_(inv_dt)

    def forward(self, h_new: torch.Tensor, h_old: torch.Tensor) -> torch.Tensor:
        orig = h_new.dtype
        pdt = self.dt_input_proj.weight.dtype
        h_new, h_old = h_new.to(pdt), h_old.to(pdt)
        delta = F.softplus(self.delta_proj(self.dt_input_proj(h_new - h_old)))
        a_bar = torch.exp(delta * -torch.exp(self.A_log))
        return (a_bar * h_new + (1 - a_bar) * h_old).to(orig)

    @torch.no_grad()
    def mean_gate(self) -> float:
        """Mean A_bar at zero input: how much of the block update is accepted at init."""
        delta = F.softplus(self.delta_proj.bias)
        return float(torch.exp(delta * -torch.exp(self.A_log)).mean())


class SigmoidGate(nn.Module):
    """g = sigmoid(b + W2 W1 (h_new - h_old));  h_next = h_old + g * (h_new - h_old).

    ``W2`` is zero-initialised so at init ``g == g0`` exactly, for every token and
    channel: a controlled, uniform damping that is near-identity for small g0.
    """

    def __init__(self, hidden_size: int, rank: int | None = None, g0: float = 0.05):
        super().__init__()
        rank = rank or max(8, hidden_size // 16)
        self.down = nn.Linear(hidden_size, rank, bias=False)
        self.up = nn.Linear(rank, hidden_size, bias=True)
        nn.init.zeros_(self.up.weight)
        with torch.no_grad():
            self.up.bias.fill_(math.log(g0 / (1 - g0)))

    def forward(self, h_new: torch.Tensor, h_old: torch.Tensor) -> torch.Tensor:
        orig = h_new.dtype
        pdt = self.down.weight.dtype
        h_new, h_old = h_new.to(pdt), h_old.to(pdt)
        g = torch.sigmoid(self.up(self.down(h_new - h_old)))
        return (h_old + g * (h_new - h_old)).to(orig)

    @torch.no_grad()
    def mean_gate(self) -> float:
        return float(torch.sigmoid(self.up.bias).mean())


def build_gate(kind: str, hidden_size: int, **kw) -> nn.Module | None:
    if kind in (None, "none"):
        return None
    if kind == "loopus":
        return LoopUSGate(hidden_size, **kw)
    if kind == "sigmoid":
        return SigmoidGate(hidden_size, **kw)
    raise ValueError(f"unknown gate kind {kind!r}")
