"""Write the v0.6 scaling, efficiency, and extension summary reports."""

from __future__ import annotations

import glob
import json
from pathlib import Path


V05 = Path(r"D:\codex-runs\jev-frozen-scaling-v05\head-runs")
V06 = Path(r"D:\codex-runs\jev-frozen-scaling-v06")
REPORTS = V06 / "reports"
MODELS = ("minicpm5-1b-base", "qwen3-0.6b-base", "k2-horizon-0.9b")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def metric(report, name):
    return report["test"]["temperature_scaled"]["exact_generative_posterior"][name]


def main() -> None:
    rows = []
    for model in MODELS:
        old = load(next(V05.joinpath(model).glob("*100k-S100.json")))
        new = load(V06 / "head-runs" / model / f"{model}-s250k-S100.json")
        wall = float(new["wall_clock_seconds"])
        delta_accuracy = metric(new, "accuracy") - metric(old, "accuracy")
        delta_nll = metric(new, "nll") - metric(old, "nll")
        delta_brier = metric(new, "brier") - metric(old, "brier")
        delta_ece = metric(new, "ece_soft") - metric(old, "ece_soft")
        rows.append({
            "model": model,
            "from_scale": 100000,
            "to_scale": 250000,
            "added_groups": 150052,
            "wall_clock_seconds": wall,
            "gpu_hours_approx": wall / 3600.0,
            "from": {key: metric(old, key) for key in ("accuracy", "nll", "brier", "ece_soft")},
            "to": {key: metric(new, key) for key in ("accuracy", "nll", "brier", "ece_soft")},
            "delta": {
                "accuracy": delta_accuracy,
                "nll": delta_nll,
                "brier": delta_brier,
                "ece_soft": delta_ece,
            },
            "marginal_quality_per_gpu_hour": {
                "accuracy_points": delta_accuracy / max(1e-9, wall / 3600.0),
                "brier_reduction": -delta_brier / max(1e-9, wall / 3600.0),
            },
        })
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "frozen-scaling-250k.json").write_text(json.dumps({
        "protocol": "jev-frozen-decision-surface-scaling/v0.6-S",
        "backbone_frozen": True,
        "rows": rows,
    }, indent=2), encoding="utf-8")
    (REPORTS / "marginal-efficiency.json").write_text(json.dumps({
        "protocol": "jev-frozen-decision-surface-scaling/v0.6-S",
        "definition": "quality delta divided by added 100k-to-250k head GPU-hours",
        "rows": rows,
    }, indent=2), encoding="utf-8")
    binding = load(REPORTS / "contradictory-binding-v06.json")
    open_world = {
        model: load(V06 / "open-world" / f"{model}.json")
        for model in MODELS
    }
    (REPORTS / "open-world-v06.json").write_text(json.dumps({
        "protocol": "jev-frozen-decision-surface-scaling/v0.6-O",
        "rows": open_world,
    }, indent=2), encoding="utf-8")
    behavior = {
        "protocol": "jev-frozen-decision-surface-scaling/v0.6",
        "v04_gate_reopened": False,
        "backbone_adaptation": False,
        "scaling": "250k S100 completed for all three backbones",
        "extensions": {
            "contradictory_binding": "completed, paired ordinary/adversarial evaluation",
            "open_world": "completed as separate outside-score lane",
        },
        "scale_rows": rows,
        "binding": binding,
        "open_world": open_world,
        "interpretation_boundary": "No QLoRA decision is created by v0.6; the closed-world scaling curve and extensions remain separate.",
    }
    (REPORTS / "v06-behavior-map.json").write_text(json.dumps(behavior, indent=2), encoding="utf-8")
    print(json.dumps({"models": len(rows), "reports": 4}, indent=2))


if __name__ == "__main__":
    main()
