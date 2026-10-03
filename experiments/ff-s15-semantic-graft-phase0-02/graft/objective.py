"""Shared loss semantics, applied within one fabric; never cross-fabric coordinates."""
from __future__ import annotations

import torch
from torch.nn import functional as F


def eligible_row_mean(per_row, eligible, zero):
    return per_row[eligible].mean() if eligible.any() else zero


def supervised_terms(output, batch):
    gl, cl = output["global_logits"], output["candidate_logits"]
    zero = gl.sum() * 0 + cl.sum() * 0
    gm = batch["global_available"]
    cm = batch["candidate_available"] & batch["candidate_mask"].unsqueeze(-1)
    semantic = F.binary_cross_entropy_with_logits(gl, batch["global_y"], reduction="none")
    semantic = torch.cat((semantic[:, :5], F.smooth_l1_loss(gl[:, 5:], batch["global_y"][:, 5:], reduction="none")), -1)
    epistemic = F.binary_cross_entropy_with_logits(cl, batch["candidate_y"], reduction="none")
    # Sum available target coordinates (and candidates), then average eligible worlds in batch.
    S = eligible_row_mean(semantic.masked_fill(~gm, 0).sum(-1), gm.any(-1), zero)
    E = eligible_row_mean(epistemic.masked_fill(~cm, 0).sum((1, 2)), cm.any((1, 2)), zero)
    return S, E


def action_loss(output, batch):
    available = batch["action_available"]
    logits = output["action_logits"]
    if not available.any():
        return logits.sum() * 0
    targets = batch["action_target"][available]
    legal_index = (targets >= 0) & (targets < logits.shape[1])
    if not legal_index.all() or not batch["candidate_mask"][available].gather(1, targets[:, None]).all():
        raise ValueError("action endpoint target not present in candidate set")
    return F.cross_entropy(logits[available], targets)


def contrast_loss(positive_score, negative_score, direction, available, margin=1.0):
    """Direction must express a canonical candidate-support change, not action legality."""
    if not available.any():
        return positive_score.sum() * 0 + negative_score.sum() * 0
    y = direction[available]
    if not ((y == 1) | (y == -1)).all():
        raise ValueError("contrast direction must be +1/-1")
    return torch.relu(margin - y * (positive_score[available] - negative_score[available])).mean()


def renderer_loss(left, right, left_mask, right_mask):
    if left_mask.shape != right_mask.shape or not torch.equal(left_mask, right_mask):
        raise ValueError("renderer candidates must be identity-aligned")
    semantic = (left["s"] - right["s"]).square().sum(-1)
    differences = (left["e"] - right["e"]).square().sum(-1)
    count = left_mask.sum(-1)
    if not (count > 0).all():
        raise ValueError("renderer pair has no aligned candidates")
    epistemic = differences.masked_fill(~left_mask, 0).sum(-1) / count
    return (semantic + epistemic).mean()


def shared_objective(output, batch, config, renderer=None, contrast=None):
    S, E = supervised_terms(output, batch)
    A = action_loss(output, batch)
    zero = S * 0 + E * 0 + A * 0
    R = renderer_loss(*renderer) if renderer is not None else zero
    CF = contrast_loss(*contrast, margin=config["loss"]["contrast_margin"]) if contrast is not None else zero
    terms = {"S": S, "E": E, "A": A, "CF": CF, "R": R}
    total = sum(config["loss"]["lambda_" + name] * value for name, value in terms.items())
    counts = {"semantic_rows": int(batch["global_available"].any(-1).sum()),
              "epistemic_candidates": int((batch["candidate_available"].any(-1) & batch["candidate_mask"]).sum()),
              "action_rows": int(batch["action_available"].sum()),
              "renderer_pairs": int(renderer[0]["s"].shape[0]) if renderer is not None else 0,
              "contrast_pairs": int(contrast[3].sum()) if contrast is not None else 0}
    return total, {**{name: float(value.detach()) for name, value in terms.items()}, "active": counts}
