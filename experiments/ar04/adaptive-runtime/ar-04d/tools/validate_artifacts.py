from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CELLS = 25
ARMS = {
    "sentinel_k1": 1,
    "sentinel_k4_cyclic": 4,
    "sentinel_k16_cyclic": 16,
    "sentinel_k16_blocked": 16,
    "sentinel_k16_pooled": 16,
    "sentinel_k64_cyclic": 64,
    "sentinel_fresh": 1050,
}
ROUNDS = 1050
COMMITS_PER_ROUND = 4
STEPS = 4200
PANEL_SIZE = 128
POOLED_SIZE = 2048
POPULATION_SIZE = 4096
CHECKPOINT_STEPS = {0, 600, 2400, 4200}


def rows(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expected_rounds(arm: str, panel_id: int) -> int:
    if arm == "sentinel_k1":
        return ROUNDS if panel_id == 0 else 0
    if arm == "sentinel_k4_cyclic":
        return 263 if panel_id < 2 else 262 if panel_id < 4 else 0
    if arm == "sentinel_k16_cyclic":
        return 66 if panel_id < 10 else 65 if panel_id < 16 else 0
    if arm == "sentinel_k16_pooled":
        return ROUNDS if panel_id == 0 else 0
    if arm == "sentinel_k16_blocked":
        return 66 if panel_id < 10 else 65 if panel_id < 16 else 0
    if arm == "sentinel_k64_cyclic":
        return 17 if panel_id < 26 else 16 if panel_id < 64 else 0
    if arm == "sentinel_fresh":
        return 1 if panel_id < ROUNDS else 0
    raise AssertionError(f"unknown arm {arm}")


def main(root: Path) -> None:
    receipt = json.loads((root / "integrity-receipt.json").read_text(encoding="utf-8"))
    require(receipt.get("integrity_valid") is True, "collection receipt is not valid")
    require(receipt.get("cells") == CELLS, "cell count mismatch")
    require(receipt.get("arms") == len(ARMS), "arm count mismatch")
    require(receipt.get("trajectories") == CELLS * len(ARMS), "trajectory count mismatch")
    require(
        receipt.get("decisions") == CELLS * len(ARMS) * STEPS,
        "decision count mismatch",
    )
    require(receipt.get("checkpoints") == CELLS * len(ARMS) * 4, "checkpoint count mismatch")
    require(
        receipt.get("master_panels") == CELLS * ROUNDS,
        "master panel count mismatch",
    )
    require(receipt.get("population_size_per_dataset") == POPULATION_SIZE, "population size mismatch")

    dataset_rows = rows(root / "dataset-manifest.csv")
    require(len(dataset_rows) == 15, "dataset manifest cardinality mismatch")
    require(
        {row["kind"] for row in dataset_rows}
        == {"training", "final_measurement", "population_reference"},
        "dataset manifest roles mismatch",
    )
    require(
        {int(row["samples"]) for row in dataset_rows if row["kind"] == "population_reference"}
        == {POPULATION_SIZE},
        "population manifest size mismatch",
    )

    panel_rows = rows(root / "panel-manifest.csv")
    require(len(panel_rows) == CELLS * ROUNDS, "master panel manifest cardinality mismatch")
    keys = {(int(row["cell_id"]), int(row["panel_id"])) for row in panel_rows}
    require(len(keys) == CELLS * ROUNDS, "master panel schedule repeats")
    require({int(row["samples"]) for row in panel_rows} == {PANEL_SIZE}, "panel size mismatch")
    panel_seeds = {
        seed
        for row in panel_rows
        for seed in (row["seed_a"], row["seed_b"], row["order_seed"])
    }
    require(len(panel_seeds) == len(panel_rows) * 3, "panel seed reuse")
    require(len({row["fingerprint"] for row in panel_rows}) == len(panel_rows), "panel fingerprint reuse")

    pooled_rows = rows(root / "pooled-panel-manifest.csv")
    require(len(pooled_rows) == CELLS, "pooled manifest cardinality mismatch")
    require({int(row["samples"]) for row in pooled_rows} == {POOLED_SIZE}, "pooled size mismatch")
    require({int(row["source_panel_count"]) for row in pooled_rows} == {16}, "pooled source count mismatch")

    decision_path = root / "trajectory-decisions.csv"
    if not decision_path.exists():
        decision_path = root / "trajectory-decisions.csv.gz"
    decision_rows = rows(decision_path)
    require(len(decision_rows) == CELLS * len(ARMS) * STEPS, "decision artifact cardinality mismatch")
    grouped: defaultdict[tuple[int, str], list[dict[str, str]]] = defaultdict(list)
    for row in decision_rows:
        grouped[(int(row["cell_id"]), row["arm"])].append(row)
    require(set(grouped) == {(cell, arm) for cell in range(CELLS) for arm in ARMS}, "decision groups mismatch")
    for (cell_id, arm), group in grouped.items():
        require(len(group) == STEPS, f"decision count mismatch for {cell_id}/{arm}")
        for round_id in range(ROUNDS):
            block = group[round_id * COMMITS_PER_ROUND : (round_id + 1) * COMMITS_PER_ROUND]
            require({int(row["evidence_round"]) for row in block} == {round_id}, "evidence round mismatch")
            require(len({row["panel_id"] for row in block}) == 1, "panel changed inside evidence round")
            require(len({row["panel_hash"] for row in block}) == 1, "panel hash changed inside evidence round")
            expected_size = POOLED_SIZE if arm == "sentinel_k16_pooled" else PANEL_SIZE
            require({int(row["verifier_size"]) for row in block} == {expected_size}, "verifier size mismatch")

    outcome_rows = rows(root / "checkpoint-outcomes.csv")
    require(len(outcome_rows) == CELLS * len(ARMS) * 4, "outcome cardinality mismatch")
    require({int(row["step"]) for row in outcome_rows} == CHECKPOINT_STEPS, "checkpoint steps mismatch")
    require({row["arm"] for row in outcome_rows} == set(ARMS), "outcome arms mismatch")

    exposure_rows = rows(root / "exposure-summary.csv")
    exposure_map = {
        (int(row["cell_id"]), row["arm"], int(row["panel_id"])): row
        for row in exposure_rows
    }
    require(len(exposure_map) == len(exposure_rows), "duplicate exposure rows")
    for cell_id in range(CELLS):
        for arm, bank_size in ARMS.items():
            active = {panel_id for panel_id in range(ROUNDS) if expected_rounds(arm, panel_id)}
            for panel_id in active:
                row = exposure_map[(cell_id, arm, panel_id)]
                scheduled = expected_rounds(arm, panel_id)
                require(int(row["scheduled_rounds"]) == scheduled, "scheduled exposure mismatch")
                require(int(row["decision_count"]) == scheduled * COMMITS_PER_ROUND, "decision exposure mismatch")
                require(int(row["scored_candidates"]) > 0, "no candidate scoring recorded")
            inactive = [
                key
                for key in exposure_map
                if key[0] == cell_id and key[1] == arm and key[2] not in active
            ]
            require(not inactive, f"inactive exposure rows for {cell_id}/{arm}")
            if arm == "sentinel_k16_pooled":
                require(int(exposure_map[(cell_id, arm, 0)]["verifier_size"]) == POOLED_SIZE, "pooled verifier size")

    checkpoints = rows(root / "checkpoint-manifest.csv")
    require(len(checkpoints) == CELLS * len(ARMS) * 4, "checkpoint manifest mismatch")
    require({int(row["step"]) for row in checkpoints} == CHECKPOINT_STEPS, "checkpoint manifest stages mismatch")
    model_bytes = (root / "checkpoint-models.bin").stat().st_size
    require(model_bytes == len(checkpoints) * 171 * 4, "checkpoint model byte count mismatch")

    validation = {
        "protocol": "AR-04D-sentinel-exposure-2026-09-26",
        "valid": True,
        "cells": CELLS,
        "arms": len(ARMS),
        "trajectories": CELLS * len(ARMS),
        "decisions": len(decision_rows),
        "checkpoints": len(checkpoints),
        "master_panels": len(panel_rows),
        "population_size": POPULATION_SIZE,
        "panel_seed_reuse": False,
        "cyclic_blocked_counts_match": True,
        "candidate_scoring_recorded": True,
    }
    (root / "validation-receipt.json").write_text(
        json.dumps(validation, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_artifacts.py ARTIFACT_DIR")
    main(Path(sys.argv[1]))
