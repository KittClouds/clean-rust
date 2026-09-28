"""Build the external JSON result set from frozen-head run reports.

This intentionally reports coverage and unavailable diagnostics explicitly. It
does not fabricate intervention or hard-sibling evidence that the current run
selection did not contain.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


REQUIRED = (
    "representation-probe.json",
    "readout-ablation.json",
    "training-size-scaling.json",
    "candidate-order-invariance.json",
    "schema-binding.json",
    "hard-sibling-challenge.json",
    "evidence-intervention.json",
    "world-intervention.json",
    "calibration.json",
    "cache-equivalence.json",
    "frozen-readout-comparison.json",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def finite(values: list[float]) -> list[float]:
    return [value for value in values if math.isfinite(value)]


def vector_metrics(prediction: list[float], gold: list[float]) -> dict[str, float]:
    if len(prediction) != len(gold):
        return {"status": "invalid_length"}  # type: ignore[return-value]
    model_delta = [float(value) for value in prediction]
    gold_delta = [float(value) for value in gold]
    model_norm = math.sqrt(sum(value * value for value in model_delta))
    gold_norm = math.sqrt(sum(value * value for value in gold_delta))
    dot = sum(a * b for a, b in zip(model_delta, gold_delta))
    if model_norm and gold_norm:
        cosine = dot / (model_norm * gold_norm)
    else:
        cosine = 0.0
    return {
        "model_delta_l2": model_norm,
        "gold_delta_l2": gold_norm,
        "absolute_delta_error": math.sqrt(sum((a - b) ** 2 for a, b in zip(model_delta, gold_delta))),
        "delta_cosine": cosine,
        "direction_agreement": float(dot >= 0.0),
    }


def native_metric(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    selected = [row for row in rows if row.get("probability_source") == "exact_generative_posterior"]
    nll = 0.0
    brier = 0.0
    correct = 0
    for row in selected:
        gold = row["gold_distribution"]
        prediction = row[field]
        keys = list(gold)
        p = [float(gold[key]) for key in keys]
        q = [max(1e-12, float(prediction.get(key, 0.0))) for key in keys]
        total = sum(q)
        q = [value / total for value in q]
        nll -= sum(a * math.log(b) for a, b in zip(p, q))
        brier += sum((a - b) ** 2 for a, b in zip(p, q))
        correct += int(max(range(len(q)), key=q.__getitem__) == max(range(len(p)), key=p.__getitem__))
    count = len(selected)
    return {
        "count": count,
        "nll": nll / max(1, count),
        "brier": brier / max(1, count),
        "accuracy": correct / max(1, count),
    }


def native_reports(native_dir: Path) -> list[dict[str, Any]]:
    if not native_dir.exists():
        return []
    result = []
    for path in sorted(native_dir.glob("*-base-frozen.json")):
        payload = read_json(path)
        rows = payload.get("rows") or []
        result.append({
            "model_name": payload.get("summary", {}).get("model", path.stem),
            "summary": payload.get("summary", {}),
            "direct": native_metric(rows, "direct_prediction"),
            "sequence_sum": native_metric(rows, "sequence_sum_prediction"),
            "sequence_mean": native_metric(rows, "sequence_mean_prediction"),
            "source_file": str(path),
        })
    return result


def intervention_report(runs: list[dict[str, Any]], class_fragment: str) -> dict[str, Any]:
    reports = []
    pair_count = 0
    metrics: list[dict[str, float]] = []
    for run in runs:
        rows = run.get("test_rows") or []
        by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_key[row.get("invariant_key", row.get("group_id", ""))].append(row)
        local_pairs = 0
        local_metrics = []
        for values in by_key.values():
            base = next((row for row in values if row.get("perturbation_class") is None), None)
            child = next((row for row in values if class_fragment in (row.get("perturbation_class") or "")), None)
            if not base or not child:
                continue
            local_pairs += 1
            child_metric = vector_metrics(
                [b - a for a, b in zip(base["prediction"], child["prediction"])],
                [b - a for a, b in zip(base["gold"], child["gold"])],
            )
            local_metrics.append(child_metric)
            metrics.append(child_metric)
        if local_pairs:
            reports.append({
                "model_name": run["model_name"],
                "head_kind": run["head_kind"],
                "representation_location": run["representation_location"],
                "loss_variant": run["loss_variant"],
                "pair_count": local_pairs,
                "mean_absolute_delta_error": sum(item["absolute_delta_error"] for item in local_metrics) / local_pairs,
                "mean_delta_cosine": sum(item["delta_cosine"] for item in local_metrics) / local_pairs,
                "direction_agreement": sum(item["direction_agreement"] for item in local_metrics) / local_pairs,
            })
            pair_count += local_pairs
    if not reports:
        return {
            "status": "not_observed",
            "reason": "No parent/intervention pairs were retained in the selected test rows.",
            "pair_count": 0,
            "runs": [],
        }
    return {"status": "observed", "pair_count": pair_count, "runs": reports, "pair_metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default=r"D:\codex-runs\jev-frozen-readout-v01\runs")
    parser.add_argument("--features", default=r"D:\codex-runs\jev-frozen-readout-v01\features")
    parser.add_argument("--output", default=r"D:\codex-runs\jev-frozen-readout-v01\reports")
    parser.add_argument("--native", default=r"D:\codex-runs\jev-frozen-readout-v01\native-test")
    parser.add_argument("--legacy-results", default=r"D:\codex-runs\jev-zero-training-recon-v01\results")
    args = parser.parse_args()
    run_dir = Path(args.runs)
    reports_dir = Path(args.output)
    runs = [read_json(path) for path in sorted(run_dir.glob("*.json"))]
    manifests = [read_json(path) for path in sorted(Path(args.features).glob("*-feature-manifest.json"))]
    native = native_reports(Path(args.native))
    legacy_shared = {}
    legacy_path = Path(args.legacy_results) / "shared-state-performance.json"
    if legacy_path.exists():
        legacy_shared = read_json(legacy_path)
    base = {
        "protocol": "jev-frozen-compatibility-readout-v0.2",
        "run_count": len(runs),
        "models": sorted({run.get("model_name") for run in runs}),
    }
    write_json(reports_dir / "representation-probe.json", {**base, "feature_manifests": manifests})
    write_json(reports_dir / "readout-ablation.json", {**base, "runs": runs})
    write_json(reports_dir / "training-size-scaling.json", {
        **base,
        "points": [
            {key: run.get(key) for key in ("model_name", "head_kind", "representation_location", "loss_variant", "train_size_groups", "test")}
            for run in runs
        ],
    })
    write_json(reports_dir / "candidate-order-invariance.json", {
        **base,
        "learned_head": [
            {key: run.get(key) for key in ("model_name", "head_kind", "representation_location", "loss_variant", "candidate_order_invariance")}
            for run in runs
        ],
        "native_reference": native,
    })
    write_json(reports_dir / "schema-binding.json", {
        **base,
        "profiles": [
            {key: run.get(key) for key in ("model_name", "head_kind", "representation_location", "loss_variant", "profile_trained", "test")}
            for run in runs
        ],
    })
    write_json(reports_dir / "hard-sibling-challenge.json", {
        **base,
        "status": "coverage_limited",
        "candidate_cardinality": [
            {key: run.get(key) for key in ("model_name", "head_kind", "representation_location", "loss_variant", "test")}
            for run in runs
        ],
        "limitation": "The current pilot does not yet tag semantic-sibling similarity as a first-class workload dimension.",
    })
    write_json(reports_dir / "evidence-intervention.json", intervention_report(runs, "observationintervention"))
    write_json(reports_dir / "world-intervention.json", intervention_report(runs, "worldintervention"))
    write_json(reports_dir / "calibration.json", {
        **base,
        "runs": [
            {key: run.get(key) for key in ("model_name", "head_kind", "representation_location", "loss_variant", "test", "external_transfer")}
            for run in runs
        ],
        "source_classes_are_separate": True,
    })
    write_json(reports_dir / "cache-equivalence.json", {
        "protocol": "jev-frozen-compatibility-readout-v0.2",
        "status": "measured_prior_reconnaissance",
        "metrics": legacy_shared,
        "note": "Feature extraction and head fitting do not claim shared-prefix cache equivalence; prior native cache results are carried as a separate systems track.",
    })
    write_json(reports_dir / "frozen-readout-comparison.json", {
        **base,
        "learned_head_runs": runs,
        "native_reference": native,
        "native_reference_scope": "bounded same-bank slice; 256 query records per model, candidate reorder enabled",
    })
    print(json.dumps({"runs": len(runs), "reports": len(REQUIRED), "output": str(reports_dir)}, indent=2))


if __name__ == "__main__":
    main()
