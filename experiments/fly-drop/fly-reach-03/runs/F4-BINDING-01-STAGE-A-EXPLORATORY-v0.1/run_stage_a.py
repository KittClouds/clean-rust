"""Exploratory inference-time role-binding intervention on the frozen F4 bank.

`--phase verify` never reads scoring truth. It replays the frozen intact readout,
then evaluates the pair-swap and 4-cycle readouts and seals their logits.
`--phase score` is only allowed after the pre-scoring integrity receipt passes.
No fitting, gradient, optimizer, or phi recomputation is present in this module.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
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
for _name, _value in THREAD_ENV.items():
    os.environ[_name] = _value

import numpy as np

REPO = Path(__file__).resolve().parents[4]
STUDY = REPO / "experiments" / "fly-reach-03"
PARENT = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
COLLECTION = STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "native-collection"
TASK_MANIFEST = STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "task-bank" / "TASK-BANK-MANIFEST.json"
MODEL_SOURCE = STUDY / "f4-presentation-02-v2" / "cphi_model.py"
DATA_SOURCE = STUDY / "f4-presentation-03" / "presentation03_data.py"
ANALYSIS_SOURCE = STUDY / "f4-presentation-03" / "analysis-repair-v0.1.3" / "analyze_results.py"
OUT = Path(__file__).resolve().parent
ARTIFACTS = OUT / "artifacts"

EXPECTED_PARENT = {
    "FIT-MANIFEST.csv": "f71d344c5bc58e86a68e7bd9163aed1ab5d945468bfe84f06a8981e6a1c2ce66",
    "PREDICTION-LOCK.json": "dd387bcc52510eac947774cb6d9303d8cdd8142cee07a60b0e39cddd4dcb54ce",
    "INTEGRITY-RECEIPT.json": "cf52cc787b3bf501b3f80944d452af3247e569f82f110c06c597e499bfca2591",
    "SOURCE-INPUT-MANIFEST.json": "7310de650f0efd5bb7ccb5342bf30e9cc8ae11a16da968e656512bda0e1b7305",
    "COLLECTION-RECEIPT.json": "74b4a574519a665dfea0bf2a1196362f1d2ba7e4ff18aae422fb653b4ca00a40",
    "ANALYSIS.json": "d79f885d3d8b8bef0579312cc72c2b5c8fa08b6edb1fcf52b66bcf5abf1b51c5",
    "F4-PRESENTATION-03-TERMINAL-RECEIPT.json": "298a77fe8aa815a3ff58722dd52a06a8e1e0637fce505955662354150203f2bb",
}
EXPECTED_INTEGRITY = "cf52cc787b3bf501b3f80944d452af3247e569f82f110c06c597e499bfca2591"
EXPECTED_MODEL = "d50521285235db36b062f9eda9a90eb4182a836e2ccb8ab292c04e9e74158099"
EXPECTED_TASK_BANK = "ad339f4a710c9cb803e68a7076da923a68486f81b7552aa767c710f885deb0a1"
EXPECTED_RAW_INPUT = "495c68070624e4b8eaeeba217aeb03bdac6636d75e6691292a59872c11a9455f"
EXPECTED_RAW_TRUTH = "ff9d000145fc503e83710ca99d65b0304d52c1f94533d92c78e28b9730214d50"
PERMUTATIONS = {
    "intact": (0, 1, 2, 3),
    "pair_swap": (1, 0, 2, 3),
    "cycle_4": (1, 2, 3, 0),
}
ASSIGNMENT_ORDER = ("1100", "1010", "0110", "1001", "0101", "0011")


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_authorities() -> dict[str, Any]:
    for name, expected in EXPECTED_PARENT.items():
        actual = sha_file(PARENT / name)
        if actual != expected:
            raise RuntimeError(f"parent authority drift: {name} {actual}")
    if sha_file(PARENT / "INTEGRITY-RECEIPT.json") != EXPECTED_INTEGRITY:
        raise RuntimeError("parent integrity receipt hash mismatch")
    if sha_file(MODEL_SOURCE) != EXPECTED_MODEL:
        raise RuntimeError("Cphi model implementation hash mismatch")
    if sha_file(COLLECTION / "RAW-PREDICTORS.bin") != EXPECTED_RAW_INPUT:
        raise RuntimeError("raw predictor bytes differ from frozen parent collection")
    if sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin") != EXPECTED_RAW_TRUTH:
        raise RuntimeError("scoring truth bytes differ from frozen parent collection")
    task = json.loads(TASK_MANIFEST.read_text(encoding="utf-8"))
    if sha_file(TASK_MANIFEST) != EXPECTED_TASK_BANK:
        raise RuntimeError("task bank manifest hash mismatch")
    return task


def array_sha(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    identity = array.dtype.str.encode("ascii") + b"\0" + struct.pack("<I", array.ndim)
    identity += struct.pack("<" + "Q" * array.ndim, *array.shape)
    return sha_bytes(identity + array.tobytes(order="C"))


def import_data_module():
    for path in (STUDY / "f4-invariant-01-impl-v2", STUDY / "scripts", STUDY / "f4-presentation-02-v2"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return load_module("f4_binding_presentation03_data", DATA_SOURCE)


def import_analysis_module():
    return load_module("f4_binding_frozen_analysis", ANALYSIS_SOURCE)


def decode_row_keys(state: Any) -> list[bytes]:
    matrix = np.asarray(state["row_keys"], dtype=np.uint8)
    if matrix.ndim != 2 or matrix.shape[1] != 18:
        raise RuntimeError("heldout state row-key shape mismatch")
    return [bytes(row) for row in matrix]


def load_prediction_epochs(analysis: Any, run: dict[str, str], expected_keys: list[bytes], parent: dict[str, Any]) -> np.ndarray:
    entry = next((item for item in parent["prediction_files"] if item["fit_id"] == run["fit_id"]), None)
    if entry is None:
        raise RuntimeError(f"prediction lock lacks {run['fit_id']}")
    path = PARENT / entry["prediction_path"]
    if sha_file(path) != entry["prediction_sha256"]:
        raise RuntimeError(f"frozen prediction hash mismatch: {run['fit_id']}")
    return analysis._decode_prediction(path, run, expected_keys)


def rho_forward(base: np.ndarray, h: np.ndarray, tensors: list[np.ndarray], permutation: tuple[int, ...], model: Any) -> np.ndarray:
    presented = np.ascontiguousarray(h[:, permutation, :], dtype=np.float32)
    rel = presented.reshape(len(base), 64)
    readout = np.concatenate((base, rel), axis=1).astype(np.float32, copy=False)
    _phi_w, _phi_b, w1, b1, w2, b2, w3, b3 = tensors
    z1 = readout @ w1 + b1
    a1 = model.gelu(z1)
    z2 = a1 @ w2 + b2
    a2 = model.gelu(z2)
    return ((a2 @ w3 + b3)[:, 0]).astype(np.float32, copy=False)


def fit_rows() -> list[dict[str, str]]:
    with (PARENT / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected = [row for row in rows if row["arm"] == "Cphi"]
    if len(selected) != 36 or len({row["fit_id"] for row in selected}) != 36:
        raise RuntimeError("frozen Cphi fit pool is not exactly 36 unique fits")
    identities = {(int(row["fold_index"]), int(row["replicate_index"])) for row in selected}
    if identities != {(fold, rep) for fold in range(12) for rep in range(3)}:
        raise RuntimeError("frozen Cphi fold/replicate grid mismatch")
    return sorted(selected, key=lambda row: (int(row["fold_index"]), int(row["replicate_index"])))


def verify_and_compute() -> dict[str, Any]:
    task = load_authorities()
    parent_lock = json.loads((PARENT / "PREDICTION-LOCK.json").read_text(encoding="utf-8"))
    integrity = json.loads((PARENT / "INTEGRITY-RECEIPT.json").read_text(encoding="utf-8"))
    if parent_lock.get("status") != "PASS" or integrity.get("status") != "PASS":
        raise RuntimeError("parent execution lock/integrity status is not PASS")
    if integrity.get("heldout_scoring_values_opened") is not True:
        raise RuntimeError("parent truth-access provenance is inconsistent with this exploratory stage")

    data = import_data_module()
    model = load_module("f4_binding_cphi_model", MODEL_SOURCE)
    analysis = import_analysis_module()
    raw = data.load_raw_panel(COLLECTION / "RAW-PREDICTORS.bin")
    folds = data.normalized_folds(raw)
    all_index = {key: i for i, key in enumerate(raw.keys)}
    model_rows = fit_rows()
    locked = {row["fit_id"]: item for item in parent_lock["prediction_files"] for row in model_rows if item["fit_id"] == row["fit_id"]}
    integrity_models = {entry["fit_id"]: entry for entry in integrity["fit_receipt_hashes"]}
    if len(locked) != 36 or len(integrity_models) != 144:
        raise RuntimeError("parent lock is missing fit records")

    task_blocks = {int(row["block_id"]): int(row["assignment_index"]) for row in task["blocks"]}
    if set(task_blocks) != {int(row["heldout_block"]) for row in model_rows}:
        raise RuntimeError("task and Cphi fit blocks differ")
    ARTIFACTS.mkdir(parents=True, exist_ok=False)
    stream_hashes_by_fold = {
        fold_index: data.shared_stream_hashes(raw.keys, fold_data.base, fold_data.tuples)
        for fold_index, fold_data in folds.items()
    }

    manifest: dict[str, Any] = {
        "schema": "F4-BINDING-01-Stage-A-pretruth-lock-v0.1",
        "identity": "F4-BINDING-01-STAGE-A-EXPLORATORY-v0.1",
        "classification": "EXPLORATORY_EXISTING_BANK_ANALYSIS_ONLY",
        "truth_opened_by_prior_parent_lineage": True,
        "parent_hashes": {name: sha_file(PARENT / name) for name in EXPECTED_PARENT},
        "collection": {
            "raw_predictors_sha256": sha_file(COLLECTION / "RAW-PREDICTORS.bin"),
            "raw_scoring_truth_sha256": sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin"),
            "task_bank_manifest_sha256": sha_file(TASK_MANIFEST),
            "data_reader_sha256": sha_file(DATA_SOURCE),
            "analysis_metric_source_sha256": sha_file(ANALYSIS_SOURCE),
            "model_source_sha256": sha_file(MODEL_SOURCE),
            "runner_source_sha256": sha_file(Path(__file__).resolve()),
        },
        "conditions": {name: list(permutation) for name, permutation in PERMUTATIONS.items()},
        "fit_outputs": [],
        "status": "RUNNING_PRETRUTH_VERIFICATION",
    }

    for row in model_rows:
        fit_id = row["fit_id"]
        fold = int(row["fold_index"])
        block = int(row["heldout_block"])
        rep = int(row["replicate_index"])
        norm = folds[fold]
        if norm.sha256 != row["normalization_sha256"] or sha_bytes(norm.payload) != row["normalization_file_sha256"]:
            raise RuntimeError(f"fold normalizer mismatch: {fit_id}")
        normalizer_path = PARENT / "normalizations" / f"fold-{fold:02d}.bin"
        if not normalizer_path.is_file() or sha_file(normalizer_path) != row["normalization_file_sha256"]:
            raise RuntimeError(f"frozen normalizer payload mismatch: {fit_id}")
        streams = stream_hashes_by_fold[fold]
        if (
            streams["base"] != row["base_stream_sha256"]
            or streams["tuples"] != row["normalized_tuple_stream_sha256"]
            or streams["paired"] != row["paired_source_input_sha256"]
        ):
            raise RuntimeError(f"frozen normalized shared-input stream mismatch: {fit_id}")

        lock_entry = locked[fit_id]
        integrity_entry = integrity_models.get(fit_id)
        if integrity_entry is None:
            raise RuntimeError(f"integrity receipt lacks {fit_id}")
        tensor_path = PARENT / row["final_tensor_path"]
        state_path = PARENT / row["heldout_state_path"]
        if sha_file(tensor_path) != lock_entry["final_tensor_sha256"] or sha_file(tensor_path) != integrity_entry["final_tensor_sha256"]:
            raise RuntimeError(f"final tensor hash mismatch: {fit_id}")
        if sha_file(state_path) != lock_entry["heldout_state_sha256"]:
            raise RuntimeError(f"heldout state hash mismatch: {fit_id}")
        if lock_entry["fit_receipt_sha256"] != integrity_entry["receipt_sha256"]:
            raise RuntimeError(f"fit receipt hash disagreement: {fit_id}")

        with np.load(state_path, allow_pickle=False) as archive:
            keys = decode_row_keys(archive)
            saved_logits = np.asarray(archive["logits"], dtype=np.float32).copy()
            h = np.asarray(archive["phi_outputs"], dtype=np.float32).copy()
            rel_saved = np.asarray(archive["relational_concat"], dtype=np.float32).copy()
        if h.shape != (len(keys), 4, 16) or not np.isfinite(h).all() or not np.isfinite(saved_logits).all():
            raise RuntimeError(f"invalid stored phi/logit arrays: {fit_id}")
        h_sha = array_sha(h)
        if not np.array_equal(rel_saved, h.reshape(len(h), 64)):
            raise RuntimeError(f"stored Cphi relational flatten mismatch: {fit_id}")
        if any(struct.unpack_from("<Q", key, 2)[0] != block for key in keys):
            raise RuntimeError(f"heldout state contains wrong block keys: {fit_id}")
        raw_heldout_keys = [key for key, value in zip(raw.keys, raw.blocks, strict=True) if int(value) == block]
        if keys != raw_heldout_keys or len(keys) != int(row["heldout_rows"]):
            raise RuntimeError(f"heldout row-key sequence mismatch: {fit_id}")
        global_indices = np.fromiter((all_index[key] for key in keys), dtype=np.int64, count=len(keys))
        base = np.ascontiguousarray(norm.base[global_indices], dtype=np.float32)
        base_sha = array_sha(base)

        tensor_raw = tensor_path.read_bytes()
        tensors = model.deserialize_tensors(tensor_raw)
        tensor_hash_before = model.tensor_hash(tensors)
        tensor_sha_before = [array_sha(value) for value in tensors]
        logits: dict[str, np.ndarray] = {}
        for name, permutation in PERMUTATIONS.items():
            logits[name] = rho_forward(base, h, tensors, permutation, model)
            if not np.isfinite(logits[name]).all():
                raise RuntimeError(f"nonfinite intervention logits: {fit_id}:{name}")

        prediction_epochs = load_prediction_epochs(analysis, row, keys, parent_lock)
        intact_match_state = np.array_equal(logits["intact"], saved_logits)
        intact_match_epoch200 = np.array_equal(logits["intact"], prediction_epochs[-1])
        if not intact_match_state or not intact_match_epoch200:
            raise RuntimeError(
                f"intact rho replay failed: {fit_id}; state={intact_match_state}, epoch200={intact_match_epoch200}"
            )
        if array_sha(h) != h_sha or model.tensor_hash(tensors) != tensor_hash_before or [array_sha(value) for value in tensors] != tensor_sha_before:
            raise RuntimeError(f"input/model tensor mutated: {fit_id}")
        if sha_file(tensor_path) != lock_entry["final_tensor_sha256"]:
            raise RuntimeError(f"on-disk model tensor drift after inference: {fit_id}")

        output_path = ARTIFACTS / f"{fit_id}.npz"
        with output_path.open("xb") as stream:
            np.savez_compressed(
                stream,
                row_keys=np.frombuffer(b"".join(keys), dtype=np.uint8).reshape(len(keys), 18),
                intact=logits["intact"], pair_swap=logits["pair_swap"], cycle_4=logits["cycle_4"],
            )
            stream.flush()
            os.fsync(stream.fileno())
        manifest["fit_outputs"].append({
            "fit_id": fit_id,
            "fold_index": fold,
            "heldout_block": block,
            "assignment_index": task_blocks[block],
            "replicate_index": rep,
            "rows": len(keys),
            "normalization_sha256": norm.sha256,
            "row_keys_sha256": sha_bytes(b"".join(keys)),
            "base_array_sha256": base_sha,
            "phi_array_sha256": h_sha,
            "parameter_tensor_sha256": tensor_hash_before,
            "individual_parameter_sha256": tensor_sha_before,
            "intact_matches_saved_state_bitwise": intact_match_state,
            "intact_matches_frozen_epoch200_bitwise": intact_match_epoch200,
            "output_path": str(output_path.relative_to(OUT)).replace("\\", "/"),
            "output_sha256": sha_file(output_path),
        })

    manifest["fit_outputs"].sort(key=lambda item: (item["fold_index"], item["replicate_index"]))
    if len(manifest["fit_outputs"]) != 36:
        raise RuntimeError("Stage A did not produce all 36 Cphi inference outputs")
    manifest["status"] = "PASS_PRETRUTH_INTEGRITY_AND_INTACT_REPLAY"
    manifest["truth_values_read_during_phase"] = False
    manifest_path = OUT / "STAGE-A-PREDICTION-LOCK.json"
    write_new_json(manifest_path, manifest)
    receipt = {
        "schema": "F4-BINDING-01-Stage-A-pretruth-integrity-v0.1",
        "identity": manifest["identity"],
        "status": "PASS",
        "prediction_lock_sha256": sha_file(manifest_path),
        "fit_count": 36,
        "output_count": len(manifest["fit_outputs"]),
        "all_intact_replays_bitwise_match_saved_state_and_epoch200": True,
        "all_input_phi_arrays_unchanged": True,
        "all_model_tensors_unchanged": True,
        "truth_values_read": False,
        "exploratory_existing_bank_only": True,
        "biological_promotion": False,
    }
    write_new_json(OUT / "PRE-SCORING-INTEGRITY-RECEIPT.json", receipt)
    return receipt


def q_diagnostics(weights: np.ndarray) -> dict[str, Any]:
    if not len(weights):
        return {"count": 0, "min": None, "max": None, "mean": None, "sum": 0.0, "ess": None}
    total = math.fsum(float(v) for v in weights)
    square = math.fsum(float(v) * float(v) for v in weights)
    return {
        "count": int(len(weights)),
        "min": float(np.min(weights)),
        "max": float(np.max(weights)),
        "mean": total / len(weights),
        "sum": total,
        "ess": total * total / square if square > 0 else None,
    }


def score_stage_a() -> dict[str, Any]:
    receipt_path = OUT / "PRE-SCORING-INTEGRITY-RECEIPT.json"
    lock_path = OUT / "STAGE-A-PREDICTION-LOCK.json"
    if not receipt_path.is_file() or not lock_path.is_file():
        raise RuntimeError("pre-scoring integrity receipt and logit lock must exist")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS" or receipt.get("prediction_lock_sha256") != sha_file(lock_path):
        raise RuntimeError("Stage A pre-scoring integrity receipt does not validate")
    if lock.get("collection", {}).get("runner_source_sha256") != sha_file(Path(__file__).resolve()):
        raise RuntimeError("Stage A runner changed after pretruth prediction lock")
    for name, expected in EXPECTED_PARENT.items():
        if sha_file(PARENT / name) != expected:
            raise RuntimeError(f"parent input drift before scoring: {name}")
    if sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin") != EXPECTED_RAW_TRUTH:
        raise RuntimeError("truth bytes changed after pre-scoring lock")
    for item in lock["fit_outputs"]:
        if sha_file(OUT / item["output_path"]) != item["output_sha256"]:
            raise RuntimeError(f"locked Stage A output drift: {item['fit_id']}")

    data = import_data_module()
    analysis = import_analysis_module()
    raw = data.load_raw_panel(COLLECTION / "RAW-PREDICTORS.bin")
    truth = data.load_scoring_truth(raw.keys, COLLECTION / "RAW-SCORING-TRUTH.bin")
    task = json.loads(TASK_MANIFEST.read_text(encoding="utf-8"))
    assignments = ["".join("1" if cue in values else "0" for cue in range(4)) for values in task["assignments"]]
    if tuple(assignments) != ASSIGNMENT_ORDER:
        raise RuntimeError("task assignment order differs from the frozen six-assignment contract")
    block_assignment = {int(item["block_id"]): int(item["assignment_index"]) for item in task["blocks"]}
    key_to_index = {key: idx for idx, key in enumerate(raw.keys)}
    q = 1.0 / truth.inclusion_probability.astype(np.float64)
    output_by_block_rep: dict[tuple[int, int], dict[str, Any]] = {}
    detailed: list[dict[str, Any]] = []
    row_key_list = list(raw.keys)

    for item in lock["fit_outputs"]:
        with np.load(OUT / item["output_path"], allow_pickle=False) as archive:
            keys = [bytes(row) for row in np.asarray(archive["row_keys"], dtype=np.uint8)]
            condition_logits = {name: np.asarray(archive[array_name], dtype=np.float32).copy() for name, array_name in (("intact", "intact"), ("pair_swap", "pair_swap"), ("cycle_4", "cycle_4"))}
        indices = np.fromiter((key_to_index[key] for key in keys), dtype=np.int64, count=len(keys))
        if len(set(indices.tolist())) != len(indices) or not np.array_equal(raw.blocks[indices], np.full(len(indices), item["heldout_block"], dtype=np.uint64)):
            raise RuntimeError(f"scoring row identity mismatch in {item['fit_id']}")
        block = int(item["heldout_block"])
        rep = int(item["replicate_index"])
        assignment_index = block_assignment[block]
        output_by_block_rep[(block, rep)] = {"indices": indices, "keys": keys, "logits": condition_logits, "substrate_ids": np.fromiter((key[0] for key in keys), dtype=np.uint8), "side_ids": np.fromiter((key[1] for key in keys), dtype=np.uint8)}

        def score_group(local_positions: np.ndarray) -> dict[str, Any]:
            global_indices = indices[local_positions]
            selected_y = truth.y[global_indices]
            result: dict[str, Any] = {
                "rows": int(len(local_positions)),
                "q_diagnostics": q_diagnostics(q[global_indices]),
                "q_diagnostics_by_target": {
                    str(label): q_diagnostics(q[global_indices[selected_y == label]]) for label in (-1, 1)
                },
            }
            for condition, logits in condition_logits.items():
                values = logits[local_positions]
                score = analysis._score(values, global_indices, truth, q)
                psi = analysis._psi(values, global_indices, truth, q, row_key_list)
                result[condition] = {
                    **score,
                    **psi,
                    "eta_delivery_cosine": analysis._delivery_alignment(values, global_indices, truth),
                }
            intact = result["intact"]
            for condition in ("pair_swap", "cycle_4"):
                current = result[condition]
                current["delta_balanced_error"] = None if current["balanced_error"] is None or intact["balanced_error"] is None else current["balanced_error"] - intact["balanced_error"]
                current["delta_signed_margin"] = None if current["signed_margin"] is None or intact["signed_margin"] is None else current["signed_margin"] - intact["signed_margin"]
                current["delta_ipw_mean_absolute_logit"] = None if current["ipw_mean_absolute_logit"] is None or intact["ipw_mean_absolute_logit"] is None else current["ipw_mean_absolute_logit"] - intact["ipw_mean_absolute_logit"]
                current["delta_psi_prop"] = None if current["psi_prop"] is None or intact["psi_prop"] is None else current["psi_prop"] - intact["psi_prop"]
                current["delta_eta_delivery_cosine"] = None if current["eta_delivery_cosine"] is None or intact["eta_delivery_cosine"] is None else current["eta_delivery_cosine"] - intact["eta_delivery_cosine"]
            return result

        block_group = score_group(np.arange(len(indices), dtype=np.int64))
        detailed.append({
            "fit_id": item["fit_id"], "block_id": block, "assignment_index": assignment_index,
            "assignment_bits": assignments[assignment_index], "replicate_index": rep,
            "metrics": block_group,
        })
        for substrate in range(9):
            for side in range(2):
                positions = np.flatnonzero((output_by_block_rep[(block, rep)]["substrate_ids"] == substrate) & (output_by_block_rep[(block, rep)]["side_ids"] == side))
                detailed.append({
                    "fit_id": item["fit_id"], "block_id": block, "assignment_index": assignment_index,
                    "assignment_bits": assignments[assignment_index], "replicate_index": rep,
                    "substrate_id": substrate, "side_id": side,
                    "metrics": score_group(positions),
                })

    assignment_results: dict[str, Any] = {}
    assignment_delta_by_condition: dict[str, dict[str, list[float | None]]] = {"pair_swap": {}, "cycle_4": {}}
    replicate_results: dict[str, Any] = {}
    for assignment_index, bits in enumerate(ASSIGNMENT_ORDER):
        blocks = tuple(sorted(block for block, value in block_assignment.items() if value == assignment_index))
        by_rep: dict[str, Any] = {}
        for rep in range(3):
            all_indices: list[np.ndarray] = []
            logits_by_condition: dict[str, list[np.ndarray]] = {name: [] for name in PERMUTATIONS}
            for block in blocks:
                panel = output_by_block_rep[(block, rep)]
                all_indices.append(panel["indices"])
                for condition in PERMUTATIONS:
                    logits_by_condition[condition].append(panel["logits"][condition])
            indices = np.concatenate(all_indices)
            entry: dict[str, Any] = {"replicate_index": rep, "rows": int(len(indices)), "support": {"positive": int(np.count_nonzero(truth.y[indices] == 1)), "negative": int(np.count_nonzero(truth.y[indices] == -1))}, "q_diagnostics": q_diagnostics(q[indices])}
            for condition in PERMUTATIONS:
                logits = np.concatenate(logits_by_condition[condition])
                entry[condition] = {
                    **analysis._score(logits, indices, truth, q),
                    **analysis._psi(logits, indices, truth, q, row_key_list),
                    "eta_delivery_cosine": analysis._delivery_alignment(logits, indices, truth),
                }
            for condition in ("pair_swap", "cycle_4"):
                intact_error = entry["intact"]["balanced_error"]
                condition_error = entry[condition]["balanced_error"]
                entry[condition]["delta_balanced_error"] = None if intact_error is None or condition_error is None else condition_error - intact_error
                for metric, prefix in (("signed_margin", "delta_signed_margin"), ("ipw_mean_absolute_logit", "delta_ipw_mean_absolute_logit"), ("psi_prop", "delta_psi_prop"), ("eta_delivery_cosine", "delta_eta_delivery_cosine")):
                    left, right = entry[condition][metric], entry["intact"][metric]
                    entry[condition][prefix] = None if left is None or right is None else left - right
            by_rep[str(rep)] = entry
        assignment_results[str(assignment_index)] = {"assignment_bits": bits, "blocks": list(blocks), "replicates": by_rep}

    def mean_finite(values: list[float | None]) -> float | None:
        present = [float(value) for value in values if value is not None]
        return math.fsum(present) / len(present) if present else None

    for condition in ("pair_swap", "cycle_4"):
        vector: list[float | None] = []
        for assignment_index in range(6):
            rep_deltas = [assignment_results[str(assignment_index)]["replicates"][str(rep)][condition]["delta_balanced_error"] for rep in range(3)]
            vector.append(mean_finite(rep_deltas))
        assignment_delta_by_condition[condition] = dict(zip(ASSIGNMENT_ORDER, vector, strict=True))
    equal_weight: dict[str, Any] = {}
    for condition in ("pair_swap", "cycle_4"):
        values = list(assignment_delta_by_condition[condition].values())
        equal_weight[condition] = {
            "assignment_delta_error_vector": values,
            "assignment_order": list(ASSIGNMENT_ORDER),
            "equal_weight_mean_delta_error": None if any(value is None for value in values) else math.fsum(float(value) for value in values) / 6,
            "evaluable_assignment_count": sum(value is not None for value in values),
        }

    result = {
        "schema": "F4-BINDING-01-Stage-A-exploratory-analysis-v0.1",
        "identity": "F4-BINDING-01-STAGE-A-EXPLORATORY-v0.1",
        "status": "EXPLORATORY_ANALYSIS_COMPLETE",
        "post_selection_existing_bank": True,
        "prior_parent_truth_access": True,
        "model_fits_or_predictions_rerun": False,
        "phi_recomputed": False,
        "conditions": {name: list(p) for name, p in PERMUTATIONS.items()},
        "metrics": ["IPW class-balanced error", "signed margin", "IPW mean absolute logit", "Psi_prop with leverage ESS and top 1/5/20 percent concentration", "delivery-aware alignment", "q min/max/mean/sum/ESS"],
        "q_weighting": "q=1/p_inclusion; no trimming, capping, winsorization, or post-hoc renormalization",
        "assignment_results": assignment_results,
        "equal_weight_assignment_deltas": equal_weight,
        "assignment_delta_error_vectors": assignment_delta_by_condition,
        "block_substrate_side_details": detailed,
        "interpretation_ceiling": "Exploratory post-selection anatomy on the existing bank; no general causal necessity claim and no automatic Stage B authorization.",
        "measured_trajectory_endpoint": "NOT_MEASURED",
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
        "prediction_lock_sha256": sha_file(lock_path),
        "parent_integrity_sha256": EXPECTED_INTEGRITY,
        "truth_file_sha256": sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin"),
    }
    write_new_json(OUT / "STAGE-A-ANALYSIS.json", result)
    lines = [
        "# F4-BINDING-01 Stage A: exploratory existing-bank anatomy", "",
        "This is a post-selection engineering diagnostic on the already-open F4-PRESENTATION-03 bank. No training, fitting, gradient, optimizer, or phi recomputation occurred.", "",
        "## Equal-weight assignment effects", "",
        "Positive Δ balanced error means role disruption worsened classification. Values average the three frozen initialization replicates within assignment; the six assignments receive equal weight.", "",
        "| Condition | ΔE 1100 | ΔE 1010 | ΔE 0110 | ΔE 1001 | ΔE 0101 | ΔE 0011 | Equal-weight mean |", "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition in ("pair_swap", "cycle_4"):
        values = equal_weight[condition]["assignment_delta_error_vector"]
        fmt = lambda v: "null" if v is None else f"{float(v):+.6f}"
        lines.append("| " + condition + " | " + " | ".join(fmt(v) for v in values) + " | " + fmt(equal_weight[condition]["equal_weight_mean_delta_error"]) + " |")
    lines += ["", "## Scope", "", "These estimates are descriptive and exploratory. They do not establish general causal necessity, authorize Stage B, or change REACH-03, calibration, controller, PHENO, or biological status. Classification, proposed polarity alignment, delivery alignment, and trajectory capability remain separate.", ""]
    report = "\n".join(lines).encode("utf-8")
    with (OUT / "STAGE-A-RESULTS.md").open("xb") as stream:
        stream.write(report)
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("verify", "score"), required=True)
    args = parser.parse_args()
    if args.phase == "verify":
        receipt = verify_and_compute()
        print(json.dumps(receipt, sort_keys=True))
    else:
        result = score_stage_a()
        print(json.dumps({"status": result["status"], "pair_swap": result["equal_weight_assignment_deltas"]["pair_swap"], "cycle_4": result["equal_weight_assignment_deltas"]["cycle_4"]}, sort_keys=True))


if __name__ == "__main__":
    main()
