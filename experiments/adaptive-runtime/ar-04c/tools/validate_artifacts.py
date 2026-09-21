from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_CELLS = 25
EXPECTED_TRAJECTORIES = 75
EXPECTED_DECISIONS = 315_000
EXPECTED_CHECKPOINTS = 300
EXPECTED_ROTATING_PANELS = 26_250
EXPECTED_ARMS = {
    "training_full96",
    "sentinel_fixed128",
    "sentinel_rotating128",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_artifacts.py OUTPUT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    receipt = json.loads((root / "integrity-receipt.json").read_text(encoding="utf-8"))
    require(receipt["integrity_valid"] is True, "collector integrity receipt is not valid")
    require(receipt["cells"] == EXPECTED_CELLS, "cell count mismatch")
    require(
        receipt["rotating_panels"] == EXPECTED_ROTATING_PANELS,
        "rotating panel count mismatch",
    )
    require(receipt["all_role_seeds_unique"] is True, "seed uniqueness failed")

    dataset_rows = list(rows(root / "dataset-manifest.csv"))
    require(len(dataset_rows) == 10, "dataset manifest cardinality mismatch")
    for row in dataset_rows:
        path = root / row["path"]
        require(path.exists(), f"missing dataset file: {path}")
        require(sha256(path) == row["sha256"], f"dataset hash mismatch: {path}")

    fixed_rows = list(rows(root / "fixed-panel-manifest.csv"))
    rotating_rows = list(rows(root / "rotating-panel-manifest.csv"))
    require(len(fixed_rows) == EXPECTED_CELLS, "fixed panel cardinality mismatch")
    require(
        len(rotating_rows) == EXPECTED_ROTATING_PANELS,
        "rotating panel cardinality mismatch",
    )
    require({int(row["samples"]) for row in fixed_rows} == {128}, "fixed panel size mismatch")
    require(
        {int(row["samples"]) for row in rotating_rows} == {128},
        "rotating panel size mismatch",
    )
    rotating_keys = {
        (int(row["cell_id"]), int(row["evidence_round"])) for row in rotating_rows
    }
    require(len(rotating_keys) == EXPECTED_ROTATING_PANELS, "rotating panel schedule repeats")
    panel_seeds = {row["seed_a"] for row in fixed_rows} | {
        row["seed_a"] for row in rotating_rows
    }
    require(
        len(panel_seeds) == EXPECTED_CELLS + EXPECTED_ROTATING_PANELS,
        "panel seed reuse",
    )

    decision_rows = list(rows(root / "trajectory-decisions.csv"))
    require(len(decision_rows) == EXPECTED_DECISIONS, "decision row count mismatch")
    require({row["arm"] for row in decision_rows} == EXPECTED_ARMS, "arm set mismatch")
    per_trajectory: dict[tuple[int, str], int] = {}
    for row in decision_rows:
        key = (int(row["cell_id"]), row["arm"])
        per_trajectory[key] = per_trajectory.get(key, 0) + 1
    require(len(per_trajectory) == EXPECTED_TRAJECTORIES, "trajectory cardinality mismatch")
    require(set(per_trajectory.values()) == {4_200}, "per-trajectory decision count mismatch")

    checkpoint_rows = list(rows(root / "checkpoint-manifest.csv"))
    outcome_rows = list(rows(root / "checkpoint-outcomes.csv"))
    metric_rows = list(rows(root / "ranking-metrics.csv"))
    require(len(checkpoint_rows) == EXPECTED_CHECKPOINTS, "checkpoint manifest mismatch")
    require(len(outcome_rows) == EXPECTED_CHECKPOINTS, "checkpoint outcome mismatch")
    require(len(metric_rows) == EXPECTED_CHECKPOINTS, "ranking metric mismatch")
    require(
        {int(row["step"]) for row in checkpoint_rows} == {0, 600, 2_400, 4_200},
        "checkpoint stages mismatch",
    )
    require(
        all(float(row["final_loss"]) == float(row["final_loss"]) for row in outcome_rows),
        "non-finite final loss",
    )
    require((root / "summary.json").exists(), "missing summary")

    validation = {
        "validation": "AR-04C read-only artifact audit",
        "valid": True,
        "cells": EXPECTED_CELLS,
        "trajectories": EXPECTED_TRAJECTORIES,
        "decisions": EXPECTED_DECISIONS,
        "checkpoints": EXPECTED_CHECKPOINTS,
        "rotating_panels": EXPECTED_ROTATING_PANELS,
        "dataset_hashes_verified": len(dataset_rows),
        "panel_seed_reuse": False,
    }
    (root / "validation-receipt.json").write_text(
        json.dumps(validation, indent=2) + "\n", encoding="utf-8"
    )

    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    means = summary["mean_final_measurement_loss"]
    report = f"""# AR-04C Results

The collection and independent artifact audit are integrity-valid. This report
is descriptive only; AR-04C has no automatic promotion rule.

- crossed cells: {EXPECTED_CELLS}
- trajectories: {EXPECTED_TRAJECTORIES}
- decisions: {EXPECTED_DECISIONS}
- rotating V128 panels: {EXPECTED_ROTATING_PANELS}
- mean final measurement loss, training V96: {means[0]:.12e}
- mean final measurement loss, fixed sentinel V128: {means[1]:.12e}
- mean final measurement loss, rotating sentinel V128: {means[2]:.12e}
- fixed minus training: {summary["fixed_minus_training"]:.12e}
- rotating minus training: {summary["rotating_minus_training"]:.12e}

Interpretation must use the full cell contrasts and checkpoint alignment
trajectory in cell-contrasts.csv, ranking-metrics.csv, and
checkpoint-outcomes.csv; no pooled mean alone is a promotion claim.
"""
    (root / "RESULTS.md").write_text(report, encoding="utf-8")
    print(json.dumps(validation, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
