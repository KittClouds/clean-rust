"""Freeze Cphi inputs and all 36 initializer bundles before fit 1."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
PREFIT = STUDY / "f4-invariant-01-prefit-v2"
IMPL = STUDY / "f4-invariant-01-impl-v2"
SCRIPTS = STUDY / "scripts"
for _path in (str(PREFIT), str(IMPL), str(SCRIPTS), str(BRANCH)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cphi_model import make_initial_tensors, serialize_tensors, tensor_hash  # noqa: E402
from fit_common import (  # noqa: E402
    BLOCKS, RUN as PARENT_RUN, load_raw_inputs, normalized_folds, read_initial_bundle,
    read_json, sha_file, shared_stream_hashes, validate_source_manifest, write_json_new,
)
from fit_contract import manifest_row_hashes, sha256_bytes, validate_fit_grid  # noqa: E402
from f4_invariant_01_model import tensor_hash as parent_tensor_hash  # noqa: E402


RUN_ID = "F4-PRESENTATION-02-CPHI-ENG1-V2"
RUN = STUDY / "runs" / RUN_ID
CONTRACT = BRANCH / "F4-PRESENTATION-02-ENGINEERING-SCREEN-v0.1.json"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_bytes_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def _sha_entry(path: Path, label: str | None = None) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"required frozen parent file missing: {path}")
    return {
        "path": _relative(path),
        "label": label or path.name,
        "byte_length": path.stat().st_size,
        "sha256": sha_file(path),
    }


def _parent_input_paths() -> list[Path]:
    task_bank = PARENT_RUN.parent / "F4-INVARIANT-01-RUN2" / "task-bank"
    v1_run = STUDY / "runs" / "F4-PRESENTATION-02-CPHI-ENG1"
    paths = [
        PARENT_RUN / "native-collection" / "RAW-PREDICTORS.bin",
        PARENT_RUN / "native-collection" / "RAW-SCORING-TRUTH.bin",
        PARENT_RUN / "COLLECTION-RECEIPT.json",
        PARENT_RUN / "FOLD-NORMALIZATION-PAYLOADS.bin",
        PARENT_RUN / "FIT-MANIFEST.csv",
        PARENT_RUN / "FIT-MANIFEST-ROW-HASHES.json",
        PARENT_RUN / "SHARED-INPUT-RECONCILIATION.json",
        PARENT_RUN / "SHARED-INPUT-RECONCILIATION-SEAL.json",
        PARENT_RUN / "TRAINING-SUPPORT-RECEIPT.json",
        PARENT_RUN / "PREDICTION-LOCK.json",
        PARENT_RUN / "INTEGRITY-RECEIPT.json",
        PARENT_RUN / "ANALYSIS.json",
        PARENT_RUN / "ANALYSIS-REPAIR-AMENDMENT-v0.1.json",
        PARENT_RUN / "F4-INVARIANT-01-TERMINAL-RECEIPT-v0.1.json",
        PARENT_RUN / "FIT-EXECUTION-PREFLIGHT-RECEIPT.json",
        PARENT_RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json",
        PARENT_RUN / "FIT-TOOLING-FREEZE-RECEIPT.json",
        v1_run / "EXECUTION-STOP-RECEIPT-v0.1.json",
        v1_run / "ENGINEERING-PREFIT-FREEZE.json",
        v1_run / "SOURCE-MANIFEST.json",
        v1_run / "FIT-MANIFEST.json",
        task_bank / "training.json",
        task_bank / "TASK-BANK-MANIFEST.json",
        IMPL / "implementation-artifacts" / "INITIALIZER-SEED-MANIFEST.json",
    ]
    lock = read_json(PARENT_RUN / "PREDICTION-LOCK.json")
    if lock.get("status") != "PASS" or len(lock.get("prediction_streams", [])) != 72:
        raise RuntimeError("parent D/S prediction lock is not a complete PASS surface")
    for item in lock["prediction_streams"]:
        paths.append(PARENT_RUN / item["prediction_path"])
        paths.append(PARENT_RUN / "fit-receipts" / f"{item['fit_id']}.json")
    for fold in range(12):
        block = BLOCKS[fold]
        for replicate in range(3):
            paths.append(PARENT_RUN / "initial-tensors" / f"S-H{block}-I{replicate}.bin")
    return list(dict.fromkeys(paths))


def _verify_parent() -> tuple[list[dict[str, str]], dict[str, str], Any, dict[int, Any], dict[str, Any]]:
    if RUN.exists():
        raise RuntimeError(f"new Cphi run identity already exists; preserve and stop: {RUN}")
    preflight = read_json(PARENT_RUN / "FIT-EXECUTION-PREFLIGHT-RECEIPT.json")
    source = validate_source_manifest(
        PARENT_RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json",
        str(preflight["source_manifest_canonical_sha256"]),
        str(preflight["source_manifest_file_sha256"]),
    )
    integrity = read_json(PARENT_RUN / "INTEGRITY-RECEIPT.json")
    lock = read_json(PARENT_RUN / "PREDICTION-LOCK.json")
    analysis = read_json(PARENT_RUN / "ANALYSIS.json")
    amendment = read_json(PARENT_RUN / "ANALYSIS-REPAIR-AMENDMENT-v0.1.json")
    if integrity.get("status") != "PASS" or lock.get("status") != "PASS" or len(lock.get("prediction_streams", [])) != 72:
        raise RuntimeError("parent integrity/prediction lock failed")
    if integrity.get("prediction_lock_sha256") != sha_file(PARENT_RUN / "PREDICTION-LOCK.json"):
        raise RuntimeError("parent integrity receipt does not name the current prediction lock")
    for item in lock["prediction_streams"]:
        pred_path = PARENT_RUN / item["prediction_path"]
        receipt_path = PARENT_RUN / "fit-receipts" / f"{item['fit_id']}.json"
        if sha_file(pred_path) != item["prediction_sha256"] or sha_file(receipt_path) != item["fit_receipt_sha256"]:
            raise RuntimeError(f"locked parent D/S output drift: {item['fit_id']}")
    if analysis.get("heldout_support", {}).get("evaluable_blocks") != 7:
        raise RuntimeError("parent support disposition is not the expected 7/12 failure")
    if amendment.get("heldout_truth_previously_opened") is not True:
        raise RuntimeError("parent truth-access provenance is not explicit")
    task_dir = PARENT_RUN.parent / "F4-INVARIANT-01-RUN2" / "task-bank"
    task_manifest = read_json(task_dir / "TASK-BANK-MANIFEST.json")
    if sha_file(task_dir / "training.json") != task_manifest.get("task_bank_sha256"):
        raise RuntimeError("parent task bank hash mismatch")
    collection = read_json(PARENT_RUN / "COLLECTION-RECEIPT.json")
    if (
        collection.get("status") != "PASS"
        or sha_file(PARENT_RUN / "native-collection" / "RAW-PREDICTORS.bin") != collection.get("predictor_file_sha256")
        or sha_file(PARENT_RUN / "native-collection" / "RAW-SCORING-TRUTH.bin") != collection.get("truth_file_sha256")
    ):
        raise RuntimeError("parent native collection hash mismatch")
    run_rows = list(csv.DictReader((PARENT_RUN / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="")))
    validate_fit_grid(run_rows)
    raw_manifest = (PARENT_RUN / "FIT-MANIFEST.csv").read_bytes()
    manifest_sha, row_hashes = manifest_row_hashes(raw_manifest)
    if manifest_sha != integrity.get("fit_manifest_sha256"):
        raise RuntimeError("parent fit manifest differs from integrity receipt")
    row_hash_receipt = read_json(PARENT_RUN / "FIT-MANIFEST-ROW-HASHES.json")
    if row_hash_receipt.get("manifest_sha256") != manifest_sha or row_hash_receipt.get("rows") != row_hashes:
        raise RuntimeError("parent fit row hashes do not reconcile")
    input_paths = _parent_input_paths()
    input_manifest = {
        "schema": "F4-PRESENTATION-02-parent-input-manifest-v1",
        "parent_run_id": "F4-INVARIANT-01-COLLECT2-EXEC2",
        "parent_truth_previously_opened": True,
        "files": [_sha_entry(path) for path in input_paths],
    }
    raw = load_raw_inputs()
    normalized = normalized_folds(raw)
    shared = read_json(PARENT_RUN / "SHARED-INPUT-RECONCILIATION.json")
    if len(shared.get("folds", [])) != 12:
        raise RuntimeError("parent shared-input receipt fold count mismatch")
    by_fold: dict[int, Any] = {}
    for fold, norm in normalized.items():
        receipt = shared["folds"][fold]
        if norm.sha256 != receipt["normalization_sha256"]:
            raise RuntimeError(f"frozen normalization payload mismatch in fold {fold}")
        hashes = shared_stream_hashes(raw.keys, norm.base, norm.tuples)
        if (
            hashes["base"] != receipt["base_stream_sha256"]
            or hashes["tuples"] != receipt["normalized_tuple_stream_sha256"]
            or hashes["paired"] != receipt["paired_source_input_sha256"]
        ):
            raise RuntimeError(f"parent normalized shared-input stream mismatch in fold {fold}")
        by_fold[fold] = norm
    return run_rows, row_hashes, raw, by_fold, {
        "source_manifest": source,
        "parent_input_manifest": input_manifest,
        "parent_integrity": integrity,
        "parent_lock": lock,
        "parent_analysis": analysis,
        "parent_analysis_repair": amendment,
        "parent_task_manifest": task_manifest,
    }


def prepare() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("identity") != RUN_ID or contract.get("panel", {}).get("new_task_or_seed_bank") is not False:
        raise RuntimeError("Cphi engineering contract identity/inputs mismatch")
    parent_rows, _parent_hashes, raw, normalized, parent = _verify_parent()
    row_by_cell = {
        (int(row["fold_index"]), int(row["replicate_index"]), row["arm"]): row
        for row in parent_rows
    }
    parent_run_rows = []
    initializer_cells = []
    run_rows = []
    RUN.mkdir(parents=True, exist_ok=False)
    (RUN / "initial-tensors").mkdir()
    (RUN / "fit-receipts").mkdir()
    (RUN / "heldout-state").mkdir()
    (RUN / "predictions").mkdir()
    (RUN / "training-traces").mkdir()

    parent_input_path = RUN / "PARENT-INPUT-MANIFEST.json"
    parent_input_bytes = _json_bytes(parent["parent_input_manifest"])
    _write_bytes_new(parent_input_path, parent_input_bytes)
    parent_input_sha = sha256_bytes(parent_input_bytes)

    shared = read_json(PARENT_RUN / "SHARED-INPUT-RECONCILIATION.json")
    for fold in range(12):
        heldout_block = BLOCKS[fold]
        norm = normalized[fold]
        input_fold = shared["folds"][fold]
        for replicate in range(3):
            parent_s = row_by_cell[(fold, replicate, "S")]
            source_id = parent_s["fit_id"]
            source_bundle_path = PARENT_RUN / "initial-tensors" / f"{source_id}.bin"
            source_values = read_initial_bundle(source_bundle_path, "S")
            if parent_tensor_hash(source_values, "S") != parent_s["initial_tensor_hash"]:
                raise RuntimeError(f"parent S initializer mismatch: {source_id}")
            values, layer_seeds = make_initial_tensors(fold, replicate, source_values[0], source_values[1])
            if values[0].tobytes() != source_values[0].tobytes() or values[1].tobytes() != source_values[1].tobytes():
                raise RuntimeError(f"Cphi phi initialization is not an exact copy: {source_id}")
            fit_id = f"CPHI-H{heldout_block}-I{replicate}"
            bundle_bytes = serialize_tensors(values)
            bundle_path = RUN / "initial-tensors" / f"{fit_id}.bin"
            _write_bytes_new(bundle_path, bundle_bytes)
            row = {
                "fit_id": fit_id,
                "arm": "Cphi",
                "fold_index": fold,
                "heldout_block": heldout_block,
                "replicate_index": replicate,
                "train_rows": int(parent_s["train_rows"]),
                "heldout_rows": int(parent_s["heldout_rows"]),
                "training_row_hash": parent_s["training_row_hash"],
                "training_order_hash": parent_s["training_order_hash"],
                "normalization_sha256": parent_s["normalization_sha256"],
                "base_stream_sha256": parent_s["base_stream_sha256"],
                "normalized_tuple_stream_sha256": parent_s["normalized_tuple_stream_sha256"],
                "paired_source_input_sha256": parent_s["paired_source_input_sha256"],
                "parent_fit_manifest_row_sha256": _parent_hashes.get(parent_s["fit_id"]),
                "parent_S_phi_initializer_path": _relative(source_bundle_path),
                "parent_S_phi_initializer_file_sha256": sha_file(source_bundle_path),
                "initial_tensor_path": f"initial-tensors/{fit_id}.bin",
                "initial_tensor_sha256": tensor_hash(values),
                "initial_tensor_file_sha256": sha256_bytes(bundle_bytes),
                "readout_layer_seeds": layer_seeds,
                "prediction_path": f"predictions/{fit_id}.bin",
                "heldout_state_path": f"heldout-state/{fit_id}.npz",
                "final_tensor_path": f"final-tensors/{fit_id}.bin",
                "training_trace_path": f"training-traces/{fit_id}.csv",
            }
            if (
                row["normalization_sha256"] != norm.sha256
                or row["base_stream_sha256"] != input_fold["base_stream_sha256"]
                or row["normalized_tuple_stream_sha256"] != input_fold["normalized_tuple_stream_sha256"]
                or row["paired_source_input_sha256"] != input_fold["paired_source_input_sha256"]
            ):
                raise RuntimeError(f"shared D/S input reconciliation changed at {fit_id}")
            run_rows.append(row)
            initializer_cells.append({
                "fit_id": fit_id,
                "fold_index": fold,
                "replicate_index": replicate,
                "source_S_phi_file_sha256": row["parent_S_phi_initializer_file_sha256"],
                "initial_tensor_sha256": row["initial_tensor_sha256"],
                "initial_tensor_file_sha256": row["initial_tensor_file_sha256"],
                "readout_layer_seeds": layer_seeds,
                "parameter_count": 19_936,
            })

    if len(run_rows) != 36 or len({row["fit_id"] for row in run_rows}) != 36:
        raise RuntimeError("Cphi fit grid is not exactly 36 unique cells")

    source_paths = [
        CONTRACT,
        BRANCH / "F4-PRESENTATION-02-ENGINEERING-IMPLEMENTATION-AMENDMENT-v0.2.json",
        BRANCH / "cphi_model.py",
        BRANCH / "prepare_cphi.py",
        BRANCH / "run_cphi.py",
        BRANCH / "verify_cphi.py",
        BRANCH / "analyze_cphi.py",
        BRANCH / "test_cphi_model.py",
        STUDY / "f4-invariant-01-impl-v2" / "f4_invariant_01_model.py",
        STUDY / "f4-invariant-01-impl-v2" / "f4_invariant_01_inputs.py",
        STUDY / "scripts" / "f4_symmetry_01_model.py",
        STUDY / "scripts" / "f4_symmetry_01_common.py",
        PREFIT / "fit_common.py",
        PREFIT / "fit_contract.py",
    ]
    source_entries = [_sha_entry(path, _relative(path)) for path in source_paths]
    source_manifest = {
        "schema": "F4-PRESENTATION-02-source-manifest-v1",
        "identity": RUN_ID,
        "files": source_entries,
    }
    source_raw = _json_bytes(source_manifest)
    _write_bytes_new(RUN / "SOURCE-MANIFEST.json", source_raw)
    source_manifest_sha = sha256_bytes(source_raw)

    initializer_manifest = {
        "schema": "F4-PRESENTATION-02-cphi-initializer-manifest-v1",
        "identity": RUN_ID,
        "task_identity_used": False,
        "phi_initialization": "bit-identical from parent S initializer for matching fold/replicate",
        "cells": initializer_cells,
    }
    initializer_raw = _json_bytes(initializer_manifest)
    _write_bytes_new(RUN / "CPHI-INITIALIZER-MANIFEST.json", initializer_raw)
    initializer_sha = sha256_bytes(initializer_raw)
    fit_manifest = {
        "schema": "F4-PRESENTATION-02-cphi-fit-manifest-v1",
        "identity": RUN_ID,
        "fit_count": len(run_rows),
        "source_manifest_sha256": source_manifest_sha,
        "parent_input_manifest_sha256": parent_input_sha,
        "initializer_manifest_sha256": initializer_sha,
        "rows": run_rows,
    }
    fit_raw = _json_bytes(fit_manifest)
    _write_bytes_new(RUN / "FIT-MANIFEST.json", fit_raw)
    fit_manifest_sha = sha256_bytes(fit_raw)

    parent_manifest_sha = sha256_bytes(_json_bytes(parent["parent_input_manifest"]))
    freeze = {
        "schema": "F4-PRESENTATION-02-prefit-freeze-v1",
        "identity": RUN_ID,
        "status": "PASS",
        "fit_count": 36,
        "architecture_parameter_count": 19_936,
        "parent_run_id": "F4-INVARIANT-01-COLLECT2-EXEC2",
        "parent_truth_previously_opened": True,
        "parent_scientific_disposition": "NOT_EVALUABLE_SUPPORT",
        "source_manifest_sha256": source_manifest_sha,
        "parent_input_manifest_sha256": parent_manifest_sha,
        "initializer_manifest_sha256": initializer_sha,
        "fit_manifest_sha256": fit_manifest_sha,
        "parent_prediction_lock_sha256": sha_file(PARENT_RUN / "PREDICTION-LOCK.json"),
        "parent_integrity_receipt_sha256": sha_file(PARENT_RUN / "INTEGRITY-RECEIPT.json"),
        "parent_analysis_sha256": sha_file(PARENT_RUN / "ANALYSIS.json"),
        "task_bank_reused": True,
        "native_collection_reused": True,
        "parent_outputs_modified": False,
        "truth_used_during_fit": False,
        "comparative_outcomes_used_during_fit": False,
    }
    freeze_raw = _json_bytes(freeze)
    _write_bytes_new(RUN / "ENGINEERING-PREFIT-FREEZE.json", freeze_raw)
    print(json.dumps({
        "status": "PREFIT_FROZEN",
        "run_id": RUN_ID,
        "fit_count": 36,
        "source_manifest_sha256": source_manifest_sha,
        "parent_input_manifest_sha256": parent_input_sha,
        "fit_manifest_sha256": fit_manifest_sha,
        "initializer_manifest_sha256": initializer_sha,
        "parent_truth_previously_opened": True,
    }, sort_keys=True))


if __name__ == "__main__":
    prepare()
