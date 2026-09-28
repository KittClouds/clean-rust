"""Post-integrity scoring for F4-INVARIANT-01; never called by the fitter."""
from __future__ import annotations

import json
import math
import os
import struct
from pathlib import Path
from typing import Any


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

from fit_common import (
    BLOCKS, RUN, load_raw_inputs, load_scoring_truth, read_json, sha_file, write_json_new,
)
from fit_contract import (
    ARMS, REPLICATES, decode_prediction_stream, delivery_alignment,
    polarity_metrics, prediction_signs, signed_margin, weighted_accuracy, weighted_balanced_error,
)


def _prediction_grid(manifest_rows: list[dict[str, str]], row_hashes: dict[str, str], raw) -> dict[tuple[str, int, int], np.ndarray]:
    output: dict[tuple[str, int, int], np.ndarray] = {}
    for row in manifest_rows:
        block = int(row["heldout_block"])
        arm = row["arm"]
        replicate = int(row["replicate_index"])
        indices = np.flatnonzero(raw.blocks == np.uint64(block))
        expected_keys = [raw.keys[int(index)] for index in indices]
        path = RUN / row["expected_prediction_path"]
        keys, logits = decode_prediction_stream(
            path.read_bytes(), block=block, arm=arm, replicate=replicate,
            manifest_row_sha256=row_hashes[row["fit_id"]], expected_keys=expected_keys,
        )
        if keys != expected_keys:
            raise RuntimeError(f"prediction order differs from raw stream: {row['fit_id']}")
        output[(arm, replicate, block)] = np.asarray(logits, dtype=np.float64)
    if len(output) != 72:
        raise RuntimeError("analysis prediction grid is incomplete")
    return output


def _truth_positions(raw, truth) -> dict[int, np.ndarray]:
    by_block = {block: np.flatnonzero(raw.blocks == np.uint64(block)) for block in BLOCKS}
    if sum(len(values) for values in by_block.values()) != len(truth.y):
        raise RuntimeError("scoring truth and raw input row counts differ")
    return by_block


