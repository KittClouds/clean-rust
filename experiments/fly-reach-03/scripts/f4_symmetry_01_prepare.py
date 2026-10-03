"""Authority preflight, clean feature preparation, and pre-fit gates."""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from f4_symmetry_01_common import (
    ARMS, BLOCKS, CONTRACT_SHA, FIT_HEADER, OUT_REL, REPO, ROOT,
    canonical_json_bytes, ensure_output_dirs, json_read, normalize_f32,
    read_raw, row_key_hash, runtime_description, sha_bytes, sha_file,
    require, sorted_tree_hashes, training_hashes, verify_manifest_sources, write_json,
    write_matrix,
)
import numpy as np

from f4_symmetry_01_model import Encoder, tensor_hash

EXPECTED_SPEC_V1_SHA = "9ef769a80e4e5e91cd9af8b26bf22f8d1b49a940fe89c1f24f571333541ce0a4"
EXPECTED_ROWS = 13420
EXPECTED_FITS = 16


def _ordered_fit_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    expected = [f"{arm}-H{block}" for arm in ARMS for block in BLOCKS]
    if len(rows) != EXPECTED_FITS or {str(row["fit_id"]) for row in rows} != set(expected):
        raise RuntimeError("FIT-MANIFEST does not contain the exact frozen Cartesian cells")
    ordered = sorted(rows, key=lambda row: (ARMS.index(str(row["arm"])), BLOCKS.index(int(row["holdout_block"]))))
    if [str(row["fit_id"]) for row in ordered] != expected:
        raise RuntimeError("FIT-MANIFEST arm-major ordering failed")
    return ordered


def _required_source_paths(out: Path) -> list[Path]:
    paths = [
        ROOT / "F4-SYMMETRY-01-CONTRACT-v0.1.md",
        ROOT / "F4-SYMMETRY-01-CONTRACT-v0.1.md.sha256",
        ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md",
        ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md.sha256",
        ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md",
        ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md.sha256",
        ROOT / "F4-SYMMETRY-01-MATH-AUDIT-v0.1.md",
        ROOT / "MATH-CONTRACT-v0.3-AUTHORITATIVE.md",
        ROOT / "MATH-CONTRACT-v0.3-SEAL.json",
        ROOT / "math-objects-v0.3.json",
        ROOT / "F4-ENCODER-SPEC-v1.json",
        ROOT / "F4-ENCODER-SPEC-v1.sha256",
        ROOT / "EXECUTION-CONTRACT-v0.2-F4-ENCODER-AMENDMENT.json",
        ROOT / "inputs/qualification/training.json",
        ROOT / "manifests/QUALIFICATION-MANIFEST.json",
        ROOT / "manifests/QUALIFICATION-CONTRACT-v0.1.json",
        ROOT / "runs/qualification-v2/f4-features-v3-post-probability/F4-V3-FEATURE-COLLECTION-RECEIPT.json",
        ROOT / "executor/Cargo.toml",
        ROOT / "executor/Cargo.lock",
        ROOT / "executor/src/collector.rs",
        ROOT / "executor/src/graph.rs",
        ROOT / "executor/src/main.rs",
        ROOT / "executor/src/qualification.rs",
        ROOT / "executor/src/reach_sim.rs",
        ROOT / "executor/src/rng.rs",
        ROOT / "executor/src/symmetry.rs",
        ROOT / "executor/src/symmetry_authority.rs",
        ROOT / "executor/src/symmetry_fixtures.rs",
        ROOT / "executor/src/symmetry_tests.rs",
        ROOT / "executor/src/task.rs",
        ROOT / "scripts/f4_symmetry_01.py",
        ROOT / "scripts/f4_symmetry_01_common.py",
        ROOT / "scripts/f4_symmetry_01_prepare.py",
        ROOT / "scripts/f4_symmetry_01_model.py",
        ROOT / "scripts/f4_symmetry_01_fit.py",
        ROOT / "scripts/f4_symmetry_01_integrity.py",
        ROOT / "scripts/test_f4_symmetry_01.py",
        ROOT / "scripts/benchmark_f4_symmetry_01.py",
        out / "bin/fly-reach-03-executor.exe",
    ]
    lineage = REPO / "experiments/fly-reach-02-v0.1b/inputs"
    paths.extend([lineage / "anatomy/nodes-L.tsv", lineage / "anatomy/nodes-R.tsv"])
    paths.extend([lineage / "anatomy/edges-L.tsv", lineage / "anatomy/edges-R.tsv"])
    for graph_index in range(1, 9):
        graph_id = f"g{graph_index:03d}"
        for side in ("L", "R"):
            paths.append(lineage / "null-graphs" / graph_id / f"edges-{side}.tsv")
    paths.extend(sorted((ROOT / "runs/qualification-v2/f4-features-v3-post-probability").glob("*.bin"), key=lambda p: p.name.encode("utf-8")))
    return paths


