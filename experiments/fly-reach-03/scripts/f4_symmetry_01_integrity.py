"""Independent prediction integrity and truth-unlocked scoring stages."""
from __future__ import annotations

import csv
import io
import json
import math
import struct
from pathlib import Path

from f4_symmetry_01_common import (
    ARMS, BLOCKS, CONTRACT_SHA, PRED_MAGIC, ROOT, TRUTH_WIDTH,
    binary_matrix, json_read, load_truth_after_integrity, read_raw,
    runtime_description, sha_bytes, sha_file, training_hashes,
    verify_manifest_sources, write_json,
)
import numpy as np


def _manifest_rows(out: Path) -> list[dict[str, str]]:
    manifest_path = out / "FIT-MANIFEST.csv"
    with manifest_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != [
            "fit_id", "arm", "holdout_block", "input_width", "train_rows", "heldout_rows",
            "contract_sha256", "source_manifest_sha256", "implementation_executable_sha256",
            "analysis_script_sha256", "feature_hash", "training_row_hash", "training_order_hash",
            "normalization_hash", "initial_tensor_hash", "expected_prediction_path",
        ]:
            raise RuntimeError("FIT-MANIFEST header mismatch")
        rows = list(reader)
    expected = [f"{arm}-H{block}" for arm in ARMS for block in BLOCKS]
    if [row["fit_id"] for row in rows] != expected:
        raise RuntimeError("fit manifest order or Cartesian grid mismatch")
    return rows


def _read_prediction(path: Path, arm: str, block: int, expected_keys: list[bytes], row_sha: str) -> np.ndarray:
    raw = path.read_bytes()
    if len(raw) < 72 or raw[:16] != PRED_MAGIC:
        raise RuntimeError(f"prediction header invalid: {path.name}")
    version, actual_block, arm_id, count = struct.unpack_from("<IQIQ", raw, 16)
    if (version, actual_block, arm_id, count) != (1, block, ARMS.index(arm), len(expected_keys)):
        raise RuntimeError(f"prediction identity/count mismatch: {path.name}")
    if raw[40:72].hex() != row_sha:
        raise RuntimeError(f"prediction FIT-MANIFEST row hash mismatch: {path.name}")
    if len(raw) != 72 + count * 22:
        raise RuntimeError(f"prediction byte length mismatch: {path.name}")
    logits = np.empty(count, dtype=np.float32)
    seen: set[bytes] = set()
    offset = 72
    for index, expected in enumerate(expected_keys):
        key = raw[offset : offset + 18]
        if key != expected:
            raise RuntimeError(f"prediction row key/order mismatch in {path.name} at {index}")
        if key in seen:
            raise RuntimeError(f"duplicate prediction key in {path.name}")
        seen.add(key)
        logits[index] = struct.unpack_from("<f", raw, offset + 18)[0]
        offset += 22
    if not np.isfinite(logits).all():
        raise RuntimeError(f"nonfinite prediction logit in {path.name}")
    return logits


