"""The C4a census: per-action support, conditional harm, the exact per-action oracle vs C1's single threshold, and the noise band."""
from __future__ import annotations

import numpy as np

from . import oracle
from .common import (ACTIONS, ELIGIBLE_MIN_CANDIDATES, ELIGIBLE_MIN_SAFE, GAIN_BAR, GATE_LEVELS, LEVELS, MIN_EXECUTIONS, PERMUTATIONS, POSSIBLE_ACT_ACTIONS, SEED, c1fit, correct_at_harm)


def candidates(dec_ppm: np.ndarray, act_ppm: np.ndarray, truth_decision: np.ndarray, truth_action: np.ndarray) -> dict:
    """C3a's candidate rows (decision top class ACT) with C1's score, the predicted action and safety."""
    v = c1fit.views(dec_ppm, act_ppm)
    cand = v["dec_top"] == c1fit.ACT
    safe = (truth_decision == c1fit.ACT) & (v["act_top"] == truth_action)
    score = np.minimum(v["dec_ppm"], v["act_ppm"])[cand].astype(np.float64)
    return {"score": score, "safe": safe[cand], "action": v["act_top"][cand].astype(int), "dec_ppm": v["dec_ppm"][cand], "act_ppm": v["act_ppm"][cand]}


def eligible_actions(action: np.ndarray, safe: np.ndarray) -> list:
    return [a for a in sorted(set(action.tolist())) if int((action == a).sum()) >= ELIGIBLE_MIN_CANDIDATES and int(((action == a) & safe).sum()) >= ELIGIBLE_MIN_SAFE]


def global_threshold(score: np.ndarray, safe: np.ndarray, level: float):
    """The score threshold of the largest set with harm <= level and >= MIN_EXECUTIONS rows (None if none)."""
    order = np.argsort(-score, kind="stable")
    s, sf = score[order], safe[order]
    correct = np.cumsum(sf)
    n = np.arange(1, len(s) + 1)
    end = np.r_[s[1:] != s[:-1], True]
    ok = end & (n >= MIN_EXECUTIONS) & (1.0 - correct / n <= level + 1e-12)
    return float(s[np.flatnonzero(ok)[-1]]) if ok.any() else None


def gain(oracle_correct: int, baseline_correct: int) -> float:
    """oracle / baseline - 1. A baseline with no qualifying set (0) is beaten by any positive count (inf), the same convention as C3a; 0 vs 0 is no gain."""
    if baseline_correct == 0:
        return float("inf") if oracle_correct > 0 else 0.0
    return oracle_correct / baseline_correct - 1


