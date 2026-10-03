"""Run frozen Stage B inference with the versioned empty-block loader repair."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path

import repair_common as common

HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent
STUDY = BRANCH.parents[1]
REPO = STUDY.parents[1]
RUN = STUDY / "runs" / "F4-BINDING-01-STAGE-B-PROSP-v0.1"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen repair source {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manifest = common.require_repair_manifest()
    common.verify_immutable_inputs(manifest)
    if any((RUN / name).exists() for name in ("PREDICTION-LOCK.json", "predictions", "fit-receipts")):
        raise RuntimeError("prediction outputs exist; preserve and stop")
    sys.path.insert(0, str(BRANCH))
    import binding_stage_b_data as data

    repair = load_source("f4_binding_stage_b_empty_loader", HERE / "binding_stage_b_empty_block_loader.py")
    data.load_predictors = lambda path, expected_blocks=data.BLOCK_IDS: repair.load_predictors_allow_empty(data, path, expected_blocks)
    runner = load_source("f4_binding_stage_b_inference_frozen", BRANCH / "run_stage_b_inference.py")
    runner.main()
    lock_path = RUN / "PREDICTION-LOCK.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    output_entries = []
    for row in lock["predictions"]:
        for key in ("prediction_path", "fit_receipt_path"):
            path = RUN / row[key]
            output_entries.append({"path": path.relative_to(RUN).as_posix(), "byte_length": path.stat().st_size, "sha256": sha_file(path)})
    receipt = {
        "schema": "F4-BINDING-01-stage-b-empty-block-inference-repair-receipt-v0.1",
        "identity": common.REPAIR_ID,
        "status": "PASS",
        "repair_manifest_sha256": sha_file(common.MANIFEST_PATH),
        "original_stop_receipt_sha256": manifest["original_inference_stop_receipt_sha256"],
        "prediction_lock_sha256": sha_file(lock_path),
        "prediction_count": lock.get("model_count"),
        "row_count_per_model": lock.get("row_count_per_model"),
        "prediction_and_fit_receipt_files": output_entries,
        "truth_values_opened": False,
        "models_refit": False,
    }
    common.write_new_json(RUN / "EMPTY-BLOCK-REPAIR-INFERENCE-RECEIPT.json", receipt)


if __name__ == "__main__":
    main()
