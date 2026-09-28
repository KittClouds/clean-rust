#!/usr/bin/env python3
"""Independent read-only audit for an AR-04B output directory."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

TIE_EPSILON = 1.0e-7
PANEL_SIZES = {8, 16, 32, 64, 128}
METHODS = {"sentinel_exact", "sentinel_taylor"}


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sign(value: float) -> int:
    if abs(value) <= TIE_EPSILON:
        return 0
    return 1 if value > 0.0 else -1


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    output = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and abs(values[order[end]] - values[order[start]]) <= TIE_EPSILON:
            end += 1
        midpoint = (start + 1 + end) / 2.0
        for index in order[start:end]:
            output[index] = midpoint
        start = end
    return output


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    covariance = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    variance_left = sum((x - mean_left) ** 2 for x in left)
    variance_right = sum((y - mean_right) ** 2 for y in right)
    if variance_left == 0.0 or variance_right == 0.0:
        return None
    return covariance / math.sqrt(variance_left * variance_right)


def compare(scores: list[float], reference: list[float]) -> dict[str, float | int | None]:
    score_ranks = ranks(scores)
    reference_ranks = ranks(reference)
    spearman = pearson(score_ranks, reference_ranks)
    compared = 0
    concordant = 0
    tied_score = 0
    tied_reference = 0
    for left in range(len(scores)):
        for right in range(left + 1, len(scores)):
            score_order = sign(scores[left] - scores[right])
            ref_order = sign(reference[left] - reference[right])
            tied_score += score_order == 0
            tied_reference += ref_order == 0
            if score_order and ref_order:
                compared += 1
                concordant += score_order == ref_order
    selected = max(range(len(scores)), key=lambda index: (scores[index], -index))
    best_reference = max(reference)
    return {
        "spearman": spearman,
        "pairwise_agreement": concordant / compared if compared else None,
        "compared_pairs": compared,
        "tied_source_pairs": tied_score,
        "tied_reference_pairs": tied_reference,
        "top1_agreement": float(selected == max(range(len(reference)), key=lambda i: (reference[i], -i))),
        "candidate_set_regret": best_reference - reference[selected],
    }


def close(actual: str, expected: float | int | None) -> bool:
    if expected is None:
        return actual == "null"
    return abs(float(actual) - float(expected)) <= 2.0e-8


def validate(root: Path) -> dict[str, object]:
    receipt = json.loads((root / "integrity-receipt.json").read_text(encoding="utf-8"))
    assert receipt["integrity_valid"] is True

    data_manifest = rows(root / "dataset-manifest.csv")
    data_artifacts = receipt["data_artifacts"]
    assert len(data_manifest) == len(data_artifacts) == 30
    unique_samples: set[bytes] = set()
    row_count = 0
    for manifest_row, artifact in zip(data_manifest, data_artifacts):
        file_path = root / manifest_row["path"]
        assert manifest_row["path"] == artifact["path"]
        assert sha256(file_path) == manifest_row["sha256"] == artifact["sha256"]
        data = file_path.read_bytes()
        count = int(manifest_row["sample_count"])
        assert len(data) == count * 36
        for offset in range(0, len(data), 36):
            sample = data[offset : offset + 36]
            assert sample not in unique_samples, "duplicate row across train/sentinel/measurement"
            unique_samples.add(sample)
            row_count += 1

    for artifact in receipt["derived_output_sha256"]:
        assert sha256(root / artifact["path"]) == artifact["sha256"]

    states = rows(root / "state-manifest.csv")
    candidates = rows(root / "candidate-manifest.csv")
    references = rows(root / "reference-action-scores.csv")
    sentinels = rows(root / "sentinel-action-scores.csv")
    metrics = rows(root / "ranking-metrics.csv")
    assert len(states) == 75
    assert len((root / "model-states.bin").read_bytes()) == 75 * 171 * 4
    assert len(candidates) == len(references) == receipt["candidate_action_count"]
    candidate_count = defaultdict(int)
    for candidate in candidates:
        candidate_count[int(candidate["state_id"])] += 1
    assert all(candidate_count[int(state["state_id"])] == int(state["candidate_count"]) for state in states)

    reference_by_state: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in references:
        reference_by_state[int(row["state_id"])].append(row)
    for state_rows in reference_by_state.values():
        state_rows.sort(key=lambda row: int(row["action_id"]))
        assert len({int(row["action_id"]) for row in state_rows}) == len(state_rows)
    action_total = sum(map(len, reference_by_state.values()))
    assert len(sentinels) == action_total * 4 * 5 * 2

    panel_scores: dict[tuple[int, int, int, str], dict[int, float]] = defaultdict(dict)
    for row in sentinels:
        panel_size = int(row["sample_count"])
        method = row["method"]
        action_id = int(row["action_id"])
        value = float(row["utility"])
        assert panel_size in PANEL_SIZES and method in METHODS and math.isfinite(value)
        key = (int(row["state_id"]), int(row["panel_id"]), panel_size, method)
        assert action_id not in panel_scores[key]
        panel_scores[key][action_id] = value
    assert len(panel_scores) == 75 * 4 * 5 * 2

    metric_index = {}
    for row in metrics:
        key = (
            int(row["state_id"]),
            int(row["panel_id"]),
            row["source"],
            int(row["panel_size"]),
        )
        assert key not in metric_index
        metric_index[key] = row
    assert len(metric_index) == 75 * (1 + 4 * 5 * 2)

    checked_metric_rows = 0
    for state_id, state_references in reference_by_state.items():
        train = [float(row["training_exact"]) for row in state_references]
        reference = [float(row["final_measurement_exact"]) for row in state_references]
        key = (state_id, -1, "training_exact", 96)
        assert_metric(metric_index[key], compare(train, reference))
        checked_metric_rows += 1
        for (group_state, panel_id, panel_size, method), values_by_action in panel_scores.items():
            if group_state != state_id:
                continue
            score = [values_by_action[index] for index in range(len(state_references))]
            source = method
            key = (state_id, panel_id, source, panel_size)
            assert_metric(metric_index[key], compare(score, reference))
            checked_metric_rows += 1
    assert checked_metric_rows == len(metrics)
    return {
        "valid": True,
        "states": len(states),
        "crossed_cells": 25,
        "candidate_actions": action_total,
        "sentinel_score_rows": len(sentinels),
        "ranking_metric_rows_independently_recomputed": checked_metric_rows,
        "unique_disjoint_sample_rows": row_count,
        "data_artifacts_hash_checked": len(data_manifest),
        "derived_output_hashes_checked": len(receipt["derived_output_sha256"]),
    }


def assert_metric(row: dict[str, str], expected: dict[str, float | int | None]) -> None:
    for key in (
        "spearman",
        "pairwise_agreement",
        "compared_pairs",
        "tied_source_pairs",
        "tied_reference_pairs",
        "top1_agreement",
        "candidate_set_regret",
    ):
        if not close(row[key], expected[key]):
            raise AssertionError(f"ranking metric mismatch for {key}: {row[key]} != {expected[key]}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_artifacts.py <run-directory>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    report = validate(root)
    (root / "validation-receipt.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
