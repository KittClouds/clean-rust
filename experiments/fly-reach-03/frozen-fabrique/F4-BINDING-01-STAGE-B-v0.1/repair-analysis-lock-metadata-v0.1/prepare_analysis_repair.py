"""Seal the analysis-only metadata join continuation after truth access."""
from __future__ import annotations

import json
from pathlib import Path

import analysis_repair_common as common


def entry(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {"path": resolved.relative_to(common.REPO.resolve()).as_posix(), "byte_length": resolved.stat().st_size, "sha256": common.sha_file(resolved)}


def main() -> None:
    if common.MANIFEST.exists() or common.MANIFEST_SHA.exists():
        raise RuntimeError("analysis repair manifest already exists; preserve and stop")
    stop_path = common.RUN / "ANALYSIS-START-STOP-RECEIPT.json"
    stop = common.read_json(stop_path)
    if stop.get("status") != "STOP_AFTER_TRUTH_OPEN_BEFORE_COMPARATIVE_OUTPUT" or stop.get("truth_values_opened") is not True:
        raise RuntimeError("preserved analysis failure/truth-access receipt mismatch")
    partial = stop.get("partial_in_memory_scoring")
    if not isinstance(partial, dict):
        raise RuntimeError("analysis stop receipt lacks partial in-memory scoring record")
    if stop.get("analysis_outputs_existed_before_failure") is not False or partial.get("comparison_outputs_written") is not False:
        raise RuntimeError("analysis repair requires a stop before comparative output")
    if partial.get("comparative_summary_produced") is not False:
        raise RuntimeError("analysis repair requires no comparative summary before the stop")
    output_names = (
        "ANALYSIS.json", "RESULTS.md", "STAGE-B-TERMINAL-RECEIPT.json", "ASSIGNMENT-METRICS.csv",
        "MODEL-ASSIGNMENT-METRICS.csv", "BLOCK-METRICS.csv", "MODEL-CELL-METRICS.csv", "STAGE-B-SUPPORT-TABLE.csv",
    )
    if any((common.RUN / name).exists() for name in output_names):
        raise RuntimeError("analysis output exists; preserve and stop")

    frozen = common.read_json(common.BRANCH / "IMPLEMENTATION-FREEZE.json")
    freeze_entry = next(row for row in frozen["source_files"] if row["path"].endswith("/analyze_stage_b.py"))
    if common.sha_file(common.REPO / Path(freeze_entry["path"])) != freeze_entry["sha256"]:
        raise RuntimeError("frozen analysis source has drifted")

    immutable_paths = [
        common.BRANCH / "IMPLEMENTATION-FREEZE.json",
        common.BRANCH / "SOURCE-INPUT-MANIFEST.json",
        common.BRANCH / "MODEL-REGISTRY.json",
        common.BRANCH / "analyze_stage_b.py",
        common.RUN / "task-bank" / "TASK-SEED-MANIFEST.json",
        common.RUN / "task-bank" / "TASK-BANK-MANIFEST.json",
        common.RUN / "task-bank" / "training.json",
        common.RUN / "native-collection" / "RAW-PREDICTORS.bin",
        common.RUN / "native-collection" / "RAW-SCORING-TRUTH.bin",
        common.RUN / "native-collection" / "NATIVE-COLLECTION-RECEIPT.json",
        common.RUN / "COLLECTION-INTEGRITY-RECEIPT.json",
        common.RUN / "PREDICTION-LOCK.json",
        common.RUN / "PRE-TRUTH-INTEGRITY-RECEIPT.json",
        common.RUN / "EMPTY-BLOCK-REPAIR-INFERENCE-RECEIPT.json",
        common.RUN / "EMPTY-BLOCK-REPAIR-INTEGRITY-RECEIPT.json",
        common.RUN / "INFERENCE-START-STOP-RECEIPT.json",
        common.RUN / "ANALYSIS-START-STOP-RECEIPT.json",
        common.EMPTY_BLOCK_REPAIR / "REPAIR-MANIFEST.json",
        common.EMPTY_BLOCK_REPAIR / "REPAIR-MANIFEST.sha256",
    ]
    immutable = [entry(path) for path in immutable_paths]
    for row in stop["files"]:
        if row["path"].endswith("/RAW-SCORING-TRUTH.bin") and row["sha256"] != next(item["sha256"] for item in immutable if item["path"] == row["path"]):
            raise RuntimeError("scoring truth changed after the recorded failed analysis")
    predictions = stop["locked_prediction_surface"]
    for row in predictions:
        path = common.REPO / Path(row["path"])
        if not path.is_file() or path.stat().st_size != row["byte_length"] or common.sha_file(path) != row["sha256"]:
            raise RuntimeError(f"locked prediction/receipt changed after analysis stop: {row['path']}")
    immutable.extend(predictions)

    repair_paths = [
        common.HERE / "analysis_repair_common.py",
        common.HERE / "prepare_analysis_repair.py",
        common.HERE / "run_analysis_repair.py",
        common.HERE / "test_analysis_repair.py",
    ]
    repair_sources = [entry(path) for path in repair_paths]
    payload = {
        "schema": "F4-BINDING-01-stage-b-analysis-metadata-repair-manifest-v0.1",
        "identity": common.IDENTITY,
        "status": "PASS",
        "parent_empty_block_repair_manifest_sha256": common.sha_file(common.EMPTY_BLOCK_REPAIR / "REPAIR-MANIFEST.json"),
        "analysis_stop_receipt_path": stop_path.relative_to(common.REPO).as_posix(),
        "analysis_stop_receipt_sha256": common.sha_file(stop_path),
        "truth_values_previously_opened": True,
        "transient_first_model_first_assignment_condition_score_calls": 3,
        "comparative_result_emitted_before_repair": False,
        "repair_scope": "Join fold_index, heldout_block, and replicate_index from the already frozen model registry into in-memory prediction-lock rows for analysis only; do not modify lock or predictions.",
        "immutable_inputs": immutable,
        "repair_sources": repair_sources,
        "models_refit": False,
        "predictions_regenerated": False,
        "truth_file_modified": False,
        "metric_definitions_changed": False,
        "support_or_disposition_rules_changed": False,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    digest = common.write_new_json(common.MANIFEST, payload)
    with common.MANIFEST_SHA.open("x", encoding="ascii", newline="") as stream:
        stream.write(digest + "\n")
        stream.flush()
    print(json.dumps({"status": "PASS", "identity": common.IDENTITY, "manifest_sha256": digest, "immutable_input_count": len(immutable), "locked_prediction_and_receipt_count": len(predictions)}, sort_keys=True))


if __name__ == "__main__":
    main()
