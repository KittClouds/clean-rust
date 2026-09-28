"""Execute the frozen 144-fit engineering screen without reading held-out truth."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_MAXIMUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np  # noqa: E402

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
TASK_DIR = RUN / "task-bank"
COLLECTION = RUN / "native-collection"
BLOCKS = tuple(range(309000, 309012))
ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
ARM_IDS = {arm: index for index, arm in enumerate(ARMS)}
PRED_MAGIC = b"F4PRES03CKPTv1\0\0"
PRED_EPOCHS = (1, 2, 4, 8, 16, 32, 64, 128, 200)
PRED_HEADER_BYTES = 90
PRED_ROW_BYTES = 18 + 4 * len(PRED_EPOCHS)
TRACE_FIXED = ("epoch", "training_bce", "training_balanced_error", "finite_state")

for _path in (BRANCH, STUDY / "f4-invariant-01-impl-v2", STUDY / "f4-presentation-02-v2", STUDY / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from cphi_model import CPhiEncoder, deserialize_tensors, serialize_tensors, tensor_hash as cphi_hash  # noqa: E402
from f4_invariant_01_model import DEncoder, d_input, tensor_hash as d_hash  # noqa: E402
from presentation03_data import load_raw_panel, load_training_labels, normalized_folds, shared_stream_hashes  # noqa: E402
from presentation03_model import (  # noqa: E402
    CHECKPOINT_EPOCHS, CphiUnsharedEncoder, DTrackedEncoder, cphi_present,
    fit_checkpointed, row_permutations, shuffle_canonical_tuples,
    unshared_tensor_hash,
)

D_NAMES = ("w1", "b1", "w2", "b2", "w3", "b3")
D_SHAPES = ((90, 128), (128,), (128, 64), (64,), (64, 1), (1,))
TRACE_LAYERS = {
    "D": ("d1", "d2", "d3"),
    "Cphi": ("phi", "rho1", "rho2", "rho3"),
    "Cphi_unshared": ("phi", "rho1", "rho2", "rho3"),
    "Cphi_shuffled": ("phi", "rho1", "rho2", "rho3"),
}


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_hashes(freeze: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for entry in freeze["source_files"]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen source drift: {entry['path']}")
        hashes[str(entry["path"])] = str(entry["sha256"])
    return hashes


def _verify_runtime(freeze: dict[str, Any]) -> None:
    runtime = freeze["runtime"]
    if (
        sys.version != runtime.get("python_version")
        or np.__version__ != runtime.get("numpy_version")
        or str(Path(sys.executable).resolve()) != runtime.get("python_executable")
        or sha_file(Path(sys.executable)) != runtime.get("python_executable_sha256")
        or any(os.environ.get(key) != "1" for key in THREAD_ENV)
    ):
        raise RuntimeError("Python/NumPy/thread environment differs from implementation freeze")


def _read_d_bundle(raw: bytes) -> list[np.ndarray]:
    offset = 0
    values = []
    for name, shape in zip(D_NAMES, D_SHAPES, strict=True):
        expected = name.encode("ascii") + b"\0"
        if raw[offset:offset + len(expected)] != expected:
            raise RuntimeError(f"D tensor bundle name mismatch: {name}")
        offset += len(expected)
        ndim = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        dims = struct.unpack_from("<" + "I" * ndim, raw, offset)
        offset += 4 * ndim
        if ndim != len(shape) or tuple(dims) != shape:
            raise RuntimeError(f"D tensor bundle shape mismatch: {name}")
        count = int(np.prod(shape, dtype=np.int64))
        values.append(np.frombuffer(raw, dtype="<f4", count=count, offset=offset).reshape(shape).copy())
        offset += 4 * count
    if offset != len(raw):
        raise RuntimeError("D tensor bundle trailing bytes")
    return values


def _serialize_d(values: list[np.ndarray]) -> bytes:
    parts = []
    for name, shape, value in zip(D_NAMES, D_SHAPES, values, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        if tuple(array.shape) != shape or not np.isfinite(array).all():
            raise RuntimeError(f"invalid final D tensor {name}")
        parts.extend((name.encode("ascii") + b"\0", struct.pack("<I", array.ndim)))
        parts.extend(struct.pack("<I", dim) for dim in shape)
        parts.append(array.tobytes(order="C"))
    return b"".join(parts)


def _read_unshared(raw: bytes) -> list[np.ndarray]:
    from presentation03_model import UNSHARED_TENSOR_NAMES, UNSHARED_TENSOR_SHAPES
    magic = b"F4PRES03UNSHARED\0"
    if not raw.startswith(magic):
        raise RuntimeError("unshared initializer magic mismatch")
    offset = len(magic)
    values = []
    for name, shape in zip(UNSHARED_TENSOR_NAMES, UNSHARED_TENSOR_SHAPES, strict=True):
        token = name.encode("ascii") + b"\0"
        if raw[offset:offset + len(token)] != token:
            raise RuntimeError(f"unshared tensor name mismatch: {name}")
        offset += len(token)
        ndim = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        dims = struct.unpack_from("<" + "I" * ndim, raw, offset)
        offset += 4 * ndim
        if ndim != len(shape) or tuple(dims) != shape:
            raise RuntimeError(f"unshared tensor shape mismatch: {name}")
        count = int(np.prod(shape, dtype=np.int64))
        values.append(np.frombuffer(raw, dtype="<f4", count=count, offset=offset).reshape(shape).copy())
        offset += 4 * count
    if offset != len(raw):
        raise RuntimeError("unshared tensor bundle trailing bytes")
    return values


def _read_initial(path: Path, arm: str) -> list[np.ndarray]:
    raw = path.read_bytes()
    if arm == "D":
        return _read_d_bundle(raw)
    if arm in ("Cphi", "Cphi_shuffled"):
        return deserialize_tensors(raw)
    return _read_unshared(raw)


def _tensor_hash(values: list[np.ndarray], arm: str) -> str:
    if arm == "D":
        return d_hash(values, "D")
    if arm in ("Cphi", "Cphi_shuffled"):
        return cphi_hash(values)
    return unshared_tensor_hash(values)


def _serialize(values: list[np.ndarray], arm: str) -> bytes:
    if arm == "D":
        return _serialize_d(values)
    if arm in ("Cphi", "Cphi_shuffled"):
        return serialize_tensors(values)
    from prepare_initializers import serialize_unshared
    return serialize_unshared(values)


def _predict(arm: str, model: Any, base: np.ndarray, tuples: np.ndarray, presented: np.ndarray) -> np.ndarray:
    if arm == "D":
        result = model.logits(d_input(base, tuples))
    elif arm == "Cphi_unshared":
        result = model.logits(base, tuples, canonical=True)
    else:
        result = model.logits(base, presented, canonical=True)
    output = np.asarray(result, dtype=np.float32)
    if output.shape != (len(base),) or not np.isfinite(output).all():
        raise RuntimeError("held-out logits have invalid shape or nonfinite values")
    return output


def _prediction_bytes(block: int, arm: str, replicate: int, row_hash: str, keys: list[bytes], logits: np.ndarray) -> bytes:
    if len(PRED_MAGIC) != 16 or logits.shape != (len(PRED_EPOCHS), len(keys)):
        raise RuntimeError("checkpoint prediction shape/magic mismatch")
    if any(len(key) != 18 for key in keys) or not np.isfinite(logits).all():
        raise RuntimeError("checkpoint prediction has malformed key/nonfinite logit")
    result = bytearray(PRED_MAGIC)
    result.extend(struct.pack("<IQBBHQ", 1, block, ARM_IDS[arm], replicate, len(PRED_EPOCHS), len(keys)))
    result.extend(bytes.fromhex(row_hash))
    result.extend(struct.pack("<" + "H" * len(PRED_EPOCHS), *PRED_EPOCHS))
    for index, key in enumerate(keys):
        result.extend(key)
        result.extend(np.ascontiguousarray(logits[:, index], dtype="<f4").tobytes())
    if len(result) != PRED_HEADER_BYTES + len(keys) * PRED_ROW_BYTES:
        raise RuntimeError("checkpoint prediction byte length mismatch")
    return bytes(result)


def _trace_bytes(trace: list[dict[str, float]], arm: str) -> bytes:
    header = TRACE_FIXED + tuple(
        f"{layer}_gradient_norm_{stat}"
        for layer in TRACE_LAYERS[arm]
        for stat in ("mean", "max")
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(trace)
    return stream.getvalue().encode("utf-8")


def _heldout_state(arm: str, model: Any, base: np.ndarray, tuples: np.ndarray, keys: list[bytes], presented: np.ndarray, permutation: np.ndarray | None, final_logits: np.ndarray) -> bytes:
    key_array = np.frombuffer(b"".join(keys), dtype=np.uint8).reshape(len(keys), 18).copy()
    arrays: dict[str, np.ndarray] = {"row_keys": key_array, "logits": final_logits.astype(np.float32, copy=False)}
    if arm == "D":
        d_features = d_input(base, tuples)
        _logits, cache = model.forward(d_features)
        arrays["canonical_d_input"] = d_features
        arrays["pre_output_hidden"] = np.asarray(cache[-1], dtype=np.float32)
    elif arm == "Cphi_unshared":
        _logits, cache = model.forward(base, tuples, canonical=False)
        ordered, zphi, phi, rel, a2 = cache[1], cache[2], cache[3], cache[4], cache[-1]
        arrays.update({"ordered_tuples": ordered, "phi_pre_activation": zphi, "phi_outputs": phi,
                       "relational_concat": rel, "pre_output_hidden": a2})
        arrays["role_separation"] = _role_separation(phi)
        arrays["posthoc_sum"] = _left_sum(phi)
    else:
        _logits, cache = model.forward(base, presented, canonical=True)
        ordered, zphi, phi, rel, a2 = cache[1], cache[2], cache[3], cache[4], cache[-1]
        arrays.update({"ordered_or_presented_tuples": ordered, "phi_pre_activation": zphi,
                       "phi_outputs": phi, "relational_concat": rel, "pre_output_hidden": a2})
        arrays["role_separation"] = _role_separation(phi)
        arrays["posthoc_sum"] = _left_sum(phi)
        if permutation is not None:
            arrays["row_permutation"] = permutation
    output = io.BytesIO()
    np.savez(output, **arrays)
    return output.getvalue()


def _role_separation(phi: np.ndarray) -> np.ndarray:
    distances = []
    for left in range(4):
        for right in range(left + 1, 4):
            distances.append(np.linalg.norm(phi[:, left] - phi[:, right], axis=1))
    return np.stack(distances, axis=1).astype(np.float32)


def _left_sum(phi: np.ndarray) -> np.ndarray:
    first = np.add(phi[:, 0], phi[:, 1])
    second = np.add(first, phi[:, 2])
    return np.add(second, phi[:, 3])


def _fit_one(row: dict[str, str], row_hash: str, norm: Any, data: Any, labels_by_block: dict[int, np.ndarray]) -> dict[str, Any]:
    arm = row["arm"]
    fold = int(row["fold_index"])
    block = int(row["heldout_block"])
    replicate = int(row["replicate_index"])
    fit_id = row["fit_id"]
    train_mask = data.blocks != np.uint64(block)
    held_mask = ~train_mask
    train_count = int(train_mask.sum())
    held_count = int(held_mask.sum())
    if train_count != int(row["train_rows"]) or held_count != int(row["heldout_rows"]):
        raise RuntimeError(f"row count changed before {fit_id}")
    shared = shared_stream_hashes(data.keys, norm.base, norm.tuples)
    if (
        norm.sha256 != row["normalization_sha256"]
        or shared["base"] != row["base_stream_sha256"]
        or shared["tuples"] != row["normalized_tuple_stream_sha256"]
        or shared["paired"] != row["paired_source_input_sha256"]
    ):
        raise RuntimeError(f"shared input mismatch before {fit_id}")
    y_full = labels_by_block[block]
    y_train = y_full[train_mask]
    if len(y_train) != train_count or set(np.unique(y_train).tolist()) != {0.0, 1.0}:
        raise RuntimeError(f"training support changed before {fit_id}")
    init_path = RUN / row["initial_tensor_path"]
    init_raw = init_path.read_bytes()
    if sha_bytes(init_raw) != row["initial_tensor_file_sha256"]:
        raise RuntimeError(f"initializer file changed before {fit_id}")
    initial_values = _read_initial(init_path, arm)
    initial_hash = _tensor_hash(initial_values, arm)
    if initial_hash != row["initial_tensor_sha256"]:
        raise RuntimeError(f"initializer tensor hash mismatch before {fit_id}")

    if arm == "D":
        model = DTrackedEncoder(fold, replicate, values=initial_values)
    elif arm == "Cphi_unshared":
        model = CphiUnsharedEncoder(initial_values)
    else:
        model = CPhiEncoder(initial_values)
    x_train = norm.base[train_mask]
    r_train = norm.tuples[train_mask]
    train_keys = [key for key, keep in zip(data.keys, train_mask, strict=True) if keep]
    permutations = None
    if arm == "Cphi_shuffled":
        permutations = row_permutations(train_keys)
    started = time.perf_counter()
    trace, checkpoints = fit_checkpointed(arm, model, x_train, r_train, y_train, permutations=permutations)
    runtime = time.perf_counter() - started
    expected_updates = 200 * ((train_count + 2047) // 2048)
    if model.step != expected_updates or model.step != int(row["expected_update_count"]):
        raise RuntimeError(f"optimizer update count mismatch in {fit_id}")
    if not all(np.isfinite(value).all() for value in model.values + model.m + model.v):
        raise RuntimeError(f"nonfinite final model state in {fit_id}")

    held_base = norm.base[held_mask]
    held_tuples = norm.tuples[held_mask]
    held_keys = [key for key, keep in zip(data.keys, held_mask, strict=True) if keep]
    presented = d_input(held_base, held_tuples) if arm == "D" else cphi_present(held_base, held_tuples)
    held_permutation = None
    if arm == "Cphi_shuffled":
        held_permutation = row_permutations(held_keys)
        presented = shuffle_canonical_tuples(presented, held_permutation)
    final_values = [value.copy() for value in model.values]
    checkpoint_logits = np.empty((len(PRED_EPOCHS), held_count), dtype=np.float32)
    checkpoint_hashes: dict[str, str] = {}
    checkpoint_dir = RUN / row["checkpoint_tensor_dir"]
    checkpoint_dir.mkdir(parents=True, exist_ok=False)
    for position, epoch in enumerate(PRED_EPOCHS):
        if epoch not in checkpoints:
            raise RuntimeError(f"missing declared checkpoint {epoch} for {fit_id}")
        model.values = [value.copy() for value in checkpoints[epoch]]
        if arm == "D":
            held_input = d_input(held_base, held_tuples)
            logits = model.logits(held_input)
        elif arm == "Cphi_unshared":
            logits = model.logits(held_base, held_tuples, canonical=False)
        else:
            logits = model.logits(held_base, presented, canonical=True)
        logits = np.asarray(logits, dtype=np.float32)
        if logits.shape != (held_count,) or not np.isfinite(logits).all():
            raise RuntimeError(f"invalid heldout checkpoint logits in {fit_id} epoch={epoch}")
        checkpoint_logits[position] = logits
        tensor_bytes = _serialize(model.values, arm)
        checkpoint_hashes[str(epoch)] = sha_bytes(tensor_bytes)
        write_new(checkpoint_dir / f"epoch-{epoch:03d}.bin", tensor_bytes)
    model.values = final_values
    repeated = _predict(arm, model, held_base, held_tuples, presented)
    if repeated.tobytes() != checkpoint_logits[-1].tobytes():
        raise RuntimeError(f"epoch-200 deterministic prediction mismatch in {fit_id}")
    prediction = _prediction_bytes(block, arm, replicate, row_hash, held_keys, checkpoint_logits)
    prediction_path = RUN / row["prediction_path"]
    write_new(prediction_path, prediction)
    final_tensor = _serialize(final_values, arm)
    final_tensor_path = RUN / row["final_tensor_path"]
    write_new(final_tensor_path, final_tensor)
    trace_raw = _trace_bytes(trace, arm)
    trace_path = RUN / row["training_trace_path"]
    write_new(trace_path, trace_raw)
    state_raw = _heldout_state(arm, model, held_base, held_tuples, held_keys, presented, held_permutation, checkpoint_logits[-1])
    state_path = RUN / row["heldout_state_path"]
    write_new(state_path, state_raw)

    receipt = {
        "schema": "F4-PRESENTATION-03-fit-receipt-v1",
        "fit_id": fit_id,
        "arm": arm,
        "fold_index": fold,
        "heldout_block": block,
        "assignment_index": int(row["assignment_index"]),
        "replicate_index": replicate,
        "parameter_count": int(row["parameter_count"]),
        "training_rows": train_count,
        "heldout_rows": held_count,
        "training_positive_count": int(row["train_positive_count"]),
        "training_negative_count": int(row["train_negative_count"]),
        "update_count": model.step,
        "checkpoint_epochs": list(PRED_EPOCHS),
        "initial_tensor_sha256": initial_hash,
        "final_tensor_sha256": _tensor_hash(final_values, arm),
        "final_tensor_file_sha256": sha_bytes(final_tensor),
        "checkpoint_tensor_hashes": checkpoint_hashes,
        "training_trace_sha256": sha_bytes(trace_raw),
        "prediction_sha256": sha_bytes(prediction),
        "heldout_state_sha256": sha_bytes(state_raw),
        "normalization_sha256": row["normalization_sha256"],
        "base_stream_sha256": row["base_stream_sha256"],
        "normalized_tuple_stream_sha256": row["normalized_tuple_stream_sha256"],
        "paired_source_input_sha256": row["paired_source_input_sha256"],
        "optimizer_summary": model.optimizer_summary(),
        "runtime_seconds": runtime,
        "finite_status": "PASS",
        "heldout_targets_or_scoring_truth_read_during_fit": False,
        "comparative_metrics_emitted_during_fit": False,
    }
    receipt_raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    receipt_path = RUN / "fit-receipts" / f"{fit_id}.json"
    write_new(receipt_path, receipt_raw)
    return {
        "fit_id": fit_id,
        "prediction_path": row["prediction_path"],
        "prediction_sha256": sha_bytes(prediction),
        "fit_receipt_path": f"fit-receipts/{fit_id}.json",
        "fit_receipt_sha256": sha_bytes(receipt_raw),
        "final_tensor_path": row["final_tensor_path"],
        "final_tensor_sha256": sha_bytes(final_tensor),
        "training_trace_sha256": sha_bytes(trace_raw),
        "heldout_state_sha256": sha_bytes(state_raw),
        "checkpoint_tensor_count": len(checkpoint_hashes),
    }


def run() -> None:
    if (RUN / "PREDICTION-LOCK.json").exists():
        raise RuntimeError("prediction lock already exists; preserve this identity")
    freeze = _read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    source_hashes = _source_hashes(freeze)
    _verify_runtime(freeze)
    prefit = _read_json(RUN / "FIT-PREFIT-RECEIPT.json")
    if prefit.get("status") != "PASS" or prefit.get("fit_count") != 144:
        raise RuntimeError("144-fit prefit receipt is missing or invalid")
    for path in (RUN / "FIT-MANIFEST.csv", RUN / "FIT-MANIFEST-ROW-HASHES.json", RUN / "NORMALIZATION-MANIFEST.json"):
        if not path.is_file():
            raise RuntimeError(f"fit preflight artifact missing: {path.name}")
    with (RUN / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    row_hash_manifest = _read_json(RUN / "FIT-MANIFEST-ROW-HASHES.json")
    fit_manifest_sha = sha_file(RUN / "FIT-MANIFEST.csv")
    if len(rows) != 144 or len({row["fit_id"] for row in rows}) != 144 or row_hash_manifest.get("manifest_sha256") != fit_manifest_sha:
        raise RuntimeError("fit manifest grid/hash mismatch")
    expected_ids = [f"{arm}-H{block}-I{replicate}" for block in BLOCKS for replicate in range(3) for arm in ARMS]
    if [row["fit_id"] for row in rows] != expected_ids:
        raise RuntimeError("fit manifest order/identity differs from frozen grid")
    for row in rows:
        for directory in ("predictions", "final-tensors", "training-traces", "checkpoint-tensors", "heldout-state", "fit-receipts"):
            path = RUN / directory
            path.mkdir(exist_ok=True)
            if any(path.iterdir()):
                raise RuntimeError(f"fit output directory is nonempty before fit 1: {directory}")
    collection_receipt = _read_json(RUN / "COLLECTION-RECEIPT.json")
    if sha_file(COLLECTION / "RAW-PREDICTORS.bin") != collection_receipt["predictor_sha256"] or sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin") != collection_receipt["truth_sha256"]:
        raise RuntimeError("native collection inputs changed before fit 1")
    from presentation03_data import load_raw_panel
    data = load_raw_panel(COLLECTION / "RAW-PREDICTORS.bin")
    norms = normalized_folds(data)
    initializer = _read_json(BRANCH / "implementation-artifacts" / "INITIALIZER-MANIFEST.json")
    if sha_file(BRANCH / "implementation-artifacts" / "INITIALIZER-MANIFEST.json") != prefit.get("initializer_manifest_sha256"):
        raise RuntimeError("initializer manifest changed after fit-surface freeze")
    if len(initializer.get("cells", [])) != 144:
        raise RuntimeError("initializer grid changed after fit-surface freeze")
    labels_by_block = {block: load_training_labels(data.keys, block, COLLECTION / "RAW-SCORING-TRUTH.bin") for block in BLOCKS}

    row_hashes = row_hash_manifest["rows"]
    results = []
    for row in rows:
        fit_id = row["fit_id"]
        line_hash = row_hashes.get(fit_id)
        if not line_hash:
            raise RuntimeError(f"fit manifest row hash missing for {fit_id}")
        result = _fit_one(row, line_hash, norms[int(row["fold_index"])], data, labels_by_block)
        results.append(result)
        print(json.dumps({"event": "fit_complete", "fit_id": fit_id, "finite_status": "PASS", "prediction_sha256": result["prediction_sha256"]}, sort_keys=True), flush=True)

    if len(results) != 144:
        raise RuntimeError("fit execution ended with an incomplete grid")
    lock = {
        "schema": "F4-PRESENTATION-03-prediction-lock-v1",
        "run_id": RUN_ID,
        "status": "PASS",
        "fit_count": len(results),
        "fit_manifest_sha256": fit_manifest_sha,
        "source_manifest_sha256": sha_file(RUN / "SOURCE-INPUT-MANIFEST.json"),
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "prediction_files": results,
        "heldout_truth_values_read_during_fitting": False,
    }
    lock_raw = (json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_new(RUN / "PREDICTION-LOCK.json", lock_raw)
    if source_hashes != _source_hashes(freeze):
        raise RuntimeError("frozen source set drifted during fit execution")
    print(json.dumps({"status": "PREDICTIONS_LOCKED", "fit_count": 144, "truth_values_read": False}, sort_keys=True))


if __name__ == "__main__":
    run()
