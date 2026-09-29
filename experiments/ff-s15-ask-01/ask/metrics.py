"""Ranking metrics and ASK threshold fitting. Pure functions of score and label arrays; ties are handled explicitly (no arbitrary order among equal scores)."""
from __future__ import annotations

import numpy as np

from .common import GRID, MIN_ASKS_FIT, MIN_ASKS_MATCHED, c1fit


def _curve(score: np.ndarray, y: np.ndarray):
    """Precision, recall and count at the end of each run of equal scores, scanning from the highest score down."""
    order = np.argsort(-score, kind="stable")
    s, yy = score[order], y[order]
    tp = np.cumsum(yy)
    n = np.arange(1, len(s) + 1)
    last = np.r_[s[1:] != s[:-1], True]
    return tp[last] / n[last], tp[last] / y.sum(), n[last]


def average_precision(score: np.ndarray, y: np.ndarray) -> float:
    precision, recall, _ = _curve(score, y)
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def auroc(score: np.ndarray, y: np.ndarray) -> float:
    """Mann-Whitney statistic with average ranks for ties."""
    order = np.argsort(score, kind="stable")
    sorted_scores = score[order]
    ranks = np.empty(len(score))
    i = 0
    while i < len(sorted_scores):
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    positives, negatives = int(y.sum()), int((~y).sum())
    return float((ranks[y].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def recall_at_precision(score: np.ndarray, y: np.ndarray, target: float, min_selected: int = MIN_ASKS_MATCHED):
    """Highest recall of any threshold whose precision is >= target with at least `min_selected` rows; None if unreachable."""
    precision, recall, n = _curve(score, y)
    ok = (precision >= target) & (n >= min_selected)
    return float(recall[ok].max()) if ok.any() else None


def fit_threshold(score: np.ndarray, y: np.ndarray, alpha: float):
    """Smallest grid threshold with >= 100 rows at or above it and a one-sided 95% Wilson lower bound on precision >= 1 - alpha; else None."""
    for threshold in GRID:
        chosen = score >= threshold
        n = int(chosen.sum())
        if n >= MIN_ASKS_FIT and c1fit.wilson_lower(int(y[chosen].sum()), n) >= 1 - alpha:
            return threshold
    return None


def rule_outcomes(score: np.ndarray, y: np.ndarray, threshold) -> dict:
    """What the ASK rule does at a threshold: asks, correct asks, precision, recall of the truth-ASK rows."""
    if threshold is None:
        return {"threshold_ppm": None, "asks": 0, "correct_asks": 0, "precision": None, "recall": 0.0}
    chosen = score >= threshold
    asks, correct = int(chosen.sum()), int(y[chosen].sum())
    return {"threshold_ppm": threshold, "asks": asks, "correct_asks": correct, "precision": correct / asks if asks else None, "recall": correct / int(y.sum())}
