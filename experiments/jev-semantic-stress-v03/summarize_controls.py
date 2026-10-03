"""Write the v0.3 layer, capacity, and promotion-gate reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(r"D:\codex-runs\jev-semantic-stress-v03")
REPORTS = ROOT / "reports"


def read_runs(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.glob("*/*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        metric = report.get("test", {}).get("raw", {}).get("exact_generative_posterior", {})
        rows.append({
            "run": str(path),
            "model": report.get("model_name"),
            "layer_fraction": report.get("layer_fraction"),
            "projection_dim": report.get("trainable_parameters"),
            "train_size_groups": report.get("train_size_groups"),
            "trainable_parameters": report.get("trainable_parameters"),
            "test": metric,
            "temperature": report.get("test", {}).get("temperature"),
        })
    return rows


def main() -> None:
    layer = read_runs(ROOT / "layer-runs")
    capacity = read_runs(ROOT / "capacity-runs")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "layer-probe.json").write_text(json.dumps({"protocol": "v0.3", "k2": "not_run_internal_layers_custom_path", "runs": layer}, indent=2), encoding="utf-8")
    (REPORTS / "head-capacity.json").write_text(json.dumps({"protocol": "v0.3", "runs": capacity, "controls": {"small": "projection_dim=16", "larger": "projection_dim=256"}}, indent=2), encoding="utf-8")
    decision = {
        "protocol": "jev-semantic-stress-intervention-geometry-v0.3",
        "backbones": ["qwen3-0.6b-base", "minicpm5-1b-base", "k2-horizon-0.9b"],
        "qlora_authorized": False,
        "decision": "defer_and_expand_frozen_readout_coverage",
        "gates": {
            "A_head_learning_saturation": {
                "status": "not_established",
                "evidence": "v0.3 stress bank has a 1k control and a 5k primary run; a larger stress-bank scaling point was not run, so saturation cannot be claimed",
            },
            "B_reproducible_residual_failure": {
                "status": "observed",
                "evidence": "all three backbones retain weak evidence-removal magnitude correlation and hard local/candidate-schema stress remains materially worse than ordinary rows",
            },
            "C_failure_across_readouts": {
                "status": "partially_observed",
                "evidence": "primary MLP, small-head, larger-head, and layer controls do not remove the residuals, but controls use smaller training budgets and are not a final saturation proof",
            },
        },
        "interpretation": [
            "The current result supports a coverage/readout stress problem, not yet a representation-level authorization for QLoRA.",
            "K2 has the strongest observed intervention delta correlations in this pilot, but this is not a capacity or architecture promotion claim.",
            "The next decisive control is a stress-bank 1k/5k/10k scaling curve with the same frozen heads and per-family held-out splits.",
        ],
        "phoenix": "out_of_scope_and_untouched",
    }
    (REPORTS / "qlora-promotion-decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
