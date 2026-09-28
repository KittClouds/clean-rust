"""Compute the read-only v0.8N Road-A semantic invariance geometry atlas.

This script consumes only the sealed, training-only shared feature cache and the
feature-free selection/certificate receipts.  It never chooses controls and it
does not open evaluation material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/phase-a-v01-contract.json"
NEUTRAL_COUNT = 8
ROLES = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, NEUTRAL_COUNT + 1)]]
EPSILON_GRID = (0.025, 0.05, 0.10, 0.15, 0.25, 0.50)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def finite(value: float) -> float:
    if not math.isfinite(value):
        raise RuntimeError(f"non-finite atlas value: {value}")
    return float(value)


def quantiles(values: torch.Tensor) -> dict[str, float]:
    values = values.detach().to(dtype=torch.float64).flatten()
    if values.numel() == 0:
        return {"count": 0, "mean": None, "std": None, "min": None, "p05": None, "p50": None, "p95": None, "max": None}
    q = torch.quantile(values, torch.tensor([0.05, 0.50, 0.95], dtype=torch.float64))
    return {
        "count": int(values.numel()),
        "mean": finite(float(values.mean())),
        "std": finite(float(values.std(unbiased=False))),
        "min": finite(float(values.min())),
        "p05": finite(float(q[0])),
        "p50": finite(float(q[1])),
        "p95": finite(float(q[2])),
        "max": finite(float(values.max())),
    }


def scalar_stats(values: list[float]) -> dict[str, float]:
    return quantiles(torch.tensor(values, dtype=torch.float64))


def mean_by_group(values: torch.Tensor, groups: list[str]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for value, group in zip(values.detach().cpu().tolist(), groups):
        grouped[group].append(float(value))
    return {key: scalar_stats(items) for key, items in sorted(grouped.items())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    selection_receipt = read_json(args.selection / "selection-receipt.json")
    selected = read_jsonl(args.selection / "selected-training-neighborhoods.jsonl")
    cache_dir = args.run / "shared-feature-cache"
    cache_receipt = read_json(cache_dir / "shared-feature-cache-receipt.json")
    feature_path = cache_dir / "shared-training-features.pt"
    scope_path = cache_dir / "training-only-feature-scope.jsonl"

    if selection_receipt.get("status") != "V08N_N0_FEATURE_FREE_SELECTION_PASS" or len(selected) != 5_000:
        raise RuntimeError("Road A requires the sealed feature-free N0 selection")
    if cache_receipt.get("status") != "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY":
        raise RuntimeError("shared training-only feature cache is not sealed")
    if cache_receipt.get("evaluation_inference") or cache_receipt.get("protected_evaluation_bodies_opened"):
        raise RuntimeError("cache boundary receipt is not clean")
    if cache_receipt["feature_tensor"]["shape"] != [55_000, 2_048]:
        raise RuntimeError("shared feature shape drift")
    if cache_receipt["feature_tensor"]["sha256"] != sha256_file(feature_path):
        raise RuntimeError("shared feature file hash drift")

    scope = read_jsonl(scope_path)
    features_payload = torch.load(feature_path, map_location="cpu", weights_only=True)
    features = features_payload["features"].to(dtype=torch.float32)
    if tuple(features.shape) != (55_000, 2_048) or len(scope) != 55_000:
        raise RuntimeError("shared feature scope/shape mismatch")
    if features_payload.get("scope_content_sha256") != cache_receipt["scope"]["content_sha256"]:
        raise RuntimeError("feature scope hash mismatch")

    certificates = {row["anchor_id"]: row for row in read_jsonl(args.run / "train-contrast-certificates.jsonl")}
    if len(certificates) != 12_000:
        raise RuntimeError("training certificate count drift")

    selected_ids = [row["anchor_id"] for row in selected]
    if len(set(selected_ids)) != 5_000:
        raise RuntimeError("selected anchor identity drift")
    scope_by_neighborhood: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scope:
        scope_by_neighborhood[row["neighborhood_id"]].append(row)
    if any(len(scope_by_neighborhood[anchor_id]) != 11 for anchor_id in selected_ids):
        raise RuntimeError("scope does not contain exactly 11 rows per selected neighborhood")

    neighborhoods: list[dict[str, Any]] = []
    for index, anchor_id in enumerate(selected_ids):
        rows = scope_by_neighborhood[anchor_id]
        rows.sort(key=lambda row: row["index"])
        if [row["role"] for row in rows] != ROLES:
            raise RuntimeError(f"role/order drift for {anchor_id}")
        neighborhoods.append({"anchor_id": anchor_id, "family_id": selected[index]["family_id"], "certificate": certificates[anchor_id], "rows": rows, "feature_index": index * 11})

    x = features.reshape(5_000, 11, 2_048)
    anchor = x[:, 0, :]
    fact = x[:, 1, :]
    sham = x[:, 2, :]
    neutrals = x[:, 3:, :]
    d_fact = fact - anchor
    d_sham = sham - anchor
    d_neutral = neutrals - anchor[:, None, :]
    r_fact = torch.linalg.vector_norm(d_fact, dim=1).to(torch.float64)
    r_sham = torch.linalg.vector_norm(d_sham, dim=1).to(torch.float64)
    r_neutral = torch.linalg.vector_norm(d_neutral, dim=2).to(torch.float64)

    def cosine(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
        left_norm = torch.linalg.vector_norm(left, dim=-1)
        right_norm = torch.linalg.vector_norm(right, dim=-1)
        denominator = (left_norm * right_norm).clamp_min(torch.finfo(torch.float64).tiny)
        return (left * right).sum(dim=-1) / denominator

    cos_sham_fact = cosine(d_sham, d_fact).to(torch.float64)
    cos_neutral_sham = cosine(d_neutral, d_sham[:, None, :]).to(torch.float64)
    cos_neutral_fact = cosine(d_neutral, d_fact[:, None, :]).to(torch.float64)
    neutral_pair_cos = torch.empty((5_000, 8, 8), dtype=torch.float64)
    for left in range(NEUTRAL_COUNT):
        for right in range(NEUTRAL_COUNT):
            neutral_pair_cos[:, left, right] = cosine(d_neutral[:, left, :], d_neutral[:, right, :])

    radius_error = (r_neutral - r_sham[:, None]).abs()
    relative_error = radius_error / r_sham[:, None].clamp_min(torch.finfo(torch.float64).tiny)
    cumulative_min_error = torch.cummin(radius_error, dim=1).values
    q_ratio = r_neutral / r_sham[:, None].clamp_min(torch.finfo(torch.float64).tiny)
    families = [row["family_id"] for row in selected]
    schema = [certificates[anchor_id]["schema_family_id"] for anchor_id in selected_ids]
    profile = [str(certificates[anchor_id]["profile_index"]) for anchor_id in selected_ids]
    axes = [f"neutral_{index}" for index in range(1, NEUTRAL_COUNT + 1)]

    axis_report: dict[str, Any] = {}
    for axis_index, axis in enumerate(axes):
        axis_report[axis] = {
            "radius": quantiles(r_neutral[:, axis_index]),
            "radius_ratio_to_sham": quantiles(q_ratio[:, axis_index]),
            "absolute_radius_error_to_sham": quantiles(radius_error[:, axis_index]),
            "relative_radius_error_to_sham": quantiles(relative_error[:, axis_index]),
            "cosine_to_sham": quantiles(cos_neutral_sham[:, axis_index]),
            "cosine_to_fact": quantiles(cos_neutral_fact[:, axis_index]),
            "by_family_radius": mean_by_group(r_neutral[:, axis_index], families),
            "by_family_relative_error": mean_by_group(relative_error[:, axis_index], families),
            "by_profile_radius": mean_by_group(r_neutral[:, axis_index], profile),
            "by_schema_radius": mean_by_group(r_neutral[:, axis_index], schema),
        }

    coverage: dict[str, dict[str, float]] = {}
    for epsilon in EPSILON_GRID:
        key = f"{epsilon:.3f}"
        coverage[key] = {f"first_{k}": finite(float((cumulative_min_error[:, k - 1] <= epsilon).to(dtype=torch.float64).mean())) for k in range(1, NEUTRAL_COUNT + 1)}

    nearest_axis = radius_error.argmin(dim=1)
    nearest_axis_counts = {axes[index]: int((nearest_axis == index).sum()) for index in range(NEUTRAL_COUNT)}
    lower_triangle = torch.triu(neutral_pair_cos, diagonal=1)
    pair_values = lower_triangle[lower_triangle != 0]
    report = {
        "status": "V08N_ROAD_A_GEOMETRY_ATLAS_PASS",
        "protocol": contract["protocol"],
        "phase_identity": "v0.8N-road-a-atlas-v01",
        "parent_contract_sha256": sha256_file(CONTRACT),
        "selection_manifest_sha256": sha256_file(args.selection / "selected-training-neighborhoods.jsonl"),
        "shared_cache_receipt_sha256": sha256_file(cache_dir / "shared-feature-cache-receipt.json"),
        "shared_feature_sha256": cache_receipt["feature_tensor"]["sha256"],
        "training_only": True,
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "neighborhoods": 5_000,
        "roles": ROLES,
        "feature_shape": list(features.shape),
        "fact_radius": quantiles(r_fact),
        "sham_radius": quantiles(r_sham),
        "sham_fact_cosine": quantiles(cos_sham_fact),
        "neutral_axes": axis_report,
        "neutral_pairwise_cosine_upper_triangle": quantiles(pair_values),
        "nearest_sham_radius_error": quantiles(cumulative_min_error[:, -1]),
        "nearest_sham_relative_error": quantiles(relative_error.gather(1, nearest_axis[:, None]).squeeze(1)),
        "nearest_axis_counts": nearest_axis_counts,
        "coverage_by_radius_error_epsilon": coverage,
        "candidate_count_curve": {
            str(k): {
                "absolute_radius_error": quantiles(cumulative_min_error[:, k - 1]),
                "relative_radius_error": quantiles(relative_error[:, :k].amin(dim=1)),
            }
            for k in range(1, NEUTRAL_COUNT + 1)
        },
        "by_family_sham_radius": mean_by_group(r_sham, families),
        "by_family_sham_fact_cosine": mean_by_group(cos_sham_fact, families),
        "by_profile_sham_radius": mean_by_group(r_sham, profile),
        "by_schema_sham_radius": mean_by_group(r_sham, schema),
        "road_b_selection_forbidden": True,
        "direction_matching": False,
        "selection_after_features": False,
    }
    output_dir = args.output / "road-a"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "road-a-geometry-atlas.json"
    if report_path.exists():
        raise RuntimeError("refusing to overwrite Road-A atlas")
    write_json(report_path, report)
    receipt = {
        "status": report["status"],
        "phase_identity": report["phase_identity"],
        "report_sha256": sha256_file(report_path),
        "report_path": str(report_path),
        "training_only": True,
        "road_b_not_selected": True,
        "no_model_head_training": True,
        "no_evaluation_inference": True,
        "no_protected_evaluation_bodies_opened": True,
        "no_phoenix": True,
    }
    write_json(output_dir / "road-a-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
