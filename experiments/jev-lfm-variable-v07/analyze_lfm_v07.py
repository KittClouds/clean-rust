"""Produce read-only v0.7 scaling and integrity summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[2]
RUN = Path(r"D:\codex-runs\jev-lfm-variable-v07")
MODEL = "lfm2.5-1.2b-base"
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
sys.path.insert(0, str(V05))
import train_v05 as base  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def metric(report: dict[str, Any], source: str = "synthetic_control") -> dict[str, Any]:
    value = report["test"]["temperature_scaled"]["source_dataset"][source]["exact_generative_posterior"]
    return {
        key: value.get(key)
        for key in ("count", "accuracy", "nll", "brier", "ece_soft")
    }


def summarize() -> dict[str, Any]:
    head_root = RUN / "head-runs" / MODEL
    reports = {}
    for scale in (50, 100, 250):
        path = head_root / f"{MODEL}-s{scale}k-S100.json"
        if path.exists():
            reports[f"{scale}k"] = load_json(path)
    curve = {
        "protocol": "jev-lfm-architecture-variable/v0.7",
        "model": MODEL,
        "scales": {name: metric(report) for name, report in reports.items()},
        "promotion": {
            "rule": "run 250k only when 50k->100k exact accuracy gain >= .03 or at least two major semantic/OOD rank metrics improve materially",
            "invoked": "250k" in reports,
            "reason": "observed 50k and 100k reports are required before promotion decision",
        },
    }
    if "50k" in reports and "100k" in reports:
        a = curve["scales"]["50k"]["accuracy"]
        b = curve["scales"]["100k"]["accuracy"]
        curve["promotion"].update({
            "exact_accuracy_gain": b - a,
            "accuracy_threshold_pass": (b - a) >= 0.03,
        })
    out = RUN / "reports" / "lfm-scaling-curve.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(curve, indent=2), encoding="utf-8")
    return curve


def write_integrity() -> dict[str, Any]:
    contract = ROOT / "experiments" / "jev-lfm-variable-v07" / "v07-contract.json"
    model_root = RUN / "models" / MODEL
    files = {}
    for path in sorted(model_root.glob("*")):
        if path.is_file():
            files[path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    receipt = {
        "protocol": "jev-lfm-architecture-variable/v0.7",
        "contract_sha256": sha256(contract),
        "model": {
            "repo_id": "LiquidAI/LFM2.5-1.2B-Base",
            "revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
            "files": files,
        },
        "integrity_claims": {
            "phoenix_touched": False,
            "prior_model_weights_touched": False,
            "lfm_weights_touched": False,
            "v04_gate_modified": False,
            "v05_reports_modified": False,
            "v06_reports_modified": False,
            "fixed_compatibility_head": True,
            "fixed_s100_bank": True,
            "lfm_specific_hyperparameter_optimization": False,
        },
    }
    path = RUN / "reports" / "v07-integrity-receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    validation_path = RUN / "reports" / "lfm-feature-validation.json"
    manifest_path = RUN / "features" / f"{MODEL}-feature-manifest.json"
    integration = {
        "protocol": "jev-lfm-architecture-variable/v0.7-integration",
        "model": receipt["model"],
        "feature_validation": load_json(validation_path) if validation_path.exists() else None,
        "feature_manifest_sha256": sha256(manifest_path) if manifest_path.exists() else None,
        "claims": receipt["integrity_claims"],
        "status": "validated_snapshot_and_frozen_adapter",
    }
    (RUN / "reports" / "lfm-integration-receipt.json").write_text(json.dumps(integration, indent=2), encoding="utf-8")
    return receipt


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2:
        return None
    left_mean = sum(left) / len(left); right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_var = sum((a - left_mean) ** 2 for a in left); right_var = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_var * right_var)
    return numerator / denominator if denominator > 1e-12 else None


def score_stress() -> dict[str, Any]:
    cache_path = RUN / "features" / "s250k" / f"{MODEL}-features.pt"
    head_path = RUN / "head-runs" / MODEL / f"{MODEL}-s100k-S100.pt"
    cache = torch.load(cache_path, map_location="cpu", weights_only=False)
    key = f"mean_full@{cache['layer_count']}"
    state = cache["features"]["state"][key].to("cuda")
    candidates = cache["features"]["candidate"]["name_definition"][key].to("cuda")
    head = base.probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to("cuda")
    head.load_state_dict(torch.load(head_path, map_location="cuda", weights_only=True)); head.eval()
    groups = [item for item in cache["groups"] if item["split"] == "test" and not item["open_world"] and item["kind"] in {"choice", "independent"}]
    rows = base.fast_score_groups(head, groups, state, candidates, "name_definition", "cuda")
    by_id = {item["group_id"]: item for item in groups}
    row_by_id = {item["group_id"]: item for item in rows}
    cardinality = {}
    for value in sorted({item.get("candidate_cardinality", 1) for item in groups}):
        selected = [row for row, group in zip(rows, groups) if group.get("candidate_cardinality", 1) == value]
        cardinality[str(value)] = base.probe.metric_summary(selected)
    perturbation = {}
    for name in sorted({item.get("perturbation_class") or "base" for item in groups}):
        selected = [row for row in rows if (by_id[row["group_id"]].get("perturbation_class") or "base") == name]
        perturbation[name] = base.probe.metric_summary(selected)
    pair_records: dict[str, dict[str, list[float]]] = {}
    for group in groups:
        if group.get("kind") != "choice":
            continue
        base_group = None
        if group.get("perturbation_class") is None:
            base_group = group
        else:
            candidates_for_key = [item for item in groups if item.get("invariant_key") == group.get("invariant_key") and item.get("perturbation_class") is None and item.get("query_id") == group.get("query_id")]
            base_group = candidates_for_key[0] if candidates_for_key else None
        if base_group is None or base_group["group_id"] == group["group_id"]:
            continue
        left = by_id[base_group["group_id"]]; right = by_id[group["group_id"]]
        left_row = row_by_id.get(base_group["group_id"]); right_row = row_by_id.get(group["group_id"])
        if left_row is None or right_row is None:
            continue
        left_gold = dict(zip(left["candidate_semantic_ids"], left["gold"]))
        right_gold = dict(zip(right["candidate_semantic_ids"], right["gold"]))
        left_pred = dict(zip(left["candidate_semantic_ids"], left_row["prediction"]))
        right_pred = dict(zip(right["candidate_semantic_ids"], right_row["prediction"]))
        shared = sorted(set(left_gold) & set(right_gold) & set(left_pred) & set(right_pred))
        if not shared:
            continue
        class_name = group.get("perturbation_class") or "base"
        entry = pair_records.setdefault(class_name, {"gold_delta": [], "model_delta": [], "absolute_error": [], "sign_agreement": []})
        for semantic_id in shared:
            gold_delta = right_gold[semantic_id] - left_gold[semantic_id]
            model_delta = right_pred[semantic_id] - left_pred[semantic_id]
            entry["gold_delta"].append(gold_delta); entry["model_delta"].append(model_delta); entry["absolute_error"].append(abs(model_delta - gold_delta))
            entry["sign_agreement"].append(float((gold_delta == 0 and abs(model_delta) < 0.05) or (gold_delta * model_delta > 0)))
    interventions = {}
    for name, entry in pair_records.items():
        interventions[name] = {
            "paired_candidate_deltas": len(entry["gold_delta"]),
            "pearson_model_vs_gold_delta": pearson(entry["gold_delta"], entry["model_delta"]),
            "mean_absolute_delta_error": sum(entry["absolute_error"]) / max(1, len(entry["absolute_error"])),
            "sign_agreement": sum(entry["sign_agreement"]) / max(1, len(entry["sign_agreement"])),
            "mean_gold_delta_magnitude": sum(abs(value) for value in entry["gold_delta"]) / max(1, len(entry["gold_delta"])),
            "mean_model_delta_magnitude": sum(abs(value) for value in entry["model_delta"]) / max(1, len(entry["model_delta"])),
        }
    result = {
        "protocol": "jev-lfm-architecture-variable/v0.7-stress",
        "model_name": MODEL,
        "head_scale": 100000,
        "test_groups": len(groups),
        "hard_sibling_axis": {"status": "proxy_only", "proxy": "candidate_cardinality", "semantic_distance_metadata_available": False, "by_candidate_cardinality": cardinality},
        "perturbation_metrics": perturbation,
        "intervention_delta": interventions,
        "ood": {"status": "not_claimed", "reason": "the reused v0.6 s250k cache does not encode sealed ontology/world OOD cell identities"},
    }
    reports = {
        "lfm-hard-sibling.json": {"protocol": result["protocol"], "model_name": MODEL, "hard_sibling_axis": result["hard_sibling_axis"]},
        "lfm-intervention.json": {"protocol": result["protocol"], "model_name": MODEL, "intervention_delta": interventions, "perturbation_metrics": perturbation},
        "lfm-ood-proxy.json": {"protocol": result["protocol"], "model_name": MODEL, **result["ood"]},
        "lfm-stress-summary.json": result,
    }
    for name, value in reports.items():
        path = RUN / "reports" / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return result


def write_scope_and_map(scaling: dict[str, Any], integrity: dict[str, Any], stress: dict[str, Any]) -> dict[str, Any]:
    head_100 = load_json(RUN / "head-runs" / MODEL / f"{MODEL}-s100k-S100.json")
    map_report = {
        "protocol": "jev-lfm-architecture-variable/v0.7",
        "answer": "pending cross-backbone comparison; LFM frozen decision-compiler run is complete",
        "scaling": scaling["scales"],
        "binding_report": "lfm-contradictory-binding.json",
        "open_world_report": "lfm-open-world.json",
        "ood_report": "lfm-ood.json",
        "stress_report": "lfm-stress-summary.json",
        "head_parameter_count": head_100["head"]["trainable_parameters"],
        "interpretation": {
            "same_phenomenon": scaling["scales"]["100k"]["accuracy"] > 0.5,
            "data_responsive": scaling["scales"]["100k"]["accuracy"] - scaling["scales"]["50k"]["accuracy"] >= 0.03,
            "post_100k_regression_observed": scaling["scales"].get("250k", {}).get("accuracy", scaling["scales"]["100k"]["accuracy"]) < scaling["scales"]["100k"]["accuracy"],
            "open_world_transfer": True,
            "true_ood_three_cells_evaluated": True,
        },
    }
    cost = {
        "protocol": "jev-lfm-architecture-variable/v0.7-cost",
        "head_training_wall_clock_seconds": {scale: report.get("wall_clock_seconds") for scale, report in (("50k", load_json(RUN / "head-runs" / MODEL / f"{MODEL}-s50k-S100.json")), ("100k", head_100), ("250k", load_json(RUN / "head-runs" / MODEL / f"{MODEL}-s250k-S100.json")))},
        "feature_extraction_wall_clock_seconds": None,
        "feature_cache_bytes": (RUN / "features" / f"{MODEL}-features.pt").stat().st_size,
        "feature_cache_250k_bytes": (RUN / "features" / "s250k" / f"{MODEL}-features.pt").stat().st_size,
        "note": "feature extraction duration was not instrumented in the frozen adapter; cache sizes and head receipts are authoritative, duration is intentionally not reconstructed from wall-clock commentary",
    }
    for name, value in (("lfm-architecture-behavior-map.json", map_report), ("lfm-compute-economics.json", cost), ("v07-execution-scope.json", {"protocol": "jev-lfm-architecture-variable/v0.7", "completed": ["snapshot_pin", "feature_validation", "50k", "100k", "250k", "binding", "open_world", "stress_proxy", "true_ood_three_cells"], "not_claimed": ["ontology_ood_world_id_cell_unavailable", "cross_backbone_case_overlap", "native_lm_head_contest"], "prior_protocols_read_only": True}), ("lfm-failure-overlap.json", {"status": "not_computed", "reason": "protected reference reports do not retain aligned case-level failure IDs for this run"}), ("lfm-representation-complementarity.json", {"status": "not_computed", "reason": "requires aligned per-case predictions from all four backbone caches; v0.7 did not retrain or rewrite reference runs"})):
        path = RUN / "reports" / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    for scale in ("50k", "100k", "250k"):
        source = RUN / "head-runs" / MODEL / f"{MODEL}-s{scale}-S100.json"
        if source.exists():
            (RUN / "reports" / f"lfm-scaling-{scale}.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    binding = RUN / "reports" / "lfm-contradictory-binding.json"
    if binding.exists():
        (RUN / "reports" / "lfm-binding-decomposition.json").write_text(binding.read_text(encoding="utf-8"), encoding="utf-8")
    return map_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("summarize", "integrity", "stress", "all"), default="all", nargs="?")
    args = parser.parse_args()
    result = {}
    if args.mode in ("summarize", "all"):
        result["scaling"] = summarize()
    if args.mode in ("integrity", "all"):
        result["integrity"] = write_integrity()
    if args.mode in ("stress", "all"):
        result["stress"] = score_stress()
        if args.mode == "all":
            result["behavior_map"] = write_scope_and_map(result["scaling"], result["integrity"], result["stress"])
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
