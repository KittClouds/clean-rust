"""Frozen q-weighted metric and paired block-bootstrap helpers for Stage B."""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def q_diagnostics(weights: np.ndarray) -> dict[str, Any]:
    q = np.asarray(weights, dtype=np.float64)
    if len(q) == 0:
        return {"count": 0, "min": None, "max": None, "mean": None, "sum": 0.0, "ess": None}
    total = math.fsum(float(value) for value in q)
    squares = math.fsum(float(value) * float(value) for value in q)
    return {
        "count": int(len(q)),
        "min": float(np.min(q)),
        "max": float(np.max(q)),
        "mean": total / len(q),
        "sum": total,
        "ess": total * total / squares if squares > 0 else None,
    }


def weighted_balanced_error(logits: np.ndarray, y: np.ndarray, q: np.ndarray) -> float | None:
    pred = np.where(np.asarray(logits) > 0.0, 1, -1)
    target = np.asarray(y, dtype=np.int8)
    weights = np.asarray(q, dtype=np.float64)
    rates = []
    for label in (-1, 1):
        selected = np.flatnonzero(target == label)
        if not len(selected):
            return None
        denom = math.fsum(float(weights[index]) for index in selected)
        if denom <= 0.0:
            return None
        numerator = math.fsum(float(weights[index]) for index in selected if pred[index] != label)
        rates.append(numerator / denom)
    return 0.5 * math.fsum(rates)


def weighted_margin(logits: np.ndarray, y: np.ndarray, q: np.ndarray) -> float | None:
    target = np.asarray(y, dtype=np.int8)
    weights = np.asarray(q, dtype=np.float64)
    means = []
    for label in (-1, 1):
        selected = np.flatnonzero(target == label)
        if not len(selected):
            continue
        denom = math.fsum(float(weights[index]) for index in selected)
        if denom <= 0.0:
            return None
        means.append(math.fsum(float(weights[index]) * int(target[index]) * float(logits[index]) for index in selected) / denom)
    return math.fsum(means) / len(means) if means else None


def weighted_mean_abs(logits: np.ndarray, q: np.ndarray) -> float | None:
    weights = np.asarray(q, dtype=np.float64)
    denom = math.fsum(float(value) for value in weights)
    if denom <= 0.0:
        return None
    return math.fsum(float(weights[i]) * abs(float(logits[i])) for i in range(len(weights))) / denom


def _leverage_summary(leverage: np.ndarray, row_keys: list[bytes]) -> dict[str, Any]:
    values = np.asarray(leverage, dtype=np.float64)
    total = math.fsum(float(value) for value in values)
    if total <= 0.0:
        return {
            "leverage_sum": 0.0, "leverage_ess": None,
            "top_1pct_share": None, "top_5pct_share": None, "top_20pct_share": None,
        }
    squares = math.fsum(float(value) * float(value) for value in values)
    order = sorted(range(len(values)), key=lambda index: (-float(values[index]), row_keys[index]))
    summary: dict[str, Any] = {
        "leverage_sum": total,
        "leverage_ess": total * total / squares if squares > 0 else None,
    }
    for percent in (1, 5, 20):
        count = math.ceil(percent * len(values) / 100.0)
        summary[f"top_{percent}pct_share"] = math.fsum(float(values[index]) for index in order[:count]) / total
    return summary


def score_condition(
    logits: np.ndarray,
    y: np.ndarray,
    q: np.ndarray,
    native_delta: np.ndarray,
    preweight: np.ndarray,
    reference: np.ndarray,
    row_keys: list[bytes],
) -> dict[str, Any]:
    values = np.asarray(logits, dtype=np.float64)
    target = np.asarray(y, dtype=np.int8)
    weights = np.asarray(q, dtype=np.float64)
    native = np.asarray(native_delta, dtype=np.float64)
    before = np.asarray(preweight, dtype=np.float64)
    ref = np.asarray(reference, dtype=np.float64)
    if len(values) != len(target) or len(values) != len(weights) or len(values) != len(row_keys):
        raise ValueError("Stage B metric vector lengths differ")
    q_info = q_diagnostics(weights)
    pred = np.where(values > 0.0, 1, -1)
    reference_sign = np.where(ref > 0.0, 1, -1)
    leverage = weights * np.abs(native) * np.abs(ref)
    leverage_total = math.fsum(float(value) for value in leverage)
    if leverage_total > 0:
        agree = math.fsum(float(leverage[i]) for i in range(len(values)) if pred[i] == reference_sign[i]) / leverage_total
        psi = 2.0 * agree - 1.0
    else:
        agree, psi = None, None
    delivered = np.clip(before + np.abs(native) * pred.astype(np.float64), 0.0, 2.0) - before
    dot = math.fsum(float(delivered[i]) * float(ref[i]) for i in range(len(values)))
    norm_u = math.sqrt(math.fsum(float(value) * float(value) for value in delivered))
    norm_g = math.sqrt(math.fsum(float(value) * float(value) for value in ref))
    eta = dot / (norm_u * norm_g) if norm_u > 0 and norm_g > 0 else None
    return {
        "row_count": int(len(values)),
        "positive_count": int(np.count_nonzero(target == 1)),
        "negative_count": int(np.count_nonzero(target == -1)),
        "balanced_error": weighted_balanced_error(values, target, weights),
        "signed_margin": weighted_margin(values, target, weights),
        "mean_absolute_logit": weighted_mean_abs(values, weights),
        "q_diagnostics": q_info,
        "psi_prop": psi,
        "weighted_sign_agreement": agree,
        "leverage": _leverage_summary(leverage, row_keys),
        "eta_delivery": eta,
    }


