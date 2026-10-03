"""Score the locked fresh Stage B inference panel after integrity PASS."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import struct
import time
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

import binding_stage_b_data as data
import binding_stage_b_model as model
import binding_stage_b_scoring as scoring
import stage_b_runtime as runtime

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parents[1]
REPO = STUDY.parents[1]
RUN_ID = "F4-BINDING-01-STAGE-B-PROSP-v0.1"
RUN = STUDY / "runs" / RUN_ID
COLLECTION = RUN / "native-collection"
LOCK_PATH = RUN / "PREDICTION-LOCK.json"
INTEGRITY_PATH = RUN / "PRE-TRUTH-INTEGRITY-RECEIPT.json"
ASSIGNMENT_ORDER = ("1100", "1010", "0110", "1001", "0101", "0011")
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
BOOTSTRAP_DOMAIN = b"F4-BINDING-01-STAGE-B/BOOTSTRAP-v0.1\0"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write_new_json(path: Path, value: Any) -> None:
    write_new_bytes(path, (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def mean_defined(values: list[float | None]) -> float | None:
    selected = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return math.fsum(selected) / len(selected) if selected else None


def read_all_predictions(lock: dict[str, Any], keys: tuple[bytes, ...]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    output = np.empty((36, len(keys), 3), dtype=np.float32)
    model_rows = []
    for model_index, entry in enumerate(lock["predictions"]):
        path = RUN / entry["prediction_path"]
        with path.open("rb") as stream:
            header = stream.read(data.HEADER_WIDTH)
            if header[:16] != data.PRED_MAGIC:
                raise RuntimeError(f"prediction magic mismatch: {entry['fit_id']}")
            version, width, count = struct.unpack_from("<IIQ", header, 16)
            if (version, width, count) != (1, data.PRED_WIDTH, len(keys)):
                raise RuntimeError(f"prediction dimensions mismatch: {entry['fit_id']}")
            for index, key in enumerate(keys):
                record = stream.read(data.PRED_WIDTH)
                if len(record) != data.PRED_WIDTH or record[:18] != key:
                    raise RuntimeError(f"prediction row identity mismatch: {entry['fit_id']}/{index}")
                output[model_index, index] = np.frombuffer(record, dtype="<f4", count=3, offset=18)
            if stream.read(1):
                raise RuntimeError(f"prediction has trailing bytes: {entry['fit_id']}")
        model_rows.append(entry)
    if not np.isfinite(output).all():
        raise RuntimeError("nonfinite prediction panel")
    return output, model_rows


def condition_metrics(
    predictions: np.ndarray,
    idx: np.ndarray,
    truth: data.ScoringTruth,
    inverse_p: np.ndarray,
    keys: tuple[bytes, ...],
) -> list[dict[str, Any]]:
    selected_keys = [keys[int(index)] for index in idx]
    y = truth.y[idx]
    q = inverse_p[idx]
    native = truth.native_delta[idx]
    preweight = truth.preweight[idx]
    reference = truth.reference[idx]
    return [
        scoring.score_condition(predictions[model_index, idx, condition_index], y, q, native, preweight, reference, selected_keys)
        for model_index in range(36)
        for condition_index in range(3)
    ]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in columns})
        stream.flush()
        os.fsync(stream.fileno())


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return value


def _flatten_metrics(row: dict[str, Any], prefix: str, metrics: dict[str, Any]) -> None:
    for key in ("row_count", "positive_count", "negative_count", "balanced_error", "signed_margin", "mean_absolute_logit", "psi_prop", "weighted_sign_agreement", "eta_delivery"):
        row[f"{prefix}{key}"] = metrics.get(key)
    row[f"{prefix}q_diagnostics"] = metrics.get("q_diagnostics")
    row[f"{prefix}leverage"] = metrics.get("leverage")


def run() -> dict[str, Any]:
    if (RUN / "ANALYSIS.json").exists() or (RUN / "RESULTS.md").exists() or (RUN / "STAGE-B-TERMINAL-RECEIPT.json").exists():
        raise RuntimeError("Stage B analysis outputs already exist; preserve and stop")
    integrity = read_json(INTEGRITY_PATH)
    if integrity.get("status") != "PASS" or integrity.get("truth_values_opened") is not False:
        raise RuntimeError("truth may be opened only after the independent pre-truth integrity PASS")
    freeze = read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    runtime.require_frozen(freeze["runtime_identity"])
    lock = read_json(LOCK_PATH)
    if sha_file(LOCK_PATH) != integrity.get("prediction_lock_sha256"):
        raise RuntimeError("prediction lock changed after integrity PASS")
    predictor_path = COLLECTION / "RAW-PREDICTORS.bin"
    truth_path = COLLECTION / "RAW-SCORING-TRUTH.bin"
    if sha_file(predictor_path) != integrity.get("predictor_sha256") or sha_file(truth_path) != integrity.get("truth_file_sha256"):
        raise RuntimeError("Stage B scoring input drift after integrity PASS")

    panel = data.load_predictors(predictor_path)
    # First scoring-truth value read in this identity occurs below, after PASS.
    truth = data.load_scoring_truth(truth_path, panel.keys)
    inverse_p = 1.0 / truth.inclusion_probability.astype(np.float64)
    if not np.isfinite(inverse_p).all():
        raise RuntimeError("nonfinite inverse-inclusion weights")

    task_manifest = read_json(RUN / "task-bank" / "TASK-BANK-MANIFEST.json")
    assignment_by_block = {int(row["block_id"]): int(row["assignment_index"]) for row in task_manifest["blocks"]}
    if set(assignment_by_block) != set(data.BLOCK_IDS):
        raise RuntimeError("task assignment map does not cover the Stage B blocks")
    block_to_indices = {block: np.flatnonzero(panel.blocks == np.uint64(block)) for block in data.BLOCK_IDS}
    assignment_to_index = {bits: index for index, bits in enumerate(ASSIGNMENT_ORDER)}
    assignment_indices = {
        index: np.flatnonzero(np.isin(panel.blocks, [block for block, assignment in assignment_by_block.items() if assignment == index]))
        for index in range(6)
    }
    bits_by_index = {int(row["assignment_index"]): row["assignment_bits"] for row in task_manifest["blocks"]}
    if any(bits_by_index[index] != ASSIGNMENT_ORDER[index] for index in range(6)):
        raise RuntimeError("frozen assignment order differs from the protocol")

    logits, model_entries = read_all_predictions(lock, panel.keys)
    if len(model_entries) != 36:
        raise RuntimeError("Stage B model panel is not exactly 36")

    assignment_model_rows: list[dict[str, Any]] = []
    assignment_summary: list[dict[str, Any]] = []
    assignment_support: dict[int, dict[str, int]] = {}
    assignment_deltas: dict[str, dict[str, float | None]] = {name: {} for name in ("pair_swap", "cycle_4")}
    model_score_cache: dict[tuple[int, int, int], dict[str, Any]] = {}
    for assignment_index, bits in enumerate(ASSIGNMENT_ORDER):
        idx = assignment_indices[assignment_index]
        positive = int(np.count_nonzero(truth.y[idx] == 1))
        negative = int(np.count_nonzero(truth.y[idx] == -1))
        assignment_support[assignment_index] = {"positive": positive, "negative": negative, "rows": int(len(idx))}
        q_info = scoring.q_diagnostics(inverse_p[idx])
        model_rows_for_assignment = []
        for model_index, entry in enumerate(model_entries):
            condition_results = []
            for condition_index, condition in enumerate(("intact", "pair_swap", "cycle_4")):
                result = scoring.score_condition(
                    logits[model_index, idx, condition_index], truth.y[idx], inverse_p[idx],
                    truth.native_delta[idx], truth.preweight[idx], truth.reference[idx],
                    [panel.keys[int(row_index)] for row_index in idx],
                )
                model_score_cache[(assignment_index, model_index, condition_index)] = result
                condition_results.append(result)
                row = {
                    "assignment_index": assignment_index, "assignment": bits,
                    "fit_id": entry["fit_id"], "fold_index": entry["fold_index"], "heldout_block": entry["heldout_block"],
                    "replicate_index": entry["replicate_index"], "condition": condition,
                    "assignment_rows": int(len(idx)), "assignment_positive": positive, "assignment_negative": negative,
                    **result,
                }
                assignment_model_rows.append(row)
            model_rows_for_assignment.append(condition_results)
        means_by_condition: list[dict[str, float | None]] = []
        for condition_index in range(3):
            means_by_condition.append({
                key: mean_defined([model_score_cache[(assignment_index, m, condition_index)].get(key) for m in range(36)])
                for key in ("balanced_error", "signed_margin", "mean_absolute_logit", "psi_prop", "weighted_sign_agreement", "eta_delivery")
            })
            means_by_condition[-1]["q_diagnostics"] = q_info
            means_by_condition[-1]["leverage"] = model_score_cache[(assignment_index, 0, condition_index)].get("leverage")
        pair_effects = []
        cycle_effects = []
        for model_index in range(36):
            intact_error = model_score_cache[(assignment_index, model_index, 0)]["balanced_error"]
            pair_error = model_score_cache[(assignment_index, model_index, 1)]["balanced_error"]
            cycle_error = model_score_cache[(assignment_index, model_index, 2)]["balanced_error"]
            pair_effects.append(None if intact_error is None or pair_error is None else float(pair_error - intact_error))
            cycle_effects.append(None if intact_error is None or cycle_error is None else float(cycle_error - intact_error))
        pair_delta = mean_defined(pair_effects)
        cycle_delta = mean_defined(cycle_effects)
        assignment_deltas["pair_swap"][bits] = pair_delta
        assignment_deltas["cycle_4"][bits] = cycle_delta
        assignment_summary.append({
            "assignment_index": assignment_index,
            "assignment": bits,
            "block_ids": [block for block, index in assignment_by_block.items() if index == assignment_index],
            "support": assignment_support[assignment_index],
            "evaluable": positive > 0 and negative > 0,
            "q_diagnostics": q_info,
            "condition_means_over_36_fixed_models": {
                "intact": means_by_condition[0], "pair_swap": means_by_condition[1], "cycle_4": means_by_condition[2],
            },
            "mean_model_paired_delta_balanced_error": {"pair_swap": pair_delta, "cycle_4": cycle_delta},
            "mean_model_paired_delta_margin": {
                "pair_swap": mean_defined([
                    None if model_score_cache[(assignment_index, m, 0)]["signed_margin"] is None or model_score_cache[(assignment_index, m, 1)]["signed_margin"] is None else
                    model_score_cache[(assignment_index, m, 1)]["signed_margin"] - model_score_cache[(assignment_index, m, 0)]["signed_margin"] for m in range(36)
                ]),
                "cycle_4": mean_defined([
                    None if model_score_cache[(assignment_index, m, 0)]["signed_margin"] is None or model_score_cache[(assignment_index, m, 2)]["signed_margin"] is None else
                    model_score_cache[(assignment_index, m, 2)]["signed_margin"] - model_score_cache[(assignment_index, m, 0)]["signed_margin"] for m in range(36)
                ]),
            },
            "mean_model_paired_delta_psi_prop": {
                "pair_swap": mean_defined([model_score_cache[(assignment_index, m, 1)]["psi_prop"] - model_score_cache[(assignment_index, m, 0)]["psi_prop"] for m in range(36) if model_score_cache[(assignment_index, m, 1)]["psi_prop"] is not None and model_score_cache[(assignment_index, m, 0)]["psi_prop"] is not None]),
                "cycle_4": mean_defined([model_score_cache[(assignment_index, m, 2)]["psi_prop"] - model_score_cache[(assignment_index, m, 0)]["psi_prop"] for m in range(36) if model_score_cache[(assignment_index, m, 2)]["psi_prop"] is not None and model_score_cache[(assignment_index, m, 0)]["psi_prop"] is not None]),
            },
            "mean_model_paired_delta_eta_delivery": {
                "pair_swap": mean_defined([model_score_cache[(assignment_index, m, 1)]["eta_delivery"] - model_score_cache[(assignment_index, m, 0)]["eta_delivery"] for m in range(36) if model_score_cache[(assignment_index, m, 1)]["eta_delivery"] is not None and model_score_cache[(assignment_index, m, 0)]["eta_delivery"] is not None]),
                "cycle_4": mean_defined([model_score_cache[(assignment_index, m, 2)]["eta_delivery"] - model_score_cache[(assignment_index, m, 0)]["eta_delivery"] for m in range(36) if model_score_cache[(assignment_index, m, 2)]["eta_delivery"] is not None and model_score_cache[(assignment_index, m, 0)]["eta_delivery"] is not None]),
            },
        })

    block_model_rows: list[dict[str, Any]] = []
    for block in data.BLOCK_IDS:
        idx = block_to_indices[block]
        assignment_index = assignment_by_block[block]
        bits = ASSIGNMENT_ORDER[assignment_index]
        for model_index, entry in enumerate(model_entries):
            for condition_index, condition in enumerate(("intact", "pair_swap", "cycle_4")):
                result = scoring.score_condition(
                    logits[model_index, idx, condition_index], truth.y[idx], inverse_p[idx],
                    truth.native_delta[idx], truth.preweight[idx], truth.reference[idx],
                    [panel.keys[int(row_index)] for row_index in idx],
                )
                block_model_rows.append({
                    "block_id": block, "assignment_index": assignment_index, "assignment": bits,
                    "fit_id": entry["fit_id"], "fold_index": entry["fold_index"], "replicate_index": entry["replicate_index"],
                    "condition": condition, **result,
                })

    cell_model_rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    cell_manifest = read_json(STUDY / "manifests" / "QUALIFICATION-MANIFEST.json")
    q_by_cell = {(row["substrate"], row["side"]): float(row["inclusion_probability"]) for row in cell_manifest["cells"]}
    for substrate_index, substrate in enumerate(SUBSTRATES):
        for side_index, side in enumerate(SIDES):
            for block in data.BLOCK_IDS:
                idx = np.flatnonzero((panel.substrates == substrate_index) & (panel.sides == side_index) & (panel.blocks == np.uint64(block)))
                assignment_index = assignment_by_block[block]
                bits = ASSIGNMENT_ORDER[assignment_index]
                positive = int(np.count_nonzero(truth.y[idx] == 1))
                negative = int(np.count_nonzero(truth.y[idx] == -1))
                cell_q = inverse_p[idx]
                support_rows.append({
                    "substrate": substrate, "side": side, "block_id": block,
                    "assignment_index": assignment_index, "assignment": bits,
                    "generated_trials": 8192, "eligible_rows_measured": "",
                    "sampled_ustar_rows": int(len(idx)), "positive_target_rows": positive,
                    "negative_target_rows": negative, "inclusion_probability": q_by_cell[(substrate, side)],
                    "cell_empty": len(idx) == 0,
                    "q_diagnostics": scoring.q_diagnostics(cell_q),
                })
                for model_index, entry in enumerate(model_entries):
                    for condition_index, condition in enumerate(("intact", "pair_swap", "cycle_4")):
                        result = scoring.score_condition(
                            logits[model_index, idx, condition_index], truth.y[idx], inverse_p[idx],
                            truth.native_delta[idx], truth.preweight[idx], truth.reference[idx],
                            [panel.keys[int(row_index)] for row_index in idx],
                        )
                        cell_model_rows.append({
                            "substrate": substrate, "side": side, "block_id": block,
                            "assignment_index": assignment_index, "assignment": bits,
                            "fit_id": entry["fit_id"], "fold_index": entry["fold_index"],
                            "replicate_index": entry["replicate_index"], "condition": condition,
                            **result,
                        })

    all_support = all(row["evaluable"] for row in assignment_summary)
    pooled_model_metrics = []
    all_idx = np.arange(len(panel.keys), dtype=np.int64)
    for model_index, entry in enumerate(model_entries):
        for condition_index, condition in enumerate(("intact", "pair_swap", "cycle_4")):
            result = scoring.score_condition(
                logits[model_index, :, condition_index], truth.y, inverse_p,
                truth.native_delta, truth.preweight, truth.reference, list(panel.keys),
            )
            pooled_model_metrics.append({"fit_id": entry["fit_id"], "condition": condition, **result})
    pooled_by_condition = {
        condition: {
            key: mean_defined([row[key] for row in pooled_model_metrics if row["condition"] == condition])
            for key in ("balanced_error", "signed_margin", "mean_absolute_logit", "psi_prop", "weighted_sign_agreement", "eta_delivery")
        }
        for condition in ("intact", "pair_swap", "cycle_4")
    }
    for condition_index, condition in enumerate(("intact", "pair_swap", "cycle_4")):
        first_model = next(row for row in pooled_model_metrics if row["condition"] == condition)
        pooled_by_condition[condition]["leverage"] = first_model["leverage"]
        pooled_by_condition[condition]["q_diagnostics"] = scoring.q_diagnostics(inverse_p)

    bootstrap_seed = int.from_bytes(hashlib.sha256(BOOTSTRAP_DOMAIN + hashlib.sha256(b"F4-BINDING-01-STAGE-B/ROOT-v1\0").digest()).digest()[:8], "little")
    if all_support:
        bootstrap = scoring.paired_block_bootstrap(logits, panel.blocks, assignment_by_block, truth.y, inverse_p, bootstrap_seed, 10_000)
    else:
        bootstrap = {
            "status": "NOT_EVALUABLE_SUPPORT", "draws_requested": 10_000,
            "draws_evaluable": 0, "draws_nondevaluable": None,
            "intervals": {"pair_swap": None, "cycle_4": None},
            "decision": "NOT_EVALUABLE_SUPPORT",
            "seed_u64": bootstrap_seed,
        }
    pair_mean = mean_defined([row["mean_model_paired_delta_balanced_error"]["pair_swap"] for row in assignment_summary]) if all_support else None
    pair_interval = bootstrap.get("intervals", {}).get("pair_swap")
    if not all_support:
        disposition = "NOT_EVALUABLE_SUPPORT"
    elif bootstrap.get("status") != "PASS":
        disposition = "INCONCLUSIVE_BOOTSTRAP_SUPPORT"
    elif pair_mean is not None and pair_mean > 0.0 and pair_interval and (pair_interval[0] > 0.0 or pair_interval[1] < 0.0):
        disposition = "AVERAGE_ROLE_BINDING_DEPENDENCE_SUPPORTED"
    else:
        disposition = "NO_CONFIRMATORY_EVIDENCE_FOR_AVERAGE_DEGRADATION"

    primary = {
        "support_evaluable": all_support,
        "evaluable_assignment_count": sum(row["evaluable"] for row in assignment_summary),
        "assignment_order": list(ASSIGNMENT_ORDER),
        "pair_swap_delta_error_vector": [assignment_deltas["pair_swap"][name] for name in ASSIGNMENT_ORDER],
        "cycle_4_delta_error_vector": [assignment_deltas["cycle_4"][name] for name in ASSIGNMENT_ORDER],
        "equal_weight_assignment_mean_delta_error": {
            "pair_swap": pair_mean,
            "cycle_4": mean_defined([row["mean_model_paired_delta_balanced_error"]["cycle_4"] for row in assignment_summary]) if all_support else None,
        },
        "pair_swap_95_percent_block_cluster_interval": pair_interval,
        "cycle_4_95_percent_block_cluster_interval": bootstrap.get("intervals", {}).get("cycle_4"),
        "bootstrap": bootstrap,
    }
    analysis = {
        "schema": "F4-BINDING-01-stage-b-analysis-v0.1",
        "identity": RUN_ID,
        "status": "ANALYSIS_COMPLETE",
        "scientific_disposition": disposition,
        "classification": "FRESH_PROSPECTIVE_ENGINEERING_CONFIRMATION",
        "truth_access_provenance": "Scoring truth was opened only after prediction lock and independent integrity PASS in this Stage B identity; parent model-training outcomes were from the prior F4-PRESENTATION-03 lineage.",
        "input_hashes": {
            "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
            "source_manifest_sha256": sha_file(BRANCH / "SOURCE-INPUT-MANIFEST.json"),
            "model_registry_sha256": sha_file(REPO / Path(read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")["model_registry_path"])),
            "task_bank_manifest_sha256": sha_file(RUN / "task-bank" / "TASK-BANK-MANIFEST.json"),
            "collection_integrity_receipt_sha256": sha_file(RUN / "COLLECTION-INTEGRITY-RECEIPT.json"),
            "prediction_lock_sha256": sha_file(LOCK_PATH),
            "pre_truth_integrity_receipt_sha256": sha_file(INTEGRITY_PATH),
            "predictor_sha256": sha_file(predictor_path),
            "truth_sha256": sha_file(truth_path),
        },
        "model_count": 36,
        "row_count": len(panel.keys),
        "assignment_support": assignment_summary,
        "primary": primary,
        "secondary_pooled_model_mean_metrics": pooled_by_condition,
        "secondary_pooled_q_diagnostics": scoring.q_diagnostics(inverse_p),
        "measures_kept_separate": ["classification", "proposed Psi", "delivery-aware alignment", "trajectory endpoint capability"],
        "trajectory_endpoint_capability": "NOT_MEASURED",
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }

    assignment_csv_rows = []
    for assignment in assignment_summary:
        base = {"assignment_index": assignment["assignment_index"], "assignment": assignment["assignment"],
                "rows": assignment["support"]["rows"], "positive": assignment["support"]["positive"],
                "negative": assignment["support"]["negative"], "evaluable": assignment["evaluable"],
                "q_diagnostics": assignment["q_diagnostics"]}
        for condition in ("intact", "pair_swap", "cycle_4"):
            condition_metrics_value = assignment["condition_means_over_36_fixed_models"][condition]
            _flatten_metrics(base, f"{condition}_", condition_metrics_value)
        base["pair_swap_delta_error"] = assignment["mean_model_paired_delta_balanced_error"]["pair_swap"]
        base["cycle_4_delta_error"] = assignment["mean_model_paired_delta_balanced_error"]["cycle_4"]
        base["pair_swap_delta_margin"] = assignment["mean_model_paired_delta_margin"]["pair_swap"]
        base["cycle_4_delta_margin"] = assignment["mean_model_paired_delta_margin"]["cycle_4"]
        base["pair_swap_delta_psi"] = assignment["mean_model_paired_delta_psi_prop"]["pair_swap"]
        base["cycle_4_delta_psi"] = assignment["mean_model_paired_delta_psi_prop"]["cycle_4"]
        base["pair_swap_delta_eta_delivery"] = assignment["mean_model_paired_delta_eta_delivery"]["pair_swap"]
        base["cycle_4_delta_eta_delivery"] = assignment["mean_model_paired_delta_eta_delivery"]["cycle_4"]
        assignment_csv_rows.append(base)

    model_assignment_csv = []
    for row in assignment_model_rows:
        result = {key: value for key, value in row.items() if key not in ("q_diagnostics", "leverage")}
        result["q_diagnostics"] = row["q_diagnostics"]
        result["leverage"] = row["leverage"]
        model_assignment_csv.append(result)
    block_csv = []
    for row in block_model_rows:
        item = {key: value for key, value in row.items() if key not in ("q_diagnostics", "leverage")}
        item["q_diagnostics"] = row["q_diagnostics"]
        item["leverage"] = row["leverage"]
        block_csv.append(item)
    cell_csv = []
    for row in cell_model_rows:
        item = {key: value for key, value in row.items() if key not in ("q_diagnostics", "leverage")}
        item["q_diagnostics"] = row["q_diagnostics"]
        item["leverage"] = row["leverage"]
        cell_csv.append(item)

    support_csv = []
    for row in support_rows:
        item = dict(row)
        item["q_diagnostics"] = row["q_diagnostics"]
        support_csv.append(item)

    # CSV files are write-once, alongside the JSON analysis and the terminal receipt.
    write_csv(RUN / "ASSIGNMENT-METRICS.csv", [
        "assignment_index", "assignment", "rows", "positive", "negative", "evaluable", "q_diagnostics",
        "intact_balanced_error", "pair_swap_balanced_error", "cycle_4_balanced_error",
        "intact_signed_margin", "pair_swap_signed_margin", "cycle_4_signed_margin",
        "intact_mean_absolute_logit", "pair_swap_mean_absolute_logit", "cycle_4_mean_absolute_logit",
        "intact_psi_prop", "pair_swap_psi_prop", "cycle_4_psi_prop",
        "intact_weighted_sign_agreement", "pair_swap_weighted_sign_agreement", "cycle_4_weighted_sign_agreement",
        "intact_eta_delivery", "pair_swap_eta_delivery", "cycle_4_eta_delivery",
        "intact_q_diagnostics", "intact_leverage", "pair_swap_q_diagnostics", "pair_swap_leverage", "cycle_4_q_diagnostics", "cycle_4_leverage",
        "pair_swap_delta_error", "cycle_4_delta_error", "pair_swap_delta_margin", "cycle_4_delta_margin",
        "pair_swap_delta_psi", "cycle_4_delta_psi", "pair_swap_delta_eta_delivery", "cycle_4_delta_eta_delivery",
    ], assignment_csv_rows)
    for path, columns, rows in (
        (RUN / "MODEL-ASSIGNMENT-METRICS.csv", ["assignment_index", "assignment", "fit_id", "fold_index", "heldout_block", "replicate_index", "condition", "assignment_rows", "assignment_positive", "assignment_negative", "row_count", "positive_count", "negative_count", "balanced_error", "signed_margin", "mean_absolute_logit", "q_diagnostics", "psi_prop", "weighted_sign_agreement", "leverage", "eta_delivery"], model_assignment_csv),
        (RUN / "BLOCK-METRICS.csv", ["block_id", "assignment_index", "assignment", "fit_id", "fold_index", "replicate_index", "condition", "row_count", "positive_count", "negative_count", "balanced_error", "signed_margin", "mean_absolute_logit", "q_diagnostics", "psi_prop", "weighted_sign_agreement", "leverage", "eta_delivery"], block_csv),
        (RUN / "MODEL-CELL-METRICS.csv", ["substrate", "side", "block_id", "assignment_index", "assignment", "fit_id", "fold_index", "replicate_index", "condition", "row_count", "positive_count", "negative_count", "balanced_error", "signed_margin", "mean_absolute_logit", "q_diagnostics", "psi_prop", "weighted_sign_agreement", "leverage", "eta_delivery"], cell_csv),
        (RUN / "STAGE-B-SUPPORT-TABLE.csv", ["substrate", "side", "block_id", "assignment_index", "assignment", "generated_trials", "eligible_rows_measured", "sampled_ustar_rows", "positive_target_rows", "negative_target_rows", "inclusion_probability", "cell_empty", "q_diagnostics"], support_csv),
    ):
        write_csv(path, columns, rows)

    write_new_json(RUN / "ANALYSIS.json", analysis)
    result_text = [
        "# F4-BINDING-01 Stage B results",
        "",
        f"Identity: `{RUN_ID}`",
        "",
        f"Disposition: `{disposition}`",
        "",
        f"Fresh task blocks: 24; model panel: 36 frozen CΦ fits; scored rows: {len(panel.keys):,}.",
        f"Assignment support: {sum(row['evaluable'] for row in assignment_summary)}/6 assignments class-complete.",
        "",
        "## Primary pair-swap result",
        "",
        f"Equal-weight assignment mean Δ balanced error: `{pair_mean}`.",
        f"Block-clustered 95% interval: `{pair_interval}`.",
        f"Assignment vector in protocol order: `{primary['pair_swap_delta_error_vector']}`.",
        "",
        "The cycle is secondary. Ψprop, delivery alignment, and classification are separate; trajectory capability is not measured.",
        "This engineering confirmation does not authorize measured REACH-03, controller work, PHENO, or biological promotion.",
    ]
    write_new_bytes(RUN / "RESULTS.md", ("\n".join(result_text) + "\n").encode("utf-8"))
    outputs = [
        RUN / "ANALYSIS.json", RUN / "RESULTS.md", RUN / "ASSIGNMENT-METRICS.csv",
        RUN / "MODEL-ASSIGNMENT-METRICS.csv", RUN / "BLOCK-METRICS.csv",
        RUN / "MODEL-CELL-METRICS.csv", RUN / "STAGE-B-SUPPORT-TABLE.csv",
    ]
    terminal = {
        "schema": "F4-BINDING-01-stage-b-terminal-receipt-v0.1",
        "identity": RUN_ID,
        "status": "ANALYSIS_COMPLETE",
        "scientific_disposition": disposition,
        "truth_access_provenance": "Fresh Stage B scoring truth opened after prediction lock and independent pre-truth integrity PASS.",
        "prediction_lock_sha256": sha_file(LOCK_PATH),
        "pre_truth_integrity_receipt_sha256": sha_file(INTEGRITY_PATH),
        "analysis_sha256": sha_file(RUN / "ANALYSIS.json"),
        "output_hashes": {path.name: sha_file(path) for path in outputs},
        "primary_pair_swap_mean_delta_error": pair_mean,
        "primary_pair_swap_interval": pair_interval,
        "evaluable_assignment_count": sum(row["evaluable"] for row in assignment_summary),
        "model_count": 36,
        "row_count": len(panel.keys),
        "qualification_only": True,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    write_new_json(RUN / "STAGE-B-TERMINAL-RECEIPT.json", terminal)
    return {"disposition": disposition, "support": sum(row["evaluable"] for row in assignment_summary), "pair_mean": pair_mean, "pair_interval": pair_interval, "truth_sha256": sha_file(truth_path)}


def main() -> None:
    started = time.perf_counter()
    result = run()
    result["analysis_runtime_seconds"] = time.perf_counter() - started
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
