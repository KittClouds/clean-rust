"""Q-only per-event weighted v0.5 loss. The denominator remains batch size."""

from __future__ import annotations

import torch
from torch.nn import functional as F

CALIBRATION_SOURCES = {
    "exact_generative_posterior",
    "empirical_annotator_distribution",
    "elicited_subjective_probability",
    "adjudicated_distribution",
}


def event_weights(arm: str, primary_count: int, auxiliary_count: int, *, device: torch.device) -> torch.Tensor:
    """Create the contracted row weights in trainer concatenation order."""
    if arm not in {"B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW"}:
        raise ValueError(f"unknown Q arm: {arm}")
    if primary_count < 0 or auxiliary_count < 0 or primary_count + auxiliary_count == 0:
        raise ValueError("invalid Q primary/auxiliary row counts")
    values = [1.0] * primary_count
    auxiliary_weight = 0.5 if arm == "B-SHAM-LOW" else 1.0
    values.extend([auxiliary_weight] * auxiliary_count)
    return torch.tensor(values, dtype=torch.float32, device=device)


def q_weighted_loss(
    logits: torch.Tensor,
    gold: torch.Tensor,
    mask: torch.Tensor,
    kinds: list[str],
    sources: list[str],
    brier_weight: float,
    row_weights: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Apply prospective per-row weights to semantic and Brier terms.

    `row_weights` is one for ordinary events and exactly 0.5 for SHAM-LOW
    auxiliary events. The arithmetic-mean denominator remains the number of
    active rows, so the dose cannot be normalized away.
    """
    if logits.ndim != 2 or gold.shape != logits.shape or mask.shape != logits.shape:
        raise ValueError("Q loss tensors must be equally shaped [batch, candidates]")
    if len(kinds) != len(logits) or len(sources) != len(logits):
        raise ValueError("Q loss metadata length differs from batch size")
    weights = row_weights.to(device=logits.device, dtype=logits.dtype)
    if weights.shape != (len(logits),) or not bool(torch.isfinite(weights).all().item()):
        raise ValueError("Q per-event weights must be a finite vector matching the batch")
    if bool(torch.any(weights <= 0).item()):
        raise ValueError("Q per-event weights must be positive")

    semantic = torch.zeros((), device=logits.device)
    brier = torch.zeros((), device=logits.device)
    for row, kind in enumerate(kinds):
        valid = mask[row]
        source = sources[row]
        if kind == "independent":
            prediction = torch.sigmoid(logits[row, 0])
            probability = gold[row, 0]
            semantic_row = F.binary_cross_entropy_with_logits(logits[row, 0], probability)
            brier_row = (prediction - probability).square() if source in CALIBRATION_SOURCES else None
        else:
            row_logits = logits[row][valid]
            row_gold = gold[row][valid]
            log_probability = F.log_softmax(row_logits, dim=0)
            probability = log_probability.exp()
            semantic_row = -(row_gold * log_probability).sum()
            brier_row = (probability - row_gold).square().sum() if source in CALIBRATION_SOURCES else None
        semantic = semantic + weights[row] * semantic_row
        if brier_row is not None:
            brier = brier + weights[row] * brier_row

    divisor = max(1, len(logits))
    mean_brier = brier / divisor
    return semantic / divisor + brier_weight * mean_brier, mean_brier
