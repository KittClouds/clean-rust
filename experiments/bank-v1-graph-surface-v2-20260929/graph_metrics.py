"""Small pure-Python metric and report helpers for Graph Surface v2."""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def matrix_rank(scores: np.ndarray, truth_index: int) -> float:
    target = scores[truth_index]
    greater = np.count_nonzero(scores > target)
    equal = np.count_nonzero(scores == target)
    return float(1 + greater + (equal - 1) / 2)


def binary_auc(y: np.ndarray, scores: np.ndarray) -> float | None:
    positives = int(np.count_nonzero(y == 1))
    negatives = int(np.count_nonzero(y == 0))
    if not positives or not negatives:
        return None
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(order), dtype=np.float64)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and scores[order[j]] == scores[order[i]]:
            j += 1
        ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    rank_sum = ranks[y == 1].sum()
    return float((rank_sum - positives * (positives + 1) / 2) / (positives * negatives))


def classification_metrics(y: np.ndarray, logits: np.ndarray, classes: int) -> dict:
    if len(y) == 0:
        return {"n": 0}
    pred = np.argmax(logits, axis=1)
    per_f1 = []
    recalls = []
    evaluated_labels = np.union1d(np.unique(y), np.unique(pred))
    for label in evaluated_labels:
        tp = int(np.count_nonzero((y == label) & (pred == label)))
        fp = int(np.count_nonzero((y != label) & (pred == label)))
        fn = int(np.count_nonzero((y == label) & (pred != label)))
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        per_f1.append(2 * precision * recall / max(1e-12, precision + recall))
        if np.any(y == label):
            recalls.append(recall)
    result = {"n": int(len(y)), "accuracy": float(np.mean(pred == y)),
              "macro_f1": float(np.mean(per_f1)), "balanced_accuracy": float(np.mean(recalls))}
    if classes == 2:
        result["roc_auc"] = binary_auc(y, logits[:, 1])
    return result


def link_metrics(ranks: list[float], candidate_counts: list[int]) -> dict:
    if not ranks:
        return {"queries": 0}
    array = np.asarray(ranks, dtype=np.float64)
    return {"queries": len(ranks), "mrr": float(np.mean(1.0 / array)),
            "hits_at_1": float(np.mean(array <= 1)),
            "hits_at_3": float(np.mean(array <= 3)),
            "hits_at_10": float(np.mean(array <= 10)),
            "mean_candidates": float(np.mean(candidate_counts))}


def random_link_metrics(records):
    def score(rows):
        if not rows:
            return {"queries": 0}
        sizes = [max(1, len(row["candidate_indices"])) for row in rows]
        mrr = [sum(1.0 / rank for rank in range(1, size + 1)) / size for size in sizes]
        return {"queries": len(rows), "mrr": float(np.mean(mrr)),
                "hits_at_1": float(np.mean([1 / size for size in sizes])),
                "hits_at_3": float(np.mean([min(3, size) / size for size in sizes])),
                "hits_at_10": float(np.mean([min(10, size) / size for size in sizes])),
                "mean_candidates": float(np.mean(sizes))}
    result = score(records)
    grouped = defaultdict(list)
    for row in records:
        grouped[str(row.get("family", "UNKNOWN"))].append(row)
    result["by_renderer"] = {family: score(rows) for family, rows in grouped.items()}
    return result


def metric_bundle(y, logits, classes, records):
    result = classification_metrics(y, logits, classes)
    if records and "feature_kind" in records[0]:
        result["by_feature_kind"] = {}
        for kind in sorted({str(row["feature_kind"]) for row in records}):
            positions = np.asarray([i for i, row in enumerate(records)
                                    if str(row["feature_kind"]) == kind], dtype=np.int64)
            result["by_feature_kind"][kind] = classification_metrics(
                y[positions], logits[positions], classes)
    if records and "family" in records[0]:
        result["by_renderer"] = {}
        for family in sorted({str(row["family"]) for row in records}):
            positions = np.asarray([i for i, row in enumerate(records)
                                    if str(row["family"]) == family], dtype=np.int64)
            result["by_renderer"][family] = classification_metrics(
                y[positions], logits[positions], classes)
    return result


def aggregate_renderer(metrics_by_split: dict, field: str, held_out: bool | None = None):
    total_weight = 0
    weighted = 0.0
    for metrics in metrics_by_split.values():
        if not isinstance(metrics, dict):
            continue
        for family, entry in (metrics.get("by_renderer") or {}).items():
            is_held = family in ("S7", "S8", "S9")
            if held_out is not None and is_held != held_out:
                continue
            value = entry.get(field)
            weight = entry.get("n", entry.get("queries", 0))
            if value is None or not weight:
                continue
            weighted += float(value) * weight
            total_weight += weight
    return weighted / total_weight if total_weight else None


def aggregate_over_splits(metrics_by_split: dict, field: str):
    total_weight = 0
    weighted = 0.0
    for metrics in metrics_by_split.values():
        if not isinstance(metrics, dict):
            continue
        value = metrics.get(field)
        weight = metrics.get("queries", metrics.get("n", 0))
        if value is None or not weight:
            continue
        weighted += float(value) * weight
        total_weight += weight
    return weighted / total_weight if total_weight else None


def aggregate_control_renderer(controls_by_split, name, field, held_out):
    total_weight = 0
    weighted = 0.0
    for split, controls in controls_by_split.items():
        if not split.startswith("TEST-"):
            continue
        metrics = controls.get(name, {})
        for family, entry in (metrics.get("by_renderer") or {}).items():
            if (family in ("S7", "S8", "S9")) != held_out:
                continue
            value = entry.get(field)
            weight = entry.get("n", entry.get("queries", 0))
            if value is None or not weight:
                continue
            weighted += float(value) * weight
            total_weight += weight
    return weighted / total_weight if total_weight else None


def aggregate_control_splits(controls_by_split, name, field):
    total_weight = 0
    weighted = 0.0
    for split, controls in controls_by_split.items():
        if not split.startswith("TEST-"):
            continue
        metrics = controls.get(name, {})
        value = metrics.get(field)
        weight = metrics.get("n", metrics.get("queries", 0))
        if value is None or not weight:
            continue
        weighted += float(value) * weight
        total_weight += weight
    return weighted / total_weight if total_weight else None


def write_report(path, report):
    lines = ["# BANK-v1 Graph Surface Extraction v2 — Results", "",
             f"**Disposition:** {report.get('gate', {}).get('status', 'SCORING_IN_PROGRESS')}", "",
             "Frozen LFM2.5-230M-Base; one span-local extraction pass; no fine-tuning or generation. "
             "Rung-0 whole-row primitives were reused read-only.", "",
             "| Task | Best local surface / head | Test metric | Control | S7/S8/S9 metric |",
             "|---|---|---:|---:|---:|"]
    for task, entry in report.get("task_summary", {}).items():
        lines.append(f"| {task} | {entry.get('best_model', '—')} | {entry.get('test_metric', '—')} | "
                     f"{entry.get('best_control', '—')} | {entry.get('held_renderer_metric', '—')} |")
    lines += ["", "The report contains split- and renderer-specific metrics, control scores, extraction provenance, and model receipts.",
              "Graph targets come from BANK-v1's synthetic canonical worlds. This is an engineering readout, not a natural-language graph or serving claim.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
