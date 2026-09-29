"""Threshold fitting, a numpy simulation of the C1 rules, outcomes, and the permutation control.

Everything here works on integer ppm arrays: `dec` is [n, 3] (ACT, ASK, ABSTAIN) and `act` is [n, 14].
Fitting only ever sees the rows it is given; the driver passes CAL rows and nothing else.
"""
from __future__ import annotations

import math

import numpy as np

ACT, ASK, ABSTAIN = 0, 1, 2  # decision class indexes (DECISIONS order)
EXECUTED, ABSTAINED, ASKED, ESCALATED = 0, 1, 2, 3  # disposition codes used by the simulation
GRID = tuple(range(340_000, 995_001, 5_000)) + (999_000,)
Z95 = 1.6448536269514722  # one-sided 95%
MIN_CANDIDATES = 100
RULES = (("abstain", ABSTAIN), ("ask", ASK), ("act", ACT))


def wilson_lower(correct: int, n: int, z: float = Z95) -> float:
    if n == 0:
        return 0.0
    p = correct / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - spread) / (1 + z * z / n)


def views(dec: np.ndarray, act: np.ndarray) -> dict:
    """Top labels and confidences. argmax takes the lowest index on a tie, exactly like the C0 runtime."""
    return {"dec_top": dec.argmax(axis=1), "dec_ppm": dec.max(axis=1), "act_top": act.argmax(axis=1), "act_ppm": act.max(axis=1)}


def class_scores(v: dict) -> dict:
    return {ABSTAIN: v["dec_ppm"], ASK: v["dec_ppm"], ACT: np.minimum(v["dec_ppm"], v["act_ppm"])}


def correctness(v: dict, truth_dec: np.ndarray, truth_act: np.ndarray) -> dict:
    return {ABSTAIN: truth_dec == ABSTAIN, ASK: truth_dec == ASK, ACT: (truth_dec == ACT) & (v["act_top"] == truth_act)}


def fit_threshold(score: np.ndarray, correct: np.ndarray, alpha: float):
    """Smallest grid threshold whose candidates' Wilson lower bound on precision is >= 1 - alpha (>= 100 candidates), else None."""
    for threshold in GRID:
        selected = score >= threshold
        n = int(selected.sum())
        if n >= MIN_CANDIDATES and wilson_lower(int(correct[selected].sum()), n) >= 1 - alpha:
            return threshold
    return None


def fit_thresholds(dec: np.ndarray, act: np.ndarray, truth_dec: np.ndarray, truth_act: np.ndarray, alpha: float) -> dict:
    v = views(dec, act)
    scores, right = class_scores(v), correctness(v, truth_dec, truth_act)
    out = {}
    for name, c in RULES:
        candidates = v["dec_top"] == c
        threshold = fit_threshold(scores[c][candidates], right[c][candidates], alpha)
        detail = {"threshold_ppm": threshold, "candidates": int(candidates.sum())}
        if threshold is not None:
            chosen = candidates & (scores[c] >= threshold)
            detail.update({"selected": int(chosen.sum()), "precision": float(right[c][chosen].mean())})
        out[name] = detail
    return out


def simulate(v: dict, thresholds: dict) -> tuple:
    """The C1 escalation rules in numpy. thresholds: name -> ppm or None (omitted). Returns (disposition codes, target class or -1)."""
    n = len(v["dec_top"])
    disposition = np.full(n, ESCALATED, dtype=np.int8)
    target = np.full(n, -1, dtype=np.int16)
    scores = class_scores(v)
    for (name, c), code in zip(RULES, (ABSTAINED, ASKED, EXECUTED)):
        threshold = thresholds.get(name)
        if threshold is None:
            continue
        chosen = (v["dec_top"] == c) & (scores[c] >= threshold)
        disposition[chosen] = code
        if c == ACT:
            target[chosen] = v["act_top"][chosen]
    return disposition, target


def argmax_baseline(v: dict) -> tuple:
    """Resolve every row by the top decision label; no thresholds."""
    disposition = np.select([v["dec_top"] == ACT, v["dec_top"] == ASK], [EXECUTED, ASKED], default=ABSTAINED).astype(np.int8)
    target = np.where(disposition == EXECUTED, v["act_top"], -1).astype(np.int16)
    return disposition, target


def outcomes(disposition: np.ndarray, target: np.ndarray, truth_dec: np.ndarray, truth_act: np.ndarray) -> dict:
    n = len(disposition)
    executed = disposition == EXECUTED
    correct_exec = executed & (truth_dec == ACT) & (target == truth_act)
    harmful = executed & ~correct_exec
    abstained, asked, escalated = disposition == ABSTAINED, disposition == ASKED, disposition == ESCALATED
    correct = correct_exec | (abstained & (truth_dec == ABSTAIN)) | (asked & (truth_dec == ASK))
    resolved = int((~escalated).sum())
    counts = {
        "rows": n, "executed": int(executed.sum()), "harmful": int(harmful.sum()), "abstained": int(abstained.sum()), "asked": int(asked.sum()),
        "escalated": int(escalated.sum()), "resolved": resolved, "correct": int(correct.sum()), "correct_executed": int(correct_exec.sum()),
    }
    counts["harm_rate"] = counts["harmful"] / counts["executed"] if counts["executed"] else None
    counts["precision"] = counts["correct"] / resolved if resolved else None
    counts["coverage"] = resolved / n if n else 0.0
    counts["correct_executed_fraction"] = counts["correct_executed"] / n if n else 0.0
    return counts


def permuted_harm_rates(v: dict, threshold, truth_dec: np.ndarray, truth_act: np.ndarray, rng: np.random.Generator, permutations: int = 200) -> np.ndarray:
    """Harm rate of the ACT rule if its confidence scores were shuffled among the rows predicted ACT (same number executed each time)."""
    if threshold is None:
        return np.array([])
    candidates = np.flatnonzero(v["dec_top"] == ACT)
    scores = class_scores(v)[ACT][candidates]
    right = correctness(v, truth_dec, truth_act)[ACT][candidates]
    rates = []
    for _ in range(permutations):
        shuffled = scores[rng.permutation(len(candidates))]
        chosen = shuffled >= threshold
        executed = int(chosen.sum())
        if executed:
            rates.append(1.0 - float(right[chosen].mean()))
    return np.array(rates)