def paired_block_bootstrap(
    panel_logits: np.ndarray,
    row_blocks: np.ndarray,
    assignments_by_block: dict[int, int],
    y: np.ndarray,
    q: np.ndarray,
    bootstrap_seed_u64: int,
    draws: int = 10_000,
) -> dict[str, Any]:
    """Cluster-resample four whole task blocks within each assignment.

    `panel_logits` has shape (36 models, rows, 3 conditions). It is used to
    form rowwise paired error differences before model averaging.
    """
    logits = np.asarray(panel_logits, dtype=np.float32)
    blocks = np.asarray(row_blocks, dtype=np.uint64)
    target = np.asarray(y, dtype=np.int8)
    weights = np.asarray(q, dtype=np.float64)
    if logits.ndim != 3 or logits.shape[0] != 36 or logits.shape[2] != 3:
        raise ValueError("Stage B bootstrap prediction shape mismatch")
    assignment_order = ("1100", "1010", "0110", "1001", "0101", "0011")
    assignment_to_index = {name: index for index, name in enumerate(assignment_order)}
    assignment_blocks = {
        assignment_to_index[bits]: sorted(block for block, assignment in assignments_by_block.items() if assignment == assignment_to_index[bits])
        for bits in assignment_order
    }
    if any(len(assignment_blocks[index]) != 4 for index in range(6)):
        raise RuntimeError("bootstrap requires exactly four blocks per assignment")

    # For each block/model/intervention/class, store the paired weighted error
    # numerator difference; class denominators are common to all arms/models.
    class_den = np.zeros((6, 4, 2), dtype=np.float64)
    diff_num = np.zeros((6, 4, 36, 2, 2), dtype=np.float64)
    for assignment in range(6):
        for slot, block in enumerate(assignment_blocks[assignment]):
            idx = np.flatnonzero(blocks == np.uint64(block))
            for class_slot, label in enumerate((-1, 1)):
                selected = idx[target[idx] == label]
                class_den[assignment, slot, class_slot] = math.fsum(float(weights[i]) for i in selected)
                if not len(selected):
                    continue
                truth = target[selected]
                q_selected = weights[selected]
                for model_index in range(36):
                    intact_error = np.where(logits[model_index, selected, 0] > 0.0, 1, -1) != truth
                    for intervention_index, condition_index in enumerate((1, 2)):
                        intervention_error = np.where(logits[model_index, selected, condition_index] > 0.0, 1, -1) != truth
                        diff_num[assignment, slot, model_index, intervention_index, class_slot] = math.fsum(
                            float(q_selected[j]) * (int(intervention_error[j]) - int(intact_error[j]))
                            for j in range(len(selected))
                        )

    rng = np.random.Generator(np.random.PCG64(bootstrap_seed_u64))
    counts = np.zeros((draws, 6, 4), dtype=np.float64)
    for assignment in range(6):
        draws_for_assignment = rng.integers(0, 4, size=(draws, 4))
        counts[:, assignment, :] = np.eye(4, dtype=np.float64)[draws_for_assignment].sum(axis=1)

    draw_values = np.empty((draws, 2), dtype=np.float64)
    valid = np.ones(draws, dtype=bool)
    for intervention_index in range(2):
        numerator = np.einsum("dab,abmc->damc", counts, diff_num[:, :, :, intervention_index, :], optimize=True)
        denominator = np.einsum("dab,abc->dac", counts, class_den, optimize=True)
        valid &= (denominator > 0.0).all(axis=(1, 2))
        safe = np.where(denominator > 0.0, denominator, 1.0)
        per_model = 0.5 * (numerator[:, :, :, 0] / safe[:, :, None, 0] + numerator[:, :, :, 1] / safe[:, :, None, 1])
        per_assignment = per_model.mean(axis=2)
        draw_values[:, intervention_index] = per_assignment.mean(axis=1)
    valid_count = int(np.count_nonzero(valid))
    if valid_count != draws:
        return {
            "status": "BOOTSTRAP_SUPPORT_FAILURE",
            "draws_requested": draws,
            "draws_evaluable": valid_count,
            "draws_nondevaluable": draws - valid_count,
            "intervals": {"pair_swap": None, "cycle_4": None},
            "decision": "INCONCLUSIVE_BOOTSTRAP_SUPPORT",
        }
    intervals = {
        "pair_swap": [float(value) for value in np.quantile(draw_values[:, 0], (0.025, 0.975))],
        "cycle_4": [float(value) for value in np.quantile(draw_values[:, 1], (0.025, 0.975))],
    }
    return {
        "status": "PASS",
        "draws_requested": draws,
        "draws_evaluable": valid_count,
        "draws_nondevaluable": 0,
        "seed_u64": int(bootstrap_seed_u64),
        "interval_method": "two-sided percentile",
        "intervals": intervals,
        "decision": "INTERVALS_DEFINED",
    }
