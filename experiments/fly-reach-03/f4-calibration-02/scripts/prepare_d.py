from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]
SYMMETRY_SCRIPTS = STUDY / "f4-symmetry-03" / "scripts"
sys.path.insert(0, str(SYMMETRY_SCRIPTS))
sys.path.insert(0, str(STUDY / "scripts"))
from common import (  # noqa: E402
    normalize_f32, read_predictors, read_json, require, sha_bytes, sha_file,
    sidecar, sorted_tuples, training_hashes, write_json, write_matrix,
)
from f4_symmetry_01_model import Encoder, tensor_hash  # noqa: E402


def _write_normalization(path: Path, holdout: int, a_mean: np.ndarray, a_scale: np.ndarray,
                         rel_mean: np.ndarray, rel_scale: np.ndarray) -> str:
    payload = b"".join(np.asarray(x, dtype="<f4").tobytes() for x in (a_mean, a_scale, rel_mean, rel_scale))
    require(len(payload) == (66 + 66 + 3 + 3) * 4, "normalization payload width changed")
    raw = b"F4SYM03NORMv1\0\0\0" + struct.pack("<IQI", 1, holdout, len(payload)) + payload
    require(len(raw) == 584, "normalization artifact length changed")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return sha_bytes(raw)


def _row_digest(row: dict[str, object], field_order: tuple[str, ...]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([row[name] for name in field_order])
    return sha_bytes(buffer.getvalue().encode("utf-8"))


def prepare(run: Path) -> None:
    task_manifest = read_json(run / "task-bank" / "TASK-BANK-MANIFEST.json")
    blocks = [int(x) for x in task_manifest["accepted_block_ids"]]
    require(len(blocks) == 12 and blocks == sorted(blocks), "frozen task block list invalid")
    collection = run / "collection-staging"
    data = read_predictors(collection / "RAW-PREDICTORS.bin", collection / "RAW-SCORING-TRUTH.bin", blocks)
    present = set(int(x) for x in data.blocks)
    require(present.issubset(set(blocks)), "U-star rows contain an unaccepted block")
    (run / "prepared-inputs").mkdir()
    (run / "normalization").mkdir()

    raw_d = sorted_tuples(data.tuples)
    fit_rows: list[dict[str, object]] = []
    fold_receipts: list[dict[str, object]] = []
    for fold_index, holdout in enumerate(blocks):
        train_mask = data.blocks != holdout
        held_mask = ~train_mask
        a_norm, a_mean, a_scale = normalize_f32(data.a, train_mask)
        rel = np.stack((data.tuples["delta"], data.tuples["incidence_delta"], data.tuples["role_delta"]), axis=2).astype(np.float32)
        rel_flat = rel.reshape(data.count * 4, 3)
        rel_train = np.repeat(train_mask, 4)
        _, rel_mean, rel_scale = normalize_f32(rel_flat, rel_train)
        d_side = sidecar(raw_d, rel_mean, rel_scale)
        matrix = np.concatenate((a_norm, d_side), axis=1).astype(np.float32)
        require(matrix.shape == (data.count, 90) and np.isfinite(matrix).all(), "D input shape/value mismatch")

        normalization_path = run / "normalization" / f"NORMALIZATION-{holdout}.bin"
        normalization_hash = _write_normalization(normalization_path, holdout, a_mean, a_scale, rel_mean, rel_scale)
        train_key_hash, train_order_hash = training_hashes(data.keys, train_mask)
        fit_id = f"D-H{holdout}"
        feature_hash = write_matrix(run / "prepared-inputs" / f"{fit_id}.bin", matrix)
        initial_hash = tensor_hash(Encoder(90, fold_index).values)
        row = {
            "fit_id": fit_id, "arm": "D", "holdout_block": holdout,
            "input_width": 90, "train_rows": int(train_mask.sum()), "heldout_rows": int(held_mask.sum()),
            "feature_hash": feature_hash, "training_row_hash": train_key_hash,
            "training_order_hash": train_order_hash, "normalization_hash": normalization_hash,
            "initial_tensor_hash": initial_hash,
            "expected_prediction_path": f"heldout-predictions/{fit_id}.bin",
        }
        fit_rows.append(row)
        fold_receipts.append({
            "holdout_block": holdout,
            "training_rows": int(train_mask.sum()), "heldout_rows": int(held_mask.sum()),
            "normalization_sha256": normalization_hash,
            "a_mean_sha256": sha_bytes(a_mean.astype("<f4").tobytes()),
            "a_scale_sha256": sha_bytes(a_scale.astype("<f4").tobytes()),
            "rel_mean_sha256": sha_bytes(rel_mean.astype("<f4").tobytes()),
            "rel_scale_sha256": sha_bytes(rel_scale.astype("<f4").tobytes()),
            "fit_id": fit_id, "feature_hash": feature_hash,
            "initial_tensor_hash": initial_hash,
        })

    fields = (
        "fit_id", "arm", "holdout_block", "input_width", "train_rows", "heldout_rows",
        "feature_hash", "training_row_hash", "training_order_hash", "normalization_hash",
        "initial_tensor_hash", "expected_prediction_path",
    )
    manifest_path = run / "FIT-MANIFEST.csv"
    with manifest_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(fit_rows)
    row_hashes = {row["fit_id"]: _row_digest(row, fields) for row in fit_rows}
    manifest_hash = sha_file(manifest_path)
    write_json(run / "FIT-MANIFEST-ROW-HASHES.json", {
        "schema": "F4-CALIBRATION-02-fit-row-hashes-v1",
        "order": [row["fit_id"] for row in fit_rows], "rows": row_hashes,
        "manifest_sha256": manifest_hash,
    })
    common = {
        "fit_count": len(fit_rows), "row_count": data.count,
        "block_ids": blocks, "empty_Ustar_block_ids": [block for block in blocks if block not in present],
        "truth_values_opened": False, "folds": fold_receipts,
    }
    write_json(run / "PRE-FIT-GATES.json", {
        "schema": "F4-CALIBRATION-02-prefit-gates-v1", "status": "PASS",
        "qualification_only": True, **common,
    })
    write_json(run / "FIT-PREPARATION-RECEIPT.json", {
        "schema": "F4-CALIBRATION-02-fit-preparation-v1", "status": "PASS",
        "manifest_sha256": manifest_hash, "preparation_script_sha256": sha_file(Path(__file__)),
        "input_builder_semantics": "frozen SYMMETRY-03 D recipe; 12-block orchestration only",
        **common,
    })
    print(json.dumps({"status": "PREFIT_PASS", "fit_count": len(fit_rows), "rows": data.count,
                      "empty_blocks": [block for block in blocks if block not in present],
                      "truth_values_opened": False}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    prepare(parser.parse_args().run.resolve())