def integrity(out: Path) -> None:
    preflight = json_read(out / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json")
    sources = verify_manifest_sources(out / "SOURCE-INPUT-MANIFEST.json")
    if sources["canonical_sha256"] != preflight["source_manifest_sha256"] or sources["file_sha256"] != preflight["source_manifest_file_sha256"]:
        raise RuntimeError("source manifest digest differs from preflight")
    if runtime_description() != preflight["runtime"]:
        raise RuntimeError("integrity runtime differs from frozen preflight")
    data = read_raw(out / "RAW-PREDICTORS.bin", out / "RAW-SCORING-TRUTH.bin")
    collection = json_read(out / "NATIVE-COLLECTION-RECEIPT.json")
    if collection.get("status") != "PASS" or collection.get("rows") != data.count:
        raise RuntimeError("native collection receipt missing or inconsistent")
    if (sha_file(out / "RAW-PREDICTORS.bin") != collection.get("predictor_sha256")
            or sha_file(out / "RAW-SCORING-TRUTH.bin") != collection.get("truth_sha256")):
        raise RuntimeError("raw collection bytes changed after collection receipt")
    rows = _manifest_rows(out)
    row_hashes = json_read(out / "FIT-MANIFEST-ROW-HASHES.json")
    manifest_path = out / "FIT-MANIFEST.csv"
    if row_hashes.get("manifest_sha256") != sha_file(manifest_path):
        raise RuntimeError("FIT-MANIFEST file hash mismatch")
    recomputed_row_hashes: dict[str, str] = {}
    for row in rows:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow([row[key] for key in (
            "fit_id", "arm", "holdout_block", "input_width", "train_rows", "heldout_rows",
            "contract_sha256", "source_manifest_sha256", "implementation_executable_sha256",
            "analysis_script_sha256", "feature_hash", "training_row_hash", "training_order_hash",
            "normalization_hash", "initial_tensor_hash", "expected_prediction_path",
        )])
        recomputed_row_hashes[row["fit_id"]] = sha_bytes(buffer.getvalue().encode("utf-8"))
    if recomputed_row_hashes != row_hashes.get("rows"):
        raise RuntimeError("FIT-MANIFEST row hashes do not match serialized rows")
    receipts_dir = out / "fit-receipts"
    prediction_dir = out / "heldout-predictions"
    receipt_files = sorted(path.name for path in receipts_dir.glob("*.json"))
    prediction_files = sorted(path.name for path in prediction_dir.glob("*.bin"))
    expected_receipts = sorted(f"{arm}-H{block}.json" for arm in ARMS for block in BLOCKS)
    expected_predictions = sorted(f"{arm}-H{block}.bin" for arm in ARMS for block in BLOCKS)
    missing_keys = duplicate_keys = extra_keys = nonfinite = 0
    paired_initialization = True
    predictions: dict[str, dict[int, np.ndarray]] = {arm: {} for arm in ARMS}
    init_by_block: dict[int, dict[str, str]] = {block: {} for block in BLOCKS}
    lock_entries = []
    if receipt_files != expected_receipts or prediction_files != expected_predictions:
        raise RuntimeError("expected exactly 16 fit receipts and 16 prediction streams")
    for row in rows:
        fit_id, arm, block = row["fit_id"], row["arm"], int(row["holdout_block"])
        receipt_path = receipts_dir / f"{fit_id}.json"
        receipt = json_read(receipt_path)
        if receipt.get("status") not in (None, "PASS") or receipt.get("finite_status") != "PASS":
            raise RuntimeError(f"fit receipt failed: {fit_id}")
        for field in (
            "contract_sha256", "source_manifest_sha256", "implementation_executable_sha256",
            "analysis_script_sha256", "feature_hash", "training_row_hash", "training_order_hash",
            "normalization_hash", "initial_tensor_hash",
        ):
            if str(receipt[field]) != str(row[field] if field in row else CONTRACT_SHA):
                raise RuntimeError(f"fit receipt mismatch {fit_id}:{field}")
        if receipt["contract_sha256"] != CONTRACT_SHA or receipt["source_manifest_sha256"] != preflight["source_manifest_sha256"]:
            raise RuntimeError(f"fit authority mismatch: {fit_id}")
        if (int(receipt["input_width"]) != int(row["input_width"])
                or int(receipt["train_rows"]) != int(row["train_rows"])
                or int(receipt["heldout_rows"]) != int(row["heldout_rows"])):
            raise RuntimeError(f"fit dimensions/count mismatch: {fit_id}")
        matrix_path = out / "prepared-inputs" / f"{fit_id}.bin"
        matrix_raw = matrix_path.read_bytes()
        if sha_bytes(matrix_raw[32:]) != row["feature_hash"]:
            raise RuntimeError(f"prepared feature bytes changed: {fit_id}")
        matrix = binary_matrix(matrix_path, int(row["input_width"]))
        if not np.isfinite(matrix).all():
            nonfinite += int(matrix.size - np.isfinite(matrix).sum())
            raise RuntimeError(f"nonfinite prepared model input: {fit_id}")
        train_mask = data.blocks != block
        train_row_hash, train_order_hash = training_hashes(data.keys, train_mask)
        if train_row_hash != row["training_row_hash"] or train_order_hash != row["training_order_hash"]:
            raise RuntimeError(f"training row/order hash mismatch: {fit_id}")
        normalization_path = out / "normalization" / f"NORMALIZATION-{block}.bin"
        if sha_file(normalization_path) != row["normalization_hash"]:
            raise RuntimeError(f"normalization hash mismatch: {fit_id}")
        expected_updates = 200 * math.ceil(int(row["train_rows"]) / 2048)
        if int(receipt["update_count"]) != expected_updates:
            raise RuntimeError(f"update count mismatch: {fit_id}")
        if receipt.get("fit_manifest_row_sha256") != row_hashes["rows"].get(fit_id):
            raise RuntimeError(f"fit manifest row digest mismatch: {fit_id}")
        if len(str(receipt.get("final_tensor_hash", ""))) != 64 or len(str(receipt.get("prediction_sha256", ""))) != 64:
            raise RuntimeError(f"fit receipt hash field malformed: {fit_id}")
        init_by_block[block][arm] = str(receipt["initial_tensor_hash"])
        held_keys = [key for key in data.keys if struct.unpack_from("<Q", key, 2)[0] == block]
        pred_path = prediction_dir / f"{fit_id}.bin"
        if sha_file(pred_path) != receipt["prediction_sha256"]:
            raise RuntimeError(f"prediction SHA mismatch: {fit_id}")
        logits = _read_prediction(pred_path, arm, block, held_keys, row_hashes["rows"][fit_id])
        predictions[arm][block] = logits
        lock_entries.append({"fit_id": fit_id, "fit_receipt_sha256": sha_file(receipt_path), "prediction_sha256": receipt["prediction_sha256"], "prediction_path": receipt["prediction_path"]})
    for block in BLOCKS:
        if len({init_by_block[block].get(arm) for arm in ("B", "C", "D")}) != 1:
            paired_initialization = False
    if not paired_initialization:
        raise RuntimeError("B/C/D paired initialization invariant failed")
    lock = json_read(out / "PREDICTION-LOCK.json")
    if lock.get("status") != "PASS" or lock.get("prediction_count") != 16 or lock.get("heldout_truth_opened") is not False:
        raise RuntimeError("prediction lock missing/inconsistent")
    if lock.get("prediction_streams") != lock_entries:
        raise RuntimeError("prediction lock entries differ from independently verified files")
    gate_status = {name: "PASS" for name in (
        "ROW_RECONCILIATION", "FORWARD_PROBABILITY", "B_DETERMINISM", "CD_VALUE_IDENTITY", "REPRESENTATION_INVARIANTS", "JOINT_INVERSION_REPRESENTATION")}
    for filename in ("ROW-RECONCILIATION-RECEIPT.json", "FORWARD-P-RECONCILIATION-RECEIPT.json", "B-DETERMINISM-RECEIPT.json", "CD-MULTISET-RECEIPT.json", "REPRESENTATION-FIXTURE-RECEIPT.json"):
        if json_read(out / filename).get("status") != "PASS":
            raise RuntimeError(f"gate not passing: {filename}")
    receipt = {
        "schema": "F4-SYMMETRY-01-integrity-receipt-v1",
        "status": "PASS",
        "expected_fit_count": 16,
        "actual_fit_count": len(rows),
        "expected_prediction_count": 16,
        "actual_prediction_count": len(prediction_files),
        "expected_row_count": data.count,
        "missing_key_count": missing_keys,
        "duplicate_key_count": duplicate_keys,
        "extra_key_count": extra_keys,
        "nonfinite_count": nonfinite,
        "source_drift_status": "PASS",
        "gate_status": gate_status,
        "paired_BCD_initialization_status": "PASS",
        "prediction_lock_sha256": sha_file(out / "PREDICTION-LOCK.json"),
        "prediction_streams": lock_entries,
        "heldout_truth_state": "SEALED",
        "heldout_truth_opened": False,
    }
    write_json(out / "INTEGRITY-RECEIPT.json", receipt)
    print(json.dumps({"status": "INTEGRITY_PASS", "fit_count": 16, "prediction_count": 16, "truth_state": "SEALED"}, sort_keys=True))


def _balanced_error(prediction: np.ndarray, q: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float | None:
    plus = mask & (y == 1)
    minus = mask & (y == -1)
    if not plus.any() or not minus.any():
        return None
    error = prediction != y
    plus_error = float(np.sum(q[plus] * error[plus]) / np.sum(q[plus]))
    minus_error = float(np.sum(q[minus] * error[minus]) / np.sum(q[minus]))
    return 0.5 * (plus_error + minus_error)


def _signed_margin(logits: np.ndarray, q: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float | None:
    plus = mask & (y == 1)
    minus = mask & (y == -1)
    margin = y.astype(np.float64) * logits.astype(np.float64)
    if plus.any() and minus.any():
        return 0.5 * (float(np.sum(q[plus] * margin[plus]) / np.sum(q[plus])) + float(np.sum(q[minus] * margin[minus]) / np.sum(q[minus])))
    if plus.any() or minus.any():
        selected = plus | minus
        return float(np.sum(q[selected] * margin[selected]) / np.sum(q[selected]))
    return None


def _psi(signs: np.ndarray, q: np.ndarray, native: np.ndarray, reference: np.ndarray) -> dict[str, float | None]:
    magnitude = np.abs(native.astype(np.float64))
    g_abs = np.abs(reference.astype(np.float64))
    reference_sign = np.where(reference > 0, 1, -1)
    weight = q * magnitude * g_abs
    total = float(np.sum(weight))
    if total == 0.0:
        return {"weighted_sign_agreement": None, "psi_prop": None}
    agreement = float(np.sum(weight * (signs == reference_sign)) / total)
    return {"weighted_sign_agreement": agreement, "psi_prop": 2.0 * agreement - 1.0}


def _delivery(signs: np.ndarray, q: np.ndarray, native: np.ndarray, preweight: np.ndarray, reference: np.ndarray) -> float | None:
    magnitude = np.abs(native.astype(np.float64))
    u = np.clip(preweight.astype(np.float64) + magnitude * signs.astype(np.float64), 0.0, 2.0) - preweight.astype(np.float64)
    g = reference.astype(np.float64)
    dot = float(np.sum(q * u * g))
    u_norm = math.sqrt(float(np.sum(q * u * u)))
    g_norm = math.sqrt(float(np.sum(q * g * g)))
    if u_norm == 0.0 or g_norm == 0.0:
        return None
    return dot / (u_norm * g_norm)


def analyze(out: Path) -> None:
    integrity_path = out / "INTEGRITY-RECEIPT.json"
    integrity_receipt = json_read(integrity_path)
    if integrity_receipt.get("status") != "PASS" or integrity_receipt.get("heldout_truth_state") != "SEALED":
        raise RuntimeError("held-out truth remains sealed until integrity passes")
    preflight = json_read(out / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json")
    sources = verify_manifest_sources(out / "SOURCE-INPUT-MANIFEST.json")
    if sources["canonical_sha256"] != preflight["source_manifest_sha256"] or sources["file_sha256"] != preflight["source_manifest_file_sha256"]:
        raise RuntimeError("source manifest changed after integrity PASS")
    if runtime_description() != preflight["runtime"]:
        raise RuntimeError("analysis runtime differs from frozen preflight")
    data = read_raw(out / "RAW-PREDICTORS.bin", out / "RAW-SCORING-TRUTH.bin")
    collection = json_read(out / "NATIVE-COLLECTION-RECEIPT.json")
    if sha_file(out / "RAW-PREDICTORS.bin") != collection.get("predictor_sha256") or sha_file(out / "RAW-SCORING-TRUTH.bin") != collection.get("truth_sha256"):
        raise RuntimeError("raw collection bytes changed after integrity PASS")
    q, y, native, preweight, reference = load_truth_after_integrity(data, integrity_path)
    predictions_by_arm: dict[str, np.ndarray] = {arm: np.empty(data.count, dtype=np.float32) for arm in ARMS}
    row_positions = {key: index for index, key in enumerate(data.keys)}
    for arm in ARMS:
        for block in BLOCKS:
            path = out / "heldout-predictions" / f"{arm}-H{block}.bin"
            raw = path.read_bytes()
            count = struct.unpack_from("<Q", raw, 32)[0]
            for local in range(count):
                offset = 72 + local * 22
                key = raw[offset : offset + 18]
                index = row_positions[key]
                predictions_by_arm[arm][index] = struct.unpack_from("<f", raw, offset + 18)[0]
    pooled: dict[str, dict[str, float]] = {}
    block_metrics: dict[str, dict[str, object]] = {}
    psi_metrics: dict[str, object] = {}
    delivery_metrics: dict[str, float | None] = {}
    all_rows = np.ones(data.count, dtype=bool)
    for arm in ARMS:
        logits = predictions_by_arm[arm].astype(np.float64)
        signs = np.where(logits > 0.0, 1, -1).astype(np.int8)
        error = _balanced_error(signs, q, y, all_rows)
        assert error is not None
        pooled[arm] = {"balanced_error": error, "omega_hat_unclipped": 1.0 - 2.0 * error, "omega_hat_clipped": max(0.0, 1.0 - 2.0 * error), "signed_margin": _signed_margin(logits, q, y, all_rows)}
        block_metrics[arm] = {}
        for block in BLOCKS:
            mask = data.blocks == block
            block_metrics[arm][str(block)] = {
                "rows": int(mask.sum()),
                "class_counts": {"positive": int(np.sum(mask & (y == 1))), "negative": int(np.sum(mask & (y == -1)))},
                "balanced_error": _balanced_error(signs, q, y, mask),
                "omega_hat": (None if _balanced_error(signs, q, y, mask) is None else max(0.0, 1.0 - 2.0 * float(_balanced_error(signs, q, y, mask)))),
                "signed_margin": _signed_margin(logits, q, y, mask),
                "signed_margin_scope": "one_class_q_weighted_Y_times_logit" if len(np.unique(y[mask])) == 1 else "class_balanced_q_weighted",
            }
        psi_metrics[arm] = _psi(signs.astype(np.float64), q, native, reference)
        delivery_metrics[arm] = _delivery(signs.astype(np.float64), q, native, preweight, reference)
    native_signs = np.where(native > 0, 1, -1).astype(np.float64)
    oracle_signs = np.where(reference > 0, 1, -1).astype(np.float64)
    psi_metrics["native_proposed_sign"] = _psi(native_signs, q, native, reference)
    psi_metrics["oracle_reference_sign"] = _psi(oracle_signs, q, native, reference)
    error_b_minus_a = pooled["B"]["balanced_error"] - pooled["A"]["balanced_error"]
    error_c_minus_b = pooled["C"]["balanced_error"] - pooled["B"]["balanced_error"]
    error_d_minus_c = pooled["D"]["balanced_error"] - pooled["C"]["balanced_error"]
    analysis = {
        "schema": "F4-SYMMETRY-01-analysis-v1",
        "status": "QUALIFICATION_ONLY_ANALYSIS_COMPLETE",
        "contract_sha256": CONTRACT_SHA,
        "source_manifest_sha256": preflight["source_manifest_sha256"],
        "rows": data.count,
        "fits": 16,
        "pooled_oof": pooled,
        "error_B_minus_A": error_b_minus_a,
        "primary_error_C_minus_B": error_c_minus_b,
        "primary_error_D_minus_C": error_d_minus_c,
        "per_block": block_metrics,
        "secondary_psi": psi_metrics,
        "secondary_delivery_cosine": delivery_metrics,
        "claim_ceiling": "utility of the declared relational sidecar (C-B); utility of canonical ordering of the same values (D-C)",
        "measured_reach03_result": False,
        "biological_promotion": False,
    }
    analysis_path = out / "F4-SYMMETRY-01-ANALYSIS.json"
    write_json(analysis_path, analysis)
    results = [
        "# F4-SYMMETRY-01 Results",
        "",
        "**Disposition:** qualification-only representation diagnosis. No measured REACH-03 result, biological promotion, native-rule change, or PHENO change follows from this run.",
        "",
        "## HIST provenance",
        "",
        "HIST is a legacy qualification provenance anchor. Its 80D values, including expected-score fields, were excluded from A/B/C/D and it was not fitted here.",
        "",
        "## A: clean admissible baseline",
        "",
        f"Pooled out-of-fold IPW-balanced error = {pooled['A']['balanced_error']:.9g}; clipped Omega-hat = {pooled['A']['omega_hat_clipped']:.9g}.",
        "",
        "## B-A: descriptive width/control contrast",
        "",
        f"error_B - error_A = {error_b_minus_a:.9g}. B is a deterministic 24D transform of fold-normalized A.",
        "",
        "## C-B: primary relational-sidecar contrast",
        "",
        f"error_C - error_B = {error_c_minus_b:.9g}. Negative values favor lower held-out error for the declared relational-sidecar package.",
        "",
        "## D-C: primary canonical-ordering contrast",
        "",
        f"error_D - error_C = {error_d_minus_c:.9g}. Negative values favor lower held-out error when those same tuple values are canonically ordered.",
        "",
        "## Blockwise signed margins",
        "",
    ]
    for arm in ARMS:
        for block in BLOCKS:
            item = block_metrics[arm][str(block)]
            results.append(f"- {arm}, block {block}: balanced error={item['balanced_error']}; signed margin={item['signed_margin']:.9g} ({item['signed_margin_scope']}).")
    results.extend(["", "## Secondary polarity and delivery metrics", ""])
    for arm in ARMS:
        results.append(f"- {arm}: Psi={psi_metrics[arm]['psi_prop']}; delivered cosine={delivery_metrics[arm]}.")
    results.append(f"- Native proposed sign: Psi={psi_metrics['native_proposed_sign']['psi_prop']}.")
    results.append(f"- Oracle reference sign: Psi={psi_metrics['oracle_reference_sign']['psi_prop']}.")
    results.extend(["", "The first-order Psi and delivery cosine are local sidecars. They do not guarantee endpoint capability under bounded multi-step dynamics.", ""])
    with (out / "RESULTS.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(results))
        stream.flush()

    terminal = {
        "schema": "F4-SYMMETRY-01-terminal-receipt-v1",
        "status": "CLOSED_QUALIFICATION_ONLY",
        "controlling_contract_sha256": CONTRACT_SHA,
        "source_manifest_sha256": preflight["source_manifest_sha256"],
        "implementation_executable_sha256": sha_file(out / "bin/fly-reach-03-executor.exe"),
        "analysis_script_sha256": sha_file(ROOT / "scripts/f4_symmetry_01_integrity.py"),
        "measured_seed_namespace": "qualification-v2-only",
        "expected_rows": 13420,
        "actual_rows": data.count,
        "expected_fits": 16,
        "actual_fits": 16,
        "integrity_status": "PASS",
        "heldout_truth_opened_after_integrity": True,
        "primary_error_C_minus_B": error_c_minus_b,
        "primary_error_D_minus_C": error_d_minus_c,
        "qualification_only": True,
        "biological_promotion": False,
        "PHENO_status_unchanged": True,
    }
    write_json(out / "F4-SYMMETRY-01-TERMINAL-RECEIPT.json", terminal)
    print(json.dumps({"status": terminal["status"], "primary_C_minus_B": error_c_minus_b, "primary_D_minus_C": error_d_minus_c, "truth_opened_after_integrity": True}, sort_keys=True))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("integrity", "analyze"))
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/f4-symmetry-01")
    args = parser.parse_args()
    if args.phase == "integrity":
        integrity(args.out)
    else:
        analyze(args.out)


if __name__ == "__main__":
    main()
