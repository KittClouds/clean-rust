"""Fold-normalize the frozen C/D inputs and declare all 16 fits."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np

from common import (
    ARMS, INPUT_WIDTH, PATTERNS, REPO, RawData, normalize_f32, read_predictors,
    read_json, require, sha_bytes, sha_file, sidecar, sorted_tuples, training_hashes,
    tuple_bytes, write_json, write_matrix,
)

OLD_SCRIPTS = REPO / "experiments/fly-reach-03/scripts"
sys.path.insert(0, str(OLD_SCRIPTS))
from f4_symmetry_01_model import Encoder, tensor_hash  # noqa: E402


def _normalized_tuple_multisets(tuples: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> list[tuple[bytes, ...]]:
    result: list[tuple[bytes, ...]] = []
    for row in tuples:
        items = []
        for item in row:
            values = [np.float32((item[name] - mean[j]) / scale[j]) for j, name in enumerate(("delta", "incidence_delta", "role_delta"))]
            items.append(struct.pack("<Bbbfff", int(item["incidence"]), int(item["role"]), int(item["incidence_role"]), *(float(x) for x in values)))
        result.append(tuple(sorted(items)))
    return result


def _write_normalization(path: Path, holdout: int, a_mean: np.ndarray, a_scale: np.ndarray, rel_mean: np.ndarray, rel_scale: np.ndarray) -> str:
    payload = b"".join(np.asarray(x, dtype="<f4").tobytes() for x in (a_mean, a_scale, rel_mean, rel_scale))
    require(len(payload) == (66 + 66 + 3 + 3) * 4, "normalization payload width changed")
    raw = b"F4SYM03NORMv1\0\0\0" + struct.pack("<IQI", 1, holdout, len(payload)) + payload
    require(len(raw) == 584, "normalization artifact length changed")
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
    return sha_bytes(raw)


def prepare(run: Path, task_run: Path) -> None:
    manifest = read_json(task_run / "TASK-BANK-MANIFEST.json")
    blocks = [int(x) for x in manifest["accepted_block_ids"]]
    require(len(blocks) == 8 and blocks == sorted(blocks), "task bank block list invalid")
    data = read_predictors(run / "RAW-PREDICTORS.bin", run / "RAW-SCORING-TRUTH.bin", blocks)
    require(data.count > 0, "native collection has no eligible common rows")
    present_blocks = set(int(x) for x in data.blocks)
    require(present_blocks.issubset(set(blocks)), "U* rows contain an unaccepted block")
    empty_blocks = [block for block in blocks if block not in present_blocks]
    (run / "prepared-inputs").mkdir()
    (run / "normalization").mkdir()
    fit_rows: list[dict[str, object]] = []
    fold_receipts: list[dict[str, object]] = []
    raw_d = sorted_tuples(data.tuples)
    raw_multisets_equal = all(
        tuple(sorted(tuple_bytes(item) for item in row)) == tuple(sorted(tuple_bytes(item) for item in drow))
        for row, drow in zip(data.tuples, raw_d, strict=True)
    )
    require(raw_multisets_equal, "STOP_CANONICAL_SIDECAR_VALUE_DRIFT before normalization")
    for fold_index, holdout in enumerate(blocks):
        train_mask = data.blocks != holdout
        held_mask = ~train_mask
        a_norm, a_mean, a_scale = normalize_f32(data.a, train_mask)
        rel = np.stack((data.tuples["delta"], data.tuples["incidence_delta"], data.tuples["role_delta"]), axis=2).astype(np.float32)
        rel_flat = rel.reshape(data.count * 4, 3)
        rel_train = np.repeat(train_mask, 4)
        _, rel_mean, rel_scale = normalize_f32(rel_flat, rel_train)
        c_side = sidecar(data.tuples, rel_mean, rel_scale)
        d_side = sidecar(raw_d, rel_mean, rel_scale)
        norm_c = _normalized_tuple_multisets(data.tuples, rel_mean, rel_scale)
        norm_d = _normalized_tuple_multisets(raw_d, rel_mean, rel_scale)
        require(norm_c == norm_d, f"STOP_CANONICAL_SIDECAR_VALUE_DRIFT after normalization at {holdout}")
        c_input = np.concatenate((a_norm, c_side), axis=1).astype(np.float32)
        d_input = np.concatenate((a_norm, d_side), axis=1).astype(np.float32)
        require(c_input.shape == d_input.shape == (data.count, 90), "C/D input shape changed")
        norm_path = run / "normalization" / f"NORMALIZATION-{holdout}.bin"
        norm_hash = _write_normalization(norm_path, holdout, a_mean, a_scale, rel_mean, rel_scale)
        train_row_hash, train_order_hash = training_hashes(data.keys, train_mask)
        fold_fit = []
        for arm, matrix in (("C", c_input), ("D", d_input)):
            fit_id = f"{arm}-H{holdout}"
            matrix_path = run / "prepared-inputs" / f"{fit_id}.bin"
            feature_hash = write_matrix(matrix_path, matrix)
            initial_hash = tensor_hash(Encoder(90, fold_index).values)
            row = {
                "fit_id": fit_id, "arm": arm, "holdout_block": holdout,
                "input_width": 90, "train_rows": int(train_mask.sum()), "heldout_rows": int(held_mask.sum()),
                "feature_hash": feature_hash, "training_row_hash": train_row_hash,
                "training_order_hash": train_order_hash, "normalization_hash": norm_hash,
                "initial_tensor_hash": initial_hash,
                "expected_prediction_path": f"heldout-predictions/{fit_id}.bin",
            }
            fit_rows.append(row)
            fold_fit.append({"fit_id": fit_id, "feature_hash": feature_hash, "initial_tensor_hash": initial_hash})
        require(fold_fit[0]["initial_tensor_hash"] == fold_fit[1]["initial_tensor_hash"], f"C/D initialization differs in fold {holdout}")
        fold_receipts.append({
            "holdout_block": holdout, "training_rows": int(train_mask.sum()), "heldout_rows": int(held_mask.sum()),
            "normalization_sha256": norm_hash, "a_mean_sha256": sha_bytes(a_mean.astype("<f4").tobytes()),
            "a_scale_sha256": sha_bytes(a_scale.astype("<f4").tobytes()),
            "rel_mean_sha256": sha_bytes(rel_mean.astype("<f4").tobytes()),
            "rel_scale_sha256": sha_bytes(rel_scale.astype("<f4").tobytes()),
            "c_d_raw_multiset_equal": True, "c_d_normalized_multiset_equal": True,
            "c_d_initial_tensor_equal": True, "fits": fold_fit,
        })

    csv_path = run / "FIT-MANIFEST.csv"
    base_fields = ("fit_id", "arm", "holdout_block", "input_width", "train_rows", "heldout_rows", "feature_hash", "training_row_hash", "training_order_hash", "normalization_hash", "initial_tensor_hash", "expected_prediction_path")
    execution = read_json(run / "EXECUTION-MANIFEST.json")
    source_sha = execution["source_manifest_canonical_sha256"]
    code_sha = sha_file(Path(__file__))
    header = (*base_fields, "contract_sha256", "source_manifest_sha256", "analysis_script_sha256")
    with csv_path.open("x", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        for row in fit_rows:
            full = {**row, "contract_sha256": execution["contract_sha256"], "source_manifest_sha256": source_sha, "analysis_script_sha256": execution["script_hashes"]["analysis.py"]}
            w.writerow(full)
    row_hashes = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            buf = io.StringIO(newline="")
            writer = csv.writer(buf, lineterminator="\n")
            writer.writerow([row[k] for k in header])
            row_hashes[row["fit_id"]] = sha_bytes(buf.getvalue().encode("utf-8"))
    write_json(run / "FIT-MANIFEST-ROW-HASHES.json", {"schema": "F4-SYMMETRY-03-fit-row-hashes-v1", "order": [x["fit_id"] for x in fit_rows], "rows": row_hashes, "manifest_sha256": sha_file(csv_path)})
    write_json(run / "PRE-FIT-GATES.json", {
        "schema": "F4-SYMMETRY-03-prefit-gates-v1", "status": "PASS", "qualification_only": True,
        "fit_count": len(fit_rows), "common_row_count": data.count, "block_ids": blocks,
        "empty_Ustar_block_ids": empty_blocks,
        "raw_C_D_multiset_equal": raw_multisets_equal, "normalized_C_D_multisets_equal": True,
        "paired_initialization_equal": True, "heldout_truth_opened": False,
        "folds": fold_receipts,
    })
    write_json(run / "FIT-PREPARATION-RECEIPT.json", {
        "schema": "F4-SYMMETRY-03-fit-preparation-v1", "status": "PASS", "fit_count": len(fit_rows),
        "row_count": data.count, "manifest_sha256": sha_file(csv_path),
        "empty_Ustar_block_ids": empty_blocks,
        "preparation_script_sha256": code_sha, "truth_values_opened": False,
        "folds": fold_receipts,
    })
    print(json.dumps({"status": "PREFIT_PASS", "fit_count": len(fit_rows), "rows": data.count, "truth_values_opened": False}, sort_keys=True))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--task-run", type=Path, required=True)
    a = p.parse_args()
    prepare(a.run.resolve(), a.task_run.resolve())
