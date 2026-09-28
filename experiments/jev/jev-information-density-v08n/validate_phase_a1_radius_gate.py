"""Validate the predeclared v0.8M sham/neutral radius gate.

This is a post-construction validation only.  It never chooses, replaces, or
reorders neighborhoods after seeing features, and it reads no held-out data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08m/phase_a/phase-a-v01-contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty value list")
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    receipt = read_json(args.feature_cache / "extraction-receipt.json")
    scope = [json.loads(line) for line in (args.feature_cache / "training-feature-scope.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [json.loads(line) for line in (args.selection / "selected-training-neighborhoods.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    tensor_payload = torch.load(args.feature_cache / "training-features.pt", map_location="cpu", weights_only=True)
    features = tensor_payload["features"].to(torch.float32)
    require(receipt["status"] == "PHASE_A1_FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY", "A1 extraction is not complete")
    require(receipt["model_head_training"] is False and receipt["evaluation_inference"] is False, "A1 boundary drift")
    require(receipt["protected_evaluation_bodies_opened"] is False and receipt["phoenix_access"] is False, "protected boundary drift")
    require(len(selected) == 5_000 and len(scope) == 20_000, "scope count drift")
    require(tuple(features.shape) == (20_000, 2048), f"feature tensor shape drift: {tuple(features.shape)}")
    require(tensor_payload["scope_content_sha256"] == receipt["scope"]["content_sha256"], "scope hash drift")

    by_role: dict[str, dict[str, Any]] = defaultdict(dict)
    by_family: dict[str, str] = {}
    for row in scope:
        by_role[row["neighborhood_id"]][row["role"]] = row
        by_family[row["neighborhood_id"]] = row["family_id"]
    feature_by_episode = {row["episode_id"]: features[index] for index, row in enumerate(scope)}
    require(len(feature_by_episode) == len(scope), "duplicate feature episode")

    rows: list[dict[str, Any]] = []
    for neighborhood in selected:
        neighborhood_id = neighborhood["anchor_id"]
        roles = by_role.get(neighborhood_id)
        require(roles is not None and set(roles) == {"anchor", "fact_flip", "sham", "neutral"}, f"role scope drift: {neighborhood_id}")
        anchor = feature_by_episode[roles["anchor"]["episode_id"]]
        sham = feature_by_episode[roles["sham"]["episode_id"]]
        neutral = feature_by_episode[roles["neutral"]["episode_id"]]
        fact = feature_by_episode[roles["fact_flip"]["episode_id"]]
        radius_sham = float(torch.linalg.vector_norm(sham - anchor))
        radius_neutral = float(torch.linalg.vector_norm(neutral - anchor))
        abs_error = abs(radius_neutral - radius_sham)
        rel_error = abs_error / max(radius_sham, 1.0e-12)
        sham_norm = float(torch.linalg.vector_norm(sham - anchor))
        neutral_norm = float(torch.linalg.vector_norm(neutral - anchor))
        direction_cosine = float(torch.dot(sham - anchor, neutral - anchor) / max(sham_norm * neutral_norm, 1.0e-12))
        rows.append({
            "neighborhood_id": neighborhood_id,
            "family_id": by_family[neighborhood_id],
            "radius_sham": radius_sham,
            "radius_neutral": radius_neutral,
            "absolute_radius_error": abs_error,
            "relative_radius_error": rel_error,
            "direction_cosine_telemetry_only": direction_cosine,
            "direction_gate": "not_applied",
        })

    gate = contract["representation_gate"]["predeclared_gate"]
    family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        family_rows[row["family_id"]].append(row)

    def stats(items: list[dict[str, Any]]) -> dict[str, float]:
        return {
            "count": len(items),
            "mean_sham_radius": sum(row["radius_sham"] for row in items) / len(items),
            "mean_neutral_radius": sum(row["radius_neutral"] for row in items) / len(items),
            "mean_absolute_radius_error": sum(row["absolute_radius_error"] for row in items) / len(items),
            "mean_relative_radius_error": sum(row["relative_radius_error"] for row in items) / len(items),
            "p95_absolute_radius_error": quantile([row["absolute_radius_error"] for row in items], 0.95),
            "mean_direction_cosine_telemetry_only": sum(row["direction_cosine_telemetry_only"] for row in items) / len(items),
        }

    overall = stats(rows)
    families = {family: stats(items) for family, items in sorted(family_rows.items())}
    checks = {
        "mean_relative_radius_difference": overall["mean_relative_radius_error"] <= float(gate["mean_relative_radius_difference_max"]),
        "p95_absolute_radius_difference": overall["p95_absolute_radius_error"] <= float(gate["p95_absolute_radius_difference_max"]),
        "per_family_mean_relative_radius_difference": all(
            result["mean_relative_radius_error"] <= float(gate["per_family_mean_relative_difference_max"])
            for result in families.values()
        ),
    }
    report = {
        "status": "PHASE_A1_RADIUS_GATE_PASS" if all(checks.values()) else "PHASE_A1_RADIUS_GATE_FAIL",
        "protocol": contract["protocol"],
        "phase_a_identity": contract["phase_a_identity"],
        "contract_sha256": sha256_file(CONTRACT),
        "feature_receipt_sha256": sha256_file(args.feature_cache / "extraction-receipt.json"),
        "selection_manifest_sha256": sha256_file(args.selection / "selected-training-neighborhoods.jsonl"),
        "training_only": True,
        "replacement_selection_after_features": False,
        "direction_matching_or_gating": False,
        "gate": gate,
        "overall": overall,
        "families": families,
        "checks": checks,
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
    }
    write_json(args.output, report)
    print(json.dumps(report, indent=2))
    if not all(checks.values()):
        raise SystemExit(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
