"""Run the original independent verifier with only the empty-block fix."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import repair_common as common

HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent


def load_source(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen source {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manifest = common.require_repair_manifest()
    common.verify_immutable_inputs(manifest)
    inference_repair = common.read_json(common.RUN / "EMPTY-BLOCK-REPAIR-INFERENCE-RECEIPT.json")
    lock_path = common.RUN / "PREDICTION-LOCK.json"
    if inference_repair.get("status") != "PASS" or inference_repair.get("prediction_lock_sha256") != common.sha_file(lock_path):
        raise RuntimeError("Stage B repaired inference receipt does not bind the locked predictions")
    for row in inference_repair["prediction_and_fit_receipt_files"]:
        path = common.RUN / row["path"]
        if not path.is_file() or path.stat().st_size != row["byte_length"] or common.sha_file(path) != row["sha256"]:
            raise RuntimeError(f"locked prediction/receipt drift: {row['path']}")
    sys.path.insert(0, str(BRANCH))
    import binding_stage_b_data as data

    loader = load_source("f4_binding_stage_b_empty_loader_integrity", HERE / "binding_stage_b_empty_block_loader.py")
    data.load_predictors = lambda path, expected_blocks=data.BLOCK_IDS: loader.load_predictors_allow_empty(data, path, expected_blocks)
    verifier = load_source("f4_binding_stage_b_integrity_frozen", BRANCH / "verify_stage_b_predictions.py")
    receipt = verifier.audit()
    verifier.write_new(verifier.INTEGRITY_PATH, receipt)
    repair_receipt = {
        "schema": "F4-BINDING-01-stage-b-empty-block-integrity-repair-receipt-v0.1",
        "identity": common.REPAIR_ID,
        "status": "PASS",
        "repair_manifest_sha256": common.sha_file(common.MANIFEST_PATH),
        "inference_repair_receipt_sha256": common.sha_file(common.RUN / "EMPTY-BLOCK-REPAIR-INFERENCE-RECEIPT.json"),
        "prediction_lock_sha256": common.sha_file(lock_path),
        "original_pretruth_integrity_receipt_sha256": common.sha_file(verifier.INTEGRITY_PATH),
        "original_pretruth_integrity_status": receipt["status"],
        "truth_values_opened": False,
    }
    common.write_new_json(common.RUN / "EMPTY-BLOCK-REPAIR-INTEGRITY-RECEIPT.json", repair_receipt)
    print(json.dumps({"status": receipt["status"], "models": receipt["model_count"], "rows_per_model": receipt["prediction_row_count_per_model"], "truth_values_opened": False}, sort_keys=True))


if __name__ == "__main__":
    main()
