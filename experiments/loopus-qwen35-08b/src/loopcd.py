"""LoopCD: contrast between the first and final recurrent states.

Training-free extrapolation along the recurrence direction (as specified in the
experiment brief; the paper itself was not reachable from the build container):

  hidden: h' = h_R + w * (h_R - h_1), then ONE decoder + norm + LM-head pass
  logits: z' = z_R + w * (z_R - z_1)
  adaptive: w = w_max * (1 - (p1 - p2)),  p1/p2 = top-2 probs of softmax(z_R)

The method presumes a weak -> strong trajectory (h_1 worse than h_R). The
evaluator checks that premise before sweeping w.
"""
from __future__ import annotations

import torch


def contrast_hidden(h_first: torch.Tensor, h_last: torch.Tensor, w) -> torch.Tensor:
    """w may be a float or a tensor broadcastable to h (e.g. (B, T, 1))."""
    return h_last + w * (h_last - h_first)


def contrast_logits(z_first: torch.Tensor, z_last: torch.Tensor, w) -> torch.Tensor:
    return z_last + w * (z_last - z_first)


def adaptive_strength(z_ref: torch.Tensor, w_max: float) -> torch.Tensor:
    """Per-token w = w_max * (1 - (p1 - p2)), shape (..., 1). Confident -> w small."""
    p = torch.softmax(z_ref.float(), dim=-1)
    top2 = p.topk(2, dim=-1).values
    return (w_max * (1.0 - (top2[..., 0] - top2[..., 1]))).unsqueeze(-1)
