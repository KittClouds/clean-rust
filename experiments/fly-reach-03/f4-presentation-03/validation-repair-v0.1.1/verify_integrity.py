"""Independent pre-analysis integrity audit for the locked 144-fit surface."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
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

import numpy as np

BRANCH = Path(__file__).resolve().parent.parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
SUPPORT_RECEIPT = STUDY / "runs" / "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1" / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json"
TASK_DIR = RUN / "task-bank"
COLLECTION = RUN / "native-collection"
BLOCKS = tuple(range(309000, 309012))
ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
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
PRED_MAGIC = b"F4PRES03CKPTv1\0\0"
PRED_EPOCHS = (1, 2, 4, 8, 16, 32, 64, 128, 200)
PRED_HEADER_BYTES = 90
PRED_ROW_BYTES = 54
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
NORMALIZATION_DOMAIN = b"F4-INV01-BASE-v1\0"
TUPLE_DOMAIN = b"F4-INV01-TUPLES-v1\0"
PAIRED_DOMAIN = b"F4-INV01-PAIRINPUT-v1\0"


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _verify_source_entry(entry: dict[str, Any], repo: Path = REPO) -> None:
    path = repo / Path(str(entry["path"]))
    if not path.is_file() or path.stat().st_size != int(entry["byte_length"]) or sha_file(path) != entry["sha256"]:
        raise RuntimeError(f"source drift: {entry['path']}")


def _validate_fit_ids(fit_ids: list[str]) -> None:
    expected = [f"{arm}-H{block}-I{replicate}" for block in BLOCKS for replicate in REPLICATES for arm in ARMS]
    if len(fit_ids) != 144 or len(set(fit_ids)) != 144:
        raise RuntimeError("FIT-MANIFEST contains missing or duplicate fit IDs")
    if fit_ids != expected:
        raise RuntimeError("FIT-MANIFEST fit grid/order mismatch")


def _validate_prediction_keys(actual: list[bytes], expected: list[bytes]) -> None:
    if len(actual) != len(set(actual)):
        raise RuntimeError("prediction stream contains duplicate row keys")
    if actual != expected:
        raise RuntimeError("prediction stream row coverage/order mismatch")


def _manifest_line_hash(line: bytes) -> str:
    if not line.endswith(b"\n") or b"\r" in line:
        raise RuntimeError("FIT-MANIFEST row line ending mismatch")
    return sha_bytes(line)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> None:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_sources() -> dict[str, Any]:
    freeze = read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    if freeze.get("status") != "PASS" or freeze.get("run_id") != RUN_ID:
        raise RuntimeError("implementation freeze mismatch")
    source_raw = (RUN / "SOURCE-INPUT-MANIFEST.json").read_bytes()
    if sha_bytes(source_raw) != freeze.get("source_manifest_file_sha256"):
        raise RuntimeError("source-input manifest file hash mismatch")
    source_manifest = json.loads(source_raw)
    if (
        sha_bytes(canonical_json(source_manifest)) != freeze.get("source_manifest_canonical_sha256")
        or source_manifest.get("entries") != freeze.get("source_files")
        or source_manifest.get("run_id") != RUN_ID
    ):
        raise RuntimeError("source-input manifest contents mismatch")
    branch_manifest = BRANCH / "SOURCE-INPUT-MANIFEST.json"
    if not branch_manifest.is_file() or sha_file(branch_manifest) != freeze.get("source_manifest_file_sha256"):
        raise RuntimeError("branch/source-run manifest copies differ")
    for entry in freeze["source_files"]:
        _verify_source_entry(entry)
    return freeze


def _training_label_summary(path: Path, keys: list[bytes], heldout_block: int) -> tuple[int, int, str]:
    """Independently hash/count training labels while skipping heldout payloads."""
    digest = hashlib.sha256(b"F4-PRESENTATION-03/TRAINING-LABELS-v1\0")
    positive = 0
    negative = 0
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32 or header[:16] != TRUTH_MAGIC:
            raise RuntimeError("training label audit truth header mismatch")
        version, width, count = struct.unpack_from("<IIQ", header, 16)
        if (version, width, count) != (1, TRUTH_WIDTH, len(keys)):
            raise RuntimeError("training label audit truth dimensions mismatch")
        for index, expected_key in enumerate(keys):
            key = stream.read(18)
            if key != expected_key:
                raise RuntimeError(f"training label audit row key mismatch at {index}")
            if struct.unpack_from("<Q", key, 2)[0] == heldout_block:
                stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
                continue
            stream.seek(8, os.SEEK_CUR)
            raw_label = stream.read(1)
            if len(raw_label) != 1:
                raise RuntimeError("truncated training target in truth stream")
            label = struct.unpack("b", raw_label)[0]
            if label not in (-1, 1):
                raise RuntimeError(f"invalid training target in truth stream at {index}")
            positive += label == 1
            negative += label == -1
            digest.update(key)
            digest.update(bytes((1 if label == 1 else 0,)))
            stream.seek(12, os.SEEK_CUR)
        if stream.tell() != 32 + len(keys) * TRUTH_WIDTH:
            raise RuntimeError("training label audit ended at the wrong offset")
    return positive, negative, digest.hexdigest()


def _read_predictors_independently(path: Path) -> tuple[list[bytes], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = path.read_bytes()
    if len(raw) < 32 or raw[:16] != INPUT_MAGIC:
        raise RuntimeError("predictor magic/header mismatch")
    version, width, count = struct.unpack_from("<IIQ", raw, 16)
    if (version, width) != (1, INPUT_WIDTH) or len(raw) != 32 + count * INPUT_WIDTH:
        raise RuntimeError("predictor width/count mismatch")
    keys: list[bytes] = []
    blocks = np.empty(count, dtype=np.uint64)
    base = np.empty((count, 66), dtype=np.float32)
    tuples = np.empty((count, 4, 6), dtype=np.float32)
    previous: tuple[int, int, int, int] | None = None
    seen: set[bytes] = set()
    for index in range(count):
        offset = 32 + index * INPUT_WIDTH
        key = raw[offset:offset + 18]
        if len(key) != 18 or key in seen:
            raise RuntimeError(f"duplicate/truncated predictor row key {index}")
        seen.add(key)
        keys.append(key)
        substrate, side = key[0], key[1]
        block, trial, coordinate = struct.unpack_from("<QII", key, 2)
        if substrate > 8 or side > 1 or block not in BLOCKS or trial >= 8192:
            raise RuntimeError(f"predictor row outside frozen domain at {index}")
        blocks[index] = block
        order = (substrate * 2 + side, BLOCKS.index(block), trial, coordinate)
        if previous is not None and order < previous:
            raise RuntimeError(f"predictor row order drift at {index}")
        previous = order
        base[index] = np.frombuffer(raw, dtype="<f4", count=66, offset=offset + 18)
        tuple_offset = offset + 18 + 66 * 4
        for cue in range(4):
            location = tuple_offset + cue * 15
            tuples[index, cue, 0] = raw[location]
            tuples[index, cue, 1] = struct.unpack_from("b", raw, location + 1)[0]
            tuples[index, cue, 2] = struct.unpack_from("b", raw, location + 2)[0]
            tuples[index, cue, 3:] = np.frombuffer(raw, dtype="<f4", count=3, offset=location + 3)
    if not np.isfinite(base).all() or not np.isfinite(tuples).all():
        raise RuntimeError("nonfinite raw predictor values")
    if set(int(value) for value in blocks) != set(BLOCKS):
        raise RuntimeError("predictor stream does not cover all frozen blocks")
    return keys, blocks, base, tuples, np.asarray(count, dtype=np.uint64)


def _truth_keys_only(path: Path, expected: list[bytes]) -> str:
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32 or header[:16] != TRUTH_MAGIC:
            raise RuntimeError("scoring truth header mismatch")
        version, width, count = struct.unpack_from("<IIQ", header, 16)
        if (version, width, count) != (1, TRUTH_WIDTH, len(expected)) or path.stat().st_size != 32 + count * TRUTH_WIDTH:
            raise RuntimeError("scoring truth dimensions mismatch")
        for index, key in enumerate(expected):
            record_key = stream.read(18)
            if record_key != key:
                raise RuntimeError(f"truth/predictor key mismatch at row {index}")
            stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
    if stream.tell() != path.stat().st_size:
        raise RuntimeError("truth key scan ended at wrong offset")
    return sha_file(path)


def _stream_hashes(keys: list[bytes], base: np.ndarray, tuples: np.ndarray) -> dict[str, str]:
    digests = {
        "base": hashlib.sha256(NORMALIZATION_DOMAIN),
        "tuples": hashlib.sha256(TUPLE_DOMAIN),
        "paired": hashlib.sha256(PAIRED_DOMAIN),
    }
    for index, key in enumerate(keys):
        base_raw = np.asarray(base[index], dtype="<f4").copy()
        tuple_raw = np.asarray(tuples[index], dtype="<f4").copy()
        base_raw[base_raw == 0] = 0
        tuple_raw[tuple_raw == 0] = 0
        bb = base_raw.tobytes(order="C")
        tb = tuple_raw.tobytes(order="C")
        digests["base"].update(key + bb)
        digests["tuples"].update(key + tb)
        digests["paired"].update(key + bb + tb)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def _read_manifest() -> tuple[list[dict[str, str]], dict[str, str], str]:
    path = RUN / "FIT-MANIFEST.csv"
    raw = path.read_bytes()
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise RuntimeError("FIT-MANIFEST line ending mismatch")
    lines = raw.splitlines(keepends=True)
    if len(lines) != 145:
        raise RuntimeError("FIT-MANIFEST must contain exactly 144 rows")
    if tuple(lines[0][:-1].decode("utf-8").split(",")) != FIT_HEADER:
        raise RuntimeError("FIT-MANIFEST header mismatch")
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    hashes: dict[str, str] = {}
    for row, line in zip(rows, lines[1:], strict=True):
        if row["fit_id"] in hashes:
            raise RuntimeError("duplicate FIT-MANIFEST fit id")
        hashes[row["fit_id"]] = _manifest_line_hash(line)
    _validate_fit_ids([row["fit_id"] for row in rows])
    if len({tuple(row[key] for key in FIT_HEADER) for row in rows}) != 144:
        raise RuntimeError("duplicate FIT-MANIFEST row")
    return rows, hashes, sha_bytes(raw)


def _scan_tensor(raw: bytes, arm: str) -> None:
    names_shapes = {
        "D": (("w1", (90, 128)), ("b1", (128,)), ("w2", (128, 64)), ("b2", (64,)), ("w3", (64, 1)), ("b3", (1,))),
        "Cphi": (("phi.w", (6, 16)), ("phi.b", (16,)), ("rho1.w", (130, 101)), ("rho1.b", (101,)), ("rho2.w", (101, 64)), ("rho2.b", (64,)), ("rho3.w", (64, 1)), ("rho3.b", (1,))),
        "Cphi_unshared": (("phi.w", (4, 6, 16)), ("phi.b", (4, 16)), ("rho1.w", (130, 101)), ("rho1.b", (101,)), ("rho2.w", (101, 64)), ("rho2.b", (64,)), ("rho3.w", (64, 1)), ("rho3.b", (1,))),
        "Cphi_shuffled": (("phi.w", (6, 16)), ("phi.b", (16,)), ("rho1.w", (130, 101)), ("rho1.b", (101,)), ("rho2.w", (101, 64)), ("rho2.b", (64,)), ("rho3.w", (64, 1)), ("rho3.b", (1,))),
    }
    magic = {"Cphi": b"F4PRES02CPHITENS\0", "Cphi_shuffled": b"F4PRES02CPHITENS\0", "Cphi_unshared": b"F4PRES03UNSHARED\0"}
    offset = len(magic.get(arm, b""))
    if offset and not raw.startswith(magic[arm]):
        raise RuntimeError(f"tensor bundle magic mismatch for {arm}")
    for name, shape in names_shapes[arm]:
        token = name.encode("ascii") + b"\0"
        if raw[offset:offset + len(token)] != token:
            raise RuntimeError(f"tensor name mismatch for {arm}.{name}")
        offset += len(token)
        ndim = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        dims = struct.unpack_from("<" + "I" * ndim, raw, offset)
        offset += 4 * ndim
        if ndim != len(shape) or tuple(dims) != shape:
            raise RuntimeError(f"tensor shape mismatch for {arm}.{name}")
        count = math.prod(shape)
        values = np.frombuffer(raw, dtype="<f4", count=count, offset=offset)
        if not np.isfinite(values).all():
            raise RuntimeError(f"nonfinite tensor {arm}.{name}")
        offset += count * 4
    if offset != len(raw):
        raise RuntimeError(f"tensor bundle has trailing bytes for {arm}")


def _prediction_rows(path: Path, expected: dict[str, Any], expected_keys: list[bytes], expected_row_hash: str) -> tuple[np.ndarray, str]:
    raw = path.read_bytes()
    if len(raw) < PRED_HEADER_BYTES or raw[:16] != PRED_MAGIC:
        raise RuntimeError(f"prediction header/magic mismatch: {path.name}")
    version, block, arm_id, replicate, epoch_count, count = struct.unpack_from("<IQBBHQ", raw, 16)
    row_hash = raw[40:72].hex()
    epochs = struct.unpack_from("<" + "H" * epoch_count, raw, 72) if epoch_count else ()
    if (
        version != 1 or block != int(expected["heldout_block"]) or arm_id != ARMS.index(expected["arm"])
        or replicate != int(expected["replicate_index"]) or epoch_count != len(PRED_EPOCHS)
        or count != len(expected_keys) or row_hash != expected_row_hash or epochs != PRED_EPOCHS
        or len(raw) != PRED_HEADER_BYTES + count * PRED_ROW_BYTES
    ):
        raise RuntimeError(f"prediction identity/count/header mismatch: {path.name}")
    actual_keys = [raw[PRED_HEADER_BYTES + index * PRED_ROW_BYTES:PRED_HEADER_BYTES + index * PRED_ROW_BYTES + 18] for index in range(count)]
    _validate_prediction_keys(actual_keys, expected_keys)
    logits = np.empty((epoch_count, count), dtype=np.float32)
    for index, key in enumerate(expected_keys):
        offset = PRED_HEADER_BYTES + index * PRED_ROW_BYTES
        logits[:, index] = np.frombuffer(raw, dtype="<f4", count=epoch_count, offset=offset + 18)
    if not np.isfinite(logits).all():
        raise RuntimeError(f"nonfinite prediction stream: {path.name}")
    return logits, sha_bytes(raw)


def _verify_task_collection(freeze: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[bytes], np.ndarray, np.ndarray, np.ndarray, str, dict[int, int]]:
    task_manifest = read_json(TASK_DIR / "TASK-BANK-MANIFEST.json")
    task_payload = TASK_DIR / "training.json"
    task_receipt = read_json(TASK_DIR / "TASK-BANK-RECEIPT.json")
    if task_manifest.get("block_ids") != list(BLOCKS) or task_manifest.get("task_bank_sha256") != sha_file(task_payload):
        raise RuntimeError("task bank hash/grid mismatch")
    if task_receipt.get("status") != "PASS" or task_receipt.get("task_bank_manifest_sha256") != sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"):
        raise RuntimeError("task bank receipt mismatch")
    assignment_counts = {index: 0 for index in range(6)}
    assignment_by_block = {}
    for row in task_manifest.get("blocks", []):
        block = int(row["block_id"])
        index = int(row["assignment_index"])
        assignment_counts[index] += 1
        assignment_by_block[block] = index
    if assignment_counts != {index: 2 for index in range(6)}:
        raise RuntimeError("task assignment balance mismatch")
    collection = read_json(RUN / "COLLECTION-RECEIPT.json")
    predictor_path = COLLECTION / "RAW-PREDICTORS.bin"
    truth_path = COLLECTION / "RAW-SCORING-TRUTH.bin"
    if collection.get("status") != "PASS" or sha_file(predictor_path) != collection.get("predictor_sha256") or sha_file(truth_path) != collection.get("truth_sha256"):
        raise RuntimeError("native collection input hash mismatch")
    keys, blocks, raw_base, raw_tuples, _count = _read_predictors_independently(predictor_path)
    _truth_keys_only(truth_path, keys)
    native = read_json(COLLECTION / "NATIVE-COLLECTION-RECEIPT.json")
    if native.get("status") != "PASS" or native.get("stream_count") != 216 or native.get("block_ids") != list(BLOCKS) or native.get("p_forward_fixture_status") != "PASS":
        raise RuntimeError("native collection receipt integrity mismatch")
    return task_manifest, collection, keys, blocks, raw_base, raw_tuples, sha_file(truth_path), assignment_counts


def run() -> None:
    output = RUN / "INTEGRITY-RECEIPT.json"
    if output.exists():
        raise RuntimeError("integrity receipt already exists; preserve and stop")
    support_context = read_json(SUPPORT_RECEIPT)
    if (support_context.get("status") != "PASS" or support_context.get("assignment_evaluable_count") != 6
        or support_context.get("truth_fields_opened") != ["inclusion_probability_p", "target_polarity_Y"]
        or support_context.get("truth_fields_not_opened") != ["native_delta", "preweight", "reference_value"]):
        raise RuntimeError("support-only truth access context mismatch")
    freeze = _verify_sources()
    prefit = read_json(RUN / "FIT-PREFIT-RECEIPT.json")
    if prefit.get("status") != "PASS" or prefit.get("fit_count") != 144:
        raise RuntimeError("fit preflight receipt does not authorize the locked grid")
    task_manifest, collection, keys, blocks, raw_base, raw_tuples, truth_sha, assignment_counts = _verify_task_collection(freeze)
    if len(keys) != int(collection["row_count"]):
        raise RuntimeError("raw predictor row count differs from collection receipt")

    # Recompute normalization and shared stream hashes using the controlling frozen normalizer.
    sys.path.insert(0, str(STUDY / "f4-invariant-01-impl-v2"))
    from f4_invariant_01_inputs import normalize_fold_inputs
    rows, row_hashes, manifest_sha = _read_manifest()
    if manifest_sha != prefit.get("fit_manifest_sha256"):
        raise RuntimeError("FIT-MANIFEST digest mismatch")
    row_hash_receipt = read_json(RUN / "FIT-MANIFEST-ROW-HASHES.json")
    if row_hash_receipt.get("manifest_sha256") != manifest_sha or row_hash_receipt.get("rows") != row_hashes:
        raise RuntimeError("FIT-MANIFEST row-hash receipt mismatch")
    normal_manifest = read_json(RUN / "NORMALIZATION-MANIFEST.json")
    if normal_manifest.get("fold_count") != 12 or len(normal_manifest.get("folds", [])) != 12:
        raise RuntimeError("normalization manifest grid mismatch")

    norm_by_fold = {}
    shared_by_fold = {}
    train_keys_by_block: dict[int, list[bytes]] = {}
    held_keys_by_block: dict[int, list[bytes]] = {}
    for block in BLOCKS:
        held_keys_by_block[block] = [key for key in keys if struct.unpack_from("<Q", key, 2)[0] == block]
        train_keys_by_block[block] = [key for key in keys if struct.unpack_from("<Q", key, 2)[0] != block]
    for fold, heldout in enumerate(BLOCKS):
        mask = blocks != np.uint64(heldout)
        norm = normalize_fold_inputs(raw_base, raw_tuples, mask, fold)
        norm_path = RUN / "normalizations" / f"fold-{fold:02d}.bin"
        if not norm_path.is_file() or sha_file(norm_path) != rows[fold * 12]["normalization_file_sha256"]:
            raise RuntimeError(f"normalization payload file mismatch for fold {fold}")
        if norm.sha256 != rows[fold * 12]["normalization_sha256"]:
            raise RuntimeError(f"recomputed normalization mismatch for fold {fold}")
        shared_by_fold[fold] = _stream_hashes(keys, norm.base, norm.tuples)
        norm_by_fold[fold] = norm
        for arm in ARMS:
            row = next(item for item in rows if int(item["fold_index"]) == fold and item["arm"] == arm)
            hashes = shared_by_fold[fold]
            if (
                hashes["base"] != row["base_stream_sha256"]
                or hashes["tuples"] != row["normalized_tuple_stream_sha256"]
                or hashes["paired"] != row["paired_source_input_sha256"]
            ):
                raise RuntimeError(f"shared normalized input hash mismatch fold={fold} arm={arm}")

    support = read_json(RUN / "TRAINING-SUPPORT-RECEIPT.json")
    if support.get("status") != "PASS" or len(support.get("folds", [])) != 12:
        raise RuntimeError("training support gate did not pass")
    support_by_block = {int(item["heldout_block"]): item for item in support["folds"]}
    if len(support_by_block) != 12 or set(support_by_block) != set(BLOCKS):
        raise RuntimeError("training support receipt block grid mismatch")
    for heldout in BLOCKS:
        positive, negative, label_hash = _training_label_summary(
            COLLECTION / "RAW-SCORING-TRUTH.bin", keys, heldout
        )
        item = support_by_block[heldout]
        expected_train_keys = train_keys_by_block[heldout]
        expected_set_hash = sha_bytes(
            b"F4-PRESENTATION-03/TRAINING-ROW-KEYS-v1\0" + b"".join(sorted(expected_train_keys))
        )
        expected_order_hash = sha_bytes(
            b"F4-PRESENTATION-03/TRAINING-ROW-KEYS-v1\0" + b"".join(expected_train_keys)
        )
        if (
            positive != int(item["training_positive_count"])
            or negative != int(item["training_negative_count"])
            or label_hash != item["training_labels_sha256"]
            or expected_set_hash != item["training_row_set_sha256"]
            or expected_order_hash != item["training_order_sha256"]
            or positive == 0
            or negative == 0
        ):
            raise RuntimeError(f"independent training-support reconciliation failed for {heldout}")
    for row in rows:
        fold = int(row["fold_index"])
        heldout = int(row["heldout_block"])
        if int(row["assignment_index"]) != next(int(block["assignment_index"]) for block in task_manifest["blocks"] if int(block["block_id"]) == heldout):
            raise RuntimeError(f"assignment/fold mismatch in {row['fit_id']}")
        if row["training_order_sha256"] != sha_bytes(b"F4-PRESENTATION-03/TRAINING-ROW-KEYS-v1\0" + b"".join(train_keys_by_block[heldout])):
            raise RuntimeError(f"training order hash mismatch in {row['fit_id']}")
        if row["training_row_set_sha256"] != sha_bytes(b"F4-PRESENTATION-03/TRAINING-ROW-KEYS-v1\0" + b"".join(sorted(train_keys_by_block[heldout]))):
            raise RuntimeError(f"training row-set hash mismatch in {row['fit_id']}")
        if row["training_labels_sha256"] != support_by_block[heldout]["training_labels_sha256"]:
            raise RuntimeError(f"training label hash mismatch in {row['fit_id']}")
        expected_updates = 200 * ((len(train_keys_by_block[heldout]) + 2047) // 2048)
        if int(row["expected_update_count"]) != expected_updates:
            raise RuntimeError(f"expected optimizer update count mismatch in {row['fit_id']}")
        if row["heldout_row_sha256"] != sha_bytes(b"F4-PRESENTATION-03/TRAINING-ROW-KEYS-v1\0" + b"".join(held_keys_by_block[heldout])):
            raise RuntimeError(f"heldout row hash mismatch in {row['fit_id']}")
        initial = RUN / row["initial_tensor_path"]
        if not initial.is_file() or sha_file(initial) != row["initial_tensor_file_sha256"]:
            raise RuntimeError(f"initial tensor file mismatch in {row['fit_id']}")
        _scan_tensor(initial.read_bytes(), row["arm"])

    fit_receipt_dir = RUN / "fit-receipts"
    receipt_paths = sorted(fit_receipt_dir.glob("*.json"))
    if len(receipt_paths) != 144:
        raise RuntimeError("fit receipt count is not 144")
    lock_path = RUN / "PREDICTION-LOCK.json"
    lock = read_json(lock_path)
    if lock.get("status") != "PASS" or lock.get("fit_count") != 144 or lock.get("fit_manifest_sha256") != manifest_sha:
        raise RuntimeError("prediction lock identity/count mismatch")
    lock_entries = lock.get("prediction_files", [])
    locked_by_id = {entry["fit_id"]: entry for entry in lock_entries}
    if len(lock_entries) != 144 or len(locked_by_id) != 144:
        raise RuntimeError("prediction lock contains missing/duplicate entries")

    expected_file_sets: dict[str, set[str]] = {name: set() for name in ("predictions", "final-tensors", "training-traces", "checkpoint-tensors", "heldout-state", "fit-receipts")}
    fit_hashes: list[dict[str, str]] = []
    prediction_file_hashes: list[dict[str, str]] = []
    for row in rows:
        fit_id = row["fit_id"]
        arm = row["arm"]
        block = int(row["heldout_block"])
        rep = int(row["replicate_index"])
        receipt_path = fit_receipt_dir / f"{fit_id}.json"
        receipt = read_json(receipt_path)
        if (
            receipt.get("fit_id") != fit_id or receipt.get("arm") != arm
            or receipt.get("heldout_block") != block or receipt.get("replicate_index") != rep
            or receipt.get("fold_index") != int(row["fold_index"])
            or receipt.get("assignment_index") != int(row["assignment_index"])
            or receipt.get("parameter_count") != int(row["parameter_count"])
            or receipt.get("training_rows") != int(row["train_rows"])
            or receipt.get("heldout_rows") != int(row["heldout_rows"])
            or receipt.get("initial_tensor_sha256") != row["initial_tensor_sha256"]
        ):
            raise RuntimeError(f"fit receipt identity mismatch in {fit_id}")
        if receipt.get("finite_status") != "PASS" or int(receipt.get("update_count", -1)) != int(row["expected_update_count"]):
            raise RuntimeError(f"fit finite/update audit mismatch in {fit_id}")
        for field in ("normalization_sha256", "base_stream_sha256", "normalized_tuple_stream_sha256", "paired_source_input_sha256"):
            if receipt.get(field) != row[field]:
                raise RuntimeError(f"fit shared-input receipt mismatch in {fit_id}: {field}")
        pred_path = RUN / row["prediction_path"]
        expected_keys = held_keys_by_block[block]
        logits, pred_sha = _prediction_rows(pred_path, row, expected_keys, row_hashes[fit_id])
        locked = locked_by_id.get(fit_id)
        if (
            locked is None or locked.get("prediction_sha256") != pred_sha
            or locked.get("prediction_path") != row["prediction_path"]
            or locked.get("fit_receipt_path") != f"fit-receipts/{fit_id}.json"
            or locked.get("fit_receipt_sha256") != sha_file(receipt_path)
            or locked.get("final_tensor_path") != row["final_tensor_path"]
            or locked.get("final_tensor_sha256") != receipt.get("final_tensor_file_sha256")
        ):
            raise RuntimeError(f"prediction lock mismatch in {fit_id}")
        if receipt.get("prediction_sha256") != pred_sha:
            raise RuntimeError(f"fit receipt prediction hash mismatch in {fit_id}")
        prediction_file_hashes.append({"fit_id": fit_id, "sha256": pred_sha})

        final_path = RUN / row["final_tensor_path"]
        final_raw = final_path.read_bytes()
        _scan_tensor(final_raw, arm)
        if sha_bytes(final_raw) != receipt.get("final_tensor_file_sha256") or sha_bytes(final_raw) != receipt.get("checkpoint_tensor_hashes", {}).get("200"):
            raise RuntimeError(f"final/checkpoint tensor mismatch in {fit_id}")
        trace_path = RUN / row["training_trace_path"]
        trace_raw = trace_path.read_bytes()
        trace_lines = trace_raw.decode("utf-8").splitlines()
        if len(trace_lines) != 201 or receipt.get("training_trace_sha256") != sha_bytes(trace_raw):
            raise RuntimeError(f"training trace count/hash mismatch in {fit_id}")
        trace_header = trace_lines[0].split(",")
        expected_trace_header = ["epoch", "training_bce", "training_balanced_error", "finite_state"] + [
            f"{layer}_gradient_norm_{stat}"
            for layer in ({"D": ("d1", "d2", "d3")}.get(arm, ("phi", "rho1", "rho2", "rho3")))
            for stat in ("mean", "max")
        ]
        if trace_header != expected_trace_header:
            raise RuntimeError(f"training trace header mismatch in {fit_id}")
        for line in trace_lines[1:]:
            values = [float(value) for value in line.split(",")]
            if not all(math.isfinite(value) for value in values):
                raise RuntimeError(f"nonfinite training trace value in {fit_id}")
            if values[3] != 1.0:
                raise RuntimeError(f"training trace finite-state failure in {fit_id}")
        for epoch in PRED_EPOCHS:
            checkpoint = RUN / row["checkpoint_tensor_dir"] / f"epoch-{epoch:03d}.bin"
            raw_tensor = checkpoint.read_bytes()
            _scan_tensor(raw_tensor, arm)
            if sha_bytes(raw_tensor) != receipt.get("checkpoint_tensor_hashes", {}).get(str(epoch)):
                raise RuntimeError(f"checkpoint tensor hash mismatch in {fit_id} epoch {epoch}")
        state_path = RUN / row["heldout_state_path"]
        if sha_file(state_path) != receipt.get("heldout_state_sha256"):
            raise RuntimeError(f"heldout state hash mismatch in {fit_id}")
        with np.load(state_path, allow_pickle=False) as state:
            state_keys = np.asarray(state["row_keys"], dtype=np.uint8)
            expected_key_array = np.frombuffer(b"".join(expected_keys), dtype=np.uint8).reshape(len(expected_keys), 18)
            if state_keys.shape != expected_key_array.shape or not np.array_equal(state_keys, expected_key_array):
                raise RuntimeError(f"heldout state row keys mismatch in {fit_id}")
            state_logits = np.asarray(state["logits"], dtype=np.float32)
            if state_logits.shape != (len(expected_keys),) or state_logits.tobytes() != logits[-1].tobytes():
                raise RuntimeError(f"heldout state logits mismatch in {fit_id}")
            for name in state.files:
                array = np.asarray(state[name])
                if array.dtype.kind == "f" and not np.isfinite(array).all():
                    raise RuntimeError(f"nonfinite heldout state {name} in {fit_id}")
        expected_file_sets["predictions"].add(row["prediction_path"])
        expected_file_sets["final-tensors"].add(row["final_tensor_path"])
        expected_file_sets["training-traces"].add(row["training_trace_path"])
        expected_file_sets["heldout-state"].add(row["heldout_state_path"])
        expected_file_sets["fit-receipts"].add(f"fit-receipts/{fit_id}.json")
        expected_file_sets["checkpoint-tensors"].update(
            f"{row['checkpoint_tensor_dir']}/epoch-{epoch:03d}.bin" for epoch in PRED_EPOCHS
        )
        fit_hashes.append({"fit_id": fit_id, "receipt_sha256": sha_file(receipt_path), "final_tensor_sha256": sha_bytes(final_raw)})

    for directory, expected in expected_file_sets.items():
        actual = {path.relative_to(RUN).as_posix() for path in (RUN / directory).rglob("*") if path.is_file()}
        if actual != expected:
            raise RuntimeError(f"unexpected/missing output files in {directory}")
    arms = {arm: sum(row["arm"] == arm for row in rows) for arm in ARMS}
    if arms != {arm: 36 for arm in ARMS}:
        raise RuntimeError("fit arm counts mismatch")
    receipt = {
        "schema": "F4-PRESENTATION-03-integrity-receipt-v1",
        "status": "PASS",
        "run_id": RUN_ID,
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "collection_receipt_sha256": sha_file(RUN / "COLLECTION-RECEIPT.json"),
        "fit_manifest_sha256": manifest_sha,
        "prediction_lock_sha256": sha_file(lock_path),
        "integrity_source_sha256": sha_file(Path(__file__).resolve()),
        "expected_fit_count": 144,
        "actual_fit_count": len(rows),
        "arm_counts": arms,
        "expected_prediction_count": 144,
        "actual_prediction_count": len(prediction_file_hashes),
        "expected_checkpoint_count": 9 * 144,
        "source_drift_count": 0,
        "missing_duplicate_extra_prediction_count": 0,
        "nonfinite_tensor_or_prediction_count": 0,
        "training_support": "PASS",
        "shared_D_Cphi_input_hashes_recomputed": True,
        "task_assignment_counts": {str(key): value for key, value in assignment_counts.items()},
        "heldout_scoring_truth_state": "TARGET_POLARITY_OPEN_FOR_SUPPORT_ONLY",
        "heldout_scoring_values_opened": True,
        "support_target_access_receipt_sha256": sha_file(SUPPORT_RECEIPT),
        "target_polarity_opened_before_fit": True,
        "support_only_truth_fields_opened": ["inclusion_probability_p", "target_polarity_Y"],
        "comparative_scoring_fields_opened_before_integrity": [],
        "remaining_truth_fields_sealed": ["native_delta", "preweight", "reference_value"],
        "truth_file_sha256": truth_sha,
        "fit_receipt_hashes": fit_hashes,
        "prediction_hashes": prediction_file_hashes,
        "qualification_only": True,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
    }
    write_new(output, receipt)
    print(json.dumps({"status": "PASS", "fits": 144, "predictions": 144, "heldout_scoring_truth": "TARGET_POLARITY_OPEN_FOR_SUPPORT_ONLY"}, sort_keys=True))


if __name__ == "__main__":
    run()
