"""Build fold normalizers and verify byte-identical D/S source streams."""
from __future__ import annotations

import hashlib
import json
import mmap
import os
import struct
import sys
from pathlib import Path


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
for _name, _value in THREAD_ENV.items():
    os.environ[_name] = _value

import numpy as np


REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT1"
RAW_DIR = RUN / "native-collection"
INPUT_PATH = RAW_DIR / "RAW-PREDICTORS.bin"
TRUTH_PATH = RAW_DIR / "RAW-SCORING-TRUTH.bin"
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
BLOCK_IDS = tuple(range(306000, 306012))
NORMSET_MAGIC = b"F4INV01NORMSET01"

PARENT_SCRIPTS = STUDY / "scripts"
IMPL = STUDY / "f4-invariant-01-impl-v2"
if str(PARENT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PARENT_SCRIPTS))
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

from f4_invariant_01_inputs import normalize_fold_inputs, shared_stream_hashes  # noqa: E402


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_new(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def load_raw_inputs() -> tuple[list[bytes], np.ndarray, np.ndarray, np.ndarray]:
    raw = INPUT_PATH.open("rb")
    mapping = mmap.mmap(raw.fileno(), 0, access=mmap.ACCESS_READ)
    try:
        if mapping[:16] != INPUT_MAGIC or len(mapping) < 32:
            raise SystemExit("STOP_INPUT_MAGIC")
        version, width, count = struct.unpack_from("<IIQ", mapping, 16)
        if version != 1 or width != INPUT_WIDTH or len(mapping) != 32 + count * INPUT_WIDTH:
            raise SystemExit("STOP_INPUT_HEADER")
        keys_matrix = np.ndarray((count, 18), dtype="u1", buffer=mapping, offset=32, strides=(INPUT_WIDTH, 1)).copy()
        base = np.ndarray((count, 66), dtype="<f4", buffer=mapping, offset=50, strides=(INPUT_WIDTH, 4)).copy()
        tuple_dtype = np.dtype(
            [("incidence", "u1"), ("role", "i1"), ("incidence_role", "i1"),
             ("delta", "<f4"), ("incidence_delta", "<f4"), ("role_delta", "<f4")],
            align=False,
        )
        packed = np.ndarray((count, 4), dtype=tuple_dtype, buffer=mapping, offset=314, strides=(INPUT_WIDTH, 15)).copy()
    finally:
        mapping.close()
        raw.close()

    tuples = np.empty((count, 4, 6), dtype=np.float32)
    tuples[:, :, 0] = packed["incidence"].astype(np.float32)
    tuples[:, :, 1] = packed["role"].astype(np.float32)
    tuples[:, :, 2] = packed["incidence_role"].astype(np.float32)
    tuples[:, :, 3] = packed["delta"]
    tuples[:, :, 4] = packed["incidence_delta"]
    tuples[:, :, 5] = packed["role_delta"]
    keys = [bytes(row) for row in keys_matrix]
    if len(set(keys)) != count:
        raise SystemExit("STOP_DUPLICATE_INPUT_ROW_KEY")
    blocks = np.fromiter((struct.unpack_from("<Q", key, 2)[0] for key in keys), dtype=np.uint64, count=count)
    if set(int(value) for value in blocks) != set(BLOCK_IDS):
        raise SystemExit("STOP_INPUT_BLOCK_COVERAGE")
    if not np.isfinite(base).all() or not np.isfinite(tuples).all():
        raise SystemExit("STOP_NONFINITE_RAW_INPUT")
    return keys, blocks, base, tuples


def main() -> None:
    if os.environ.get("OPENBLAS_NUM_THREADS") != "1" or os.environ.get("OMP_NUM_THREADS") != "1":
        raise SystemExit("STOP_NUMERICAL_THREAD_POLICY")
    collection = json.loads((RUN / "COLLECTION-RECEIPT.json").read_text(encoding="utf-8"))
    if collection.get("status") != "PASS" or collection.get("comparative_outcomes_opened") is not False:
        raise SystemExit("STOP_COLLECTION_NOT_CLOSED")
    if sha_file(INPUT_PATH) != collection.get("predictor_file_sha256") or sha_file(TRUTH_PATH) != collection.get("truth_file_sha256"):
        raise SystemExit("STOP_RAW_SURFACE_DRIFT")
    output_json = RUN / "SHARED-INPUT-RECONCILIATION.json"
    output_norm = RUN / "FOLD-NORMALIZATION-PAYLOADS.bin"
    if output_json.exists() or output_norm.exists() or (RUN / "FIT-MANIFEST.csv").exists():
        raise SystemExit("STOP_RECONCILIATION_OUTPUT_EXISTS")

    keys, blocks, base_raw, tuples_raw = load_raw_inputs()
    fold_records = []
    norm_payloads = bytearray()
    for fold_index, holdout in enumerate(BLOCK_IDS):
        train_mask = blocks != np.uint64(holdout)
        normalized = normalize_fold_inputs(base_raw, tuples_raw, train_mask, fold_index)
        hashes = shared_stream_hashes(keys, normalized.base, normalized.tuples)
        norm_payloads.extend(normalized.payload)
        fold_records.append({
            "fold_index": fold_index,
            "holdout_block": holdout,
            "normalization_sha256": normalized.sha256,
            "base_stream_sha256": hashes["base"],
            "normalized_tuple_stream_sha256": hashes["tuples"],
            "paired_source_input_sha256": hashes["paired"],
            "arm_inputs": {"D": dict(hashes), "S": dict(hashes)},
            "d_s_hashes_identical": True,
            "training_rows": int(train_mask.sum()),
            "heldout_rows": int((~train_mask).sum()),
        })

    header = NORMSET_MAGIC + struct.pack("<IIII", 1, len(BLOCK_IDS), 576, 0)
    if len(header) != 32 or len(norm_payloads) != len(BLOCK_IDS) * 576:
        raise SystemExit("STOP_NORMALIZATION_PAYLOAD_LAYOUT")
    with output_norm.open("xb") as stream:
        stream.write(header)
        stream.write(norm_payloads)
        stream.flush()
        os.fsync(stream.fileno())

    reconciliation = {
        "schema": "F4-INVARIANT-01-COLLECT1-shared-input-reconciliation-v1",
        "status": "PASS",
        "run_id": "F4-INVARIANT-01-COLLECT1",
        "raw_predictor_sha256": sha_file(INPUT_PATH),
        "raw_scoring_truth_sha256": sha_file(TRUTH_PATH),
        "row_count": len(keys),
        "row_key_order_sha256": sha_bytes(b"".join(keys)),
        "normalized_population": "all native-collected Ustar rows in frozen global collector order; no label or score read during normalization",
        "fold_count": len(fold_records),
        "folds": fold_records,
        "normalization_payloads_path": "FOLD-NORMALIZATION-PAYLOADS.bin",
        "normalization_payloads_sha256": sha_file(output_norm),
        "normalization_payload_bytes": output_norm.stat().st_size,
        "d_s_common_input_hashes_match_all_folds": all(fold["d_s_hashes_identical"] for fold in fold_records),
        "training_labels_or_scoring_truth_read": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "qualification_only": True,
    }
    raw = write_new(output_json, reconciliation)
    seal = {
        "schema": "F4-INVARIANT-01-COLLECT1-shared-input-reconciliation-seal-v1",
        "status": "PASS",
        "reconciliation_file_sha256": sha_bytes(raw),
        "normalization_payloads_sha256": sha_file(output_norm),
        "fold_count": len(fold_records),
        "d_s_hash_mismatches": 0,
    }
    write_new(RUN / "SHARED-INPUT-RECONCILIATION-SEAL.json", seal)
    print(json.dumps({"status": "PASS", "rows": len(keys), "folds": len(fold_records), "fit_manifest_created": False}, sort_keys=True))


if __name__ == "__main__":
    main()
