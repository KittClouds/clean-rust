"""Freeze the narrow pre-inference repair without changing Stage B inputs."""
from __future__ import annotations

import json
from pathlib import Path

import repair_common as common


def entry(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(common.REPO.resolve()).as_posix(),
        "byte_length": resolved.stat().st_size,
        "sha256": common.sha_file(resolved),
    }


def main() -> None:
    if common.MANIFEST_PATH.exists() or common.MANIFEST_SHA_PATH.exists():
        raise RuntimeError("repair manifest already exists; preserve and stop")
    stop_path = common.RUN / "INFERENCE-START-STOP-RECEIPT.json"
    stop = common.read_json(stop_path)
    if stop.get("status") != "STOP_BEFORE_PREDICTION_OUTPUT" or stop.get("truth_values_opened") is not False:
        raise RuntimeError("expected preserved pre-inference stop receipt is absent")
    if any((common.RUN / name).exists() for name in ("PREDICTION-LOCK.json", "predictions", "fit-receipts", "PRE-TRUTH-INTEGRITY-RECEIPT.json", "ANALYSIS.json")):
        raise RuntimeError("Stage B outputs exist; this repair must be pre-inference")
    collection_receipt = common.read_json(common.RUN / "COLLECTION-INTEGRITY-RECEIPT.json")
    if collection_receipt.get("status") != "PASS" or collection_receipt.get("target_values_opened") is not False:
        raise RuntimeError("sealed collection is not available as an unopened input")

    immutable_paths = [
        common.BRANCH / "IMPLEMENTATION-FREEZE.json",
        common.BRANCH / "MODEL-REGISTRY.json",
        common.BRANCH / "SOURCE-INPUT-MANIFEST.json",
        common.RUN / "task-bank" / "TASK-SEED-MANIFEST.json",
        common.RUN / "task-bank" / "TASK-SEED-RECEIPT.json",
        common.RUN / "task-bank" / "TASK-BANK-MANIFEST.json",
        common.RUN / "task-bank" / "TASK-BANK-RECEIPT.json",
        common.RUN / "task-bank" / "training.json",
        common.RUN / "native-collection" / "RAW-PREDICTORS.bin",
        common.RUN / "native-collection" / "RAW-SCORING-TRUTH.bin",
        common.RUN / "native-collection" / "NATIVE-COLLECTION-RECEIPT.json",
        common.RUN / "COLLECTION-INTEGRITY-RECEIPT.json",
        common.RUN / "INFERENCE-START-STOP-RECEIPT.json",
    ]
    expected_stop = {row["path"]: row["sha256"] for row in stop["files"]}
    immutable = [entry(path) for path in immutable_paths]
    for row in immutable:
        if row["path"] in expected_stop and row["sha256"] != expected_stop[row["path"]]:
            raise RuntimeError(f"preserved Stage B input changed since stop: {row['path']}")

    repair_paths = [
        common.HERE / "binding_stage_b_empty_block_loader.py",
        common.HERE / "repair_common.py",
        common.HERE / "prepare_empty_block_repair.py",
        common.HERE / "run_stage_b_inference_repair.py",
        common.HERE / "verify_stage_b_integrity_repair.py",
        common.HERE / "analyze_stage_b_repair.py",
        common.HERE / "test_empty_block_loader.py",
    ]
    repair_sources = [entry(path) for path in repair_paths]
    value = {
        "schema": "F4-BINDING-01-stage-b-empty-block-repair-manifest-v0.1",
        "identity": common.REPAIR_ID,
        "status": "PASS",
        "repair_scope": "Only permit absence of an expected block ID when that block has zero U* rows; retain rejection of out-of-domain block IDs.",
        "original_inference_stop_receipt_path": stop_path.relative_to(common.REPO).as_posix(),
        "original_inference_stop_receipt_sha256": common.sha_file(stop_path),
        "original_implementation_freeze_sha256": common.sha_file(common.BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "original_source_input_manifest_sha256": common.sha_file(common.BRANCH / "SOURCE-INPUT-MANIFEST.json"),
        "immutable_inputs": immutable,
        "repair_sources": repair_sources,
        "task_regenerated": False,
        "native_collection_repeated": False,
        "models_refit": False,
        "prediction_outputs_existed_at_repair_freeze": False,
        "truth_values_opened": False,
        "metrics_or_support_rules_changed": False,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    digest = common.write_new_json(common.MANIFEST_PATH, value)
    with common.MANIFEST_SHA_PATH.open("x", encoding="ascii", newline="") as stream:
        stream.write(digest + "\n")
        stream.flush()
    print(json.dumps({"status": "PASS", "identity": common.REPAIR_ID, "manifest_sha256": digest, "immutable_input_count": len(immutable), "repair_source_count": len(repair_sources)}, sort_keys=True))


if __name__ == "__main__":
    main()