def _check_sidecar(path: Path, expected: str | None = None) -> str:
    actual = sha_file(path)
    text = path.with_name(path.name + ".sha256").read_text(encoding="utf-8").split()[0]
    require_hash = expected or text
    if actual != require_hash or text != actual:
        raise RuntimeError(f"authority hash mismatch for {path.name}: actual={actual} sidecar={text}")
    return actual


def preflight(binary: Path, out: Path | None = None, predecessor_stop: Path | None = None) -> Path:
    out = out or ROOT / OUT_REL
    if out.exists():
        raise RuntimeError(f"fresh output identity already exists; preserve it and stop: {out}")
    predecessor = None
    if predecessor_stop is not None:
        predecessor_receipt = json_read(predecessor_stop)
        if predecessor_receipt.get("status") != "STOP" or predecessor_receipt.get("measured_namespace_created") is not False:
            raise RuntimeError("predecessor attempt is not a pre-measurement STOP receipt")
        predecessor = {
            "path_from_study_root": predecessor_stop.resolve().relative_to(ROOT.resolve()).as_posix(),
            "sha256": sha_file(predecessor_stop),
        }
    if sha_file(ROOT / "F4-SYMMETRY-01-CONTRACT-v0.1.md") != CONTRACT_SHA:
        raise RuntimeError("frozen F4-SYMMETRY-01 contract hash mismatch")
    _check_sidecar(ROOT / "F4-SYMMETRY-01-CONTRACT-v0.1.md", CONTRACT_SHA)
    _check_sidecar(ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md", EXPECTED_SPEC_V1_SHA)
    _check_sidecar(ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md")
    if not binary.is_file():
        raise RuntimeError(f"compiled executor missing: {binary}")
    out.mkdir(parents=True, exist_ok=False)
    (out / "bin").mkdir()
    shutil.copy2(binary, out / "bin/fly-reach-03-executor.exe")
    entries = sorted_tree_hashes(_required_source_paths(out))
    source_manifest = {"schema": "F4-SYMMETRY-01-source-input-manifest-v1", "entries": entries}
    canonical_digest = sha_bytes(canonical_json_bytes(source_manifest))
    manifest_path = out / "SOURCE-INPUT-MANIFEST.json"
    pretty = write_json(manifest_path, source_manifest)
    file_digest = sha_bytes(pretty)
    runtime = runtime_description()
    require(runtime["python_version"].startswith("3.13.15"), "frozen Python runtime version mismatch")
    require(runtime["numpy_version"] == "2.5.3", "frozen NumPy runtime version mismatch")
    receipt = {
        "schema": "F4-SYMMETRY-01-implementation-preflight-v1",
        "status": "PASS",
        "controlling_contract_sha256": CONTRACT_SHA,
        "implementation_spec_v1_sha256": sha_file(ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md"),
        "implementation_amendment_v0_2_sha256": sha_file(ROOT / "F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md"),
        "source_manifest_sha256": canonical_digest,
        "source_manifest_file_sha256": file_digest,
        "source_manifest_entry_count": len(entries),
        "runtime": runtime,
        "source_hashes": {item["path"]: item["sha256"] for item in entries},
        "expected_rows": EXPECTED_ROWS,
        "expected_fits": EXPECTED_FITS,
        "qualification_only": True,
        "measured_namespace_created": False,
        "predecessor_premeasurement_stop": predecessor,
    }
    write_json(out / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json", receipt)
    return out


def collect_native(out: Path, lineage: Path) -> None:
    _verify_source_authority(out)
    executable = out / "bin/fly-reach-03-executor.exe"
    command = [str(executable), "--f4-symmetry-01-collect", str(ROOT), str(lineage), str(out)]
    result = subprocess.run(command, cwd=REPO, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"native collection stopped ({result.returncode}): {result.stderr[-3000:]}")
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip())


def _projection_matrix() -> np.ndarray:
    positive = np.frombuffer(struct.pack("<I", 0x3DFC1764), dtype="<f4")[0]
    matrix = np.empty((24, 66), dtype=np.float32)
    prefix = b"F4-SYMMETRY-01-B-PROJ-v1"
    for row in range(24):
        for column in range(66):
            digest = hashlib.sha256(prefix + struct.pack("<II", row, column)).digest()
            matrix[row, column] = positive if digest[0] & 1 == 0 else -positive
    return matrix


def _project_f32(a_normalized: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    rows = a_normalized.shape[0]
    outputs = np.empty((rows, matrix.shape[0]), dtype=np.float32)
    product = np.empty(rows, dtype=np.float32)
    for projection in range(matrix.shape[0]):
        acc = np.zeros(rows, dtype=np.float32)
        for column in range(matrix.shape[1]):
            np.multiply(a_normalized[:, column], matrix[projection, column], out=product)
            np.add(acc, product, out=acc)
        outputs[:, projection] = acc
    return outputs


def _tuple_bytes(row: np.void) -> bytes:
    return struct.pack("<Bbbfff", int(row["incidence"]), int(row["role"]), int(row["incidence_role"]), float(row["delta"]), float(row["incidence_delta"]), float(row["role_delta"]))


def _tuple_sort_key(row: np.void) -> tuple[float | int, ...]:
    values = (int(row["incidence"]), int(row["role"]), int(row["incidence_role"]), float(row["delta"]), float(row["incidence_delta"]), float(row["role_delta"]))
    if not all(math.isfinite(float(value)) for value in values[3:]):
        raise RuntimeError("nonfinite relational tuple in D ordering")
    return values


def _sorted_rows(tuples: np.ndarray) -> np.ndarray:
    ordered = np.empty_like(tuples)
    for row_index, row in enumerate(tuples):
        order = sorted(range(4), key=lambda cue: _tuple_sort_key(row[cue]))
        ordered[row_index] = row[order]
    return ordered


def _sidecar(raw_tuples: np.ndarray, rel_mean: np.ndarray, rel_scale: np.ndarray) -> np.ndarray:
    count = raw_tuples.shape[0]
    out = np.empty((count, 4, 6), dtype=np.float32)
    out[:, :, 0] = raw_tuples["incidence"].astype(np.float32)
    out[:, :, 1] = raw_tuples["role"].astype(np.float32)
    out[:, :, 2] = raw_tuples["incidence_role"].astype(np.float32)
    for component, field in enumerate(("delta", "incidence_delta", "role_delta")):
        out[:, :, 3 + component] = ((raw_tuples[field] - rel_mean[component]) / rel_scale[component]).astype(np.float32)
    return out.reshape(count, 24)


def _row_multisets(tuples: np.ndarray) -> list[tuple[bytes, ...]]:
    return [tuple(sorted(_tuple_bytes(item) for item in row)) for row in tuples]


def _normalized_tuple_multisets(tuples: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> list[tuple[bytes, ...]]:
    output: list[tuple[bytes, ...]] = []
    for row in tuples:
        values: list[bytes] = []
        for item in row:
            floats = [np.float32((item[field] - mean[index]) / scale[index]) for index, field in enumerate(("delta", "incidence_delta", "role_delta"))]
            values.append(struct.pack("<Bbbfff", int(item["incidence"]), int(item["role"]), int(item["incidence_role"]), *(float(value) for value in floats)))
        output.append(tuple(sorted(values)))
    return output


def _write_normalization(path: Path, holdout: int, a_mean: np.ndarray, a_scale: np.ndarray, b_mean: np.ndarray, b_scale: np.ndarray, rel_mean: np.ndarray, rel_scale: np.ndarray) -> str:
    payload = b"".join(np.asarray(part, dtype="<f4").tobytes(order="C") for part in (a_mean, a_scale, b_mean, b_scale, rel_mean, rel_scale))
    if len(payload) != 744:
        raise RuntimeError(f"normalization payload width drift: {len(payload)}")
    raw = b"FLYREACH3SYMNOR\0" + struct.pack("<IQI", 1, holdout, 744) + payload
    if len(raw) != 776:
        raise RuntimeError("normalization artifact must be 776 bytes")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha_bytes(raw)


def _source_manifest_hash(out: Path) -> tuple[str, str]:
    receipt = json_read(out / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json")
    return str(receipt["source_manifest_sha256"]), str(receipt["source_manifest_file_sha256"])


def _verify_source_authority(out: Path) -> dict[str, object]:
    expected_canonical, expected_file = _source_manifest_hash(out)
    actual = verify_manifest_sources(out / "SOURCE-INPUT-MANIFEST.json")
    if actual["canonical_sha256"] != expected_canonical or actual["file_sha256"] != expected_file:
        raise RuntimeError("source manifest digest differs from preflight")
    return actual


def _run_fixtures(out: Path, lineage: Path) -> None:
    command = [str(out / "bin/fly-reach-03-executor.exe"), "--f4-symmetry-01-fixtures", str(ROOT), str(lineage), str(out)]
    result = subprocess.run(command, cwd=REPO, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"symmetry fixture gate stopped ({result.returncode}): {result.stderr[-3000:]}")
    if result.stdout.strip():
        print(result.stdout.rstrip())


def prepare(out: Path, lineage: Path) -> None:
    preflight = json_read(out / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json")
    if preflight.get("status") != "PASS" or preflight.get("controlling_contract_sha256") != CONTRACT_SHA:
        raise RuntimeError("implementation preflight has not passed")
    _verify_source_authority(out)
    if any((out / name).exists() for name in ("B-PROJECTION-MATRIX.bin", "FIT-MANIFEST.csv", "PRE-FIT-GATES.json")):
        raise RuntimeError("preparation artifacts already exist; preserve this identity and stop")
    for receipt_name in ("ROW-RECONCILIATION-RECEIPT.json", "FORWARD-P-RECONCILIATION-RECEIPT.json", "NATIVE-COLLECTION-RECEIPT.json"):
        if not (out / receipt_name).is_file():
            collect_native(out, lineage)
            break
    native_collection = json_read(out / "NATIVE-COLLECTION-RECEIPT.json")
    if native_collection.get("status") != "PASS":
        raise RuntimeError("native collection receipt has not passed")
    if (sha_file(out / "RAW-PREDICTORS.bin") != native_collection.get("predictor_sha256")
            or sha_file(out / "RAW-SCORING-TRUTH.bin") != native_collection.get("truth_sha256")):
        raise RuntimeError("raw collection bytes changed after native collection")
    data = read_raw(out / "RAW-PREDICTORS.bin", out / "RAW-SCORING-TRUTH.bin")
    if data.count != EXPECTED_ROWS:
        raise RuntimeError("raw feature row count mismatch")
    ensure_output_dirs(out)
    projection = _projection_matrix()
    projection_bytes = np.ascontiguousarray(projection, dtype="<f4").tobytes()
    projection_hash = sha_bytes(projection_bytes)
    projection_file = out / "B-PROJECTION-MATRIX.bin"
    with projection_file.open("xb") as stream:
        stream.write(projection_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    projection_repeat = _projection_matrix()
    if projection_repeat.tobytes() != projection.tobytes():
        raise RuntimeError("B projection regeneration is not deterministic")

    b_receipts: list[dict[str, object]] = []
    cd_receipts: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    fold_initial_hashes: dict[int, dict[str, str]] = {}
    for fold_index, holdout in enumerate(BLOCKS):
        train_mask = data.blocks != holdout
        held_mask = ~train_mask
        a_norm, a_mean, a_scale = normalize_f32(data.a, train_mask)
        b_raw = _project_f32(a_norm, projection)
        b_repeat = _project_f32(a_norm, projection)
        if b_raw.tobytes(order="C") != b_repeat.tobytes(order="C"):
            raise RuntimeError(f"B sidecar repeat differs for holdout {holdout}")
        b_norm, b_mean, b_scale = normalize_f32(b_raw, train_mask)

        c_tuples = data.tuples
        d_tuples = _sorted_rows(c_tuples)
        raw_c = _row_multisets(c_tuples)
        raw_d = _row_multisets(d_tuples)
        if raw_c != raw_d:
            raise RuntimeError(f"STOP_CANONICAL_SIDECAR_VALUE_DRIFT before normalization at {holdout}")
        rel_c = np.stack((c_tuples["delta"], c_tuples["incidence_delta"], c_tuples["role_delta"]), axis=2).astype(np.float32)
        rel_d = np.stack((d_tuples["delta"], d_tuples["incidence_delta"], d_tuples["role_delta"]), axis=2).astype(np.float32)
        rel_c_rows = rel_c.reshape(data.count * 4, 3)
        rel_train_mask = np.repeat(train_mask, 4)
        _, rel_mean, rel_scale = normalize_f32(rel_c_rows, rel_train_mask)
        norm_c_multi = _normalized_tuple_multisets(c_tuples, rel_mean, rel_scale)
        norm_d_multi = _normalized_tuple_multisets(d_tuples, rel_mean, rel_scale)
        if norm_c_multi != norm_d_multi:
            raise RuntimeError(f"STOP_CANONICAL_SIDECAR_VALUE_DRIFT after normalization at {holdout}")
        c_side = _sidecar(c_tuples, rel_mean, rel_scale)
        d_side = _sidecar(d_tuples, rel_mean, rel_scale)
        c_input = np.concatenate((a_norm, c_side), axis=1).astype(np.float32)
        d_input = np.concatenate((a_norm, d_side), axis=1).astype(np.float32)
        b_input = np.concatenate((a_norm, b_norm), axis=1).astype(np.float32)
        arm_inputs = {"A": a_norm, "B": b_input, "C": c_input, "D": d_input}
        normalization_hash = _write_normalization(out / "normalization" / f"NORMALIZATION-{holdout}.bin", holdout, a_mean, a_scale, b_mean, b_scale, rel_mean, rel_scale)
        b_output_hash = sha_bytes(np.ascontiguousarray(b_norm, dtype="<f4").tobytes())
        b_receipts.append({"holdout_block": holdout, "projection_sha256": projection_hash, "a_normalizer_sha256": sha_bytes(a_mean.astype("<f4").tobytes() + a_scale.astype("<f4").tobytes()), "b_normalizer_sha256": sha_bytes(b_mean.astype("<f4").tobytes() + b_scale.astype("<f4").tobytes()), "b_output_sha256": b_output_hash, "repeat_identical": True})
        cd_receipts.append({"holdout_block": holdout, "raw_row_multiset_equal": True, "normalized_row_multiset_equal": True, "c_values_sha256": sha_bytes(np.ascontiguousarray(c_side, dtype="<f4").tobytes()), "d_values_sha256": sha_bytes(np.ascontiguousarray(d_side, dtype="<f4").tobytes()), "shared_relation_mean_sha256": sha_bytes(rel_mean.astype("<f4").tobytes()), "shared_relation_scale_sha256": sha_bytes(rel_scale.astype("<f4").tobytes())})
        fold_initial_hashes[holdout] = {}
        train_keys = [key for key, keep in zip(data.keys, train_mask, strict=True) if keep]
        train_row_hash, train_order_hash = training_hashes(data.keys, train_mask)
        for arm in ARMS:
            matrix = arm_inputs[arm]
            input_width = matrix.shape[1]
            matrix_path = out / "prepared-inputs" / f"{arm}-H{holdout}.bin"
            matrix_bytes = write_matrix(matrix_path, matrix)
            feature_hash = sha_bytes(matrix_bytes[32:])
            initial_hash = tensor_hash(Encoder(input_width, fold_index).values)
            fold_initial_hashes[holdout][arm] = initial_hash
            manifest_rows.append({
                "fit_id": f"{arm}-H{holdout}", "arm": arm, "holdout_block": holdout,
                "input_width": input_width, "train_rows": int(train_mask.sum()), "heldout_rows": int(held_mask.sum()),
                "feature_hash": feature_hash, "training_row_hash": train_row_hash, "training_order_hash": train_order_hash,
                "normalization_hash": normalization_hash, "initial_tensor_hash": initial_hash,
                "expected_prediction_path": f"heldout-predictions/{arm}-H{holdout}.bin",
            })
    for holdout, hashes in fold_initial_hashes.items():
        if len({hashes[arm] for arm in ("B", "C", "D")}) != 1:
            raise RuntimeError(f"B/C/D initial tensor hashes differ at holdout {holdout}")

    write_json(out / "B-DETERMINISM-RECEIPT.json", {"schema": "F4-SYMMETRY-01-B-determinism-v1", "gate_id": "B_DETERMINISM", "status": "PASS", "projection_sha256": projection_hash, "projection_regenerated_identically": True, "folds": b_receipts, "no_row_or_target_key_used": True})
    write_json(out / "CD-MULTISET-RECEIPT.json", {"schema": "F4-SYMMETRY-01-CD-multiset-v1", "gate_id": "CD_VALUE_IDENTITY", "status": "PASS", "raw_C_D_row_multisets_equal": True, "normalized_C_D_row_multisets_equal": True, "folds": cd_receipts})
    _run_fixtures(out, lineage)
    _verify_source_authority(out)
    gate_names = ("ROW_RECONCILIATION", "FORWARD_PROBABILITY", "B_DETERMINISM", "CD_VALUE_IDENTITY", "REPRESENTATION_INVARIANTS", "JOINT_INVERSION_REPRESENTATION")
    gates = {}
    receipts = {
        "ROW_RECONCILIATION": "ROW-RECONCILIATION-RECEIPT.json",
        "FORWARD_PROBABILITY": "FORWARD-P-RECONCILIATION-RECEIPT.json",
        "B_DETERMINISM": "B-DETERMINISM-RECEIPT.json",
        "CD_VALUE_IDENTITY": "CD-MULTISET-RECEIPT.json",
        "REPRESENTATION_INVARIANTS": "REPRESENTATION-FIXTURE-RECEIPT.json",
    }
    for name in gate_names:
        if name == "JOINT_INVERSION_REPRESENTATION":
            gates[name] = "PASS" if json_read(out / receipts["REPRESENTATION_INVARIANTS"]).get("joint_inversion_tuple_checks", 0) > 0 else "FAIL"
        else:
            gates[name] = str(json_read(out / receipts[name]).get("status"))
    if any(status != "PASS" for status in gates.values()):
        raise RuntimeError(f"pre-fit implementation gates did not pass: {gates}")
    write_json(out / "PRE-FIT-GATES.json", {"schema": "F4-SYMMETRY-01-prefit-gates-v1", "status": "PASS", "gate_status": gates, "target_symmetry_diagnostic": json_read(out / "TARGET-SYMMETRY-DIAGNOSTIC.json"), "fit_count": EXPECTED_FITS, "truth_opened": False})

    write_json(out / "COLLECTION-RECEIPT.json", {
        "schema": "F4-SYMMETRY-01-collection-receipt-v1",
        "status": "PASS",
        "qualification_rows": data.count,
        "fit_grid_declared": 16,
        "pre_fit_gates": gates,
        "source_manifest_sha256": preflight["source_manifest_sha256"],
        "truth_opened": False,
        "measured_namespace_created": False,
    })

    source_sha, _source_file_sha = _source_manifest_hash(out)
    binary_sha = sha_file(out / "bin/fly-reach-03-executor.exe")
    analysis_sha = sha_file(ROOT / "scripts/f4_symmetry_01_integrity.py")
    manifest_rows = _ordered_fit_rows(manifest_rows)
    csv_buffer = []
    order_rows = []
    line_hashes: dict[str, str] = {}
    for item in manifest_rows:
        row = [item["fit_id"], item["arm"], str(item["holdout_block"]), str(item["input_width"]), str(item["train_rows"]), str(item["heldout_rows"]), CONTRACT_SHA, source_sha, binary_sha, analysis_sha, item["feature_hash"], item["training_row_hash"], item["training_order_hash"], item["normalization_hash"], item["initial_tensor_hash"], item["expected_prediction_path"]]
        buffer = __import__("io").StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(row)
        row_bytes = buffer.getvalue().encode("utf-8")
        line_hashes[item["fit_id"]] = sha_bytes(row_bytes)
        order_rows.append(item["fit_id"])
        csv_buffer.append(row_bytes)
    csv_path = out / "FIT-MANIFEST.csv"
    with csv_path.open("xb") as stream:
        stream.write((FIT_HEADER + "\n").encode("utf-8"))
        for row in csv_buffer:
            stream.write(row)
        stream.flush()
        os.fsync(stream.fileno())
    write_json(out / "FIT-MANIFEST-ROW-HASHES.json", {"schema": "F4-SYMMETRY-01-fit-manifest-row-hashes-v1", "rows": line_hashes, "order": order_rows, "manifest_sha256": sha_file(csv_path)})
    require_order = [f"{arm}-H{block}" for arm in ARMS for block in BLOCKS]
    if order_rows != require_order:
        raise RuntimeError("FIT-MANIFEST row order mismatch")
    if len(manifest_rows) != EXPECTED_FITS:
        raise RuntimeError("FIT-MANIFEST cell count mismatch")
    print(json.dumps({"status": "PREFIT_GATES_PASS", "rows": data.count, "fits_declared": EXPECTED_FITS, "truth_opened": False}, sort_keys=True))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "collect", "prepare"))
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / OUT_REL)
    parser.add_argument("--predecessor-stop", type=Path)
    parser.add_argument("--lineage", type=Path, default=REPO / "experiments/fly-reach-02-v0.1b")
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out
    if args.phase == "preflight":
        if args.binary is None:
            parser.error("--binary is required for preflight")
        preflight(args.binary, args.out, args.predecessor_stop)
    elif args.phase == "collect":
        collect_native(out, args.lineage)
    else:
        prepare(out, args.lineage)


if __name__ == "__main__":
    main()
