"""The NLI-UNKNOWN oracle-headroom census. Pure functions of score and label arrays."""
from __future__ import annotations

import numpy as np

from .common import B_GRID, GO_THRESHOLD, MIN_ROWS, PERMUTATIONS, SEED, TARGET_PRECISION


def usable_set(score: np.ndarray, y: np.ndarray, target: float = TARGET_PRECISION, min_rows: int = MIN_ROWS):
    """The highest-recall threshold with precision >= target and >= min_rows rows (ties kept together). None if no threshold qualifies."""
    order = np.argsort(-score, kind="stable")
    s, yy = score[order], y[order]
    tp = np.cumsum(yy)
    n = np.arange(1, len(s) + 1)
    last = np.r_[s[1:] != s[:-1], True]
    ok = last & (tp / n >= target) & (n >= min_rows)
    if not ok.any():
        return None
    threshold = s[np.flatnonzero(ok)[-1]]  # recall never falls as the set grows, so the largest qualifying set has the highest recall
    return {"threshold": int(threshold), "mask": score >= threshold}


def size_matched(score: np.ndarray, k: int) -> np.ndarray:
    mask = np.zeros(len(score), dtype=bool)
    mask[np.argsort(-score, kind="stable")[:k]] = True
    return mask


def stats(mask: np.ndarray, y: np.ndarray) -> dict:
    n, tp = int(mask.sum()), int((mask & y).sum())
    return {"rows": n, "true_positives": tp, "false_positives": n - tp, "precision": tp / n if n else None, "recall": tp / int(y.sum())}


def best_conjunction(score_a: np.ndarray, score_b: np.ndarray, y: np.ndarray, b_grid=B_GRID) -> dict:
    """Best recall of `A >= a AND B >= b` at precision >= target over the grid. b = 0 is A alone. Recall is over all positives in `y`."""
    total = int(y.sum())
    best = {"recall": -1.0, "true_positives": 0, "rows": 0, "a_threshold": None, "b": None}
    baseline = None
    for b in b_grid:
        keep = score_b >= b
        if int(keep.sum()) < MIN_ROWS:
            continue
        found = usable_set(score_a[keep], y[keep])
        if found is None:
            continue
        chosen = found["mask"]
        tp = int((chosen & y[keep]).sum())
        recall = tp / total
        if b == 0:
            baseline = recall
        if recall > best["recall"]:
            best = {"recall": recall, "true_positives": tp, "rows": int(chosen.sum()), "a_threshold": found["threshold"], "b": int(b)}
    best["baseline_recall"] = baseline
    best["headroom"] = None if not baseline else best["recall"] / baseline - 1
    return best


def veto_ceiling(score_a: np.ndarray, allowed: np.ndarray, y: np.ndarray) -> dict:
    """The same search with a perfect veto: only rows in `allowed` can be flagged."""
    total = int(y.sum())
    base = usable_set(score_a, y)
    found = usable_set(score_a[allowed], y[allowed])
    if base is None or found is None:
        return {"baseline_recall": None if base is None else int((base["mask"] & y).sum()) / total, "recall": None, "headroom": None}
    base_recall = int((base["mask"] & y).sum()) / total
    recall = int((found["mask"] & y[allowed]).sum()) / total
    return {"baseline_recall": base_recall, "recall": recall, "headroom": recall / base_recall - 1, "rows": int(found["mask"].sum()),
            "precision": float((found["mask"] & y[allowed]).sum() / found["mask"].sum())}


def noise_band(score_a: np.ndarray, score_b: np.ndarray, y: np.ndarray, permutations: int = PERMUTATIONS, seed: int = SEED) -> dict:
    """Headroom of the same conjunction search when `score_b` is shuffled among rows: what the search finds by chance."""
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(permutations):
        h = best_conjunction(score_a, score_b[rng.permutation(len(score_b))], y)["headroom"]
        values.append(0.0 if h is None else h)
    values = np.array(values)
    return {"median": float(np.median(values)), "p95": float(np.percentile(values, 95)), "max": float(values.max()), "permutations": permutations}


def union_view(score_a: np.ndarray, score_n: np.ndarray, y: np.ndarray) -> dict:
    """The four sets of the plan: A, N, intersection, union; plus misses recovered and false positives shared."""
    a = usable_set(score_a, y)
    if a is None:
        return {"available": False}
    a_mask = a["mask"]
    n_found = usable_set(score_n, y)
    n_mask, n_kind = (n_found["mask"], "precision_matched") if n_found else (size_matched(score_n, int(a_mask.sum())), "size_matched")
    tp_a, tp_n = a_mask & y, n_mask & y
    misses = y & ~a_mask
    fp_a = a_mask & ~y
    return {
        "available": True, "A": stats(a_mask, y) | {"threshold": a["threshold"]}, "N": stats(n_mask, y) | {"kind": n_kind, "threshold": None if not n_found else n_found["threshold"]},
        "intersection": stats(a_mask & n_mask, y), "union": stats(a_mask | n_mask, y),
        "oracle_union_headroom": int((tp_a | tp_n).sum()) / int(tp_a.sum()) - 1, "realizable_union_headroom": int(((a_mask | n_mask) & y).sum()) / int(tp_a.sum()) - 1,
        "ask_misses": int(misses.sum()), "misses_recovered_by_n": int((misses & n_mask).sum()), "misses_recovered_share": int((misses & n_mask).sum()) / int(misses.sum()),
        "a_false_positives": int(fp_a.sum()), "false_positives_shared_with_n": int((fp_a & n_mask).sum()), "false_positive_share_shared": int((fp_a & n_mask).sum()) / int(fp_a.sum()) if fp_a.sum() else None,
        "true_positives_lost_if_n_required": int((tp_a & ~n_mask).sum()), "false_positives_removed_if_n_required": int((fp_a & ~n_mask).sum()),
    }


def lift_table(score_a: np.ndarray, score_b: np.ndarray, y: np.ndarray, a_bins: int = 10, b_bins: int = 3) -> dict:
    """ASK rate in each cell of (deciles of A) x (terciles of B), equal-count bins by rank. Descriptive: where does B add discrimination beyond A?"""
    def bins(score, k):
        ranks = np.empty(len(score), dtype=int)
        ranks[np.argsort(score, kind="stable")] = np.arange(len(score))
        return (ranks * k) // len(score)

    ab, bb = bins(score_a, a_bins), bins(score_b, b_bins)
    return {"rows": [[int(((ab == i) & (bb == j)).sum()) for j in range(b_bins)] for i in range(a_bins)],
            "ask_rate": [[float(y[(ab == i) & (bb == j)].mean()) if ((ab == i) & (bb == j)).any() else None for j in range(b_bins)] for i in range(a_bins)]}


def decide(primary: dict) -> dict:
    """The preregistered rule. `primary` carries the union view, the conjunction result, its noise band and the perfect-NLI ceiling."""
    v_head = primary["conjunction"]["headroom"]
    ceiling = primary["ceiling"]["headroom"]
    v = bool(v_head is not None and ceiling is not None and v_head >= GO_THRESHOLD and v_head > primary["noise"]["p95"] and ceiling >= GO_THRESHOLD)
    u = primary["union"]
    u_ok = bool(u["available"] and u["union"]["precision"] is not None and u["union"]["precision"] >= TARGET_PRECISION and u["realizable_union_headroom"] >= GO_THRESHOLD)
    return {"V_veto_earned": v, "U_union_earned": u_ok, "route_earned": bool(v or u_ok)}
