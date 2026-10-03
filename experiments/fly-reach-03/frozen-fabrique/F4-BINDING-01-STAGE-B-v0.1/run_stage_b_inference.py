"""Inference-only Stage B runner over the exact frozen 36-model CΦ panel."""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

import binding_stage_b_data as data
import binding_stage_b_model as model
import stage_b_runtime as runtime

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parents[1]
REPO = STUDY.parents[1]
RUN_ID = "F4-BINDING-01-STAGE-B-PROSP-v0.1"
RUN = STUDY / "runs" / RUN_ID
PARENT = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
COLLECTION = RUN / "native-collection"
PREDICTIONS = RUN / "predictions"
FIT_RECEIPTS = RUN / "fit-receipts"
LOCK_PATH = RUN / "PREDICTION-LOCK.json"
PRED_MAGIC = data.PRED_MAGIC
PRED_WIDTH = data.PRED_WIDTH
HEADER_WIDTH = data.HEADER_WIDTH
BATCH_SIZE = 2048


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_authorities() -> tuple[dict[str, Any], dict[str, Any], data.PredictorPanel]:
    freeze = read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    collection_receipt = read_json(RUN / "COLLECTION-INTEGRITY-RECEIPT.json")
    registry_path = REPO / Path(freeze["model_registry_path"])
    registry = read_json(registry_path)
    if freeze.get("identity") != RUN_ID or freeze.get("status") != "PASS" or freeze.get("task_bank_created") is not False:
        raise RuntimeError("Stage B implementation freeze mismatch")
    runtime.require_frozen(freeze["runtime_identity"])
    if sha_file(BRANCH / "SOURCE-INPUT-MANIFEST.json") != freeze.get("source_manifest_file_sha256"):
        raise RuntimeError("Stage B source-input manifest drift")
    if sha_file(registry_path) != freeze.get("model_registry_sha256") or registry.get("model_count") != 36:
        raise RuntimeError("frozen CΦ model registry mismatch")
    if collection_receipt.get("status") != "PASS" or collection_receipt.get("target_values_opened") is not False:
        raise RuntimeError("collection integrity has not passed without target access")
    for entry in [*freeze["source_files"], *freeze["parent_artifacts"]]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen Stage B input drift: {entry['path']}")
    predictor_path = COLLECTION / "RAW-PREDICTORS.bin"
    if sha_file(predictor_path) != collection_receipt.get("predictor_sha256"):
        raise RuntimeError("Stage B predictor bytes changed after collection integrity")
    panel = data.load_predictors(predictor_path)
    if len(panel.keys) != int(collection_receipt["row_count"]):
        raise RuntimeError("Stage B predictor row count differs from integrity receipt")
    return freeze, registry, panel


