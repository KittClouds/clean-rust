"""Independent pre-truth verifier for the sealed F4-INVARIANT-01 fit grid."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import struct
import sys
from pathlib import Path


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
TOOLS = STUDY / "f4-invariant-01-prefit-v2"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from fit_common import (
    BLOCKS, RUN, REPO, STUDY, IMPL, INPUT_MAGIC, INPUT_WIDTH, load_raw_inputs, read_json,
    sha_file, verify_truth_header, write_json_new,
)
from fit_contract import ARMS, FIT_HEADER, PRED_MAGIC, REPLICATES, PRED_RECORD_BYTES, sha256_bytes
from f4_invariant_01_inputs import normalize_fold_inputs, shared_stream_hashes
from f4_invariant_01_model import tensor_hash


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _verify_source_manifest(path: Path, expected_canonical: str, expected_file: str) -> dict[str, object]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema") != "F4-INVARIANT-01-fit-execution-source-manifest-v1":
        raise RuntimeError("source manifest schema mismatch")
    if sha256_bytes(_canonical(manifest)) != expected_canonical or sha256_bytes(raw) != expected_file:
        raise RuntimeError("source manifest digest mismatch")
    for item in manifest["entries"]:
        source = REPO / Path(item["path"])
        if not source.is_file() or source.stat().st_size != item["byte_length"] or sha_file(source) != item["sha256"]:
            raise RuntimeError(f"source drift: {item['path']}")
    return manifest


def _read_manifest_bytes(path: Path) -> tuple[list[dict[str, str]], dict[str, str], str]:
    raw = path.read_bytes()
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise RuntimeError("FIT-MANIFEST line endings invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) != 73:
        raise RuntimeError("FIT-MANIFEST row count is not 72")
    text = raw.decode("utf-8")
    rows = _parse_manifest_lines(io.StringIO(text, newline=""))
    # DictReader accepts text; row digests use exact source bytes including LF.
    row_hashes: dict[str, str] = {}
    for row, line in zip(rows, lines[1:], strict=True):
        if row["fit_id"] in row_hashes:
            raise RuntimeError("duplicate fit id")
        row_hashes[row["fit_id"]] = sha256_bytes(line)
    manifest_sha = sha256_bytes(raw)
    return rows, row_hashes, manifest_sha


def _parse_manifest_lines(lines) -> list[dict[str, str]]:
    """Parse CSV from a line/file iterable and reject character iterables."""
    if isinstance(lines, (str, bytes, bytearray)):
        raise TypeError("CSV input must be a line iterable, not a character iterable")
    reader = csv.DictReader(lines)
    if tuple(reader.fieldnames or ()) != FIT_HEADER:
        raise RuntimeError("FIT-MANIFEST header mismatch")
    rows = list(reader)
    if len(rows) != 72:
        raise RuntimeError("FIT-MANIFEST row count is not 72")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise RuntimeError("FIT-MANIFEST row width mismatch")
    return rows


def _tree_sha256(entries: list[dict[str, object]]) -> str:
    payload = bytearray()
    for entry in sorted(entries, key=lambda item: str(item["path"])):
        payload.extend(str(entry["path"]).encode("utf-8"))
        payload.append(0)
        payload.extend(str(entry["sha256"]).encode("ascii"))
        payload.append(10)
    return sha256_bytes(bytes(payload))


def _verify_integrity_repair_amendment() -> dict[str, object]:
    amendment_path = RUN / "INTEGRITY-REPAIR-AMENDMENT-v0.1a.json"
    amendment = read_json(amendment_path)
    expected = {
        "schema": "F4-INVARIANT-01-integrity-repair-amendment-v0.1a",
        "run_id": "F4-INVARIANT-01-COLLECT2-EXEC2",
        "original_verifier_sha256": "ef53f4ed13529781a8de4f3fa85b7650dc76e4e10017ddbcca67608126fc604f",
        "original_stop_receipt_sha256": "7f2d0820480f5aa75e8231a2077064139a1fb10fbb56cd566b2797b7eb4ddf6a",
        "fit_manifest_sha256": "47b440bb4f9f4d93c897b0835dfe4159e7579a92d2fa5e0e41d93b3084bf8048",
        "prediction_lock_sha256": "47d812653111164c84d2c6b2e861729d7e5356e39821d9d0ff6d9d8c9d63301a",
    }
    if any(amendment.get(key) != value for key, value in expected.items()):
        raise RuntimeError("integrity-repair amendment authority mismatch")
    draft_path = RUN / "INTEGRITY-REPAIR-AMENDMENT-v0.1.json"
    if sha_file(draft_path) != amendment.get("superseded_precheck_draft_sha256"):
        raise RuntimeError("superseded precheck amendment draft changed")
    if amendment.get("repaired_verifier_sha256") != sha_file(Path(__file__)):
        raise RuntimeError("repaired verifier hash differs from amendment")
    if amendment.get("repair_tests_sha256") != sha_file(Path(__file__).with_name("test_fit_integrity_repair.py")):
        raise RuntimeError("repair test hash differs from amendment")
    stop_path = RUN / "INTEGRITY-STOP-RECEIPT.json"
    if sha_file(stop_path) != expected["original_stop_receipt_sha256"]:
        raise RuntimeError("original integrity stop receipt changed")
    manifest_path = RUN / "FIT-MANIFEST.csv"
    lock_path = RUN / "PREDICTION-LOCK.json"
    if sha_file(manifest_path) != expected["fit_manifest_sha256"] or sha_file(lock_path) != expected["prediction_lock_sha256"]:
        raise RuntimeError("locked manifest or prediction lock changed")

    actual_groups = {
        "fit_receipts": ("fit-receipts", sorted((RUN / "fit-receipts").glob("*.json"))),
        "prediction_streams": ("heldout-predictions", sorted((RUN / "heldout-predictions").glob("*.bin"))),
    }
    inventories = amendment.get("locked_output_inventory")
    if not isinstance(inventories, dict):
        raise RuntimeError("repair amendment locked output inventory missing")
    actual_entries: dict[str, list[dict[str, object]]] = {}
    expected_counts = {"fit_receipts": 72, "prediction_streams": 72}
    for group, (directory, paths) in actual_groups.items():
        frozen_entries = inventories.get(group)
        if not isinstance(frozen_entries, list) or len(paths) != expected_counts[group] or len(frozen_entries) != expected_counts[group]:
            raise RuntimeError(f"locked {group} count mismatch")
        actual = [
            {"path": f"{directory}/{path.name}", "byte_length": path.stat().st_size, "sha256": sha_file(path)}
            for path in paths
        ]
        if actual != frozen_entries:
            raise RuntimeError(f"locked {group} inventory drift")
        actual_entries[group] = actual
        if amendment.get(f"{group}_tree_sha256") != _tree_sha256(actual):
            raise RuntimeError(f"locked {group} aggregate hash mismatch")
    combined = actual_entries["fit_receipts"] + actual_entries["prediction_streams"]
    if amendment.get("combined_locked_output_tree_sha256") != _tree_sha256(combined):
        raise RuntimeError("combined locked output aggregate hash mismatch")
    return amendment


def _expected_fit_ids() -> list[str]:
    return [f"{arm}-H{block}-I{rep}" for rep in REPLICATES for arm in ARMS for block in BLOCKS]


def _read_prediction_independently(path: Path, *, block: int, arm: str, replicate: int, row_sha: str, expected_keys: list[bytes]) -> str:
    raw = path.read_bytes()
    if len(raw) < 72 or raw[:16] != PRED_MAGIC:
        raise RuntimeError(f"prediction header invalid: {path.name}")
    version, actual_block, arm_id, actual_rep, count = struct.unpack_from("<IQBB2xQ", raw, 16)
    if (version, actual_block, arm_id, actual_rep, count) != (1, block, ARMS.index(arm), replicate, len(expected_keys)):
        raise RuntimeError(f"prediction identity/count invalid: {path.name}")
    if raw[40:72] != bytes.fromhex(row_sha) or len(raw) != 72 + count * PRED_RECORD_BYTES:
        raise RuntimeError(f"prediction row-hash/length invalid: {path.name}")
    seen: set[bytes] = set()
    for index, expected in enumerate(expected_keys):
        offset = 72 + index * PRED_RECORD_BYTES
        key = raw[offset:offset + 18]
        logit = struct.unpack_from("<f", raw, offset + 18)[0]
        if key != expected or key in seen or not math.isfinite(logit):
            raise RuntimeError(f"missing, reordered, duplicate, or nonfinite prediction at {path.name}:{index}")
        seen.add(key)
    if len(seen) != count:
        raise RuntimeError(f"prediction coverage mismatch: {path.name}")
    return sha256_bytes(raw)


def _verify_truth_keys_only(path: Path, expected_keys: list[bytes]) -> None:
    """Check predictor/truth row identity without interpreting scoring fields."""
    with path.open("rb") as stream:
        stream.seek(32)
        for index, expected in enumerate(expected_keys):
            key = stream.read(18)
            if key != expected:
                raise RuntimeError(f"truth row-key mismatch at row {index}")
            stream.seek(21, os.SEEK_CUR)
        if stream.tell() != path.stat().st_size:
            raise RuntimeError("truth row-key scan ended at an unexpected offset")


def run() -> None:
    output = RUN / "INTEGRITY-RECEIPT.json"
    if output.exists():
        raise RuntimeError("integrity receipt already exists; preserve this identity")
    amendment = _verify_integrity_repair_amendment()
    preflight = read_json(RUN / "FIT-EXECUTION-PREFLIGHT-RECEIPT.json")
    tools = STUDY / "f4-invariant-01-prefit-v2"
    design_sha = sha_file(STUDY / "F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md")
    spec_sha = sha_file(STUDY / "F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md")
    if (
        preflight.get("run_id") != "F4-INVARIANT-01-COLLECT2-EXEC2"
        or
        preflight.get("design_contract_sha256") != design_sha
        or preflight.get("implementation_spec_sha256") != spec_sha
        or preflight.get("executable_sha256") != sha_file(tools / "fit_executor.py")
        or preflight.get("analysis_sha256") != sha_file(tools / "fit_analysis.py")
        or preflight.get("model_source_sha256") != sha_file(IMPL / "f4_invariant_01_model.py")
        or preflight.get("input_source_sha256") != sha_file(IMPL / "f4_invariant_01_inputs.py")
    ):
        raise RuntimeError("preflight authority/executable hash mismatch")
    source = _verify_source_manifest(
        RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json",
        preflight["source_manifest_canonical_sha256"], preflight["source_manifest_file_sha256"],
    )
    rows, row_hashes, manifest_sha = _read_manifest_bytes(RUN / "FIT-MANIFEST.csv")
    if manifest_sha != preflight["fit_manifest_sha256"]:
        raise RuntimeError("FIT-MANIFEST hash differs from preflight")
    expected_ids = _expected_fit_ids()
    if [row["fit_id"] for row in rows] != expected_ids:
        raise RuntimeError("FIT-MANIFEST grid/order mismatch")
    if sum(row["arm"] == "D" for row in rows) != 36 or sum(row["arm"] == "S" for row in rows) != 36:
        raise RuntimeError("FIT-MANIFEST must have 36 rows per arm")

    row_hash_manifest = read_json(RUN / "FIT-MANIFEST-ROW-HASHES.json")
    if row_hash_manifest.get("manifest_sha256") != manifest_sha or row_hash_manifest.get("rows") != row_hashes:
        raise RuntimeError("FIT-MANIFEST row-hash sidecar mismatch")
    collection = read_json(RUN / "COLLECTION-RECEIPT.json")
    raw_predictors = RUN / "native-collection" / "RAW-PREDICTORS.bin"
    raw_truth = RUN / "native-collection" / "RAW-SCORING-TRUTH.bin"
    if sha_file(raw_predictors) != collection["predictor_file_sha256"] or sha_file(raw_truth) != collection["truth_file_sha256"]:
        raise RuntimeError("COLLECT2 raw stream changed")
    if sha_file(raw_predictors) != preflight["predictor_file_sha256"] or sha_file(raw_truth) != preflight["truth_file_sha256"]:
        raise RuntimeError("raw stream differs from fit preflight")
    verify_truth_header(expected_count=int(collection["row_count"]))

    task_dir = RUN.parent / "F4-INVARIANT-01-RUN2" / "task-bank"
    task_manifest = read_json(task_dir / "TASK-BANK-MANIFEST.json")
    if sha_file(task_dir / "training.json") != task_manifest["task_bank_sha256"] or task_manifest["task_bank_sha256"] != collection["task_bank_sha256"]:
        raise RuntimeError("frozen task bank changed")
    if task_manifest["block_ids"] != list(BLOCKS):
        raise RuntimeError("task block list changed")

    reconciliation = read_json(RUN / "SHARED-INPUT-RECONCILIATION.json")
    if reconciliation.get("status") != "PASS" or reconciliation.get("fold_count") != 12 or not reconciliation.get("d_s_common_input_hashes_match_all_folds"):
        raise RuntimeError("shared input reconciliation not PASS")
    support = read_json(RUN / "TRAINING-SUPPORT-RECEIPT.json")
    if support.get("status") != "PASS" or support.get("training_support_failures"):
        raise RuntimeError("training support receipt not PASS")
    initializer_path = IMPL / "implementation-artifacts" / "INITIALIZER-SEED-MANIFEST.json"
    initializer = read_json(initializer_path)
    initializer_sha = sha_file(initializer_path)
    if initializer_sha != preflight["initializer_seed_manifest_sha256"]:
        raise RuntimeError("initializer seed manifest changed")
    bundle_manifest_path = RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json"
    bundle_manifest = read_json(bundle_manifest_path)
    if sha_file(bundle_manifest_path) != preflight["initial_tensor_bundle_manifest_sha256"] or bundle_manifest.get("cell_count") != 72:
        raise RuntimeError("initial tensor bundle manifest changed or is incomplete")

    data = load_raw_inputs(raw_predictors)
    _verify_truth_keys_only(raw_truth, data.keys)
    normalized_by_fold = {}
    for fold_index, holdout in enumerate(BLOCKS):
        train_mask = data.blocks != np.uint64(holdout)
        norm = normalize_fold_inputs(data.base, data.tuples, train_mask, fold_index)
        expected = reconciliation["folds"][fold_index]
        hashes = shared_stream_hashes(data.keys, norm.base, norm.tuples)
        if norm.sha256 != expected["normalization_sha256"] or hashes["base"] != expected["base_stream_sha256"] or hashes["tuples"] != expected["normalized_tuple_stream_sha256"] or hashes["paired"] != expected["paired_source_input_sha256"]:
            raise RuntimeError(f"normalization/shared-input mismatch in fold {fold_index}")
        normalized_by_fold[fold_index] = norm

    receipt_paths = sorted((RUN / "fit-receipts").glob("*.json"))
    prediction_paths = sorted((RUN / "heldout-predictions").glob("*.bin"))
    if len(receipt_paths) != 72 or len(prediction_paths) != 72:
        raise RuntimeError("expected exactly 72 fit receipts and 72 prediction streams")
    if sorted(path.stem for path in receipt_paths) != sorted(expected_ids) or sorted(path.stem for path in prediction_paths) != sorted(expected_ids):
        raise RuntimeError("unexpected or missing fit output path")

    lock = read_json(RUN / "PREDICTION-LOCK.json")
    if (
        lock.get("status") != "PASS" or lock.get("fit_count") != 72
        or lock.get("fit_manifest_sha256") != manifest_sha
        or lock.get("source_manifest_sha256") != preflight["source_manifest_canonical_sha256"]
        or lock.get("heldout_truth_opened") is not False
        or lock.get("comparative_metrics_emitted_during_fitting") is not False
    ):
        raise RuntimeError("prediction lock missing or inconsistent")
    lock_entries = {item["fit_id"]: item for item in lock.get("prediction_streams", [])}
    if len(lock_entries) != 72 or set(lock_entries) != set(expected_ids):
        raise RuntimeError("prediction lock stream grid mismatch")

    verified = []
    row_by_id = {row["fit_id"]: row for row in rows}
    for fold_index, holdout in enumerate(BLOCKS):
        pair = [row_by_id[f"{arm}-H{holdout}-I0"] for arm in ARMS]
        shared_fields = (
            "base_stream_sha256", "normalized_tuple_stream_sha256", "paired_source_input_sha256",
            "normalization_sha256", "training_row_hash", "training_order_hash",
        )
        if any(pair[0][field] != pair[1][field] for field in shared_fields):
            raise RuntimeError(f"D/S paired manifest inputs differ for fold {fold_index}")
    init_by_key = {(cell["fold_index"], cell["replicate_index"], cell["arm"]): cell for cell in initializer["cells"]}
    for fit_id in expected_ids:
        row = row_by_id[fit_id]
        arm, holdout, replicate = row["arm"], int(row["heldout_block"]), int(row["replicate_index"])
        fold_index = int(row["fold_index"])
        if row["fit_id"] != f"{arm}-H{holdout}-I{replicate}" or holdout != BLOCKS[fold_index]:
            raise RuntimeError(f"fit identity mismatch: {fit_id}")
        train_mask = data.blocks != np.uint64(holdout)
        train_keys = [key for key, keep in zip(data.keys, train_mask, strict=True) if keep]
        held_keys = [key for key, keep in zip(data.keys, ~train_mask, strict=True) if keep]
        sorted_hash = hashlib.sha256(b"".join(sorted(train_keys))).hexdigest()
        order_hash = hashlib.sha256(b"".join(train_keys)).hexdigest()
        if sorted_hash != row["training_row_hash"] or order_hash != row["training_order_hash"]:
            raise RuntimeError(f"training key hash mismatch: {fit_id}")
        norm = normalized_by_fold[fold_index]
        if row["normalization_sha256"] != norm.sha256:
            raise RuntimeError(f"normalization hash mismatch: {fit_id}")
        expected_cell = init_by_key[(fold_index, replicate, arm)]
        bundle = RUN / "initial-tensors" / f"{fit_id}.bin"
        if sha_file(bundle) != expected_cell["initial_tensor_sha256"] or row["initial_tensor_hash"] != expected_cell["initial_tensor_sha256"]:
            raise RuntimeError(f"initial tensor bundle mismatch: {fit_id}")
        receipt_path = RUN / "fit-receipts" / f"{fit_id}.json"
        fit_receipt = read_json(receipt_path)
        expected_updates = 200 * ((len(train_keys) + 2047) // 2048)
        fold_reconciliation = reconciliation["folds"][fold_index]
        expected_static = {
            "contract_sha256": preflight["design_contract_sha256"],
            "source_manifest_sha256": preflight["source_manifest_canonical_sha256"],
            "executable_sha256": preflight["executable_sha256"],
            "analysis_sha256": preflight["analysis_sha256"],
            "base_stream_sha256": fold_reconciliation["base_stream_sha256"],
            "normalized_tuple_stream_sha256": fold_reconciliation["normalized_tuple_stream_sha256"],
            "paired_source_input_sha256": fold_reconciliation["paired_source_input_sha256"],
            "initializer_seed_manifest_sha256": initializer_sha,
            "expected_prediction_path": f"heldout-predictions/{fit_id}.bin",
        }
        if any(row.get(key) != value for key, value in expected_static.items()):
            raise RuntimeError(f"fit manifest frozen-input identity mismatch: {fit_id}")
        fields = {
            "fit_id": fit_id, "arm": arm, "fold_index": fold_index, "heldout_block": holdout,
            "replicate_index": replicate, "train_rows": len(train_keys), "heldout_rows": len(held_keys),
            "contract_sha256": row["contract_sha256"], "source_manifest_sha256": row["source_manifest_sha256"],
            "executable_sha256": row["executable_sha256"], "analysis_sha256": row["analysis_sha256"],
            "base_stream_sha256": row["base_stream_sha256"],
            "normalized_tuple_stream_sha256": row["normalized_tuple_stream_sha256"],
            "paired_source_input_sha256": row["paired_source_input_sha256"],
            "normalization_sha256": row["normalization_sha256"],
            "training_row_hash": sorted_hash, "training_order_hash": order_hash,
            "initializer_seed_manifest_sha256": initializer_sha,
            "initial_tensor_hash": row["initial_tensor_hash"], "update_count": expected_updates,
            "finite_status": "PASS", "repeat_prediction_identical": True,
            "fit_manifest_row_sha256": row_hashes[fit_id],
            "batch_size": 2048,
            "epoch_count": 200,
            "architecture_id": "sorted_tuple_mlp_v1" if arm == "D" else "shared_set_encoder_v1",
            "parameter_count": 19969 if arm == "D" else 19057,
        }
        if fit_receipt.get("schema") != "F4-INVARIANT-01-fit-receipt-v1" or any(fit_receipt.get(key) != value for key, value in fields.items()):
            raise RuntimeError(f"fit receipt mismatch: {fit_id}")
        fit_runtime = fit_receipt.get("runtime", {})
        frozen_runtime = preflight["runtime"]
        if (
            fit_runtime.get("python") != frozen_runtime.get("python_version")
            or fit_runtime.get("python_executable") != frozen_runtime.get("python_executable")
            or fit_runtime.get("numpy") != frozen_runtime.get("numpy_version")
            or fit_runtime.get("thread_environment") != frozen_runtime.get("thread_environment")
        ):
            raise RuntimeError(f"fit runtime receipt mismatch: {fit_id}")
        final_hash = str(fit_receipt.get("final_tensor_hash", ""))
        if len(final_hash) != 64 or any(char not in "0123456789abcdef" for char in final_hash):
            raise RuntimeError(f"final tensor hash absent: {fit_id}")
        prediction_path = RUN / row["expected_prediction_path"]
        prediction_sha = _read_prediction_independently(
            prediction_path, block=holdout, arm=arm, replicate=replicate,
            row_sha=row_hashes[fit_id], expected_keys=held_keys,
        )
        if prediction_sha != fit_receipt.get("prediction_sha256") or prediction_sha != lock_entries[fit_id].get("prediction_sha256"):
            raise RuntimeError(f"prediction hash mismatch: {fit_id}")
        if lock_entries[fit_id].get("fit_receipt_sha256") != sha_file(receipt_path) or lock_entries[fit_id].get("prediction_path") != row["expected_prediction_path"]:
            raise RuntimeError(f"prediction-lock receipt mismatch: {fit_id}")
        verified.append({"fit_id": fit_id, "fit_receipt_sha256": sha_file(receipt_path), "prediction_sha256": prediction_sha})

    _verify_source_manifest(
        RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json",
        preflight["source_manifest_canonical_sha256"], preflight["source_manifest_file_sha256"],
    )
    integrity = {
        "schema": "F4-INVARIANT-01-integrity-receipt-v0.2",
        "run_id": "F4-INVARIANT-01-COLLECT2-EXEC2",
        "status": "PASS",
        "heldout_truth_state": "SEALED",
        "fit_count": 72,
        "arm_fit_counts": {"D": 36, "S": 36},
        "prediction_count": 72,
        "verified_fit_and_prediction_hashes": verified,
        "fit_manifest_sha256": manifest_sha,
        "source_manifest_canonical_sha256": preflight["source_manifest_canonical_sha256"],
        "task_bank_sha256": collection["task_bank_sha256"],
        "predictor_file_sha256": collection["predictor_file_sha256"],
        "truth_file_sha256": collection["truth_file_sha256"],
        "normalization_fold_count": 12,
        "d_s_shared_input_hash_mismatches": 0,
        "missing_duplicate_extra_or_nonfinite_prediction_records": 0,
        "comparative_metrics_computed": False,
        "scoring_truth_values_opened": False,
        "qualification_only": True,
        "integrity_repair_amendment_sha256": sha_file(RUN / "INTEGRITY-REPAIR-AMENDMENT-v0.1a.json"),
        "integrity_repair_verifier_sha256": sha_file(Path(__file__)),
        "repair_test_sha256": amendment["repair_tests_sha256"],
        "original_failed_integrity_stop_receipt_sha256": amendment["original_stop_receipt_sha256"],
        "prediction_lock_sha256": amendment["prediction_lock_sha256"],
    }
    write_json_new(output, integrity)
    print(json.dumps({"status": "INTEGRITY_PASS", "fit_count": 72, "prediction_count": 72, "truth_state": "SEALED"}, sort_keys=True))


if __name__ == "__main__":
    run()
