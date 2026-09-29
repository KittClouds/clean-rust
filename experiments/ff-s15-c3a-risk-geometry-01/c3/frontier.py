"""Risk-coverage frontiers at matched harm, the paired bootstrap, and the preregistered dominance rule. Pure functions."""
from __future__ import annotations

import numpy as np

from .common import BOOTSTRAP_PERCENTILE, BOOTSTRAPS, GAIN_BAR, LEVELS, LEVELS_NEEDED, MIN_EXECUTIONS, SEED


def correct_at_harm(score: np.ndarray, safe: np.ndarray, levels=LEVELS, min_executions: int = MIN_EXECUTIONS) -> dict:
    """For each harm level H: correct executions of the largest set (safest first, ties kept together) with harm rate <= H and >= min_executions rows. 0 if none."""
    order = np.argsort(-score, kind="stable")
    s, ok_safe = score[order], safe[order]
    correct = np.cumsum(ok_safe)
    n = np.arange(1, len(s) + 1)
    group_end = np.r_[s[1:] != s[:-1], True]
    harm = 1.0 - correct / n
    out = {}
    for level in levels:
        ok = group_end & (n >= min_executions) & (harm <= level + 1e-12)
        out[level] = int(correct[np.flatnonzero(ok)[-1]]) if ok.any() else 0
    return out


def paired_bootstrap(scores: dict, safe: np.ndarray, baseline: str = "c1_min", bootstraps: int = BOOTSTRAPS, seed: int = SEED, levels=LEVELS) -> dict:
    """name -> level -> the low percentile of (correct_at_harm(score) - correct_at_harm(baseline)) over resamples of the candidate rows."""
    rng = np.random.default_rng(seed)
    n = len(safe)
    diffs = {name: {level: [] for level in levels} for name in scores if name != baseline}
    for _ in range(bootstraps):
        idx = rng.integers(0, n, n)
        base = correct_at_harm(scores[baseline][idx], safe[idx], levels)
        for name, s in scores.items():
            if name == baseline:
                continue
            got = correct_at_harm(s[idx], safe[idx], levels)
            for level in levels:
                diffs[name][level].append(got[level] - base[level])
    return {name: {level: float(np.percentile(v, BOOTSTRAP_PERCENTILE)) for level, v in per.items()} for name, per in diffs.items()}


def dominance(points: dict, low: dict, baseline: str = "c1_min") -> dict:
    """name -> {levels_passed, dominates}. Passing a level: >= GAIN_BAR x the baseline's correct executions and the bootstrap low percentile of the difference > 0."""
    out = {}
    for name, per in points.items():
        if name == baseline:
            continue
        passed = [level for level, v in per.items() if v > 0 and v >= GAIN_BAR * points[baseline][level] - 1e-9 and low[name][level] > 0]  # a baseline with no qualifying set (0) is beaten by any positive count
        out[name] = {"levels_passed": passed, "dominates": len(passed) >= LEVELS_NEEDED}
    return out