def run_one(model_entry: dict[str, Any], panel: data.PredictorPanel, normalizer_cache: dict[int, tuple[np.ndarray, ...]]) -> dict[str, Any]:
    fit_id = str(model_entry["fit_id"])
    fold = int(model_entry["fold_index"])
    tensor_entry = model_entry["tensor"]
    tensor_path = REPO / Path(tensor_entry["path"])
    if sha_file(tensor_path) != tensor_entry["sha256"]:
        raise RuntimeError(f"frozen tensor changed: {fit_id}")
    tensors = model.load_tensor_bundle(tensor_path)
    params_before = model.parameter_hashes(tensors)
    tensor_content_before = model.CPHI.tensor_hash(tensors)

    if fold not in normalizer_cache:
        norm_entry = model_entry["normalization"]
        norm_path = REPO / Path(norm_entry["path"])
        if sha_file(norm_path) != norm_entry["sha256"]:
            raise RuntimeError(f"frozen normalization changed for fold {fold}")
        normalizer_cache[fold] = data.load_normalizer(norm_path, fold)
    normalizer = normalizer_cache[fold]
    n = len(panel.keys)
    logits = np.empty((n, 3), dtype=np.float32)
    filled = np.zeros(n, dtype=np.bool_)
    h_records: list[dict[str, Any]] = []
    for block in data.BLOCK_IDS:
        indices = np.flatnonzero(panel.blocks == np.uint64(block))
        if not len(indices):
            h_records.append({"block_id": block, "row_count": 0, "h_sha256_before": None, "h_sha256_after": None})
            continue
        x, r = data.apply_normalizer(panel.base[indices], panel.tuples[indices], normalizer)
        block_keys = tuple(panel.keys[int(index)] for index in indices)
        h = model.h_from_normalized(x, r, tensors)
        h_before = model.h_identity_sha(block_keys, h)
        if h.shape != (len(indices), 4, 16) or h.dtype != np.float32:
            raise RuntimeError(f"H shape or dtype mismatch: {fit_id}/{block}")
        for arm_index, arm in enumerate(("intact", "pair_swap", "cycle_4")):
            condition = "cycle_4" if arm == "cycle_4" else arm
            logits[indices, arm_index] = model.rho_forward(x, h, tensors, model.PERMUTATIONS[condition])
        h_after = model.h_identity_sha(block_keys, h)
        if h_before != h_after:
            raise RuntimeError(f"H changed across inference conditions: {fit_id}/{block}")
        filled[indices] = True
        h_records.append({
            "block_id": block,
            "row_count": int(len(indices)),
            "h_sha256_before": h_before,
            "h_sha256_after": h_after,
            "h_shape": [int(value) for value in h.shape],
            "h_dtype": h.dtype.str,
            "source_row_key_sha256": sha_bytes(b"".join(block_keys)),
        })
    if not filled.all() or not np.isfinite(logits).all():
        raise RuntimeError(f"prediction surface is missing or nonfinite: {fit_id}")
    params_after = model.parameter_hashes(tensors)
    tensor_content_after = model.CPHI.tensor_hash(tensors)
    if params_before != params_after or tensor_content_before != tensor_content_after:
        raise RuntimeError(f"trained CΦ parameters changed during inference: {fit_id}")

    prediction_path = PREDICTIONS / f"{fit_id}.bin"
    header = PRED_MAGIC + struct.pack("<IIQ", 1, PRED_WIDTH, n)
    with prediction_path.open("xb") as stream:
        stream.write(header)
        for index, key in enumerate(panel.keys):
            stream.write(key)
            stream.write(np.asarray(logits[index], dtype="<f4").tobytes(order="C"))
        stream.flush()
        os.fsync(stream.fileno())
    prediction_sha = sha_file(prediction_path)
    receipt = {
        "schema": "F4-BINDING-01-stage-b-fit-inference-receipt-v0.1",
        "identity": RUN_ID,
        "fit_id": fit_id,
        "fold_index": fold,
        "heldout_block": int(model_entry["heldout_block"]),
        "replicate_index": int(model_entry["replicate_index"]),
        "tensor_bundle_sha256": tensor_entry["sha256"],
        "tensor_content_sha256_before": tensor_content_before,
        "tensor_content_sha256_after": tensor_content_after,
        "parameter_hashes_before": params_before,
        "parameter_hashes_after": params_after,
        "normalization_sha256": model_entry["normalization"]["sha256"],
        "predictor_sha256": sha_file(COLLECTION / "RAW-PREDICTORS.bin"),
        "row_key_sha256": sha_bytes(b"".join(panel.keys)),
        "row_count": n,
        "conditions": {name: list(value) for name, value in model.PERMUTATIONS.items()},
        "intervention_order": ["intact", "pair_swap", "cycle_4"],
        "h_source_hashes_by_block": h_records,
        "optimizer_state_created": False,
        "gradient_or_update_called": False,
        "phi_recomputed_per_intervention": False,
        "target_values_opened": False,
        "prediction_path": prediction_path.relative_to(RUN).as_posix(),
        "prediction_sha256": prediction_sha,
        "finite_logits": True,
    }
    receipt_path = FIT_RECEIPTS / f"{fit_id}.json"
    write_new(receipt_path, canonical_json(receipt))
    return {
        "fit_id": fit_id,
        "prediction_path": prediction_path.relative_to(RUN).as_posix(),
        "prediction_bytes": prediction_path.stat().st_size,
        "prediction_sha256": prediction_sha,
        "fit_receipt_path": receipt_path.relative_to(RUN).as_posix(),
        "fit_receipt_sha256": sha_file(receipt_path),
        "row_count": n,
    }


def main() -> None:
    if LOCK_PATH.exists() or PREDICTIONS.exists() or FIT_RECEIPTS.exists():
        raise RuntimeError("Stage B prediction output already exists; preserve and stop")
    if not (RUN / "COLLECTION-INTEGRITY-RECEIPT.json").is_file():
        raise RuntimeError("Stage B collection integrity must pass before inference")
    started = time.perf_counter()
    freeze, registry, panel = verify_authorities()
    PREDICTIONS.mkdir(parents=True, exist_ok=False)
    FIT_RECEIPTS.mkdir(parents=True, exist_ok=False)
    normalizers: dict[int, tuple[np.ndarray, ...]] = {}
    entries = []
    model_rows = registry["models"]
    if len(model_rows) != 36:
        raise RuntimeError("frozen model panel is not exactly 36 models")
    for model_entry in model_rows:
        entries.append(run_one(model_entry, panel, normalizers))
    if len({entry["fit_id"] for entry in entries}) != 36 or any(entry["row_count"] != len(panel.keys) for entry in entries):
        raise RuntimeError("incomplete Stage B model prediction panel")
    lock = {
        "schema": "F4-BINDING-01-stage-b-prediction-lock-v0.1",
        "identity": RUN_ID,
        "status": "PASS",
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "source_manifest_sha256": sha_file(BRANCH / "SOURCE-INPUT-MANIFEST.json"),
        "model_registry_sha256": sha_file(REPO / Path(freeze["model_registry_path"])),
        "collection_integrity_receipt_sha256": sha_file(RUN / "COLLECTION-INTEGRITY-RECEIPT.json"),
        "task_bank_manifest_sha256": sha_file(RUN / "task-bank" / "TASK-BANK-MANIFEST.json"),
        "predictor_sha256": sha_file(COLLECTION / "RAW-PREDICTORS.bin"),
        "model_count": len(entries),
        "row_count_per_model": len(panel.keys),
        "conditions": {name: list(value) for name, value in model.PERMUTATIONS.items()},
        "predictions": entries,
        "target_values_opened": False,
        "runtime_seconds": time.perf_counter() - started,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
    }
    write_new(LOCK_PATH, canonical_json(lock))
    print(json.dumps({"status": "PASS", "models": len(entries), "rows_per_model": len(panel.keys), "lock_sha256": sha_file(LOCK_PATH), "target_values_opened": False}, sort_keys=True))


if __name__ == "__main__":
    main()
