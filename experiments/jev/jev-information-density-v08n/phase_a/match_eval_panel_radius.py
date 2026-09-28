"""Select the held-out matched-neutral control by the frozen radius-only rule."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/eval-panel-v01-contract.json"
NEUTRAL_COUNT = 8
ROLES = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, 9)]]


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def tie_hash(anchor_id: str, role: str) -> str:
    return hashlib.sha256(f"{anchor_id}|{role}".encode("utf-8")).hexdigest()


def target_hash(target: list[float]) -> str:
    payload = json.dumps(target, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def quantile(values: torch.Tensor, q: float) -> float:
    return float(torch.quantile(values.to(torch.float64), torch.tensor(q, dtype=torch.float64)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    scope_receipt = read_json(args.panel / "semantic-scope-receipt.json")
    scope = read_jsonl(args.panel / "heldout-feature-scope.jsonl")
    feature_receipt = read_json(args.features / "heldout-feature-cache-receipt.json")
    feature_path = args.features / "heldout-features.pt"
    if scope_receipt["status"] != "V08N_HELDOUT_PANEL_SEMANTIC_SCOPE_PASS" or len(scope) != 22_000:
        raise RuntimeError("semantic held-out scope is not promotable")
    if feature_receipt["status"] != "V08N_HELDOUT_FEATURE_CACHE_SEALED_FROZEN_BACKBONE_ONLY":
        raise RuntimeError("held-out feature cache is not sealed")
    if feature_receipt["scope_sha256"] != sha256_file(args.panel / "heldout-feature-scope.jsonl"):
        raise RuntimeError("feature scope drift")
    if feature_receipt["feature_tensor"]["sha256"] != sha256_file(feature_path):
        raise RuntimeError("feature tensor hash drift")
    if contract["representation"]["direction_or_cosine_matching"]:
        raise RuntimeError("direction matching is forbidden")

    payload = torch.load(feature_path, map_location="cpu", weights_only=True)
    features = payload["features"].to(dtype=torch.float64)
    if tuple(features.shape) != (22_000, 2_048):
        raise RuntimeError("held-out feature shape drift")
    if payload.get("scope_sha256") != sha256_file(args.panel / "heldout-feature-scope.jsonl"):
        raise RuntimeError("feature payload scope drift")
    by_neighborhood: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scope:
        by_neighborhood[row["neighborhood_id"]].append(row)
    if len(by_neighborhood) != 2_000 or any(len(rows) != 11 for rows in by_neighborhood.values()):
        raise RuntimeError("held-out neighborhood scope drift")

    selected: list[dict[str, Any]] = []
    all_panel_rows: list[dict[str, Any]] = []
    relative_errors: list[float] = []
    absolute_errors: list[float] = []
    family_relative: dict[str, list[float]] = defaultdict(list)
    axis_counts: Counter[str] = Counter()
    neighborhoods = sorted(by_neighborhood.items(), key=lambda item: item[0])
    x = features.reshape(2_000, 11, 2_048)
    for index, (anchor_id, rows) in enumerate(neighborhoods):
        rows.sort(key=lambda row: row["index"])
        if [row["role"] for row in rows] != ROLES:
            raise RuntimeError(f"held-out role order drift: {anchor_id}")
        anchor, _, sham = x[index, 0], x[index, 1], x[index, 2]
        neutral = x[index, 3:]
        sham_radius = float(torch.linalg.vector_norm(sham - anchor))
        neutral_radius = torch.linalg.vector_norm(neutral - anchor, dim=1)
        errors = (neutral_radius - sham_radius).abs()
        candidates = []
        for neutral_index, error in enumerate(errors.tolist(), start=1):
            role = f"neutral_{neutral_index}"
            candidates.append((float(error), tie_hash(anchor_id, role), neutral_index))
        error, _, selected_index = min(candidates, key=lambda item: (item[0], item[1]))
        selected_row = rows[2 + selected_index]
        relative = error / max(sham_radius, torch.finfo(torch.float64).tiny)
        absolute = error
        family = rows[0]["family_id"]
        axis = selected_row["role"]
        selected_record = {
            "neighborhood_id": anchor_id,
            "family_id": family,
            "template_id": rows[0]["template_id"],
            "anchor_episode_id": rows[0]["episode_id"],
            "fact_episode_id": rows[1]["episode_id"],
            "sham_episode_id": rows[2]["episode_id"],
            "matched_neutral_episode_id": selected_row["episode_id"],
            "sham_axis": rows[2]["role"],
            "matched_neutral_axis": axis,
            "sham_radius": sham_radius,
            "matched_neutral_radius": float(neutral_radius[selected_index - 1]),
            "absolute_radius_error": absolute,
            "relative_radius_error": relative,
            "target_hash": target_hash(rows[0]["target"]),
            "selection_rule": "argmin absolute sham-radius mismatch; sha256(anchor_id|role) tie-break",
        }
        selected.append(selected_record)
        all_panel_rows.append({
            "neighborhood_id": anchor_id,
            "family_id": family,
            "template_id": rows[0]["template_id"],
            "anchor_episode_id": rows[0]["episode_id"],
            "fact_episode_id": rows[1]["episode_id"],
            "sham_episode_id": rows[2]["episode_id"],
            "matched_neutral_episode_id": selected_row["episode_id"],
            "target_hash": target_hash(rows[0]["target"]),
            "partition": "eval",
        })
        relative_errors.append(relative)
        absolute_errors.append(absolute)
        family_relative[family].append(relative)
        axis_counts[axis] += 1

    relative_tensor = torch.tensor(relative_errors, dtype=torch.float64)
    absolute_tensor = torch.tensor(absolute_errors, dtype=torch.float64)
    family_means = {family: sum(values) / len(values) for family, values in sorted(family_relative.items())}
    gates = contract["representation"]["gates"]
    gate_results = {
        "mean_relative_radius_difference": float(relative_tensor.mean()),
        "p95_absolute_radius_difference": quantile(absolute_tensor, 0.95),
        "per_family_mean_relative_radius_difference": family_means,
        "mean_relative_pass": float(relative_tensor.mean()) <= gates["mean_relative_radius_difference_max"],
        "p95_absolute_pass": quantile(absolute_tensor, 0.95) <= gates["p95_absolute_radius_difference_max"],
        "per_family_pass": all(value <= gates["per_family_mean_relative_difference_max"] for value in family_means.values()),
        "all_pass": False,
    }
    gate_results["all_pass"] = bool(gate_results["mean_relative_pass"] and gate_results["p95_absolute_pass"] and gate_results["per_family_pass"])

    args.output.mkdir(parents=True, exist_ok=False)
    write_jsonl(args.output / "selected-heldout-matched-neutral.jsonl", selected)
    write_jsonl(args.output / "heldout-matched-panel-manifest.jsonl", all_panel_rows)
    write_json(args.output / "radius-gate-report.json", {"status": "PASS" if gate_results["all_pass"] else "FAIL", "rule": "frozen radius-only selection", "gates": gates, "results": gate_results})
    write_json(args.output / "semantic-axis-composition.json", {"selected_count": len(selected), "axis_counts": dict(sorted(axis_counts.items())), "selection_rule": "radius-only; no direction/cosine; no replacement shopping"})
    receipt = {
        "status": "V08N_HELDOUT_MATCHED_PANEL_RADIUS_GATE_PASS" if gate_results["all_pass"] else "V08N_HELDOUT_MATCHED_PANEL_RADIUS_GATE_FAIL",
        "identity": "v0.8N-eval-panel-v01",
        "contract_sha256": sha256_file(CONTRACT),
        "semantic_scope_sha256": sha256_file(args.panel / "semantic-scope-receipt.json"),
        "feature_cache_sha256": sha256_file(args.features / "heldout-feature-cache-receipt.json"),
        "feature_tensor_sha256": sha256_file(feature_path),
        "neighborhood_count": len(selected),
        "selection_rule": "argmin absolute sham-radius mismatch; sha256(anchor_id|role) tie-break",
        "direction_or_cosine_used": False,
        "evaluation_outcomes_used": False,
        "replacement_selection_after_geometry": False,
        "gates": gate_results,
        "outputs": {
            "selected": {"path": str(args.output / "selected-heldout-matched-neutral.jsonl"), "sha256": sha256_file(args.output / "selected-heldout-matched-neutral.jsonl")},
            "panel_manifest": {"path": str(args.output / "heldout-matched-panel-manifest.jsonl"), "sha256": sha256_file(args.output / "heldout-matched-panel-manifest.jsonl")},
            "radius_report": {"path": str(args.output / "radius-gate-report.json"), "sha256": sha256_file(args.output / "radius-gate-report.json")},
            "axis_report": {"path": str(args.output / "semantic-axis-composition.json"), "sha256": sha256_file(args.output / "semantic-axis-composition.json")},
        },
        "head_load": False,
        "head_training": False,
        "evaluation_inference": False,
        "newtight_access": False,
        "phoenix_access": False,
        "panel_locked": True,
    }
    write_json(args.output / "matched-panel-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if gate_results["all_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
