"""Verify frozen Stage B inference reproduces the existing CΦ held-out states.

This task-independent gate reads predictor features and saved model outputs only.
It never opens scoring truth or creates an optimizer.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

import stage_b_runtime as runtime
import binding_stage_b_data as data
import binding_stage_b_model as model

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parents[1]
PARENT = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
PARENT_COLLECTION = STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "native-collection"
PARENT_BLOCKS = tuple(range(309000, 309012))
LOGIT_ABSOLUTE_TOLERANCE = 1.0e-5


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    predictor_path = PARENT_COLLECTION / "RAW-PREDICTORS.bin"
    manifest_path = PARENT / "FIT-MANIFEST.csv"
    if not predictor_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("parent replay inputs are unavailable")
    panel = data.load_predictors(predictor_path, PARENT_BLOCKS)
    with manifest_path.open("r", encoding="utf-8", newline="") as stream:
        models = [row for row in csv.DictReader(stream) if row.get("arm") == "Cphi"]
    if len(models) != 36:
        raise RuntimeError("parent replay did not locate exactly 36 CΦ fits")

    normalizers: dict[int, tuple[np.ndarray, ...]] = {}
    checked = []
    for entry in models:
        fit_id = entry["fit_id"]
        fold = int(entry["fold_index"])
        block = int(entry["heldout_block"])
        tensor_path = PARENT / entry["final_tensor_path"]
        state_path = PARENT / entry["heldout_state_path"]
        normalizer_path = PARENT / "normalizations" / f"fold-{fold:02d}.bin"
        if fold not in normalizers:
            normalizers[fold] = data.load_normalizer(normalizer_path, fold)
        tensors = model.load_tensor_bundle(tensor_path)
        idx = np.flatnonzero(panel.blocks == np.uint64(block))
        if not len(idx):
            raise RuntimeError(f"no parent predictor rows for {fit_id}")

        with np.load(state_path, allow_pickle=False) as state:
            saved_keys = state["row_keys"]
            saved_h = state["phi_outputs"]
            saved_logits = state["logits"]
            keys = np.asarray([np.frombuffer(panel.keys[int(i)], dtype=np.uint8) for i in idx], dtype=np.uint8)
            if not np.array_equal(saved_keys, keys):
                raise RuntimeError(f"parent replay row-key/order mismatch: {fit_id}")
            x, tuples = data.apply_normalizer(panel.base[idx], panel.tuples[idx], normalizers[fold])
            h = model.h_from_normalized(x, tuples, tensors)
            logits = model.rho_forward(x, h, tensors, model.PERMUTATIONS["intact"])
            if not np.array_equal(h, saved_h):
                max_error = float(np.max(np.abs(h.astype(np.float64) - saved_h.astype(np.float64))))
                raise RuntimeError(f"parent CΦ representation replay mismatch: {fit_id}; max_abs={max_error:.9g}")
            errors = np.abs(logits.astype(np.float64) - saved_logits.astype(np.float64))
            max_error = float(np.max(errors))
            sign_changes = int(np.count_nonzero((logits > 0.0) != (saved_logits > 0.0)))
            if max_error > LOGIT_ABSOLUTE_TOLERANCE or sign_changes:
                raise RuntimeError(
                    f"parent CΦ logit replay outside frozen arithmetic envelope: "
                    f"{fit_id}; max_abs={max_error:.9g}; sign_changes={sign_changes}"
                )
        checked.append({
            "fit_id": fit_id,
            "heldout_block": block,
            "row_count": int(len(idx)),
            "tensor_sha256": sha_file(tensor_path),
            "normalizer_sha256": sha_file(normalizer_path),
            "state_sha256": sha_file(state_path),
            "phi_outputs_bitwise_equal": True,
            "intact_logits_max_abs_error": max_error,
            "intact_logits_absolute_tolerance": LOGIT_ABSOLUTE_TOLERANCE,
            "intact_logit_sign_changes": sign_changes,
            "intact_logits_within_float32_arithmetic_envelope": True,
        })

    receipt = {
        "schema": "F4-BINDING-01-stage-b-parent-replay-receipt-v0.2",
        "status": "PASS",
        "fit_count": len(checked),
        "predictor_sha256": sha_file(predictor_path),
        "fit_manifest_sha256": sha_file(manifest_path),
        "truth_values_opened": False,
        "optimizer_created": False,
        "feature_outputs_bitwise_equal": all(row["phi_outputs_bitwise_equal"] for row in checked),
        "maximum_absolute_logit_error": max(row["intact_logits_max_abs_error"] for row in checked),
        "maximum_logit_sign_changes": max(row["intact_logit_sign_changes"] for row in checked),
        "arithmetic_acceptance_rule": "bitwise φ outputs; per-row absolute logit error <= 1e-5; zero sign-decision changes",
        "runtime_identity": runtime.identity(),
        "verifier_sha256": sha_file(Path(__file__).resolve()),
        "models": checked,
    }
    raw = (json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    out = BRANCH / "PARENT-REPLAY-RECEIPT-v0.2.json"
    if out.exists():
        raise RuntimeError("parent replay receipt already exists; preserve and stop")
    out.write_bytes(raw)
    print(json.dumps({"status": "PASS", "fit_count": len(checked), "receipt_sha256": hashlib.sha256(raw).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
