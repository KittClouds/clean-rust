"""Mechanical pre-fit check of row support and feature schema for R1 probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import numpy as np

from r1_sensor_probe_data_v01 import ACTION_ORDER, KIND_ORDER, Rows, SensorData

EXPECTED_DIMS = {
    "semantic": {"real": 2048, "shuffled": 2048, "surface": 45, "template": 29},
    "binding": {"real": 4102, "shuffled": 4102, "surface": 64, "template": 35},
    "action": {"real": 4180, "shuffled": 4180, "surface": 124, "template": 108},
}
ARMS = ("real", "shuffled", "surface", "template")


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def audit(data_root: Path, extraction: Path) -> dict[str, Any]:
    data = SensorData(data_root, extraction)
    result: dict[str, Any] = {}
    for rung, maker, classes in (
        ("semantic", data.semantic_rows, len(KIND_ORDER)),
        ("binding", data.binding_rows, 2),
        ("action", data.action_rows, len(ACTION_ORDER)),
    ):
        result[rung] = {}
        for split in ("train", "validation", "evaluation"):
            arm_rows: dict[str, Rows] = {arm: maker(split, arm) for arm in ARMS}
            base = arm_rows["real"]
            for arm, rows in arm_rows.items():
                if rows.input_dim != EXPECTED_DIMS[rung][arm]:
                    raise ValueError(f"{rung}/{split}/{arm}: width {rows.input_dim} != {EXPECTED_DIMS[rung][arm]}")
                if rows.keys.tolist() != base.keys.tolist() or rows.families.tolist() != base.families.tolist() or rows.conditions.tolist() != base.conditions.tolist():
                    raise ValueError(f"{rung}/{split}/{arm}: row identity differs from real arm")
                if split == "evaluation":
                    if not np.all(rows.labels == -1):
                        raise ValueError(f"{rung}/{arm}: evaluation labels entered feature rows")
                elif set(rows.labels.tolist()) != set(range(classes)):
                    raise ValueError(f"{rung}/{split}/{arm}: incomplete class support")
                if len(rows):
                    # Check representative batches while keeping the full action tensor lazy.
                    probe_ids = np.unique(np.asarray([0, len(rows) // 2, len(rows) - 1], dtype=np.int64))
                    if not np.isfinite(rows.batch(probe_ids)).all():
                        raise ValueError(f"{rung}/{split}/{arm}: non-finite constructed feature")
            result[rung][split] = {
                "rows": len(base), "labels_hidden": split == "evaluation",
                "class_support": {str(cls): int(np.sum(base.labels == cls)) for cls in range(classes)} if split != "evaluation" else None,
                "input_dims": {arm: rows.input_dim for arm, rows in arm_rows.items()},
                "all_arm_row_identity_equal": True,
            }
    condition_rows = {condition: 0 for condition in ("id_seen", "template_ood", "vocabulary_ood", "joint_ood")}
    action_eval = data.action_rows("evaluation", "real")
    for condition in condition_rows:
        condition_rows[condition] = int(np.sum(action_eval.conditions == condition))
    if any(value == 0 for value in condition_rows.values()):
        raise ValueError("an action evaluation condition has no rows")
    return {
        "schema": "R1_SENSOR_PROBE_ROW_AUDIT_V01", "status": "PASS",
        "data_root": str(data_root), "extraction_root": str(extraction),
        "data_hashes": {name: sha256_file(data_root / name)[0] for name in (
            "public-probe-tasks.jsonl", "private-probe-targets.jsonl", "private-action-examples.jsonl",
            "name-queries.jsonl", "family-split.jsonl")},
        "extraction_integrity_receipt_sha256": sha256_file(extraction / "EXTRACTION-INTEGRITY-RECEIPT-v04.json")[0],
        "rungs": result, "action_evaluation_rows_by_condition": condition_rows,
        "training_validation_labels_only_used_for_row_targets": True,
        "evaluation_features_have_no_target_labels": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = audit(args.data_root.resolve(strict=True), args.extraction.resolve(strict=True))
    payload = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
