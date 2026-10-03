"""Exploratory leverage localization on locked F4-SYMMETRY-01 RUN4 predictions.

This diagnostic performs no fits and writes only to a new F4-SYMMETRY-02
artifact directory. The analysis contract must be frozen before --analyze.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT.parent))

from f4_symmetry_01_common import (  # noqa: E402
    ARMS, BLOCKS, CONTRACT_SHA, PRED_MAGIC, ROOT, TRUTH_WIDTH,
    json_read, load_truth_after_integrity, read_raw, sha_bytes, sha_file,
    write_json,
)

RUN = ROOT / "artifacts/f4-symmetry-01-RUN4"
OUT = ROOT / "artifacts/f4-symmetry-02-leverage-localization"
QUANTILES = (0.2, 0.4, 0.6, 0.8)
DIMENSIONS = ("block", "abs_reference_g_quintile", "native_magnitude_quintile",
              "leverage_quintile", "cue_incidence_pattern")


def _sha(path: Path) -> str:
    return sha_file(path)


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()


def freeze_contract(out: Path) -> None:
    if out.exists():
        raise RuntimeError(f"diagnostic output already exists; refusing overwrite: {out}")
    out.mkdir(parents=True)
    integrity_path = RUN / "INTEGRITY-RECEIPT.json"
    lock_path = RUN / "PREDICTION-LOCK.json"
    integrity = json_read(integrity_path)
    lock = json_read(lock_path)
    if integrity.get("status") != "PASS":
        raise RuntimeError("RUN4 integrity receipt is not PASS")
    if lock.get("status") != "PASS" or lock.get("prediction_count") != 16:
        raise RuntimeError("RUN4 prediction lock is not complete")
    script_hash = _sha(SCRIPT)
    collection = json_read(RUN / "NATIVE-COLLECTION-RECEIPT.json")
    contract = {
        "schema": "F4-SYMMETRY-02-leverage-localization-contract-v1",
        "status": "FROZEN_BEFORE_DERIVED_DIAGNOSTICS",
        "analysis_class": "EXPLORATORY_POST_OUTCOME_QUALIFICATION_ONLY",
        "parent_contract_sha256": CONTRACT_SHA,
        "parent_identity": "F4-SYMMETRY-01-RUN4",
        "parent_integrity_receipt_sha256": _sha(integrity_path),
        "parent_prediction_lock_sha256": _sha(lock_path),
        "predictor_sha256": _sha(RUN / "RAW-PREDICTORS.bin"),
        "scoring_truth_sha256": _sha(RUN / "RAW-SCORING-TRUTH.bin"),
        "collection_receipt_sha256": _sha(RUN / "NATIVE-COLLECTION-RECEIPT.json"),
        "collection_predictor_sha256": collection["predictor_sha256"],
        "collection_truth_sha256": collection["truth_sha256"],
        "analysis_script_sha256": script_hash,
        "row_population": "all 13,420 existing RUN4 U* rows; no refitting, resampling, or row exclusion",
        "prediction_sign_rule": "+1 when held-out logit > 0; otherwise -1, matching RUN4 scoring",
        "native_magnitude": "m=abs(native proposed delta) from the locked RUN4 scoring truth",
        "row_leverage_weight": "w=q*m*abs(g), where q is the frozen inclusion weight",
        "target_sign": "y=+1 when g>0 else -1; all RUN4 rows are on the already-frozen nonzero target channel",
        "delta_psi_row": "2*w*(I[D sign correct]-I[C sign correct])/sum_all(w)",
        "subgroup_metrics": [
            "row_count", "leverage_weight", "leverage_share_of_global", "psi_C_local",
            "psi_D_local", "delta_psi_local", "delta_psi_global_contribution",
            "disagreement_row_fraction", "disagreement_leverage_fraction",
            "D_weighted_accuracy_on_disagreements", "disagreement_delta_psi_global_contribution",
        ],
        "groupings": {
            "block": "the four frozen RUN4 block IDs; include all blocks, including one-class 303003",
            "abs_reference_g_quintile": "pooled unweighted empirical quintiles of abs(g), NumPy linear quantiles at 20/40/60/80%; ties go to the higher bin via searchsorted(side=right)",
            "native_magnitude_quintile": "pooled unweighted empirical quintiles of abs(native proposed delta), same quantile/tie rule",
            "leverage_quintile": "pooled unweighted empirical quintiles of q*abs(native proposed delta)*abs(g), same quantile/tie rule",
            "cue_incidence_pattern": "four incidence bits in stored absolute cue-slot order; bit c is tuple[c].incidence; pattern integer is sum(bit_c<<c)",
        },
        "uncertainty": "none; this is a deterministic decomposition of the already-opened RUN4 qualification predictions, not an inferential estimate",
        "prohibited": ["new fits", "new seeds", "prediction changes", "row replacement", "measured REACH-03 namespace", "biological promotion", "PHENO change"],
    }
    write_json(out / "ANALYSIS-CONTRACT.json", contract)
    print(json.dumps({"status": "CONTRACT_FROZEN", "output": str(out), "script_sha256": script_hash}, sort_keys=True))


def _load_predictions() -> tuple[dict[str, list[float]], dict[str, str]]:
    integrity = json_read(RUN / "INTEGRITY-RECEIPT.json")
    lock_path = RUN / "PREDICTION-LOCK.json"
    lock = json_read(lock_path)
    if integrity.get("status") != "PASS" or lock.get("status") != "PASS":
        raise RuntimeError("RUN4 integrity or prediction lock failed")
    if integrity.get("heldout_truth_state") not in ("SEALED", "OPENED_AFTER_INTEGRITY"):
        raise RuntimeError("RUN4 truth state is not integrity-gated")
    if len(lock.get("prediction_streams", [])) != 16:
        raise RuntimeError("prediction lock does not contain 16 streams")
    data = read_raw(RUN / "RAW-PREDICTORS.bin", RUN / "RAW-SCORING-TRUTH.bin")
    key_position = {key: pos for pos, key in enumerate(data.keys)}
    if len(key_position) != data.count:
        raise RuntimeError("duplicate row key in locked predictor set")
    pred = {arm: [math.nan] * data.count for arm in ("C", "D")}
    expected_keys_by_block = {
        block: [key for key in data.keys if struct.unpack_from("<Q", key, 2)[0] == block]
        for block in BLOCKS
    }
    stream_hashes: dict[str, str] = {}
    lock_entries = {str(item["fit_id"]): item for item in lock["prediction_streams"]}
    for arm in ("C", "D"):
        for block in BLOCKS:
            fit_id = f"{arm}-H{block}"
            entry = lock_entries.get(fit_id)
            if entry is None:
                raise RuntimeError(f"missing locked prediction entry {fit_id}")
            fit_receipt = RUN / "fit-receipts" / f"{fit_id}.json"
            path = RUN / str(entry["prediction_path"])
            if _sha(fit_receipt) != entry["fit_receipt_sha256"] or _sha(path) != entry["prediction_sha256"]:
                raise RuntimeError(f"locked receipt/prediction hash mismatch for {fit_id}")
            raw = path.read_bytes()
            if len(raw) < 72 or raw[:16] != PRED_MAGIC:
                raise RuntimeError(f"malformed prediction stream {fit_id}")
            version, got_block, arm_id, count = struct.unpack_from("<IQIQ", raw, 16)
            expected_keys = expected_keys_by_block[block]
            if (version, got_block, arm_id, count) != (1, block, ("A", "B", "C", "D").index(arm), len(expected_keys)):
                raise RuntimeError(f"prediction identity/count mismatch for {fit_id}")
            row_hashes = json_read(RUN / "FIT-MANIFEST-ROW-HASHES.json")["rows"]
            if raw[40:72].hex() != row_hashes[fit_id] or len(raw) != 72 + 22 * count:
                raise RuntimeError(f"prediction manifest/length mismatch for {fit_id}")
            offset = 72
            for expected_key in expected_keys:
                key = raw[offset:offset + 18]
                if key != expected_key:
                    raise RuntimeError(f"prediction row order mismatch for {fit_id}")
                value = struct.unpack_from("<f", raw, offset + 18)[0]
                if not math.isfinite(value):
                    raise RuntimeError(f"nonfinite prediction for {fit_id}")
                pred[arm][key_position[key]] = value
                offset += 22
            stream_hashes[fit_id] = _sha(path)
    for arm in pred:
        if any(not math.isfinite(value) for value in pred[arm]):
            raise RuntimeError(f"missing prediction rows for {arm}")
    return pred, stream_hashes


def _quantile_bins(values: Any) -> tuple[Any, list[float], list[str]]:
    import numpy as np
    x = np.asarray(values, dtype=np.float64)
    cuts = np.quantile(x, QUANTILES, method="linear")
    codes = np.searchsorted(cuts, x, side="right")
    labels = [f"Q{i+1}" for i in range(5)]
    return codes, [float(value) for value in cuts], labels


def _group_rows(name: str, values: Any, labels: list[str], codes: list[int] | None = None) -> list[tuple[str, Any]]:
    import numpy as np
    array = np.asarray(values)
    groups = []
    code_values = list(range(len(labels))) if codes is None else codes
    if len(code_values) != len(labels):
        raise RuntimeError(f"label/code count mismatch for {name}")
    for code, label in zip(code_values, labels, strict=True):
        mask = array == code
        if mask.any():
            groups.append((label, mask))
    if not groups:
        raise RuntimeError(f"no groups for {name}")
    return groups


def _metrics(mask: Any, *, q: Any, m: Any, g: Any, y: Any, c_sign: Any, d_sign: Any,
             global_leverage: float) -> dict[str, Any]:
    import numpy as np
    w = q[mask] * m[mask] * np.abs(g[mask])
    denom = float(w.sum(dtype=np.float64))
    if denom <= 0.0:
        raise RuntimeError("a diagnostic group has zero leverage weight")
    c_correct = c_sign[mask] == y[mask]
    d_correct = d_sign[mask] == y[mask]
    delta_mass = float(np.sum(w * (d_correct.astype(np.float64) - c_correct.astype(np.float64)), dtype=np.float64))
    disagree = c_sign[mask] != d_sign[mask]
    disagree_mass = float(w[disagree].sum(dtype=np.float64))
    psi_c = 2.0 * float(np.sum(w * c_correct, dtype=np.float64)) / denom - 1.0
    psi_d = 2.0 * float(np.sum(w * d_correct, dtype=np.float64)) / denom - 1.0
    global_contribution = 2.0 * delta_mass / global_leverage
    d_disagree_accuracy = None
    if disagree_mass > 0.0:
        d_disagree_accuracy = float(np.sum(w[disagree] * d_correct[disagree], dtype=np.float64) / disagree_mass)
    return {
        "row_count": int(mask.sum()),
        "leverage_weight": denom,
        "leverage_share_of_global": denom / global_leverage,
        "psi_C_local": psi_c,
        "psi_D_local": psi_d,
        "delta_psi_local": psi_d - psi_c,
        "delta_psi_global_contribution": global_contribution,
        "disagreement_row_fraction": float(disagree.mean()),
        "disagreement_leverage_fraction": disagree_mass / denom,
        "D_weighted_accuracy_on_disagreements": d_disagree_accuracy,
        "disagreement_delta_psi_global_contribution": global_contribution,
    }


def analyze(out: Path) -> None:
    import numpy as np
    contract_path = out / "ANALYSIS-CONTRACT.json"
    contract = json_read(contract_path)
    if contract.get("schema") != "F4-SYMMETRY-02-leverage-localization-contract-v1":
        raise RuntimeError("diagnostic contract schema mismatch")
    if contract.get("status") != "FROZEN_BEFORE_DERIVED_DIAGNOSTICS":
        raise RuntimeError("diagnostic contract not frozen")
    if _sha(SCRIPT) != contract.get("analysis_script_sha256"):
        raise RuntimeError("analysis script changed after contract freeze")
    integrity_path = RUN / "INTEGRITY-RECEIPT.json"
    lock_path = RUN / "PREDICTION-LOCK.json"
    inputs = {
        "integrity_receipt_sha256": _sha(integrity_path),
        "prediction_lock_sha256": _sha(lock_path),
        "predictor_sha256": _sha(RUN / "RAW-PREDICTORS.bin"),
        "scoring_truth_sha256": _sha(RUN / "RAW-SCORING-TRUTH.bin"),
        "collection_receipt_sha256": _sha(RUN / "NATIVE-COLLECTION-RECEIPT.json"),
    }
    for field, actual in inputs.items():
        contract_field = "parent_" + field if field.startswith(("integrity_", "prediction_")) else field
        # Predictor and truth hashes are stored directly in the frozen contract.
        expected = contract.get(contract_field)
        if expected is None and field in ("integrity_receipt_sha256", "prediction_lock_sha256"):
            expected = contract.get("parent_" + field)
        if expected != actual:
            raise RuntimeError(f"frozen input hash mismatch: {field}")
    data = read_raw(RUN / "RAW-PREDICTORS.bin", RUN / "RAW-SCORING-TRUTH.bin")
    collection = json_read(RUN / "NATIVE-COLLECTION-RECEIPT.json")
    if inputs["predictor_sha256"] != collection["predictor_sha256"] or inputs["scoring_truth_sha256"] != collection["truth_sha256"]:
        raise RuntimeError("raw scoring bytes differ from native collection receipt")
    q, target, native, preweight, reference = load_truth_after_integrity(data, integrity_path)
    del preweight  # Only used by the separate delivery metric, not this localization.
    if not np.isin(target, (-1, 1)).all() or np.any(reference == 0.0):
        raise RuntimeError("RUN4 scoring set is not exactly the frozen nonzero target channel")
    if not np.array_equal(target.astype(np.int8), np.where(reference > 0.0, 1, -1).astype(np.int8)):
        raise RuntimeError("scoring target does not match the reference sign")
    if np.any(q <= 0.0) or not np.isfinite(q).all():
        raise RuntimeError("invalid inclusion weights")
    m = np.abs(native.astype(np.float64))
    g = reference.astype(np.float64)
    if np.any(m <= 0.0) or not np.isfinite(m).all() or not np.isfinite(g).all():
        raise RuntimeError("invalid native magnitude or reference value")
    target_sign = np.where(g > 0.0, 1, -1).astype(np.int8)
    predictions, prediction_hashes = _load_predictions()
    c_sign = np.where(np.asarray(predictions["C"]) > 0.0, 1, -1).astype(np.int8)
    d_sign = np.where(np.asarray(predictions["D"]) > 0.0, 1, -1).astype(np.int8)
    leverage = q * m * np.abs(g)
    total_leverage = float(leverage.sum(dtype=np.float64))
    if not math.isfinite(total_leverage) or total_leverage <= 0.0:
        raise RuntimeError("invalid total leverage mass")
    correct_c = c_sign == target_sign
    correct_d = d_sign == target_sign
    psi_c = 2.0 * float(np.sum(leverage * correct_c, dtype=np.float64)) / total_leverage - 1.0
    psi_d = 2.0 * float(np.sum(leverage * correct_d, dtype=np.float64)) / total_leverage - 1.0
    row_delta = 2.0 * leverage * (correct_d.astype(np.float64) - correct_c.astype(np.float64)) / total_leverage
    disagreements = c_sign != d_sign
    delta = float(row_delta.sum(dtype=np.float64))
    if abs(delta - (psi_d - psi_c)) > 1e-12:
        raise RuntimeError("row delta contributions do not reconstruct pooled DeltaPsi")
    if np.any(row_delta[~disagreements] != 0.0):
        raise RuntimeError("DeltaPsi contribution appears outside the C/D disagreement set")
    g_codes, g_cuts, qlabels = _quantile_bins(np.abs(g))
    m_codes, m_cuts, _ = _quantile_bins(m)
    l_codes, l_cuts, _ = _quantile_bins(leverage)
    patterns = np.zeros(data.count, dtype=np.uint8)
    for cue in range(4):
        patterns |= (data.tuples["incidence"][:, cue].astype(np.uint8) << cue)
    groups: list[dict[str, Any]] = []
    all_mask = np.ones(data.count, dtype=bool)
    dimensions: list[tuple[str, Any, list[str], list[int] | None]] = [
        ("block", data.blocks, [str(block) for block in BLOCKS], list(BLOCKS)),
        ("abs_reference_g_quintile", g_codes, qlabels, None),
        ("native_magnitude_quintile", m_codes, qlabels, None),
        ("leverage_quintile", l_codes, qlabels, None),
    ]
    for dim, codes, labels, group_codes in dimensions:
        for label, mask in _group_rows(dim, codes, labels, group_codes):
            metrics = _metrics(mask, q=q, m=m, g=g, y=target_sign, c_sign=c_sign,
                               d_sign=d_sign, global_leverage=total_leverage)
            groups.append({"dimension": dim, "group": label, **metrics})
    pattern_labels = sorted(int(v) for v in np.unique(patterns))
    for pattern in pattern_labels:
        mask = patterns == pattern
        metrics = _metrics(mask, q=q, m=m, g=g, y=target_sign, c_sign=c_sign,
                           d_sign=d_sign, global_leverage=total_leverage)
        groups.append({"dimension": "cue_incidence_pattern", "group": f"{pattern:04b}", **metrics})
    global_metrics = _metrics(all_mask, q=q, m=m, g=g, y=target_sign, c_sign=c_sign,
                              d_sign=d_sign, global_leverage=total_leverage)
    global_metrics.update({
        "psi_C_from_RUN4": psi_c,
        "psi_D_from_RUN4": psi_d,
        "delta_psi_row_sum": delta,
        "disagreement_rows": int(disagreements.sum()),
        "disagreement_row_fraction": float(disagreements.mean()),
        "disagreement_leverage_fraction": float(leverage[disagreements].sum(dtype=np.float64) / total_leverage),
        "D_weighted_accuracy_on_disagreements": float(np.sum(leverage[disagreements] * correct_d[disagreements], dtype=np.float64) / leverage[disagreements].sum(dtype=np.float64)) if disagreements.any() else None,
        "C_weighted_accuracy_on_disagreements": float(np.sum(leverage[disagreements] * correct_c[disagreements], dtype=np.float64) / leverage[disagreements].sum(dtype=np.float64)) if disagreements.any() else None,
        "all_delta_psi_is_on_disagreement_set": bool(np.all(row_delta[~disagreements] == 0.0)),
    })
    fields = ["dimension", "group", "row_count", "leverage_weight", "leverage_share_of_global",
              "psi_C_local", "psi_D_local", "delta_psi_local", "delta_psi_global_contribution",
              "disagreement_row_fraction", "disagreement_leverage_fraction",
              "D_weighted_accuracy_on_disagreements", "disagreement_delta_psi_global_contribution"]
    _write_csv(out / "LEVERAGE-LOCALIZATION.csv", groups, fields)
    result = {
        "schema": "F4-SYMMETRY-02-leverage-localization-v1",
        "status": "EXPLORATORY_POST_OUTCOME_QUALIFICATION_ONLY_COMPLETE",
        "parent_identity": "F4-SYMMETRY-01-RUN4",
        "analysis_contract_sha256": _sha(contract_path),
        "analysis_script_sha256": _sha(SCRIPT),
        "input_hashes": inputs,
        "locked_prediction_hashes_C_D": prediction_hashes,
        "rows": data.count,
        "pooled": global_metrics,
        "quantile_cutpoints": {
            "abs_reference_g": g_cuts,
            "native_magnitude": m_cuts,
            "leverage_q_m_abs_g": l_cuts,
            "quantiles": list(QUANTILES),
            "method": "NumPy linear empirical quantile, pooled rows, unweighted; ties assigned to higher bin",
        },
        "cue_incidence_encoding": "four bits in original cue-slot order; displayed group string is bit3..bit0",
        "groups": groups,
        "uncertainty": None,
        "claim_ceiling": "descriptive localization of the already observed RUN4 qualification DeltaPsi; no confirmatory inference, symmetry mechanism, measured REACH-03 result, native-controller result, biological promotion, or PHENO change",
    }
    write_json(out / "LEVERAGE-LOCALIZATION.json", result)
    md = [
        "# F4-SYMMETRY-02 Leverage Localization",
        "",
        "**Disposition:** exploratory, post-outcome, analysis-only qualification diagnostic on the locked F4-SYMMETRY-01 RUN4 prediction streams. No fits were run.",
        "",
        f"- Rows: {data.count}",
        f"- Psi C: {psi_c:.9f}",
        f"- Psi D: {psi_d:.9f}",
        f"- Delta Psi D-C: {delta:.9f}",
        f"- C/D disagreement rows: {int(disagreements.sum())} ({disagreements.mean():.3%})",
        f"- Leverage mass on disagreement rows: {global_metrics['disagreement_leverage_fraction']:.3%}",
        f"- D correct on disagreement leverage: {global_metrics['D_weighted_accuracy_on_disagreements']:.3%}",
        "",
        "Every `delta_psi_global_contribution` below is the subgroup's additive share of pooled D-C DeltaPsi. `delta_psi_local` renormalizes within that subgroup. The row contributions sum to pooled DeltaPsi and are zero outside the C/D disagreement set.",
        "",
        "## By block",
        "",
        "| Block | Rows | Leverage share | Local DeltaPsi | Pooled contribution | Disagreement leverage | D correct when disagreeing |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in groups:
        if item["dimension"] == "block":
            md.append(f"| {item['group']} | {item['row_count']} | {item['leverage_share_of_global']:.3%} | {item['delta_psi_local']:.6f} | {item['delta_psi_global_contribution']:.6f} | {item['disagreement_leverage_fraction']:.3%} | {item['D_weighted_accuracy_on_disagreements'] if item['D_weighted_accuracy_on_disagreements'] is not None else 'n/a'} |")
    md.extend([
        "",
        "## By pooled quintile and cue-incidence pattern",
        "",
        "See `LEVERAGE-LOCALIZATION.csv` for each subgroup's row count, leverage mass, local and pooled DeltaPsi, and C/D disagreement statistics.",
        "",
        "## Scope",
        "",
        "The bins and decompositions describe these qualification rows only. They do not establish that canonicalization caused a general symmetry effect, that the predictor is usable as a controller, or that a local DeltaPsi improvement changes multi-step trajectory outcomes. No uncertainty interval is computed.",
        "",
    ])
    with (out / "LEVERAGE-LOCALIZATION.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(md))
        stream.flush()
    output_files = [out / name for name in ("ANALYSIS-CONTRACT.json", "LEVERAGE-LOCALIZATION.csv", "LEVERAGE-LOCALIZATION.json", "LEVERAGE-LOCALIZATION.md")]
    receipt = {
        "schema": "F4-SYMMETRY-02-leverage-localization-receipt-v1",
        "status": "CLOSED_EXPLORATORY_QUALIFICATION_ONLY",
        "parent_identity": "F4-SYMMETRY-01-RUN4",
        "analysis_contract_sha256": _sha(contract_path),
        "analysis_script_sha256": _sha(SCRIPT),
        "analysis_sha256": _sha(out / "LEVERAGE-LOCALIZATION.json"),
        "csv_sha256": _sha(out / "LEVERAGE-LOCALIZATION.csv"),
        "markdown_sha256": _sha(out / "LEVERAGE-LOCALIZATION.md"),
        "source_hashes": inputs,
        "locked_prediction_hashes_C_D": prediction_hashes,
        "rows": data.count,
        "fits_run": 0,
        "delta_psi_D_minus_C": delta,
        "qualification_only": True,
        "measured_reach03_result": False,
        "biological_promotion": False,
        "PHENO_status_unchanged": True,
    }
    write_json(out / "TERMINAL-RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "output": str(out), "delta_psi_D_minus_C": delta,
                      "disagreement_leverage_fraction": global_metrics["disagreement_leverage_fraction"],
                      "receipt_sha256": _sha(out / "TERMINAL-RECEIPT.json")}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("freeze-contract", "analyze"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.mode == "freeze-contract":
        freeze_contract(args.out)
    else:
        analyze(args.out)


if __name__ == "__main__":
    main()
