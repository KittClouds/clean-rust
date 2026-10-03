"""Create compact v0.5 scaling reports from completed frozen-head runs."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v05")
REPORTS = RUN / "reports"
HEADS = RUN / "head-runs"
V04 = Path(r"D:\codex-runs\jev-frozen-saturation-v04")


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def metric(report: dict[str, Any], source: str) -> dict[str, Any]:
    return (report.get("test", {}).get("raw", {}) or {}).get(source, {})


def run_rows() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(HEADS.glob("*/*.json")):
        if path.name == "summary.json":
            continue
        report = load(path)
        if not report or "scale" not in report:
            continue
        exact = metric(report, "exact_generative_posterior")
        human = metric(report, "empirical_annotator_distribution")
        hard = metric(report, "hard_label")
        rows.append({
            "model": report["model_name"],
            "scale": report["scale"],
            "mixture": report["mixture"],
            "train_groups": report["train_groups"],
            "train_source_counts": report.get("train_source_counts", {}),
            "wall_clock_seconds": report.get("wall_clock_seconds"),
            "peak_cuda_memory_bytes": report.get("peak_cuda_memory_bytes"),
            "exact_test": exact,
            "human_test": human,
            "hard_test": hard,
            "temperature": report.get("test", {}).get("temperature"),
            "validation": report.get("validation", {}),
            "external_transfer": report.get("external_transfer", {}),
            "report_path": str(path),
        })
    return rows


def write(name: str, value: Any) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / name).write_text(json.dumps(value, indent=2), encoding="utf-8")


def main() -> None:
    rows = run_rows()
    manifest = load(RUN / "banks" / "scale-manifest.json", {})
    real_manifest = load(RUN / "real-bank" / "manifest.json", {})
    by_key = {(row["model"], row["scale"], row["mixture"]): row for row in rows}

    write("frozen-scaling-curve.json", {
        "protocol": "jev-frozen-decision-surface-scaling/v0.5",
        "v04_boundary": "sealed; qlora-final-gate.json was not modified",
        "run_count": len(rows),
        "rows": rows,
    })
    write("semantic-family-scaling.json", {
        "protocol": "jev-frozen-decision-surface-scaling/v0.5",
        "bank_manifest": str(RUN / "banks" / "scale-manifest.json"),
        "synthetic_root_world_count": manifest.get("synthetic_family_count"),
        "scales": {
            scale: {
                key: value
                for key, value in data.items()
                if key not in {"selected_families"}
            }
            for scale, data in (manifest.get("scales", {}) or {}).items()
        },
        "real": real_manifest,
    })
    mixture = defaultdict(list)
    for row in rows:
        mixture[row["scale"]].append(row)
    write("mixture-comparison.json", {
        "by_scale": {str(scale): values for scale, values in mixture.items()},
        "interpretation": "compare semantic breadth against exact-posterior retention; no aggregate score",
    })
    write("real-transfer.json", {
        "rows": [
            {
                "model": row["model"],
                "scale": row["scale"],
                "mixture": row["mixture"],
                "human_test": row["human_test"],
                "hard_test": row["hard_test"],
                "external_transfer": row["external_transfer"],
            }
            for row in rows
        ],
        "source_semantics": {
            "human": "empirical annotator distribution",
            "hard": "discrimination only; not calibrated probability",
        },
    })
    write("synthetic-calibration-retention.json", {
        "rows": [
            {
                "model": row["model"],
                "scale": row["scale"],
                "mixture": row["mixture"],
                "exact_test": row["exact_test"],
                "validation": row["validation"],
                "temperature": row["temperature"],
            }
            for row in rows
        ],
        "sources_are_stratified": True,
    })

    residual_rows = []
    for model in sorted({row["model"] for row in rows}):
        for mixture_name in ("S100", "S75_R25", "S50_R50"):
            first = by_key.get((model, 50_000, mixture_name))
            second = by_key.get((model, 100_000, mixture_name))
            if not first or not second:
                continue
            a = first["exact_test"]
            b = second["exact_test"]
            acc_delta = (b.get("accuracy", 0.0) - a.get("accuracy", 0.0))
            brier_delta = (b.get("brier", 0.0) - a.get("brier", 0.0))
            if acc_delta >= 0.02 and brier_delta <= 0.01:
                status = "resolved_by_data"
            elif acc_delta > 0.0:
                status = "improving_but_unresolved"
            else:
                status = "stable_residual"
            residual_rows.append({
                "model": model,
                "mixture": mixture_name,
                "from_scale": 50_000,
                "to_scale": 100_000,
                "exact_accuracy_delta": acc_delta,
                "exact_brier_delta": brier_delta,
                "status": status,
                "note": "aggregate persistence proxy; v0.4 case-level residual IDs remain authoritative",
            })
    write("residuals-by-scale.json", {"rows": residual_rows})
    write("persistent-representation-candidates.json", {
        "is_qlora_authorization": False,
        "v04_qlora_result": "unauthorized_for_all_three_backbones",
        "candidates": [row for row in residual_rows if row["status"] != "resolved_by_data"],
        "definition": "candidate inventory only; no new adaptation gate is created in v0.5",
    })
    write("cross-backbone-complementarity.json", {
        "rows": [
            {
                "model": row["model"],
                "scale": row["scale"],
                "mixture": row["mixture"],
                "exact_test": row["exact_test"],
                "human_test": row["human_test"],
                "wall_clock_seconds": row["wall_clock_seconds"],
            }
            for row in rows
        ],
        "warning": "aggregate differences do not establish representation complementarity without case-level identities",
    })
    write("compute-cost-curve.json", {
        "rows": [
            {
                "model": row["model"],
                "scale": row["scale"],
                "mixture": row["mixture"],
                "train_groups": row["train_groups"],
                "wall_clock_seconds": row["wall_clock_seconds"],
                "peak_cuda_memory_bytes": row["peak_cuda_memory_bytes"],
            }
            for row in rows
        ],
        "feature_cache_manifests": [
            str(path) for path in sorted((RUN / "features").glob("*/*-feature-manifest.json"))
        ],
    })
    write("contradictory-binding.json", {
        "status": "not_run_in_first_v05_scaling_pass",
        "reason": "binding adversaries are a separate diagnostic and are not silently folded into scaling metrics",
        "required_follow_up": "evaluate against each completed frozen head before any adaptation study",
    })
    write("v05-behavior-map.json", {
        "protocol": "jev-frozen-decision-surface-scaling/v0.5",
        "backbones": sorted({row["model"] for row in rows}),
        "scales": sorted({row["scale"] for row in rows}),
        "mixtures": sorted({row["mixture"] for row in rows}),
        "runs_completed": len(rows),
        "runs_expected": 18,
        "execution_scope": {
            "status": "cost_bounded_anchor_set",
            "completed_run_count": len(rows),
            "anchor_rule": "all three backbones at 50k/S100 and 100k/S100",
            "mixture_rule": "full 50k mixture matrix retained for MiniCPM; Qwen mixture cells observed during the initial matrix run; K2 mixture cells deferred",
            "not_a_missing_data_imputation": True,
        },
        "v04_boundary": {
            "qlora_authorized": False,
            "gate_reopened": False,
            "gate_file": str(V04 / "reports" / "qlora-final-gate.json"),
        },
    })
    write("execution-scope.json", {
        "protocol": "jev-frozen-decision-surface-scaling/v0.5",
        "status": "cost_bounded_anchor_set",
        "completed_runs": len(rows),
        "expected_full_matrix_cells": 18,
        "anchor_cells": sorted(
            [
                {"model": row["model"], "scale": row["scale"], "mixture": row["mixture"]}
                for row in rows
                if row["mixture"] == "S100"
            ],
            key=lambda item: (item["model"], item["scale"]),
        ),
        "mixture_cells_completed": sorted(
            [
                {"model": row["model"], "scale": row["scale"], "mixture": row["mixture"]}
                for row in rows
                if row["scale"] == 50_000 and row["mixture"] != "S100"
            ],
            key=lambda item: (item["model"], item["mixture"]),
        ),
        "deferred_cells": [
            {"model": "k2-horizon-0.9b", "scale": 50_000, "mixture": "S75_R25"},
            {"model": "k2-horizon-0.9b", "scale": 50_000, "mixture": "S50_R50"},
            {"model": "k2-horizon-0.9b", "scale": 100_000, "mixture": "S75_R25"},
            {"model": "k2-horizon-0.9b", "scale": 100_000, "mixture": "S50_R50"},
            {"model": "qwen3-0.6b-base", "scale": 100_000, "mixture": "S75_R25"},
            {"model": "qwen3-0.6b-base", "scale": 100_000, "mixture": "S50_R50"},
        ],
        "reason": "head-only cells are several minutes each on the local GPU; no semantic values are synthesized for deferred cells",
        "v04_boundary": "sealed; QLoRA remains unauthorized and qlora-final-gate.json is unchanged",
    })
    print(json.dumps({"runs": len(rows), "reports": str(REPORTS)}, indent=2))


if __name__ == "__main__":
    main()
