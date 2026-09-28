"""Descriptive Cphi versus frozen D/S analysis over the reused panel."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import struct
import sys
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
PREFIT = STUDY / "f4-invariant-01-prefit-v2"
IMPL = STUDY / "f4-invariant-01-impl-v2"
SCRIPTS = STUDY / "scripts"
for _path in (str(PREFIT), str(IMPL), str(SCRIPTS), str(BRANCH)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import numpy as np  # noqa: E402

from fit_common import (  # noqa: E402
    BLOCKS, RUN as PARENT_RUN, load_raw_inputs, load_scoring_truth, read_json, sha_file,
    write_json_new,
)
from fit_contract import (  # noqa: E402
    REPLICATES, decode_prediction_stream, delivery_alignment, manifest_row_hashes,
    polarity_metrics, prediction_signs, signed_margin, weighted_accuracy, weighted_balanced_error,
)
from run_cphi import PRED_MAGIC, RUN, RUN_ID  # noqa: E402
from verify_cphi import _decode_prediction  # noqa: E402


ARMS = ("D", "S", "Cphi")


def _score(logits: np.ndarray, indices: np.ndarray, truth) -> dict[str, Any]:
    y = truth.y[indices].astype(np.int64)
    q = truth.q[indices].astype(np.float64)
    signs = np.asarray(prediction_signs(logits.tolist()), dtype=np.int64)
    error = weighted_balanced_error(signs.tolist(), y.tolist(), q.tolist())
    return {
        "rows": int(len(indices)),
        "positive": int(np.count_nonzero(y == 1)),
        "negative": int(np.count_nonzero(y == -1)),
        "balanced_error": error,
        "omega": None if error is None else 1.0 - 2.0 * error,
        "weighted_accuracy": weighted_accuracy(signs.tolist(), y.tolist(), q.tolist()),
        "signed_margin": signed_margin(logits.tolist(), y.tolist(), q.tolist()),
    }


def _logit_diagnostics(logits: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    signs = np.where(logits > 0.0, 1, -1)
    abs_logits = np.abs(logits.astype(np.float64))
    wrong = signs != y
    correct = ~wrong
    def quantiles(values: np.ndarray) -> dict[str, float | None]:
        if not len(values):
            return {"q50": None, "q90": None, "q99": None}
        q = np.quantile(values, [0.5, 0.9, 0.99])
        return {"q50": float(q[0]), "q90": float(q[1]), "q99": float(q[2])}
    return {
        "abs_logit_all": quantiles(abs_logits),
        "abs_logit_wrong": quantiles(abs_logits[wrong]),
        "abs_logit_correct": quantiles(abs_logits[correct]),
        "wrong_rows": int(np.count_nonzero(wrong)),
    }


def _read_cphi_prediction(path: Path, block: int, replicate: int, keys: list[bytes]) -> np.ndarray:
    raw = path.read_bytes()
    return np.asarray(_decode_prediction(raw, block, replicate, keys), dtype=np.float64)


def _read_parent_predictions(raw, parent_manifest: list[dict[str, str]]) -> dict[tuple[str, int, int], np.ndarray]:
    row_hashes = read_json(PARENT_RUN / "FIT-MANIFEST-ROW-HASHES.json")["rows"]
    output = {}
    for row in parent_manifest:
        block = int(row["heldout_block"])
        arm = row["arm"]
        rep = int(row["replicate_index"])
        indices = np.flatnonzero(raw.blocks == np.uint64(block))
        keys = [raw.keys[int(i)] for i in indices]
        path = PARENT_RUN / row["expected_prediction_path"]
        _decoded_keys, logits = decode_prediction_stream(
            path.read_bytes(), block=block, arm=arm, replicate=rep,
            manifest_row_sha256=row_hashes[row["fit_id"]], expected_keys=keys,
        )
        output[(arm, rep, block)] = np.asarray(logits, dtype=np.float64)
    if len(output) != 72:
        raise RuntimeError("parent D/S prediction grid is incomplete")
    return output


def _read_cphi_states(raw, fit_rows: list[dict[str, Any]]) -> tuple[dict[tuple[int, int], dict[str, np.ndarray]], dict[tuple[int, int], np.ndarray]]:
    states: dict[tuple[int, int], dict[str, np.ndarray]] = {}
    logits: dict[tuple[int, int], np.ndarray] = {}
    for row in fit_rows:
        block = int(row["heldout_block"])
        rep = int(row["replicate_index"])
        indices = np.flatnonzero(raw.blocks == np.uint64(block))
        expected_keys = np.frombuffer(b"".join(raw.keys[int(index)] for index in indices), dtype=np.uint8).reshape(len(indices), 18)
        with np.load(RUN / row["heldout_state_path"], allow_pickle=False) as archive:
            if archive["row_keys"].tobytes() != expected_keys.tobytes():
                raise RuntimeError(f"Cphi state row keys changed at {row['fit_id']}")
            states[(rep, block)] = {
                name: archive[name].copy()
                for name in ("ordered_tuples", "phi_outputs", "relational_concat", "posthoc_sum", "penultimate_hidden", "role_separation")
            }
            logits[(rep, block)] = archive["logits"].astype(np.float64)
    if len(states) != 36:
        raise RuntimeError("Cphi heldout state grid incomplete")
    return states, logits


def _nearest_opposite(sum_state: np.ndarray, ordered_state: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
    sum_state = sum_state.astype(np.float32, copy=False)
    ordered_state = ordered_state.reshape(len(y), -1).astype(np.float32, copy=False)
    nearest = np.empty(len(y), dtype=np.int64)
    distance = np.empty(len(y), dtype=np.float32)
    for label in (-1, 1):
        query_indices = np.flatnonzero(y == label)
        candidate_indices = np.flatnonzero(y == -label)
        if not len(query_indices) or not len(candidate_indices):
            continue
        candidates = sum_state[candidate_indices]
        candidate_norm = np.einsum("ij,ij->i", candidates, candidates)
        for start in range(0, len(query_indices), 128):
            query = query_indices[start:start + 128]
            vectors = sum_state[query]
            query_norm = np.einsum("ij,ij->i", vectors, vectors)
            distance2 = query_norm[:, None] + candidate_norm[None, :] - 2.0 * (vectors @ candidates.T)
            np.maximum(distance2, 0.0, out=distance2)
            local = np.argmin(distance2, axis=1)
            nearest[query] = candidate_indices[local]
            distance[query] = np.sqrt(distance2[np.arange(len(query)), local])
    ordered_distance = np.linalg.norm(ordered_state - ordered_state[nearest], axis=1)
    ratio = ordered_distance / np.maximum(distance.astype(np.float64), 1e-8)
    return {"nearest_index": nearest, "sum_distance": distance, "ordered_distance": ordered_distance, "distance_ratio": ratio.astype(np.float32)}


def _training_trace_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_epoch: dict[int, list[dict[str, float]]] = {}
    for row in rows:
        path = RUN / row["training_trace_path"]
        with path.open("r", encoding="utf-8", newline="") as stream:
            for item in csv.DictReader(stream):
                by_epoch.setdefault(int(item["epoch"]), []).append({key: float(value) for key, value in item.items() if key != "epoch"})
    summary = []
    for epoch in sorted(by_epoch):
        cells = by_epoch[epoch]
        item: dict[str, Any] = {"epoch": epoch, "fit_cells": len(cells)}
        for key in cells[0]:
            values = np.asarray([cell[key] for cell in cells], dtype=np.float64)
            item[f"{key}_mean"] = float(np.mean(values))
            item[f"{key}_std"] = float(np.std(values, ddof=0))
        summary.append(item)
    return {
        "historical_D_S_training_curves_available": False,
        "historical_D_S_training_curve_reason": "Parent fit receipts preserve final tensor hashes but no checkpoints or epoch loss/error traces; rerunning D/S was outside this screen.",
        "cphi_epochs": summary,
        "cphi_initial_to_final": {
            key: {"first_epoch_mean": summary[0][f"{key}_mean"], "last_epoch_mean": summary[-1][f"{key}_mean"]}
            for key in ("training_bce", "training_balanced_error")
        },
    }


def _role_diversity(raw) -> np.ndarray:
    result = np.empty(len(raw.keys), dtype=np.uint8)
    for index in range(len(result)):
        tuples = raw.tuples[index, :, :3]
        result[index] = len({tuple(int(v) for v in item) for item in tuples})
    return result


def analyze() -> dict[str, Any]:
    integrity = read_json(RUN / "INTEGRITY-RECEIPT.json")
    lock_path = RUN / "PREDICTION-LOCK.json"
    lock = read_json(lock_path)
    if integrity.get("status") != "PASS" or integrity.get("identity") != RUN_ID or integrity.get("truth_opened_by_this_run_before_integrity") is not False:
        raise RuntimeError("Cphi analysis is blocked until its independent integrity receipt passes")
    if integrity.get("prediction_lock_sha256") != sha_file(lock_path) or lock.get("status") != "PASS":
        raise RuntimeError("Cphi prediction lock changed after integrity")

    raw = load_raw_inputs()
    truth = load_scoring_truth(PARENT_RUN / "INTEGRITY-RECEIPT.json", expected_keys=raw.keys)
    indices_by_block = {block: np.flatnonzero(raw.blocks == np.uint64(block)) for block in BLOCKS}
    parent_rows = list(csv.DictReader((PARENT_RUN / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="")))
    parent_pred = _read_parent_predictions(raw, parent_rows)
    cphi_rows = read_json(RUN / "FIT-MANIFEST.json")["rows"]
    cphi_states, cphi_logits = _read_cphi_states(raw, cphi_rows)

    predictions: dict[tuple[str, int, int], np.ndarray] = dict(parent_pred)
    for (rep, block), values in cphi_logits.items():
        predictions[("Cphi", rep, block)] = values

    pooled: dict[str, dict[str, Any]] = {}
    contrasts: list[dict[str, Any]] = []
    all_logits: dict[tuple[str, int], np.ndarray] = {}
    all_indices: dict[int, np.ndarray] = {}
    for rep in REPLICATES:
        indices = np.concatenate([indices_by_block[block] for block in BLOCKS])
        all_indices[rep] = indices
        pooled[str(rep)] = {}
        for arm in ARMS:
            logits = np.concatenate([predictions[(arm, rep, block)] for block in BLOCKS])
            all_logits[(arm, rep)] = logits
            pooled[str(rep)][arm] = _score(logits, indices, truth)
        contrasts.append({
            "replicate": rep,
            "cphi_minus_D_balanced_error": pooled[str(rep)]["Cphi"]["balanced_error"] - pooled[str(rep)]["D"]["balanced_error"],
            "cphi_minus_S_balanced_error": pooled[str(rep)]["Cphi"]["balanced_error"] - pooled[str(rep)]["S"]["balanced_error"],
        })
    means = {
        arm: float(np.mean([pooled[str(rep)][arm]["balanced_error"] for rep in REPLICATES]))
        for arm in ARMS
    }

    blockwise = []
    for block in BLOCKS:
        indices = indices_by_block[block]
        y = truth.y[indices].astype(np.int64)
        cells: dict[str, list[float | None]] = {arm: [] for arm in ARMS}
        margins: dict[str, list[float]] = {arm: [] for arm in ARMS}
        for arm in ARMS:
            for rep in REPLICATES:
                logits = predictions[(arm, rep, block)]
                signs = prediction_signs(logits.tolist())
                cells[arm].append(weighted_balanced_error(signs, y.tolist(), truth.q[indices].tolist()))
                margins[arm].append(signed_margin(logits.tolist(), y.tolist(), truth.q[indices].tolist()))
        blockwise.append({
            "block": block,
            "rows": int(len(indices)),
            "positive": int(np.count_nonzero(y == 1)),
            "negative": int(np.count_nonzero(y == -1)),
            "class_complete": len(np.unique(y)) == 2,
            "balanced_error_by_replicate": cells,
            "mean_Cphi_minus_D": None if any(v is None for v in cells["D"] + cells["Cphi"]) else float(np.mean(np.asarray(cells["Cphi"]) - np.asarray(cells["D"]))),
            "mean_Cphi_minus_S": None if any(v is None for v in cells["S"] + cells["Cphi"]) else float(np.mean(np.asarray(cells["Cphi"]) - np.asarray(cells["S"]))),
            "signed_margin_by_replicate": margins,
        })

    logit_diagnostics = {}
    for arm in ARMS:
        logit_diagnostics[arm] = {}
        for rep in REPLICATES:
            indices = all_indices[rep]
            logit_diagnostics[arm][str(rep)] = _logit_diagnostics(all_logits[(arm, rep)], truth.y[indices])

    disagreement = {}
    for rep in REPLICATES:
        indices = all_indices[rep]
        y = truth.y[indices]
        for other in ("S", "Cphi"):
            d_sign = np.where(all_logits[("D", rep)] > 0.0, 1, -1)
            other_sign = np.where(all_logits[(other, rep)] > 0.0, 1, -1)
            mask = d_sign != other_sign
            d_correct = d_sign[mask] == y[mask]
            o_correct = other_sign[mask] == y[mask]
            disagreement[f"D_vs_{other}_rep{rep}"] = {
                "rows": int(np.count_nonzero(mask)),
                "fraction": float(np.mean(mask)),
                "D_correct": int(np.count_nonzero(d_correct)),
                f"{other}_correct": int(np.count_nonzero(o_correct)),
                "D_win_count": int(np.count_nonzero(d_correct & ~o_correct)),
                f"{other}_win_count": int(np.count_nonzero(o_correct & ~d_correct)),
            }

    role_div = _role_diversity(raw)
    role_groups: dict[str, Any] = {}
    for diversity in sorted(set(role_div.tolist())):
        indices = np.flatnonzero(role_div == diversity)
        group = {"rows": int(len(indices)), "positive": int(np.count_nonzero(truth.y[indices] == 1)), "negative": int(np.count_nonzero(truth.y[indices] == -1)), "balanced_error_by_replicate": {}}
        for arm in ARMS:
            values = []
            for rep in REPLICATES:
                signs = np.where(all_logits[(arm, rep)][indices] > 0.0, 1, -1).tolist()
                values.append(weighted_balanced_error(signs, truth.y[indices].astype(int).tolist(), truth.q[indices].tolist()))
            group["balanced_error_by_replicate"][arm] = values
        role_groups[str(diversity)] = group

    role_separation_by_rep = {}
    pooling_collision = {"definition": "Nearest opposite-target row in the post-hoc sum of Cphi's learned phi outputs, within the same held-out block and fit; this is not S's learned hidden state.", "by_block_replicate": [], "pooled": {}}
    collision_dist = []
    collision_ratio = []
    collision_low = {arm: [] for arm in ARMS}
    for rep in REPLICATES:
        separation = np.empty(len(raw.keys), dtype=np.float32)
        for block in BLOCKS:
            indices = indices_by_block[block]
            state = cphi_states[(rep, block)]
            separation[indices] = state["role_separation"]
            y = truth.y[indices].astype(np.int64)
            if len(np.unique(y)) != 2:
                continue
            near = _nearest_opposite(state["posthoc_sum"], state["relational_concat"], y)
            low_cut = float(np.quantile(near["sum_distance"], 0.05))
            low = near["sum_distance"] <= low_cut
            local = {arm: np.asarray(np.where(predictions[(arm, rep, block)] > 0.0, 1, -1), dtype=np.int64) for arm in ARMS}
            correct_low = {
                arm: float(np.mean(local[arm][low] == y[low])) if np.any(low) else None
                for arm in ARMS
            }
            collision_dist.extend(near["sum_distance"].astype(float).tolist())
            collision_ratio.extend(near["distance_ratio"].astype(float).tolist())
            for arm in ARMS:
                collision_low[arm].extend((local[arm][low] == y[low]).tolist())
            pooling_collision["by_block_replicate"].append({
                "block": block,
                "replicate": rep,
                "rows": int(len(indices)),
                "nearest_opposite_sum_distance_q50_q90": [float(v) for v in np.quantile(near["sum_distance"], [0.5, 0.9])],
                "matched_ordered_concat_distance_q50_q90": [float(v) for v in np.quantile(near["ordered_distance"], [0.5, 0.9])],
                "ordered_to_sum_distance_ratio_q50_q90": [float(v) for v in np.quantile(near["distance_ratio"], [0.5, 0.9])],
                "bottom_5pct_sum_distance_rows": int(np.count_nonzero(low)),
                "bottom_5pct_sum_distance_accuracy": correct_low,
                "bottom_5pct_S_wrong_high_confidence": int(np.count_nonzero(low & (local["S"] != y) & (np.abs(predictions[("S", rep, block)]) >= np.quantile(np.abs(predictions[("S", rep, block)]), 0.9)))),
            })
        role_separation_by_rep[str(rep)] = {
            "q20_q40_q60_q80": [float(value) for value in np.quantile(separation, [0.2, 0.4, 0.6, 0.8])],
            "bins": [],
        }
        edges = np.quantile(separation, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
        for bin_index in range(5):
            mask = (separation >= edges[bin_index]) & ((separation <= edges[bin_index + 1]) if bin_index == 4 else (separation < edges[bin_index + 1]))
            summary = {"bin": bin_index, "lower": float(edges[bin_index]), "upper": float(edges[bin_index + 1]), "rows": int(np.count_nonzero(mask)), "arm_balanced_error": {}}
            indices = np.flatnonzero(mask)
            for arm in ARMS:
                logits = all_logits[(arm, rep)][mask]
                summary["arm_balanced_error"][arm] = weighted_balanced_error(
                    prediction_signs(logits.tolist()), truth.y[indices].astype(int).tolist(), truth.q[indices].tolist(),
                )
            role_separation_by_rep[str(rep)]["bins"].append(summary)
    if collision_dist:
        pooling_collision["pooled"] = {
            "query_count": len(collision_dist),
            "nearest_opposite_sum_distance_q50_q90": [float(v) for v in np.quantile(collision_dist, [0.5, 0.9])],
            "ordered_to_sum_distance_ratio_q50_q90": [float(v) for v in np.quantile(collision_ratio, [0.5, 0.9])],
            "bottom_5pct_sum_distance_accuracy": {arm: float(np.mean(values)) if values else None for arm, values in collision_low.items()},
        }

    psi = {}
    delivery = {}
    for rep in REPLICATES:
        indices = all_indices[rep]
        psi[str(rep)] = {}
        delivery[str(rep)] = {}
        keys = [raw.keys[int(index)] for index in indices]
        for arm in ARMS:
            signs = np.asarray(prediction_signs(all_logits[(arm, rep)].tolist()), dtype=np.int64)
            psi[str(rep)][arm] = polarity_metrics(
                signs.tolist(), truth.y[indices].astype(int).tolist(), truth.q[indices].tolist(),
                truth.native_delta[indices].tolist(), truth.reference[indices].tolist(), keys,
            )
            delivery[str(rep)][arm] = delivery_alignment(
                signs.tolist(), truth.native_delta[indices].tolist(), truth.preweight[indices].tolist(), truth.reference[indices].tolist(),
            )

    block_306005 = next(item for item in blockwise if item["block"] == 306005)
    result = {
        "schema": "F4-PRESENTATION-02-analysis-v1",
        "identity": RUN_ID,
        "status": "DESCRIPTIVE_ENGINEERING_SCREEN_COMPLETE",
        "qualification_only": True,
        "parent_scientific_disposition": "NOT_EVALUABLE_SUPPORT",
        "parent_heldout_support": "7/12; unchanged and not repaired by this screen",
        "parent_truth_previously_opened": True,
        "new_fits": 36,
        "parent_D_S_fits_rerun": 0,
        "parent_D_S_training_curves_available": False,
        "integrity_status": "PASS",
        "integrity_receipt_sha256": sha_file(RUN / "INTEGRITY-RECEIPT.json"),
        "mean_pooled_balanced_error_by_arm": means,
        "pooled_by_replicate": pooled,
        "replicate_contrasts": contrasts,
        "blockwise": blockwise,
        "named_block_306005": block_306005,
        "logit_confidence_diagnostics": logit_diagnostics,
        "D_S_Cphi_disagreement_anatomy": disagreement,
        "Cphi_training_trajectory": _training_trace_summary(cphi_rows),
        "role_diversity_groups": role_groups,
        "role_separation_diagnostics": role_separation_by_rep,
        "posthoc_sum_pooling_collision_diagnostic": pooling_collision,
        "capability_weighted_polarity_by_replicate": psi,
        "delivery_alignment_by_replicate": delivery,
        "interpretation_ceiling": "A Cphi result is evidence about the shared-phi canonical-concatenation package on this reused panel. It does not isolate tuple identity alone because the readout factorization differs from D and S.",
        "measured_reach03_authorized": False,
        "pheno_status": "unchanged",
        "biological_promotion": False,
    }
    write_json_new(RUN / "ANALYSIS.json", result)
    d, s, c = means["D"], means["S"], means["Cphi"]
    lines = [
        "# F4-PRESENTATION-02 Cphi engineering screen",
        "",
        "Descriptive engineering comparison on the reused F4-INVARIANT-01 panel. The parent scientific disposition remains `NOT_EVALUABLE_SUPPORT` (7/12 class-complete blocks), and the parent analysis had previously opened held-out truth.",
        "",
        f"- New fits: {len(cphi_rows)} Cphi; parent D/S reruns: 0.",
        f"- Mean pooled balanced error: D={d:.6f}, S-sum={s:.6f}, Cphi={c:.6f}.",
        f"- Cphi minus D: {c-d:+.6f}; Cphi minus S-sum: {c-s:+.6f}.",
        f"- Block 306005 mean balanced errors: D={np.mean(block_306005['balanced_error_by_replicate']['D']):.6f}, S-sum={np.mean(block_306005['balanced_error_by_replicate']['S']):.6f}, Cphi={np.mean(block_306005['balanced_error_by_replicate']['Cphi']):.6f}.",
        "- Cphi training traces include epoch BCE, training balanced error, and per-layer gradient norm summaries. Parent D/S training traces were not retained, so no historical curve comparison is available without rerunning those arms.",
        "- Role-separation and post-hoc sum-neighbor diagnostics use Cphi's learned shared phi. They do not reconstruct S-sum's own trained hidden state.",
        "- No calibration promotion, measured REACH-03, controller, PHENO reopening, or biological promotion is authorized by this engineering screen.",
        "",
        "## Replicate contrasts",
        "",
        "| Replicate | Cphi − D error | Cphi − S error |",
        "| ---: | ---: | ---: |",
    ]
    for item in contrasts:
        lines.append(f"| {item['replicate']} | {item['cphi_minus_D_balanced_error']:+.6f} | {item['cphi_minus_S_balanced_error']:+.6f} |")
    lines.extend(["", "## Block 306005", "", "| Arm | Replicate errors | Mean |", "| --- | --- | ---: |"])
    for arm in ARMS:
        errors = block_306005["balanced_error_by_replicate"][arm]
        mean = float(np.mean(errors))
        lines.append(f"| {arm} | {', '.join(f'{value:.6f}' for value in errors)} | {mean:.6f} |")
    lines.append("")
    (RUN / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    terminal = {
        "schema": "F4-PRESENTATION-02-terminal-receipt-v1",
        "identity": RUN_ID,
        "status": "ENGINEERING_SCREEN_COMPLETE",
        "scientific_status": "NOT_EVALUABLE_SUPPORT",
        "parent_heldout_support": "7/12; unchanged",
        "analysis_provenance": "ANALYSIS_COMPLETE_WITH_PREVIOUS_TRUTH_ACCESS",
        "parent_truth_previously_opened": True,
        "parent_truth_opened_before_repaired_parent_analysis": True,
        "parent_analysis_had_no_comparative_result_before_repair": True,
        "new_comparative_results_are_descriptive_engineering_only": True,
        "fit_count": 36,
        "parent_D_S_reruns": 0,
        "integrity_status": "PASS",
        "integrity_receipt_sha256": sha_file(RUN / "INTEGRITY-RECEIPT.json"),
        "prediction_lock_sha256": sha_file(RUN / "PREDICTION-LOCK.json"),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.json"),
        "source_manifest_sha256": sha_file(RUN / "SOURCE-MANIFEST.json"),
        "analysis_sha256": sha_file(RUN / "ANALYSIS.json"),
        "results_markdown_sha256": sha_file(RUN / "RESULTS.md"),
        "measured_reach03_authorized": False,
        "controller_authorized": False,
        "pheno_status": "unchanged",
        "biological_promotion": False,
    }
    write_json_new(RUN / "F4-PRESENTATION-02-TERMINAL-RECEIPT-v1.json", terminal)
    return result


if __name__ == "__main__":
    result = analyze()
    print(json.dumps({"status": result["status"], "mean_pooled_balanced_error_by_arm": result["mean_pooled_balanced_error_by_arm"], "new_fits": result["new_fits"]}, sort_keys=True))
