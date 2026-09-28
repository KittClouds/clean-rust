"""Build training support, fold normalizers, task-free initializers, and 144 fits."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_MAXIMUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
TASK_DIR = RUN / "task-bank"
COLLECTION = RUN / "native-collection"
ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
BLOCKS = tuple(range(309000, 309012))
REPLICATES = tuple(range(3))
FIT_HEADER = (
    "fit_id", "arm", "fold_index", "heldout_block", "assignment_index", "replicate_index",
    "train_rows", "heldout_rows", "train_positive_count", "train_negative_count",
    "training_row_set_sha256", "training_order_sha256", "training_labels_sha256",
    "heldout_row_sha256", "normalization_sha256", "normalization_file_sha256",
    "base_stream_sha256", "normalized_tuple_stream_sha256", "paired_source_input_sha256",
    "initializer_manifest_sha256", "initial_tensor_path", "initial_tensor_file_sha256",
    "initial_tensor_sha256", "parameter_count", "expected_update_count",
    "prediction_path", "final_tensor_path", "training_trace_path", "checkpoint_tensor_dir",
    "heldout_state_path", "analysis_source_sha256", "integrity_source_sha256", "runner_source_sha256",
)


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def _verify_sources() -> tuple[dict[str, Any], dict[str, str]]:
    freeze = json.loads((BRANCH / "IMPLEMENTATION-FREEZE.json").read_text(encoding="utf-8"))
    if freeze.get("status") != "PASS" or freeze.get("run_id") != RUN_ID:
        raise RuntimeError("implementation freeze is invalid")
    for entry in freeze["source_files"]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen source drift: {entry['path']}")
    return freeze, {str(entry["path"]): str(entry["sha256"]) for entry in freeze["source_files"]}


def _load_data():
    if str(BRANCH) not in sys.path:
        sys.path.insert(0, str(BRANCH))
    from presentation03_data import load_raw_panel
    return load_raw_panel(COLLECTION / "RAW-PREDICTORS.bin")


def _load_task_mapping() -> tuple[dict[int, int], dict[str, Any]]:
    manifest = json.loads((TASK_DIR / "TASK-BANK-MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("block_ids") != list(BLOCKS) or manifest.get("block_count") != 12:
        raise RuntimeError("task manifest does not match frozen block identity")
    mapping = {int(row["block_id"]): int(row["assignment_index"]) for row in manifest["blocks"]}
    if set(mapping) != set(BLOCKS):
        raise RuntimeError("invalid task assignment map")
    if any(list(mapping.values()).count(index) != 2 for index in range(6)):
        raise RuntimeError("assignment map does not have exactly two blocks per assignment")
    return mapping, manifest


def _row_digest(keys: list[bytes], *, as_set: bool) -> str:
    selected = sorted(keys) if as_set else keys
    digest = hashlib.sha256(b"F4-PRESENTATION-03/TRAINING-ROW-KEYS-v1\0")
    for key in selected:
        if len(key) != 18:
            raise RuntimeError("unexpected training row key width")
        digest.update(key)
    return digest.hexdigest()


def _labels_for_fold(keys: list[bytes], heldout: int) -> tuple[list[int], dict[str, int], str]:
    from presentation03_data import load_training_labels
    labels = load_training_labels(keys, heldout, COLLECTION / "RAW-SCORING-TRUTH.bin")
    train_positions = [index for index, key in enumerate(keys) if struct.unpack_from("<Q", key, 2)[0] != heldout]
    targets = [int(labels[index]) for index in train_positions]
    positive = sum(value == 1 for value in targets)
    negative = len(targets) - positive
    digest = hashlib.sha256(b"F4-PRESENTATION-03/TRAINING-LABELS-v1\0")
    for index in train_positions:
        digest.update(keys[index])
        digest.update(bytes((int(labels[index]),)))
    return train_positions, {"positive": positive, "negative": negative}, digest.hexdigest()


def _write_csv_new(path: Path, rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIT_HEADER, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    raw = stream.getvalue().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    return raw


def prepare() -> None:
    freeze, source_hashes = _verify_sources()
    collection_receipt = json.loads((RUN / "COLLECTION-RECEIPT.json").read_text(encoding="utf-8"))
    if collection_receipt.get("status") != "PASS" or collection_receipt.get("run_id") != RUN_ID:
        raise RuntimeError("native collection is not PASS")
    for path, key in ((COLLECTION / "RAW-PREDICTORS.bin", "predictor_sha256"), (COLLECTION / "RAW-SCORING-TRUTH.bin", "truth_sha256")):
        if sha_file(path) != collection_receipt.get(key):
            raise RuntimeError(f"collection input hash mismatch: {path.name}")
    task_assignment, task_manifest = _load_task_mapping()
    data = _load_data()
    if len(data.keys) != int(collection_receipt["row_count"]):
        raise RuntimeError("raw predictor count differs from collection receipt")
    from presentation03_data import normalized_folds, shared_stream_hashes
    normalizations = normalized_folds(data)
    initializer_manifest_path = BRANCH / "implementation-artifacts" / "INITIALIZER-MANIFEST.json"
    initializer = json.loads(initializer_manifest_path.read_text(encoding="utf-8"))
    if initializer.get("initializer_cell_count") != 144 or initializer.get("task_ids_or_seeds_used") is not False:
        raise RuntimeError("task-free initializer authority mismatch")
    initializer_by_key = {(int(cell["fold_index"]), int(cell["replicate_index"]), str(cell["arm"])): cell for cell in initializer["cells"]}
    if len(initializer_by_key) != 144:
        raise RuntimeError("initializer manifest grid is incomplete")
    for cell in initializer["cells"]:
        path = BRANCH / "implementation-artifacts" / Path(cell["relative_path"])
        if not path.is_file() or path.stat().st_size != int(cell["file_bytes"]) or sha_file(path) != cell["file_sha256"]:
            raise RuntimeError(f"initializer bundle drift: {cell['fit_key']}")

    run_init = RUN / "initial-tensors"
    norm_dir = RUN / "normalizations"
    for path in (run_init, norm_dir):
        if path.exists():
            raise RuntimeError(f"fit surface output already exists: {path.name}")
        path.mkdir(parents=True, exist_ok=False)

    support_rows: list[dict[str, Any]] = []
    fit_rows: list[dict[str, Any]] = []
    normalization_records: list[dict[str, Any]] = []
    for fold, heldout in enumerate(BLOCKS):
        train_mask = data.blocks != heldout
        held_mask = ~train_mask
        norm = normalizations[fold]
        norm_path = norm_dir / f"fold-{fold:02d}.bin"
        norm_path.write_bytes(norm.payload)
        norm_sha = sha_file(norm_path)
        hashes = shared_stream_hashes(data.keys, norm.base, norm.tuples)
        keys_train = [key for key, keep in zip(data.keys, train_mask, strict=True) if keep]
        keys_held = [key for key, keep in zip(data.keys, held_mask, strict=True) if keep]
        train_positions, counts, label_sha = _labels_for_fold(data.keys, heldout)
        if len(train_positions) != len(keys_train):
            raise RuntimeError("training label positions do not match row mask")
        support_rows.append({
            "fold_index": fold,
            "heldout_block": heldout,
            "heldout_assignment_index": task_assignment[heldout],
            "training_row_count": len(keys_train),
            "heldout_row_count": len(keys_held),
            "training_positive_count": counts["positive"],
            "training_negative_count": counts["negative"],
            "training_row_set_sha256": _row_digest(keys_train, as_set=True),
            "training_order_sha256": _row_digest(keys_train, as_set=False),
            "training_labels_sha256": label_sha,
            "status": "PASS" if keys_train and counts["positive"] and counts["negative"] else "STOP_DEGENERATE_TRAINING_FOLD",
        })
        normalization_records.append({
            "fold_index": fold,
            "heldout_block": heldout,
            "normalization_sha256": norm.sha256,
            "normalization_file_sha256": norm_sha,
            "base_stream_sha256": hashes["base"],
            "normalized_tuple_stream_sha256": hashes["tuples"],
            "paired_source_input_sha256": hashes["paired"],
            "training_rows": len(keys_train),
        })
        if not keys_train or counts["positive"] == 0 or counts["negative"] == 0:
            continue
        for replicate in REPLICATES:
            for arm in ARMS:
                cell = initializer_by_key[(fold, replicate, arm)]
                fit_id = f"{arm}-H{heldout}-I{replicate}"
                source_bundle = BRANCH / "implementation-artifacts" / Path(cell["relative_path"])
                initial_rel = f"initial-tensors/{fit_id}.bin"
                initial_path = RUN / initial_rel
                shutil.copyfile(source_bundle, initial_path)
                fit_rows.append({
                    "fit_id": fit_id,
                    "arm": arm,
                    "fold_index": fold,
                    "heldout_block": heldout,
                    "assignment_index": task_assignment[heldout],
                    "replicate_index": replicate,
                    "train_rows": len(keys_train),
                    "heldout_rows": len(keys_held),
                    "train_positive_count": counts["positive"],
                    "train_negative_count": counts["negative"],
                    "training_row_set_sha256": _row_digest(keys_train, as_set=True),
                    "training_order_sha256": _row_digest(keys_train, as_set=False),
                    "training_labels_sha256": label_sha,
                    "heldout_row_sha256": _row_digest(keys_held, as_set=False),
                    "normalization_sha256": norm.sha256,
                    "normalization_file_sha256": norm_sha,
                    "base_stream_sha256": hashes["base"],
                    "normalized_tuple_stream_sha256": hashes["tuples"],
                    "paired_source_input_sha256": hashes["paired"],
                    "initializer_manifest_sha256": sha_file(initializer_manifest_path),
                    "initial_tensor_path": initial_rel,
                    "initial_tensor_file_sha256": sha_file(initial_path),
                    "initial_tensor_sha256": cell["tensor_sha256"],
                    "parameter_count": cell["parameter_count"],
                    "expected_update_count": 200 * ((len(keys_train) + 2047) // 2048),
                    "prediction_path": f"predictions/{fit_id}.bin",
                    "final_tensor_path": f"final-tensors/{fit_id}.bin",
                    "training_trace_path": f"training-traces/{fit_id}.csv",
                    "checkpoint_tensor_dir": f"checkpoint-tensors/{fit_id}",
                    "heldout_state_path": f"heldout-state/{fit_id}.npz",
                    "analysis_source_sha256": source_hashes["experiments/fly-reach-03/f4-presentation-03/analyze_results.py"],
                    "integrity_source_sha256": source_hashes["experiments/fly-reach-03/f4-presentation-03/verify_integrity.py"],
                    "runner_source_sha256": source_hashes["experiments/fly-reach-03/f4-presentation-03/run_fits.py"],
                })

    support_status = "PASS" if len(support_rows) == 12 and all(row["status"] == "PASS" for row in support_rows) else "STOP_DEGENERATE_TRAINING_FOLD"
    support_receipt = {
        "schema": "F4-PRESENTATION-03-training-support-receipt-v1",
        "status": support_status,
        "run_id": RUN_ID,
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "collection_receipt_sha256": sha_file(RUN / "COLLECTION-RECEIPT.json"),
        "fold_count": len(support_rows),
        "heldout_support_used_to_change_execution": False,
        "folds": support_rows,
    }
    write_new(RUN / "TRAINING-SUPPORT-RECEIPT.json", support_receipt)
    if support_status != "PASS":
        raise RuntimeError("STOP_DEGENERATE_TRAINING_FOLD; no fit manifest or fits created")
    if len(fit_rows) != 144:
        raise RuntimeError(f"fit surface cardinality changed: {len(fit_rows)}")

    csv_raw = _write_csv_new(RUN / "FIT-MANIFEST.csv", fit_rows)
    line_hashes: dict[str, str] = {}
    lines = csv_raw.splitlines(keepends=True)
    for line, row in zip(lines[1:], fit_rows, strict=True):
        line_hashes[row["fit_id"]] = sha_bytes(line)
    write_new(RUN / "FIT-MANIFEST-ROW-HASHES.json", {
        "schema": "F4-PRESENTATION-03-fit-row-hashes-v1",
        "manifest_sha256": sha_bytes(csv_raw),
        "row_count": len(line_hashes),
        "rows": line_hashes,
    })
    write_new(RUN / "NORMALIZATION-MANIFEST.json", {
        "schema": "F4-PRESENTATION-03-normalization-manifest-v1",
        "fold_count": len(normalization_records),
        "folds": normalization_records,
    })
    prefit = {
        "schema": "F4-PRESENTATION-03-fit-prefit-receipt-v1",
        "status": "PASS",
        "run_id": RUN_ID,
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "collection_receipt_sha256": sha_file(RUN / "COLLECTION-RECEIPT.json"),
        "training_support_receipt_sha256": sha_file(RUN / "TRAINING-SUPPORT-RECEIPT.json"),
        "initializer_manifest_sha256": sha_file(initializer_manifest_path),
        "fit_manifest_sha256": sha_bytes(csv_raw),
        "fit_count": len(fit_rows),
        "arms": {arm: sum(row["arm"] == arm for row in fit_rows) for arm in ARMS},
        "normalization_manifest_sha256": sha_file(RUN / "NORMALIZATION-MANIFEST.json"),
        "shared_input_hashes_identical_across_arms": True,
        "training_truth_scope": "only non-heldout Y values were read; no heldout score fields were read",
        "heldout_support_used_to_change_execution": False,
        "fits_executed": False,
    }
    write_new(RUN / "FIT-PREFIT-RECEIPT.json", prefit)
    print(json.dumps({"status": "PASS", "fit_count": len(fit_rows), "training_folds": len(support_rows), "fits_executed": False}, sort_keys=True))


if __name__ == "__main__":
    prepare()