def sanitize(value):
    """JSON has no infinity: write it as the string "inf"."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return "inf" if isinstance(value, float) and np.isinf(value) else value


def _curves(score, safe, action, actions):
    return [oracle.prefix_curve(score[action == a], safe[action == a]) for a in actions]


def oracle_at_levels(score, safe, action, actions, levels=LEVELS, track=False) -> dict:
    hcap = oracle.hcap_for(int(safe.sum()), max(levels))
    return oracle.solve(_curves(score, safe, action, actions), levels, hcap, MIN_EXECUTIONS, track)


def analyze(cand: dict, thresholds_act, truth_decision: np.ndarray, truth_action: np.ndarray, permutations: int = PERMUTATIONS, seed: int = SEED) -> dict:
    """Everything for one surface. `thresholds_act` is C1's frozen alpha 0.05 ACT threshold (or None)."""
    score, safe, action = cand["score"], cand["safe"], cand["action"]
    eligible = eligible_actions(action, safe)
    mask = np.isin(action, eligible)
    s, sf, a = score[mask], safe[mask], action[mask]
    out = {
        "candidates": int(len(score)), "eligible_actions": [ACTIONS[x] for x in eligible], "eligible_candidates": int(mask.sum()), "excluded_candidates": int((~mask).sum()),
        "excluded_by_action": {ACTIONS[x]: int((action == x).sum()) for x in sorted(set(action[~mask].tolist()))},
        "support": {ACTIONS[x]: {"candidates": int((a == x).sum()), "safe": int(((a == x) & sf).sum())} for x in eligible},
    }
    global_points = correct_at_harm(s, sf, LEVELS)
    out["global_correct_at_harm"] = {str(k): v for k, v in global_points.items()}
    out["global_correct_at_harm_all_candidates"] = {str(k): v for k, v in correct_at_harm(score, safe, LEVELS).items()}
    real = oracle_at_levels(s, sf, a, eligible, track=True)
    out["oracle"] = {str(k): {"correct": v["correct"], "harmful": v["harmful"], "per_action": None if v["per_action"] is None else
                              {ACTIONS[x]: p for x, p in zip(eligible, v["per_action"])}} for k, v in real.items()}
    out["oracle_gain"] = {str(k): gain(real[k]["correct"], global_points[k]) for k in LEVELS}
    conditional = {}
    for level in LEVELS:
        t = global_threshold(s, sf, level)
        conditional[str(level)] = None if t is None else {ACTIONS[x]: {"executed": int(((a == x) & (s >= t)).sum()), "harmful": int(((a == x) & (s >= t) & ~sf).sum()),
                                                                     "harm_rate": (float(((a == x) & (s >= t) & ~sf).sum() / ((a == x) & (s >= t)).sum()) if ((a == x) & (s >= t)).any() else None)} for x in eligible}
    out["conditional_harm_at_global_threshold"] = conditional
    rng = np.random.default_rng(seed)
    gains = {str(k): [] for k in LEVELS}
    for _ in range(permutations):
        shuffled = a[rng.permutation(len(a))]
        got = oracle_at_levels(s, sf, shuffled, eligible)
        for k in LEVELS:
            gains[str(k)].append(gain(got[k]["correct"], global_points[k]))
    out["noise_band"] = {k: {"median": float(np.median(v)), "p95": float(np.percentile(v, 95, method="higher")), "max": float(np.max(v))} for k, v in gains.items()}
    out["coherence"] = coherence(cand, thresholds_act)
    out["post_hoc"] = {"note": "added after the conditional-harm table was read", "c1_a05_executions_by_predicted_action": c1_executions_by_action(cand, thresholds_act),
                       "top_k_harm_by_predicted_action": top_k_harm(s, sf, a, eligible),
                       "truth_act_distribution": {ACTIONS[x]: int(((truth_decision == c1fit.ACT) & (truth_action == x)).sum()) for x in sorted(set(truth_action[truth_decision == c1fit.ACT].tolist()))}}
    gate = {}
    for level in GATE_LEVELS:
        g = out["oracle_gain"][str(level)]
        gate[str(level)] = bool(g >= GAIN_BAR and g > out["noise_band"][str(level)]["p95"])
    out["gate_levels_passed"] = gate
    out["gate_passed"] = all(gate.values())
    return sanitize(out)


def top_k_harm(score: np.ndarray, safe: np.ndarray, action: np.ndarray, actions, ks=(25, 50, 100, 200)) -> dict:
    """Post hoc: how safe is each action's very top of the ranking? Harm rate among the k highest-scoring candidates predicted as that action (None if fewer than k)."""
    out = {}
    for a in actions:
        order = np.argsort(-score[action == a], kind="stable")
        sf = safe[action == a][order]
        out[ACTIONS[a]] = {str(k): (float(1.0 - sf[:k].mean()) if len(sf) >= k else None) for k in ks}
    return out


def c1_executions_by_action(cand: dict, threshold) -> dict:
    """Post hoc: what C1's frozen alpha 0.05 ACT rule executes, by predicted action: executions, correct, harmful."""
    if threshold is None:
        return {}
    fired = (cand["dec_ppm"] >= threshold) & (cand["act_ppm"] >= threshold)
    return {ACTIONS[a]: {"executed": int((fired & (cand["action"] == a)).sum()), "correct": int((fired & (cand["action"] == a) & cand["safe"]).sum()),
                         "harmful": int((fired & (cand["action"] == a) & ~cand["safe"]).sum())} for a in sorted(set(cand["action"].tolist())) if (fired & (cand["action"] == a)).any()}


def coherence(cand: dict, threshold) -> dict:
    """Candidates whose predicted action can never be a correct ACT execution, and their share of the harm at C1's frozen alpha 0.05 ACT threshold."""
    impossible = ~np.isin(cand["action"], [ACTIONS.index(x) for x in POSSIBLE_ACT_ACTIONS])
    out = {"impossible_action_candidates": int(impossible.sum()), "impossible_action_safe": int((impossible & cand["safe"]).sum()),
           "impossible_by_action": {ACTIONS[x]: int((cand["action"] == x).sum()) for x in sorted(set(cand["action"][impossible].tolist()))}}
    if threshold is None:
        out.update({"c1_executed": 0, "c1_harmful": 0, "c1_harmful_impossible": 0})
        return out
    fired = (cand["dec_ppm"] >= threshold) & (cand["act_ppm"] >= threshold)
    harmful = fired & ~cand["safe"]
    out.update({"c1_executed": int(fired.sum()), "c1_harmful": int(harmful.sum()), "c1_harmful_impossible": int((harmful & impossible).sum()),
                "c1_impossible_executed": int((fired & impossible).sum())})
    return out
