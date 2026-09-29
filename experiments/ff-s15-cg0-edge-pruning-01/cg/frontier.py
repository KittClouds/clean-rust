"""Matched pruning frontiers for T0 (type-pair table), T0+T1 and T1 alone, parameter transfer, and the shuffled-score noise band. Pure functions.

Inputs are arrays over the pair universe of one evaluated split: `label` (1 = edge), `pair_type` (code), `score` (higher = more edge-like; T1 prunes low scores).
`rank` maps every pair-type code to its position in T0's fixed order (ascending TRAIN edge rate); T0 prunes the first k type pairs.
"""
from __future__ import annotations

import numpy as np

from .common import PERMUTATIONS, SEED


def t0_rank(pairs, edges) -> np.ndarray:
    """rank[code] = position of the type pair when ordered by ascending TRAIN edge rate. A type pair never seen in TRAIN has no rate and is placed last (never pruned first)."""
    pairs, edges = np.asarray(pairs, dtype=np.float64), np.asarray(edges, dtype=np.float64)
    rate = np.where(pairs > 0, edges / np.maximum(pairs, 1), np.inf)
    order = sorted(range(len(pairs)), key=lambda c: (rate[c], c))
    rank = np.empty(len(pairs), dtype=np.int64)
    for position, code in enumerate(order):
        rank[code] = position
    return rank


def _budget(eps: float, edges: int, already: int) -> int:
    """Edges that may still be lost: floor(eps * E) minus what T0 already lost (tolerance for float rounding)."""
    return int(np.floor(eps * edges + 1e-9)) - already


def frontier(label: np.ndarray, pair_type: np.ndarray, score: np.ndarray, rank: np.ndarray, epsilons) -> dict:
    """For each edge-loss budget: the best pruned share of non-edges for T0, T0+T1 (k and threshold jointly optimised) and T1 alone, plus the parameters that achieve it."""
    label = label.astype(np.int64)
    edges, non_edges = int(label.sum()), int((1 - label).sum())
    g = rank[pair_type]
    present = np.unique(g)
    top = int(rank.max()) + 1
    e_by_rank = np.bincount(g, weights=label, minlength=top)
    n_by_rank = np.bincount(g, weights=1 - label, minlength=top)
    cum_e = np.r_[0, np.cumsum(e_by_rank)].astype(np.int64)   # cum_e[k] = edges lost if the first k type pairs are pruned
    cum_n = np.r_[0, np.cumsum(n_by_rank)].astype(np.int64)
    order = np.argsort(score, kind="stable")
    y_sorted, g_sorted, s_sorted = label[order], g[order], score[order]
    candidates = sorted({0} | {int(r) + 1 for r in present})   # k only matters where it adds a present type pair
    out = {str(e): {"T0": None, "T0+T1": None, "T1": None} for e in epsilons}
    for k in candidates:
        residual = g_sorted >= k
        e_cs = np.cumsum(y_sorted * residual)
        n_cs = np.cumsum((1 - y_sorted) * residual)
        for eps in epsilons:
            allowed = _budget(eps, edges, int(cum_e[k]))
            if allowed < 0:
                continue
            slot = out[str(eps)]
            share0 = cum_n[k] / max(non_edges, 1)
            if slot["T0"] is None or share0 > slot["T0"]["pruned_share"]:
                slot["T0"] = {"k": k, "pruned_share": float(share0), "edge_loss": float(cum_e[k] / max(edges, 1))}
            idx = int(np.searchsorted(e_cs, allowed, side="right"))   # residual positions 0..idx-1 can be pruned within the remaining budget
            pruned_residual_n = int(n_cs[idx - 1]) if idx > 0 else 0
            pruned_residual_e = int(e_cs[idx - 1]) if idx > 0 else 0
            share = (cum_n[k] + pruned_residual_n) / max(non_edges, 1)
            threshold = float(s_sorted[idx - 1]) if idx > 0 else float("-inf")
            record = {"k": k, "threshold": threshold, "pruned_share": float(share), "edge_loss": float((cum_e[k] + pruned_residual_e) / max(edges, 1))}
            if slot["T0+T1"] is None or share > slot["T0+T1"]["pruned_share"]:
                slot["T0+T1"] = record
            if k == 0:
                slot["T1"] = record
    for eps in epsilons:
        s = out[str(eps)]
        s["gain"] = None if s["T0"] is None or s["T0+T1"] is None else s["T0+T1"]["pruned_share"] - s["T0"]["pruned_share"]
        s["edges"], s["non_edges"] = edges, non_edges
    return out


def apply_params(label: np.ndarray, pair_type: np.ndarray, score: np.ndarray, rank: np.ndarray, k: int, threshold: float) -> dict:
    """Prune pairs in the first k type pairs, and residual pairs scoring at or below the threshold; report the achieved edge loss and pruned share."""
    g = rank[pair_type]
    pruned = (g < k) | ((g >= k) & (score <= threshold))
    edges, non_edges = int(label.sum()), int((1 - label).sum())
    return {"edge_loss": float((pruned & (label == 1)).sum() / max(edges, 1)), "pruned_share": float((pruned & (label == 0)).sum() / max(non_edges, 1))}


def noise_band(label, pair_type, score, rank, epsilons, permutations: int = PERMUTATIONS, seed: int = SEED) -> dict:
    """T0+T1 gain when T1's scores are shuffled among the evaluated pairs: what re-optimising a threshold on unrelated scores finds."""
    rng = np.random.default_rng(seed)
    gains = {str(e): [] for e in epsilons}
    for _ in range(permutations):
        f = frontier(label, pair_type, score[rng.permutation(len(score))], rank, epsilons)
        for e in epsilons:
            gains[str(e)].append(f[str(e)]["gain"] if f[str(e)]["gain"] is not None else 0.0)
    return {e: {"median": float(np.median(v)), "p95": float(np.percentile(v, 95)), "max": float(np.max(v))} for e, v in gains.items()}


def within_pair_type_auc(label, pair_type, score, auc, min_each: int = 30) -> dict:
    """AUC of T1 inside each type pair that has enough of both classes, and the pair-weighted mean. T0 is constant inside a type pair, so its within-type-pair AUC is 0.5 by construction."""
    per, weight, total = {}, 0, 0.0
    for code in np.unique(pair_type):
        m = pair_type == code
        y = label[m]
        if int(y.sum()) >= min_each and int((1 - y).sum()) >= min_each:
            a = auc(score[m], y)
            per[int(code)] = {"auc": a, "pairs": int(m.sum()), "edges": int(y.sum())}
            weight += int(m.sum())
            total += a * int(m.sum())
    return {"weighted_mean": total / weight if weight else None, "pairs_covered": weight, "per_type_pair": per}
