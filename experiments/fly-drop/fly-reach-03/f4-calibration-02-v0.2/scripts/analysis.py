"""Score the locked D-only calibration predictions after integrity PASS."""
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]
sys.path.insert(0, str(STUDY / "f4-symmetry-03" / "scripts"))
from common import (  # noqa: E402
    PRED_MAGIC, REPO, canonical_json, read_json, read_predictors, require,
    sha_bytes, sha_file, write_json,
)


def _read_prediction(path: Path, block: int, keys: list[bytes], row_hash: str) -> np.ndarray:
    raw = path.read_bytes()
    require(len(raw) >= 72 and raw[:16] == PRED_MAGIC, f"prediction header invalid: {path.name}")
    version, heldout, arm_id, count = struct.unpack_from("<IQIQ", raw, 16)
    require((version, heldout, arm_id, count) == (1, block, 1, len(keys)), f"prediction identity/count mismatch: {path.name}")
    require(raw[40:72].hex() == row_hash and len(raw) == 72 + 22 * count, f"prediction digest/size mismatch: {path.name}")
    logits = np.empty(count, dtype=np.float32)
    offset = 72
    for index, key in enumerate(keys):
        require(raw[offset:offset + 18] == key, f"prediction key/order mismatch {path.name}:{index}")
        logits[index] = struct.unpack_from("<f", raw, offset + 18)[0]
        offset += 22
    require(np.isfinite(logits).all(), f"nonfinite held-out logits: {path.name}")
    return logits


def _open_truth(data) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = data.truth_path.read_bytes()
    n = data.count
    p = np.ndarray(n, dtype="<f8", buffer=raw, offset=50, strides=(39,)).copy()
    y = np.ndarray(n, dtype="i1", buffer=raw, offset=58, strides=(39,)).copy()
    native = np.ndarray(n, dtype="<f4", buffer=raw, offset=59, strides=(39,)).copy()
    preweight = np.ndarray(n, dtype="<f4", buffer=raw, offset=63, strides=(39,)).copy()
    reference = np.ndarray(n, dtype="<f4", buffer=raw, offset=67, strides=(39,)).copy()
    require(np.isfinite(p).all() and (p > 0.0).all() and (p <= 1.0).all(), "invalid inclusion probability")
    require(np.isin(y, (-1, 1)).all(), "common population contains zero or nonbinary target")
    require(np.isfinite(native).all() and np.isfinite(preweight).all() and np.isfinite(reference).all(), "nonfinite calibration truth")
    return 1.0 / p, y, native.astype(np.float64), preweight.astype(np.float64), reference.astype(np.float64)


