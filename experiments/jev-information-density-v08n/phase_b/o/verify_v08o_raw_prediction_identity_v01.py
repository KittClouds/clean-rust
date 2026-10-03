"""Metadata-only pre-analysis verification of the sealed v0.8O prediction matrix."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


OUTPUT = Path(r"D:\codex-runs\jev-information-density-v08o\v0.8O-capability-trajectory-cartography-v01")
SEEDS = (20260927, 20260928, 20260929)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
EPOCHS = (0, 1, 2, 3)
VIEWS = frozenset(("anchor", "fact_flip", "sham", "matched_neutral"))
ANALYSIS_SOURCE = Path(__file__).resolve().with_name("analyze_v08o_trajectory_v01.py")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify() -> dict:
    output_receipt = OUTPUT / "raw-prediction-identity-audit-v01.json"
    amendment_path = OUTPUT / "analysis-reporting-correction-v01.json"
    if output_receipt.exists() or amendment_path.exists():
        raise FileExistsError("raw identity audit already exists; no rewrite")
    preflight_path = OUTPUT / "preinference-verification-v01.json"
    opening_path = OUTPUT / "v08o-opening-receipt-v01.json"
    tree_path = OUTPUT / "raw-prediction-hash-tree-v01.json"
    inference_path = OUTPUT / "inference-receipt-v01.json"
    prediction_path = OUTPUT / "raw-predictions-v01.jsonl"
    preflight = read_json(preflight_path)
    opening = read_json(opening_path)
    tree = read_json(tree_path)
    inference = read_json(inference_path)
    raw_sha = sha256_file(prediction_path)

    if preflight.get("checkpoint_count") != 27 or preflight.get("panel_bodies_or_targets_read") is not False:
        raise RuntimeError("O preflight did not seal the complete checkpoint inventory before panel access")
    if preflight.get("predictions_or_o_metrics_created") is not False:
        raise RuntimeError("O preflight does not attest that predictions and metrics were absent before opening")
    if opening.get("opening_count") != 3 or opening.get("o_predictions_or_metrics_exist_at_opening") is not False:
        raise RuntimeError("O panel opening receipt is not the authorized third opening")
    if tree.get("status") != "V08O_ALL_EPOCH_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS":
        raise RuntimeError("raw prediction tree does not certify seal-before-analysis")
    if tree.get("prediction_rows") != 288_000 or inference.get("prediction_rows") != 288_000:
        raise RuntimeError("raw prediction row count differs from the frozen contract")
    if tree.get("files", {}).get(prediction_path.name, {}).get("sha256") != raw_sha:
        raise RuntimeError("raw prediction bytes differ from the sealed hash tree")
    if inference.get("prediction_sha256") != raw_sha:
        raise RuntimeError("inference receipt does not bind the raw prediction file")

    expected: dict[str, str] = {}
    for item in preflight["checkpoints"]:
        key = f"{item['seed']}/{item['arm']}/epoch-{item['epoch']}"
        if key in expected:
            raise RuntimeError(f"duplicate checkpoint identity in preflight: {key}")
        expected[key] = item["sha256"]
    for seed, item in preflight["initialization_templates"].items():
        for arm in ARMS:
            expected[f"{seed}/{arm}/epoch-0"] = item["sha256"]
    if len(expected) != 36 or expected != tree.get("checkpoint_sha256_by_cell"):
        raise RuntimeError("prediction-tree checkpoint bindings differ from the preflight inventory")

    counts: Counter[str] = Counter()
    ids_by_cell: dict[str, set[str]] = {key: set() for key in expected}
    views_by_cell: dict[str, dict[str, set[str]]] = {key: {} for key in expected}
    with prediction_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            row = json.loads(line)
            key = f"{row['seed']}/{row['arm']}/epoch-{row['epoch']}"
            if key not in expected:
                raise RuntimeError(f"unexpected cell identity at prediction row {line_number}: {key}")
            if row.get("checkpoint_sha256") != expected[key]:
                raise RuntimeError(f"checkpoint hash mismatch at prediction row {line_number}: {key}")
            neighborhood_id = str(row["neighborhood_id"])
            view = str(row["view"])
            if view not in VIEWS:
                raise RuntimeError(f"unexpected held-out view at row {line_number}: {view}")
            counts[key] += 1
            ids_by_cell[key].add(neighborhood_id)
            block = views_by_cell[key].setdefault(neighborhood_id, set())
            if view in block:
                raise RuntimeError(f"duplicate view at prediction row {line_number}: {key}/{neighborhood_id}/{view}")
            block.add(view)

    if set(counts) != set(expected) or any(counts[key] != 8_000 for key in expected):
        raise RuntimeError("one or more response-matrix cells do not contain exactly 8,000 rows")
    if any(len(ids_by_cell[key]) != 2_000 for key in expected):
        raise RuntimeError("one or more cells do not contain exactly 2,000 neighborhoods")
    if any(len(views_by_cell[key]) != 2_000 or any(views != VIEWS for views in views_by_cell[key].values()) for key in expected):
        raise RuntimeError("one or more neighborhoods lack exactly the four contracted view rows")
    common_ids = ids_by_cell[next(iter(expected))]
    if any(ids != common_ids for ids in ids_by_cell.values()):
        raise RuntimeError("response-matrix cells do not share the exact held-out neighborhood IDs")
    metric_outputs = (
        "neighborhood-metrics-v01.jsonl", "trajectory-response-matrix-v01.json",
        "transition-four-cell-decomposition-v01.json", "paired-sham-minus-matched-trajectories-v01.json",
        "parameter-trajectories-v01.json", "trajectory-cartography-v01.md",
    )
    if any((OUTPUT / name).exists() for name in metric_outputs):
        raise RuntimeError("analysis outputs already exist; no post-seal correction may proceed")

    audit = {
        "status": "V08O_RAW_PREDICTION_IDENTITY_AUDIT_PASS_NO_METRIC_ANALYSIS",
        "identity": "POST-HOC v0.8O CAPABILITY TRAJECTORY CARTOGRAPHY OF SEALED PHASE-B CHECKPOINTS",
        "verifier_source_sha256": sha256_file(Path(__file__).resolve()),
        "preflight_sha256": sha256_file(preflight_path),
        "opening_receipt_sha256": sha256_file(opening_path),
        "raw_prediction_hash_tree_sha256": sha256_file(tree_path),
        "raw_prediction_sha256": raw_sha,
        "prediction_rows": sum(counts.values()),
        "cell_count": len(counts),
        "checkpoint_cell_bindings_verified": len(expected),
        "neighborhoods_per_cell": 2_000,
        "view_rows_per_neighborhood": 4,
        "common_neighborhood_ids_across_cells": True,
        "prediction_values_or_targets_used_for_selection": False,
        "metrics_computed": False,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with output_receipt.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    amendment = {
        "status": "V08O_PREANALYSIS_REPORTING_CORRECTION_NO_METRIC_CHANGE",
        "identity": "POST-HOC v0.8O CAPABILITY TRAJECTORY CARTOGRAPHY OF SEALED PHASE-B CHECKPOINTS",
        "reason": "The frozen parameter_trajectory schema specifies epoch-0 paired update cosines as null; the pre-analysis implementation omitted the epoch-0 pairwise keys.",
        "scope": "Add the three epoch-0 pairwise records with update_cosine=null and update_distance_l2=0.0. No prediction rows, metric definitions, aggregation, checkpoint identity, or interpretation rule is changed.",
        "analysis_source_sha256_at_opening": preflight["source_hashes"]["analysis"],
        "corrected_analysis_source_sha256": sha256_file(ANALYSIS_SOURCE),
        "raw_prediction_sha256": raw_sha,
        "raw_identity_audit_sha256": sha256_file(output_receipt),
        "no_analysis_outputs_existed_at_correction": True,
        "no_metric_values_inspected_for_correction": True,
        "corrected_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with amendment_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(amendment, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return audit


def main() -> None:
    receipt = verify()
    print(json.dumps({"status": receipt["status"], "rows": receipt["prediction_rows"],
                      "cells": receipt["cell_count"], "raw_sha256": receipt["raw_prediction_sha256"]}, separators=(",", ":")))


if __name__ == "__main__":
    main()
