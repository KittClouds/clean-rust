"""The per-action oracle: the exact maximum of correct executions over one threshold per action subject to overall harm <= H.

Each action contributes a prefix of its own candidates ordered safest first, i.e. one threshold. A choice is (harmful h, correct c) per action; the objective is total correct;
the constraint is total harmful <= rho * total correct with rho = H / (1 - H). Dynamic programming over actions, with the state being the total harmful count (capped, since harm <= 10% bounds it).
"""
from __future__ import annotations

import numpy as np

NEG = -(10 ** 9)


def prefix_curve(score: np.ndarray, safe: np.ndarray) -> dict:
    """Threshold scores, harmful counts and correct counts at the end of each run of equal scores, safest first; entry 0 is the empty set."""
    order = np.argsort(-score, kind="stable")
    s, sf = score[order], safe[order]
    correct = np.cumsum(sf)
    harmful = np.arange(1, len(s) + 1) - correct
    end = np.r_[s[1:] != s[:-1], True]
    return {"threshold": np.r_[np.inf, s[end]], "harmful": np.r_[0, harmful[end]], "correct": np.r_[0, correct[end]]}


def _best_correct_by_harm(curve: dict, cap: int) -> np.ndarray:
    """For each harmful count h in 0..cap: the most correct executions any prefix with exactly h harmful executions has (-1 if none)."""
    best = np.full(cap + 1, -1, dtype=np.int64)
    keep = curve["harmful"] <= cap
    np.maximum.at(best, curve["harmful"][keep], curve["correct"][keep])
    return best


def solve(curves: list, levels, hcap: int, min_executions: int = 100, track: bool = False) -> dict:
    """Best total correct executions at each harm level, and (if `track`) the per-action prefix chosen."""
    f = np.full(hcap + 1, NEG, dtype=np.int64)
    f[0] = 0
    choices = []
    for curve in curves:
        g = _best_correct_by_harm(curve, hcap)
        new = np.full(hcap + 1, NEG, dtype=np.int64)
        arg = np.full(hcap + 1, -1, dtype=np.int64)
        for ho in np.flatnonzero(g >= 0):
            cand = f[:hcap + 1 - ho] + g[ho]
            better = cand > new[ho:]
            new[ho:] = np.where(better, cand, new[ho:])
            arg[ho:] = np.where(better, ho, arg[ho:])
        f = new
        choices.append(arg)
    hs = np.arange(hcap + 1)
    out = {}
    for level in levels:
        rho = level / (1.0 - level)
        feasible = (f > 0) & (hs <= rho * f + 1e-9) & (hs + f >= min_executions)
        if not feasible.any():
            out[level] = {"correct": 0, "harmful": 0, "per_action": None}
            continue
        h_star = int(np.flatnonzero(feasible)[np.argmax(f[feasible])])
        entry = {"correct": int(f[h_star]), "harmful": h_star, "per_action": None}
        if track:
            h, picks = h_star, []
            for a in range(len(curves) - 1, -1, -1):
                ho = int(choices[a][h])
                curve = curves[a]
                idx = int(np.flatnonzero(curve["harmful"] == ho)[-1])  # the largest prefix with that many harmful
                picks.append({"harmful": ho, "correct": int(curve["correct"][idx]), "executed": ho + int(curve["correct"][idx]), "threshold": float(curve["threshold"][idx])})
                h -= ho
            entry["per_action"] = picks[::-1]
        out[level] = entry
    return out


def hcap_for(total_safe: int, max_level: float) -> int:
    """No feasible solution can have more harmful executions than rho_max times the safe ones there are."""
    return int(np.ceil(max_level / (1.0 - max_level) * total_safe)) + 2