def _balanced_error(sign: np.ndarray, q: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float | None:
    positive = mask & (y == 1)
    negative = mask & (y == -1)
    if not positive.any() or not negative.any():
        return None
    wrong = sign != y
    e_pos = float(np.sum(q[positive] * wrong[positive], dtype=np.float64) / np.sum(q[positive], dtype=np.float64))
    e_neg = float(np.sum(q[negative] * wrong[negative], dtype=np.float64) / np.sum(q[negative], dtype=np.float64))
    return 0.5 * (e_pos + e_neg)


def _margin(logits: np.ndarray, q: np.ndarray, y: np.ndarray, mask: np.ndarray) -> tuple[float | None, str]:
    positive = mask & (y == 1)
    negative = mask & (y == -1)
    values = y.astype(np.float64) * logits.astype(np.float64)
    if positive.any() and negative.any():
        p = float(np.sum(q[positive] * values[positive], dtype=np.float64) / np.sum(q[positive], dtype=np.float64))
        n = float(np.sum(q[negative] * values[negative], dtype=np.float64) / np.sum(q[negative], dtype=np.float64))
        return 0.5 * (p + n), "class_balanced_ipw"
    selected = positive | negative
    if selected.any():
        return float(np.sum(q[selected] * values[selected], dtype=np.float64) / np.sum(q[selected], dtype=np.float64)), "single_class_ipw"
    return None, "undefined"


def _concentration(weights: np.ndarray) -> dict[str, object]:
    total = float(np.sum(weights, dtype=np.float64))
    if len(weights) == 0 or total <= 0.0:
        return {"leverage_total": total, "effective_sample_size": 0.0,
                "top_1pct_share": None, "top_5pct_share": None, "top_20pct_share": None}
    squared = float(np.sum(weights * weights, dtype=np.float64))
    ordered = np.sort(weights)[::-1]
    shares: dict[str, float] = {}
    for label, fraction in (("1pct", .01), ("5pct", .05), ("20pct", .20)):
        count = max(1, math.ceil(len(ordered) * fraction))
        shares[f"top_{label}_share"] = float(np.sum(ordered[:count], dtype=np.float64) / total)
    return {"leverage_total": total, "effective_sample_size": total * total / squared if squared > 0.0 else 0.0, **shares}


def _score(mask: np.ndarray, *, q: np.ndarray, y: np.ndarray, logits: np.ndarray,
           native: np.ndarray, preweight: np.ndarray, reference: np.ndarray) -> dict[str, object]:
    positive = mask & (y == 1)
    negative = mask & (y == -1)
    signs = np.where(logits > 0.0, 1, -1).astype(np.int8)
    epsilon = _balanced_error(signs, q, y, mask)
    raw_omega = None if epsilon is None else 1.0 - 2.0 * epsilon
    clipped_omega = None if raw_omega is None else max(0.0, raw_omega)
    score_weights = q[mask] * np.abs(native[mask]) * np.abs(reference[mask])
    score_total = float(np.sum(score_weights, dtype=np.float64))
    psi = None if score_total <= 0.0 else 2.0 * float(
        np.sum(score_weights * (signs[mask] == y[mask]), dtype=np.float64) / score_total
    ) - 1.0
    native_sign = np.where(native >= 0.0, 1, -1).astype(np.int8)
    oracle_sign = np.where(reference >= 0.0, 1, -1).astype(np.int8)
    psi_native = None if score_total <= 0.0 else 2.0 * float(
        np.sum(score_weights * (native_sign[mask] == y[mask]), dtype=np.float64) / score_total
    ) - 1.0
    psi_reference = None if score_total <= 0.0 else 2.0 * float(
        np.sum(score_weights * (oracle_sign[mask] == y[mask]), dtype=np.float64) / score_total
    ) - 1.0
    delivered = np.clip(preweight[mask] + np.abs(native[mask]) * signs[mask], 0.0, 2.0) - preweight[mask]
    grad = reference[mask]
    dot = float(np.sum(q[mask] * delivered * grad, dtype=np.float64))
    u_norm = math.sqrt(float(np.sum(q[mask] * delivered * delivered, dtype=np.float64)))
    g_norm = math.sqrt(float(np.sum(q[mask] * grad * grad, dtype=np.float64)))
    eta = None if u_norm == 0.0 or g_norm == 0.0 else dot / (u_norm * g_norm)
    signed_margin, margin_scope = _margin(logits, q, y, mask)
    evaluable = bool(positive.any() and negative.any())
    return {
        "rows": int(mask.sum()),
        "class_counts": {"positive": int(positive.sum()), "negative": int(negative.sum())},
        "evaluable": evaluable,
        "balanced_error": epsilon,
        "omega_hat_unclipped": raw_omega,
        "omega_hat_clipped": clipped_omega,
        "signed_margin": signed_margin,
        "signed_margin_scope": margin_scope,
        "psi_prop": psi,
        "psi_native_sign": psi_native,
        "psi_reference_sign": psi_reference,
        "eta_del": eta,
        "leverage_concentration": _concentration(score_weights),
    }


def analyze(run: Path) -> None:
    integrity_path = run / "INTEGRITY-RECEIPT.json"
    integrity = read_json(integrity_path)
    require(integrity.get("status") == "PASS" and integrity.get("heldout_truth_state") == "SEALED" and
            integrity.get("heldout_truth_values_opened") is False, "analysis requires a sealed-truth integrity PASS")
    manifest_path = run / "EXECUTION-MANIFEST.json"
    seal = read_json(run / "PREEXECUTION-SEAL.json")
    require(sha_file(manifest_path) == seal["execution_manifest_file_sha256"], "execution manifest changed")
    manifest = read_json(manifest_path)
    source = read_json(run / "SOURCE-INPUT-MANIFEST.json")
    for entry in source["entries"]:
        path = REPO.joinpath(*str(entry["path"]).split("/"))
        require(path.is_file() and path.stat().st_size == entry["byte_length"] and sha_file(path) == entry["sha256"],
                f"sealed source/input drift: {entry['path']}")
    require(sha_bytes(canonical_json(source)) == manifest["source_manifest_canonical_sha256"], "source canonical hash changed")
    require(sha_file(run / "SOURCE-INPUT-MANIFEST.json") == manifest["source_manifest_file_sha256"], "source manifest file changed")

    blocks = [int(value) for value in manifest["block_ids"]]
    staging = run / "collection-staging"
    data = read_predictors(staging / "RAW-PREDICTORS.bin", staging / "RAW-SCORING-TRUTH.bin", blocks)
    row_hashes = read_json(run / "FIT-MANIFEST-ROW-HASHES.json")["rows"]
    logits = np.full(data.count, np.nan, dtype=np.float32)
    for block in blocks:
        mask = data.blocks == block
        keys = [key for key, selected in zip(data.keys, mask, strict=True) if selected]
        local = _read_prediction(run / "heldout-predictions" / f"D-H{block}.bin", block, keys, row_hashes[f"D-H{block}"])
        logits[mask] = local
    require(np.isfinite(logits).all(), "out-of-fold predictions do not cover the full common population")

    # Opening target and reference values is permitted only after the receipt above.
    q, y, native, preweight, reference = _open_truth(data)
    pooled_mask = np.ones(data.count, dtype=bool)
    pooled = _score(pooled_mask, q=q, y=y, logits=logits, native=native, preweight=preweight, reference=reference)
    by_block: list[dict[str, object]] = []
    for block in blocks:
        mask = data.blocks == block
        score = _score(mask, q=q, y=y, logits=logits, native=native, preweight=preweight, reference=reference)
        by_block.append({"block_id": block, **score})

    evaluable = [row for row in by_block if row["evaluable"]]
    support_pass = len(evaluable) >= 10
    fold_pass = support_pass and all(float(row["omega_hat_clipped"]) >= 0.70 for row in evaluable)
    pooled_pass = (pooled["balanced_error"] is not None and
                   float(pooled["balanced_error"]) <= 0.10 and float(pooled["omega_hat_clipped"]) >= 0.80)
    if not support_pass:
        disposition = "NOT_EVALUABLE_SUPPORT"
    elif fold_pass and pooled_pass:
        disposition = "PASS_F4_CALIBRATION"
    else:
        disposition = "CALIBRATION_GATE_FAIL"

    analysis = {
        "schema": "F4-CALIBRATION-02-v0.2-analysis-v1",
        "run_id": manifest["run_id"], "contract_sha256": manifest["contract_sha256"],
        "integrity_receipt_sha256": sha_file(integrity_path),
        "qualification_only": True, "measured_reach03_authorized": False,
        "truth_opened_after_integrity_pass": True,
        "row_count": data.count, "block_ids": blocks,
        "scoring": "q=1/p_inclusion; equal IPW class weighting; logit zero predicts negative",
        "gate": {
            "minimum_evaluable_blocks": 10, "total_blocks": 12,
            "evaluable_blocks": len(evaluable), "evaluable_block_ids": [int(row["block_id"]) for row in evaluable],
            "support_pass": support_pass, "every_evaluable_block_omega_hat_min": 0.70,
            "evaluable_block_gate_pass": fold_pass,
            "pooled_balanced_error_max": 0.10, "pooled_omega_hat_min": 0.80,
            "pooled_gate_pass": pooled_pass,
        },
        "pooled_D": pooled,
        "blockwise_D": by_block,
        "disposition": disposition,
        "claim_boundary": "Qualification calibration only. A pass makes a separately sealed measured REACH-03 preparation eligible; it does not authorize measured execution, a polarity controller, PHENO, or biological promotion.",
    }
    write_json(run / "ANALYSIS.json", analysis)

    fields = [
        "block_id", "rows", "positive_count", "negative_count", "evaluable", "balanced_error",
        "omega_hat_unclipped", "omega_hat_clipped", "signed_margin", "signed_margin_scope",
        "psi_prop", "psi_native_sign", "psi_reference_sign", "eta_del", "leverage_total",
        "leverage_ess", "leverage_top_1pct_share", "leverage_top_5pct_share", "leverage_top_20pct_share",
        "evaluable_block_gate_pass",
    ]
    with (run / "BLOCK-OUTCOMES.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in by_block:
            classes = row["class_counts"]
            concentration = row["leverage_concentration"]
            writer.writerow({
                "block_id": row["block_id"], "rows": row["rows"],
                "positive_count": classes["positive"], "negative_count": classes["negative"],
                "evaluable": row["evaluable"], "balanced_error": row["balanced_error"],
                "omega_hat_unclipped": row["omega_hat_unclipped"],
                "omega_hat_clipped": row["omega_hat_clipped"],
                "signed_margin": row["signed_margin"], "signed_margin_scope": row["signed_margin_scope"],
                "psi_prop": row["psi_prop"], "psi_native_sign": row["psi_native_sign"],
                "psi_reference_sign": row["psi_reference_sign"], "eta_del": row["eta_del"],
                "leverage_total": concentration["leverage_total"],
                "leverage_ess": concentration["effective_sample_size"],
                "leverage_top_1pct_share": concentration["top_1pct_share"],
                "leverage_top_5pct_share": concentration["top_5pct_share"],
                "leverage_top_20pct_share": concentration["top_20pct_share"],
                "evaluable_block_gate_pass": None if not row["evaluable"] else float(row["omega_hat_clipped"]) >= 0.70,
            })
    with (run / "POOLED-OUTCOME.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(pooled, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")

    err = pooled["balanced_error"]
    omega = pooled["omega_hat_clipped"]
    lines = [
        "# F4-CALIBRATION-02 Results", "",
        "Fresh ordinary qualification blocks; frozen D-only calibration candidate.", "",
        f"- Disposition: **{disposition}**.",
        f"- Held-out U* rows: {data.count:,}.",
        f"- Evaluable blocks: {len(evaluable)}/12; minimum required: 10.",
        f"- Pooled IPW-balanced error: {err if err is not None else 'undefined'} (maximum 0.10).",
        f"- Pooled clipped Omega-hat: {omega if omega is not None else 'undefined'} (minimum 0.80).",
        f"- Pooled unclipped Omega-hat: {pooled['omega_hat_unclipped'] if pooled['omega_hat_unclipped'] is not None else 'undefined'}.",
        f"- Every evaluable block meets Omega-hat >= 0.70: {fold_pass}.",
        "",
        "Empty and one-class blocks remain in the panel. Their balanced-error scores are undefined; available rows remain in pooled scoring.",
        "Leverage-weighted Psi and its concentration are secondary diagnostics; they are not calibration gates and do not imply trajectory improvement.",
        "",
        "Measured REACH-03 remains unauthorized by this calibration contract. A pass permits preparation of a separate measured seal only.",
        "",
        "See `BLOCK-OUTCOMES.csv` for all twelve folds and `ANALYSIS.json` for the full gate receipt.", "",
    ]
    with (run / "RESULTS.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
    receipt = {
        "schema": "F4-CALIBRATION-02-v0.2-analysis-receipt-v1", "status": "PASS",
        "analysis_script_sha256": sha_file(Path(__file__)),
        "integrity_receipt_sha256": sha_file(integrity_path),
        "analysis_sha256": sha_file(run / "ANALYSIS.json"),
        "block_outcomes_sha256": sha_file(run / "BLOCK-OUTCOMES.csv"),
        "pooled_outcome_sha256": sha_file(run / "POOLED-OUTCOME.json"),
        "results_sha256": sha_file(run / "RESULTS.md"),
        "disposition": disposition, "heldout_truth_opened_after_integrity_pass": True,
        "qualification_only": True, "measured_reach03_authorized": False,
    }
    write_json(run / "ANALYSIS-RECEIPT.json", receipt)
    print(json.dumps({"status": disposition, "rows": data.count, "evaluable_blocks": len(evaluable),
                      "pooled_balanced_error": err, "pooled_omega_hat": omega}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    analyze(parser.parse_args().run.resolve())