def _concat_prediction(predictions, arm: str, replicate: int, positions: dict[int, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    logits: list[np.ndarray] = []
    indices: list[np.ndarray] = []
    for block in BLOCKS:
        logits.append(predictions[(arm, replicate, block)])
        indices.append(positions[block])
    return np.concatenate(logits), np.concatenate(indices)


def _margin_one_class(logits: np.ndarray, y: np.ndarray, q: np.ndarray) -> float | None:
    denom = math.fsum(float(value) for value in q)
    if not len(y) or denom <= 0.0:
        return None
    return math.fsum(float(q[i]) * int(y[i]) * float(logits[i]) for i in range(len(y))) / denom


def _score_population(logits: np.ndarray, indices: np.ndarray, truth) -> dict[str, Any]:
    y = truth.y[indices].astype(np.int64)
    q = truth.q[indices].astype(np.float64)
    signs = np.asarray(prediction_signs(logits), dtype=np.int64)
    error = weighted_balanced_error(signs, y, q)
    raw_omega = None if error is None else 1.0 - 2.0 * error
    return {
        "row_count": int(len(indices)),
        "positive_rows": int(np.count_nonzero(y == 1)),
        "negative_rows": int(np.count_nonzero(y == -1)),
        "balanced_error": error,
        "omega_unclipped": raw_omega,
        "omega_clipped": None if raw_omega is None else max(0.0, raw_omega),
        "q_weighted_accuracy": weighted_accuracy(signs, y, q),
        "signed_margin": signed_margin(logits, y, q),
    }


def _psi_population(signs: np.ndarray, indices: np.ndarray, truth, row_keys: list[bytes]) -> dict[str, Any]:
    local_keys = [row_keys[int(index)] for index in indices]
    return polarity_metrics(
        signs.astype(np.int64).tolist(),
        truth.y[indices].astype(np.int64).tolist(),
        truth.q[indices].astype(np.float64).tolist(),
        truth.native_delta[indices].astype(np.float64).tolist(),
        truth.reference[indices].astype(np.float64).tolist(),
        local_keys,
    )


def run() -> dict[str, Any]:
    integrity_path = RUN / "INTEGRITY-RECEIPT.json"
    integrity = read_json(integrity_path)
    if integrity.get("status") != "PASS" or integrity.get("heldout_truth_state") != "SEALED":
        raise RuntimeError("analysis is locked until independent integrity PASS")
    if integrity.get("scoring_truth_values_opened") is not False:
        raise RuntimeError("integrity receipt reports premature scoring-truth access")

    manifest_path = RUN / "FIT-MANIFEST.csv"
    raw_manifest = manifest_path.read_bytes()
    import csv
    rows = list(csv.DictReader(raw_manifest.decode("utf-8").splitlines()))
    row_hashes = read_json(RUN / "FIT-MANIFEST-ROW-HASHES.json")["rows"]
    raw = load_raw_inputs()
    truth = load_scoring_truth(integrity_path, expected_keys=raw.keys)
    positions = _truth_positions(raw, truth)
    predictions = _prediction_grid(rows, row_hashes, raw)

    pooled: dict[str, Any] = {}
    replicate_contrasts: list[dict[str, Any]] = []
    replicate_data: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
    for replicate in REPLICATES:
        arm_scores: dict[str, Any] = {}
        arm_logits: dict[str, np.ndarray] = {}
        arm_indices: dict[str, np.ndarray] = {}
        for arm in ARMS:
            logits, indices = _concat_prediction(predictions, arm, replicate, positions)
            arm_logits[arm], arm_indices[arm] = logits, indices
            replicate_data[(arm, replicate)] = (logits, indices)
            arm_scores[arm] = _score_population(logits, indices, truth)
        pooled[str(replicate)] = arm_scores
        replicate_contrasts.append({
            "replicate_index": replicate,
            "s_minus_d_balanced_error": arm_scores["S"]["balanced_error"] - arm_scores["D"]["balanced_error"],
        })

    mean_errors = {
        arm: math.fsum(float(pooled[str(rep)][arm]["balanced_error"]) for rep in REPLICATES) / len(REPLICATES)
        for arm in ARMS
    }
    mean_delta = math.fsum(item["s_minus_d_balanced_error"] for item in replicate_contrasts) / len(REPLICATES)

    blockwise: list[dict[str, Any]] = []
    for block in BLOCKS:
        indices = positions[block]
        y = truth.y[indices].astype(np.int64)
        q = truth.q[indices].astype(np.float64)
        arm_rep_errors: dict[str, list[float | None]] = {"D": [], "S": []}
        arm_rep_margins: dict[str, list[dict[str, Any]]] = {"D": [], "S": []}
        for arm in ARMS:
            for replicate in REPLICATES:
                logits = predictions[(arm, replicate, block)]
                signs = prediction_signs(logits)
                arm_rep_errors[arm].append(weighted_balanced_error(signs, y, q))
                if len(set(y.tolist())) == 2:
                    arm_rep_margins[arm].append({"kind": "equal_class_ipw", "value": signed_margin(logits, y, q)})
                else:
                    arm_rep_margins[arm].append({"kind": "one_class_q_weighted_y_logit", "value": _margin_one_class(logits, y, q)})
        deltas = [s - d for d, s in zip(arm_rep_errors["D"], arm_rep_errors["S"], strict=True) if d is not None and s is not None]
        blockwise.append({
            "block": block,
            "rows": int(len(indices)),
            "class_complete": len(set(y.tolist())) == 2,
            "positive_rows": int(np.count_nonzero(y == 1)),
            "negative_rows": int(np.count_nonzero(y == -1)),
            "balanced_error_D_by_replicate": arm_rep_errors["D"],
            "balanced_error_S_by_replicate": arm_rep_errors["S"],
            "mean_s_minus_d_balanced_error": None if not deltas else math.fsum(deltas) / len(deltas),
            "signed_margin_D_by_replicate": arm_rep_margins["D"],
            "signed_margin_S_by_replicate": arm_rep_margins["S"],
        })

    polarity: dict[str, Any] = {"by_replicate": {}, "native": None, "reference_sign_oracle": None}
    delivery: dict[str, Any] = {"by_replicate": {}, "native": None, "reference_sign_oracle": None}
    all_indices = np.arange(len(truth.y), dtype=np.int64)
    native_signs = np.sign(truth.native_delta).astype(np.int64)
    oracle_signs = np.where(truth.reference > 0.0, 1, -1).astype(np.int64)
    polarity["native"] = _psi_population(native_signs, all_indices, truth, raw.keys)
    polarity["reference_sign_oracle"] = _psi_population(oracle_signs, all_indices, truth, raw.keys)
    delivery["native"] = delivery_alignment(
        native_signs.tolist(), truth.native_delta.tolist(), truth.preweight.tolist(), truth.reference.tolist(),
    )
    delivery["reference_sign_oracle"] = delivery_alignment(
        oracle_signs.tolist(), truth.native_delta.tolist(), truth.preweight.tolist(), truth.reference.tolist(),
    )
    for replicate in REPLICATES:
        polarity["by_replicate"][str(replicate)] = {}
        delivery["by_replicate"][str(replicate)] = {}
        for arm in ARMS:
            logits, indices = replicate_data[(arm, replicate)]
            signs = np.asarray(prediction_signs(logits), dtype=np.int64)
            polarity["by_replicate"][str(replicate)][arm] = _psi_population(signs, indices, truth, raw.keys)
            delivery["by_replicate"][str(replicate)][arm] = delivery_alignment(
                signs.tolist(), truth.native_delta[indices].tolist(), truth.preweight[indices].tolist(), truth.reference[indices].tolist(),
            )

    support = read_json(RUN / "TRAINING-SUPPORT-RECEIPT.json")
    evaluable = int(support["heldout_class_complete_blocks"])
    replicate_wins = sum(item["s_minus_d_balanced_error"] < 0.0 for item in replicate_contrasts)
    evaluable_block_rows = [row for row in blockwise if row["class_complete"]]
    block_wins = sum(
        row["mean_s_minus_d_balanced_error"] is not None and row["mean_s_minus_d_balanced_error"] < 0.0
        for row in evaluable_block_rows
    )
    required_block_wins = math.ceil(2 * evaluable / 3)
    support_pass = evaluable >= 10
    comparative_pass = (
        mean_delta < 0.0 and replicate_wins >= 2 and block_wins >= required_block_wins
    )
    if not support_pass:
        disposition = "NOT_EVALUABLE_SUPPORT"
    elif comparative_pass:
        disposition = "NOMINATE_S_FOR_SEPARATE_CALIBRATION"
    else:
        disposition = "NO_CLEAR_COMPARATIVE_ADVANTAGE"
    result = {
        "schema": "F4-INVARIANT-01-analysis-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "qualification_only": True,
        "integrity_status": "PASS",
        "fit_count": 72,
        "pooled_by_replicate": pooled,
        "mean_replicate_balanced_error": mean_errors,
        "replicate_s_minus_d_contrasts": replicate_contrasts,
        "mean_s_minus_d_balanced_error": mean_delta,
        "blockwise": blockwise,
        "polarity_weighted": polarity,
        "delivery_eta_del": delivery,
        "heldout_support": {"evaluable_blocks": evaluable, "required_blocks": 10, "status": "FAIL" if evaluable < 10 else "PASS"},
        "advancement_checks": {
            "mean_s_minus_d_negative": mean_delta < 0.0,
            "replicate_wins": replicate_wins,
            "replicate_wins_required": 2,
            "block_wins": block_wins,
            "block_wins_required": required_block_wins,
            "comparative_rule_pass": comparative_pass,
            "evaluated_only_if_support_passes": support_pass,
        },
        "advancement_disposition": disposition,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    write_json_new(RUN / "ANALYSIS.json", result)
    markdown = [
        "# F4-INVARIANT-01 Results",
        "",
        "Qualification-only descriptive comparison. Integrity passed before held-out truth was opened.",
        "",
        f"- Held-out support: {evaluable}/12 class-complete blocks (required 10/12).",
        f"- Disposition: `{disposition}`.",
        f"- Mean replicate pooled balanced error: D={mean_errors['D']:.8f}, S={mean_errors['S']:.8f}.",
        f"- Mean paired S-D balanced error: {mean_delta:.8f}.",
        "- Support failure prevents advancement; reported scores are descriptive only.",
        "- Measured REACH-03 remains unauthorized; biological promotion is false; PHENO is unchanged.",
        "",
    ]
    results_path = RUN / "RESULTS.md"
    with results_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(markdown))
        stream.flush()
        os.fsync(stream.fileno())
    return result


if __name__ == "__main__":
    summary = run()
    print(json.dumps({"status": summary["advancement_disposition"], "fit_count": summary["fit_count"]}, sort_keys=True))
