"""Pure metadata/prediction helpers for the sealed v0.8H audit.

This module deliberately imports no model runtime. It reads JSON/SQLite-derived
records and saved predictions only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

EPS = 1e-12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def signature_distance(random_counts: Mapping[str, int], curated_counts: Mapping[str, int],
                       expected_mass: int | None = None) -> dict[str, int | float]:
    """Reconcile equal-mass training-signature multisets and their TV distance."""
    random_mass = sum(int(value) for value in random_counts.values())
    curated_mass = sum(int(value) for value in curated_counts.values())
    if random_mass != curated_mass:
        raise ValueError(f"training arms have unequal occurrence mass: {random_mass} != {curated_mass}")
    if expected_mass is not None and random_mass != expected_mass:
        raise ValueError(f"training arms have unexpected occurrence mass: {random_mass} != {expected_mass}")
    keys = random_counts.keys() | curated_counts.keys()
    l1 = sum(abs(int(random_counts.get(key, 0)) - int(curated_counts.get(key, 0))) for key in keys)
    if l1 % 2:
        raise ValueError("equal-mass integer signature vectors must have even L1 distance")
    return {
        "groups_per_arm": random_mass,
        "signature_count_l1": l1,
        "random_enriched_mass": l1 // 2,
        "curated_enriched_mass": l1 // 2,
        "D_train": 0.5 * l1 / random_mass if random_mass else 0.0,
        "unique_signatures_random": len(random_counts),
        "unique_signatures_curated": len(curated_counts),
    }


def entropy(probabilities: Iterable[float]) -> float:
    return -sum(p * math.log(max(EPS, p)) for p in probabilities if p > 0.0)


def target_distribution(row: dict[str, Any]) -> list[float]:
    values = [float(value) for value in row["gold"]]
    if row["kind"] == "independent":
        if len(values) != 1 or not 0.0 <= values[0] <= 1.0:
            raise ValueError(f"invalid independent target: {row.get('group_id')}")
        return [values[0], 1.0 - values[0]]
    if not values or any(value < 0.0 for value in values):
        raise ValueError(f"invalid categorical target: {row.get('group_id')}")
    total = sum(values)
    if abs(total - 1.0) > 1e-4:
        raise ValueError(f"categorical target is not normalized: {row.get('group_id')} sum={total}")
    return [value / total for value in values]


def distribution_geometry(row: dict[str, Any]) -> dict[str, float | int]:
    p = target_distribution(row)
    ordered = sorted(p, reverse=True)
    h = entropy(p)
    return {
        "entropy_nats": h,
        "max_probability": ordered[0],
        "top_two_margin": ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0),
        "effective_count": math.exp(h),
        "one_hot_distance": 1.0 - ordered[0],
        "normalized_entropy": h / math.log(len(p)) if len(p) > 1 else 0.0,
        "decision_alternatives": len(p),
        "gold_top1_position": max(range(len(row["gold"])), key=lambda i: float(row["gold"][i])),
        "gold_top2_position": (
            sorted(range(len(row["gold"])), key=lambda i: float(row["gold"][i]), reverse=True)[1]
            if len(row["gold"]) > 1 else -1
        ),
        "binary_gold_class": int(float(row["gold"][0]) >= 0.5) if row["kind"] == "independent" else -1,
    }


def row_metrics(row: dict[str, Any]) -> dict[str, float]:
    gold = [float(value) for value in row["gold"]]
    pred = [min(1.0, max(0.0, float(value))) for value in row["prediction"]]
    if len(gold) != len(pred) or not gold:
        raise ValueError(f"gold/prediction cardinality mismatch: {row.get('group_id')}")
    if row["kind"] == "independent":
        g, p = gold[0], pred[0]
        return {
            "accuracy": float((p >= 0.5) == (g >= 0.5)),
            "nll": -(g * math.log(max(EPS, p)) + (1.0 - g) * math.log(max(EPS, 1.0 - p))),
            "brier": (p - g) ** 2,
            "posterior_l1": abs(p - g),
            "confidence": p if p >= 0.5 else 1.0 - p,
            "gold_confidence": g if p >= 0.5 else 1.0 - g,
        }
    p_sum, g_sum = sum(pred), sum(gold)
    if abs(p_sum - 1.0) > 1e-4 or abs(g_sum - 1.0) > 1e-4:
        raise ValueError(f"closed-set distribution is not normalized: {row.get('group_id')}")
    pred_i = max(range(len(pred)), key=pred.__getitem__)
    gold_i = max(range(len(gold)), key=gold.__getitem__)
    result = {
        "accuracy": float(pred_i == gold_i),
        "nll": -sum(g * math.log(max(EPS, p)) for g, p in zip(gold, pred)),
        "brier": sum((p - g) ** 2 for g, p in zip(gold, pred)),
        "posterior_l1": sum(abs(p - g) for g, p in zip(gold, pred)),
        "confidence": pred[pred_i],
        "gold_confidence": gold[pred_i],
    }
    if row.get("view") == "ordinal_score" and len(gold) > 1:
        g_cdf = p_cdf = squared = 0.0
        for g, p in zip(gold[:-1], pred[:-1]):
            g_cdf += g
            p_cdf += p
            squared += (g_cdf - p_cdf) ** 2
        result.update({
            "ordinal_rps": squared / (len(gold) - 1),
            "ordinal_adjacent": float(abs(pred_i - gold_i) <= 1),
            "gold_expected_rank": sum(i * value for i, value in enumerate(gold)),
            "pred_expected_rank": sum(i * value for i, value in enumerate(pred)),
        })
    return result


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + end - 1) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    mx, my = sum(left) / len(left), sum(right) / len(right)
    vx = sum((x - mx) ** 2 for x in left)
    vy = sum((y - my) ** 2 for y in right)
    if vx == 0.0 or vy == 0.0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(left, right)) / math.sqrt(vx * vy)


def spearman(left: list[float], right: list[float]) -> float | None:
    return pearson(rankdata(left), rankdata(right))


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    metrics = [row_metrics(row) for row in rows]
    output: dict[str, Any] = {"count": len(rows)}
    names = ("accuracy", "nll", "brier", "posterior_l1", "ordinal_rps", "ordinal_adjacent")
    for name in names:
        values = [item[name] for item in metrics if name in item]
        if values:
            output[name] = sum(values) / len(values)
    ece = 0.0
    bins = []
    for index in range(10):
        selected = [(item["confidence"], item["gold_confidence"]) for item in metrics
                    if min(9, int(item["confidence"] * 10)) == index]
        if selected:
            confidence = sum(item[0] for item in selected) / len(selected)
            target = sum(item[1] for item in selected) / len(selected)
            ece += len(selected) / len(rows) * abs(confidence - target)
            bins.append({"bin": index, "count": len(selected), "mean_confidence": confidence,
                         "mean_gold_confidence": target})
        else:
            bins.append({"bin": index, "count": 0})
    output["ece_soft"] = ece
    output["reliability_bins"] = bins
    if rows[0].get("view") == "ordinal_score":
        output["expected_rank_spearman"] = spearman(
            [item["gold_expected_rank"] for item in metrics],
            [item["pred_expected_rank"] for item in metrics],
        )
    return output


def weighted_quantile(values: list[float], weights: list[float], q: float) -> float | None:
    pairs = sorted((float(value), float(weight)) for value, weight in zip(values, weights) if weight > 0)
    total = sum(weight for _, weight in pairs)
    if not pairs or total <= 0:
        return None
    target = min(1.0, max(0.0, q)) * total
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= target:
            return value
    return pairs[-1][0]


def weighted_numeric(values: list[float], weights: list[float]) -> dict[str, Any]:
    total = sum(weight for weight in weights if weight > 0)
    if total <= 0:
        return {"mass": 0}
    mean = sum(value * weight for value, weight in zip(values, weights) if weight > 0) / total
    return {
        "mass": total,
        "mean": mean,
        "p10": weighted_quantile(values, weights, 0.10),
        "p25": weighted_quantile(values, weights, 0.25),
        "median": weighted_quantile(values, weights, 0.50),
        "p75": weighted_quantile(values, weights, 0.75),
        "p90": weighted_quantile(values, weights, 0.90),
    }


def weighted_categorical(values: list[str], weights: list[float]) -> dict[str, Any]:
    counts: dict[str, float] = defaultdict(float)
    total = 0.0
    for value, weight in zip(values, weights):
        if weight > 0:
            counts[str(value)] += weight
            total += weight
    return {
        "mass": total,
        "counts": dict(sorted(counts.items())),
        "proportions": {key: value / total for key, value in sorted(counts.items())} if total else {},
    }


def categorical_tv(left: dict[str, float], right: dict[str, float]) -> float:
    keys = left.keys() | right.keys()
    left_total, right_total = sum(left.values()), sum(right.values())
    if left_total <= 0 or right_total <= 0:
        return 0.0 if left_total == right_total else 1.0
    return 0.5 * sum(abs(left.get(key, 0.0) / left_total - right.get(key, 0.0) / right_total)
                     for key in keys)


def root_cluster_interval(rows: list[dict[str, Any]], metric: str, seed: int,
                          repetitions: int = 2000) -> dict[str, Any]:
    """Paired curated-minus-random root-cluster bootstrap using frozen row metrics."""
    import numpy as np

    by_root: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if "_delta_metrics" not in row or metric not in row["_delta_metrics"]:
            continue
        root = str(row.get("root_id") or row.get("episode_id") or row["group_id"])
        by_root[root].append(float(row["_delta_metrics"][metric]))
    roots = sorted(by_root)
    if not roots:
        return {"status": "NOT_MEASURABLE", "cluster_count": 0}
    sums = np.asarray([sum(by_root[root]) for root in roots], dtype=np.float64)
    counts = np.asarray([len(by_root[root]) for root in roots], dtype=np.float64)
    point = float(sums.sum() / counts.sum())
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(roots), size=(repetitions, len(roots)))
    boot_sums = sums[indices].sum(axis=1)
    boot_counts = counts[indices].sum(axis=1)
    draws = boot_sums / np.maximum(boot_counts, 1.0)
    return {
        "point_delta_curated_minus_random": point,
        "family_cluster_bootstrap_95pct": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "bootstrap_repetitions": repetitions,
        "cluster_count": len(roots),
        "cluster_unit": "root_id",
    }


def calibration_bins(rows: list[dict[str, Any]], bins: int = 10) -> list[dict[str, Any]]:
    output = []
    for index in range(bins):
        selected: list[tuple[float, float]] = []
        low, high = index / bins, (index + 1) / bins
        for row in rows:
            if row["kind"] == "independent":
                predicted = float(row["prediction"][0])
                target = float(row["gold"][0])
            else:
                probabilities = [float(value) for value in row["prediction"]]
                top = max(range(len(probabilities)), key=probabilities.__getitem__)
                predicted = probabilities[top]
                target = float(row["gold"][top])
            if low <= predicted < high or (index == bins - 1 and predicted == 1.0):
                selected.append((predicted, target))
        output.append({
            "bin": index,
            "range": [low, high],
            "count": len(selected),
            "mean_prediction": sum(x for x, _ in selected) / len(selected) if selected else None,
            "mean_target_at_prediction": sum(y for _, y in selected) / len(selected) if selected else None,
        })
    return output
