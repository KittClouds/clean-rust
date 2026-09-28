"""Open truth only after integrity PASS and score the frozen engineering screen."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import struct
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_MAXIMUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

BRANCH = Path(__file__).resolve().parent.parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
TASK_DIR = RUN / "task-bank"
COLLECTION = RUN / "native-collection"
BLOCKS = tuple(range(309000, 309012))
ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
REPLICATES = tuple(range(3))
EPOCHS = (1, 2, 4, 8, 16, 32, 64, 128, 200)
PRED_MAGIC = b"F4PRES03CKPTv1\0\0"
PRED_HEADER_BYTES = 90
PRED_ROW_BYTES = 54


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _weighted_error(logits: np.ndarray, targets: np.ndarray, weights: np.ndarray) -> float | None:
    prediction = np.where(logits > 0.0, 1, -1)
    rates = []
    for label in (-1, 1):
        selected = targets == label
        denominator = math.fsum(float(value) for value in weights[selected])
        if not selected.any() or denominator <= 0.0:
            return None
        numerator = math.fsum(float(weights[index]) for index in np.flatnonzero(selected) if prediction[index] != label)
        rates.append(numerator / denominator)
    return 0.5 * math.fsum(rates)


def _weighted_margin(logits: np.ndarray, targets: np.ndarray, weights: np.ndarray) -> float | None:
    means = []
    for label in (-1, 1):
        selected = targets == label
        if not selected.any():
            continue
        denominator = math.fsum(float(value) for value in weights[selected])
        if denominator <= 0.0:
            return None
        numerator = math.fsum(float(weights[index]) * int(targets[index]) * float(logits[index]) for index in np.flatnonzero(selected))
        means.append(numerator / denominator)
    if not means:
        return None
    return math.fsum(means) / len(means)


def _weighted_mean_abs(logits: np.ndarray, weights: np.ndarray) -> float | None:
    denominator = math.fsum(float(value) for value in weights)
    if denominator <= 0.0:
        return None
    return math.fsum(float(weights[index]) * abs(float(logits[index])) for index in range(len(logits))) / denominator


def _score(logits: np.ndarray, indices: np.ndarray, truth: Any, inverse_inclusion: np.ndarray) -> dict[str, Any]:
    y = truth.y[indices].astype(np.int8)
    weights = inverse_inclusion[indices]
    return {
        "row_count": int(len(indices)),
        "positive_count": int(np.count_nonzero(y == 1)),
        "negative_count": int(np.count_nonzero(y == -1)),
        "balanced_error": _weighted_error(logits, y, weights),
        "signed_margin": _weighted_margin(logits, y, weights),
        "ipw_mean_absolute_logit": _weighted_mean_abs(logits, weights),
    }


def _psi(logits: np.ndarray, indices: np.ndarray, truth: Any, weights: np.ndarray, row_keys: list[bytes]) -> dict[str, Any]:
    if len(indices) == 0:
        return {"psi_prop": None, "weighted_sign_agreement": None, "leverage_sum": 0.0, "leverage_ess": None,
                "top_1pct_share": None, "top_5pct_share": None, "top_20pct_share": None}
    sign = np.where(logits > 0.0, 1, -1)
    reference_sign = np.where(truth.reference[indices] > 0.0, 1, -1)
    leverage = weights[indices] * np.abs(truth.native_delta[indices].astype(np.float64)) * np.abs(truth.reference[indices].astype(np.float64))
    total = math.fsum(float(value) for value in leverage)
    if total <= 0.0:
        return {"psi_prop": None, "weighted_sign_agreement": None, "leverage_sum": 0.0, "leverage_ess": None,
                "top_1pct_share": None, "top_5pct_share": None, "top_20pct_share": None}
    agreement = math.fsum(float(leverage[position]) for position in range(len(indices)) if sign[position] == reference_sign[position]) / total
    square_sum = math.fsum(float(value) * float(value) for value in leverage)
    order = sorted(range(len(indices)), key=lambda position: (-float(leverage[position]), row_keys[int(indices[position])]))
    concentration = {}
    for percent in (1, 5, 20):
        count = math.ceil(percent * len(indices) / 100.0)
        concentration[f"top_{percent}pct_share"] = math.fsum(float(leverage[position]) for position in order[:count]) / total
    return {
        "psi_prop": 2.0 * agreement - 1.0,
        "weighted_sign_agreement": agreement,
        "leverage_sum": total,
        "leverage_ess": total * total / square_sum if square_sum > 0.0 else None,
        **concentration,
    }


def _delivery_alignment(logits: np.ndarray, indices: np.ndarray, truth: Any) -> float | None:
    sign = np.where(logits > 0.0, 1.0, -1.0)
    magnitude = np.abs(truth.native_delta[indices].astype(np.float64))
    preweight = truth.preweight[indices].astype(np.float64)
    reference = truth.reference[indices].astype(np.float64)
    delivered = np.clip(preweight + magnitude * sign, 0.0, 2.0) - preweight
    dot = math.fsum(float(delivered[i]) * float(reference[i]) for i in range(len(indices)))
    norm_u = math.sqrt(math.fsum(float(delivered[i]) ** 2 for i in range(len(indices))))
    norm_g = math.sqrt(math.fsum(float(reference[i]) ** 2 for i in range(len(indices))))
    if norm_u == 0.0 or norm_g == 0.0:
        return None
    return dot / (norm_u * norm_g)


def _decode_prediction(path: Path, row: dict[str, str], expected_keys: list[bytes]) -> np.ndarray:
    raw = path.read_bytes()
    if len(raw) < PRED_HEADER_BYTES or raw[:16] != PRED_MAGIC:
        raise RuntimeError(f"prediction stream header mismatch: {path.name}")
    version, block, arm_id, replicate, epoch_count, count = struct.unpack_from("<IQBBHQ", raw, 16)
    epochs = struct.unpack_from("<" + "H" * epoch_count, raw, 72) if epoch_count else ()
    if (
        (version, block, arm_id, replicate, epoch_count, count)
        != (1, int(row["heldout_block"]), ARMS.index(row["arm"]), int(row["replicate_index"]), len(EPOCHS), len(expected_keys))
        or epochs != EPOCHS
        or len(raw) != PRED_HEADER_BYTES + count * PRED_ROW_BYTES
    ):
        raise RuntimeError(f"prediction identity/shape mismatch: {path.name}")
    output = np.empty((len(EPOCHS), count), dtype=np.float32)
    for index, key in enumerate(expected_keys):
        offset = PRED_HEADER_BYTES + index * PRED_ROW_BYTES
        if raw[offset:offset + 18] != key:
            raise RuntimeError(f"prediction row key mismatch: {path.name}:{index}")
        output[:, index] = np.frombuffer(raw, dtype="<f4", count=len(EPOCHS), offset=offset + 18)
    if not np.isfinite(output).all():
        raise RuntimeError(f"nonfinite prediction stream: {path.name}")
    return output


def _truth_and_rows(integrity: dict[str, Any]):
    from presentation03_data import load_raw_panel, load_scoring_truth
    raw_path = COLLECTION / "RAW-PREDICTORS.bin"
    truth_path = COLLECTION / "RAW-SCORING-TRUTH.bin"
    if sha_file(truth_path) != integrity.get("truth_file_sha256"):
        raise RuntimeError("truth file changed after integrity PASS")
    raw = load_raw_panel(raw_path)
    truth = load_scoring_truth(truth_path)
    if len(raw.keys) != len(truth.y):
        raise RuntimeError("truth/predictor row count mismatch")
    return raw, truth


def _assignment_labels(task_manifest: dict[str, Any]) -> tuple[dict[int, int], dict[int, str]]:
    by_block = {int(row["block_id"]): int(row["assignment_index"]) for row in task_manifest["blocks"]}
    labels = {}
    for index, assignment in enumerate(task_manifest["assignments"]):
        bits = ["1" if cue in assignment else "0" for cue in range(4)]
        labels[index] = "".join(bits)
    if set(by_block) != set(BLOCKS):
        raise RuntimeError("task assignment blocks malformed")
    return by_block, labels


def _subset_indices(block_to_indices: dict[int, np.ndarray], blocks: tuple[int, ...]) -> np.ndarray:
    return np.concatenate([block_to_indices[block] for block in blocks])


def _scatter_pooled_logits(
    prediction_map: dict[tuple[str, int, int], np.ndarray],
    arm: str,
    replicate: int,
    block_to_indices: dict[int, np.ndarray],
    blocks: tuple[int, ...],
    row_count: int,
    checkpoint_index: int = -1,
) -> np.ndarray:
    """Restore block predictions to raw-panel row order before pooled scoring."""
    output = np.empty(row_count, dtype=np.float32)
    seen = np.zeros(row_count, dtype=np.bool_)
    for block in blocks:
        indices = block_to_indices[block]
        values = prediction_map[(arm, replicate, block)][checkpoint_index]
        if len(indices) != len(values) or seen[indices].any():
            raise RuntimeError("pooled prediction block rows overlap or differ in size")
        output[indices] = values
        seen[indices] = True
    if not seen.all():
        raise RuntimeError("pooled prediction reconstruction has missing rows")
    return output


def run() -> dict[str, Any]:
    analysis_path = RUN / "ANALYSIS.json"
    results_path = RUN / "RESULTS.md"
    if analysis_path.exists() or results_path.exists():
        raise RuntimeError("analysis output already exists; preserve this identity")
    freeze = read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    for entry in freeze["source_files"]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen source drift before analysis: {entry['path']}")
    integrity = read_json(RUN / "INTEGRITY-RECEIPT.json")
    if (integrity.get("status") != "PASS"
        or integrity.get("heldout_scoring_truth_state") != "TARGET_POLARITY_OPEN_FOR_SUPPORT_ONLY"
        or integrity.get("heldout_scoring_values_opened") is not True
        or integrity.get("support_only_truth_fields_opened") != ["inclusion_probability_p", "target_polarity_Y"]
        or integrity.get("comparative_scoring_fields_opened_before_integrity") != []
        or integrity.get("remaining_truth_fields_sealed") != ["native_delta", "preweight", "reference_value"]):
        raise RuntimeError("integrity lacks declared support-only truth-access context")
    lock = read_json(RUN / "PREDICTION-LOCK.json")
    if lock.get("status") != "PASS" or lock.get("fit_count") != 144:
        raise RuntimeError("prediction lock not complete")
    fit_rows = list(csv.DictReader((RUN / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="")))
    task_manifest = read_json(TASK_DIR / "TASK-BANK-MANIFEST.json")
    block_assignment, assignment_names = _assignment_labels(task_manifest)
    raw, truth = _truth_and_rows(integrity)
    p = truth.inclusion_probability.astype(np.float64)
    if (p <= 0.0).any() or (p > 1.0).any() or not np.isfinite(p).all():
        raise RuntimeError("invalid recorded inclusion probabilities")
    inverse_inclusion = 1.0 / p
    block_to_indices = {block: np.flatnonzero(raw.blocks == np.uint64(block)) for block in BLOCKS}
    assignment_to_blocks = {index: tuple(block for block in BLOCKS if block_assignment[block] == index) for index in range(6)}
    if any(len(value) != 2 for value in assignment_to_blocks.values()):
        raise RuntimeError("assignment strata no longer have two heldout blocks")

    prediction_map: dict[tuple[str, int, int], np.ndarray] = {}
    for row in fit_rows:
        block = int(row["heldout_block"])
        expected_keys = [key for key in raw.keys if struct.unpack_from("<Q", key, 2)[0] == block]
        pred = _decode_prediction(RUN / row["prediction_path"], row, expected_keys)
        prediction_map[(row["arm"], int(row["replicate_index"]), block)] = pred
    if len(prediction_map) != 144:
        raise RuntimeError("analysis prediction grid incomplete")

    primary: dict[str, Any] = {
        "endpoint_epoch": 200,
        "weighting": "inverse inclusion probability q=1/p, class-balanced within assignment, then equal weight across six assignments",
        "assignment_scores_by_replicate": {},
        "macro_error_by_replicate": {},
        "mean_macro_error": {},
        "replicate_contrasts": {},
        "assignment_contrasts": {},
        "block_scores": [],
        "support": {},
    }
    assignment_score_cache: dict[tuple[str, int, int], float | None] = {}
    assignment_support = {}
    for assignment, group_blocks in assignment_to_blocks.items():
        indices = _subset_indices(block_to_indices, group_blocks)
        y = truth.y[indices]
        positive = int(np.count_nonzero(y == 1))
        negative = int(np.count_nonzero(y == -1))
        assignment_support[assignment] = {
            "assignment_index": assignment,
            "assignment_bits": assignment_names[assignment],
            "blocks": list(group_blocks),
            "row_count": int(len(indices)),
            "positive_count": positive,
            "negative_count": negative,
            "evaluable": bool(positive and negative),
        }
        for replicate in REPLICATES:
            for arm in ARMS:
                logits_parts = [prediction_map[(arm, replicate, block)][-1] for block in group_blocks]
                logits = np.concatenate(logits_parts)
                score = _weighted_error(logits, y, inverse_inclusion[indices])
                assignment_score_cache[(arm, replicate, assignment)] = score
                primary["assignment_scores_by_replicate"].setdefault(str(replicate), {}).setdefault(arm, {})[str(assignment)] = score
    all_assignment_support = all(row["evaluable"] for row in assignment_support.values())
    for replicate in REPLICATES:
        primary["macro_error_by_replicate"][str(replicate)] = {}
        for arm in ARMS:
            values = [assignment_score_cache[(arm, replicate, assignment)] for assignment in range(6)]
            macro = math.fsum(value for value in values if value is not None) / 6 if all(value is not None for value in values) else None
            primary["macro_error_by_replicate"][str(replicate)][arm] = macro
    for arm in ARMS:
        values = [primary["macro_error_by_replicate"][str(rep)][arm] for rep in REPLICATES]
        primary["mean_macro_error"][arm] = math.fsum(value for value in values if value is not None) / 3 if all(value is not None for value in values) else None
    for other in ("D", "Cphi_unshared", "Cphi_shuffled"):
        replicate_values = []
        for replicate in REPLICATES:
            left = primary["macro_error_by_replicate"][str(replicate)]["Cphi"]
            right = primary["macro_error_by_replicate"][str(replicate)][other]
            replicate_values.append(None if left is None or right is None else left - right)
        primary["replicate_contrasts"][f"Cphi_minus_{other}"] = replicate_values
    for assignment in range(6):
        primary["assignment_contrasts"][str(assignment)] = {}
        for other in ("D", "Cphi_unshared", "Cphi_shuffled"):
            values = [assignment_score_cache[("Cphi", rep, assignment)] - assignment_score_cache[(other, rep, assignment)]
                      for rep in REPLICATES
                      if assignment_score_cache[("Cphi", rep, assignment)] is not None and assignment_score_cache[(other, rep, assignment)] is not None]
            primary["assignment_contrasts"][str(assignment)][f"Cphi_minus_{other}"] = math.fsum(values) / len(values) if len(values) == 3 else None

    for block in BLOCKS:
        indices = block_to_indices[block]
        y = truth.y[indices]
        block_record = {
            "block_id": block,
            "assignment_index": block_assignment[block],
            "assignment_bits": assignment_names[block_assignment[block]],
            "row_count": int(len(indices)),
            "positive_count": int(np.count_nonzero(y == 1)),
            "negative_count": int(np.count_nonzero(y == -1)),
            "arms": {},
        }
        for replicate in REPLICATES:
            block_record["arms"][str(replicate)] = {}
            for arm in ARMS:
                logits = prediction_map[(arm, replicate, block)][-1]
                block_record["arms"][str(replicate)][arm] = _score(logits, indices, truth, inverse_inclusion)
        primary["block_scores"].append(block_record)
    primary["support"] = {
        "assignment_strata_evaluable": sum(bool(value["evaluable"]) for value in assignment_support.values()),
        "required_assignment_strata": 6,
        "all_assignment_strata_evaluable": all_assignment_support,
        "assignment_details": {str(key): value for key, value in assignment_support.items()},
        "block_class_complete_count": sum(row["positive_count"] > 0 and row["negative_count"] > 0 for row in primary["block_scores"]),
    }
    cphi_mean = primary["mean_macro_error"]["Cphi"]
    d_mean = primary["mean_macro_error"]["D"]
    replicate_wins = sum(value is not None and value < 0.0 for value in primary["replicate_contrasts"]["Cphi_minus_D"])
    assignment_mean_contrasts = [primary["assignment_contrasts"][str(index)]["Cphi_minus_D"] for index in range(6)]
    assignment_wins = sum(value is not None and value < 0.0 for value in assignment_mean_contrasts)
    primary["engineering_nomination"] = {
        "rule": "all six assignment strata evaluable; Cphi macro error lower than D; Cphi wins at least 2/3 replicate macro comparisons; Cphi wins at least 4/6 assignment-specific mean comparisons",
        "support_pass": all_assignment_support,
        "mean_macro_error_Cphi_lower_than_D": cphi_mean is not None and d_mean is not None and cphi_mean < d_mean,
        "replicate_wins_Cphi_minus_D": replicate_wins,
        "assignment_wins_Cphi_minus_D": assignment_wins,
        "disposition": "Cphi_RETAINS_ENGINEERING_LEAD" if all_assignment_support and cphi_mean is not None and d_mean is not None and cphi_mean < d_mean and replicate_wins >= 2 and assignment_wins >= 4 else "NO_CPHI_ENGINEERING_NOMINATION",
        "calibration_or_measured_execution_authorized": False,
    }

    checkpoints: dict[str, Any] = {}
    for epoch_index, epoch in enumerate(EPOCHS):
        by_arm = {}
        for arm in ARMS:
            replicate_scores = []
            for replicate in REPLICATES:
                assignment_values = []
                for assignment, group_blocks in assignment_to_blocks.items():
                    indices = _subset_indices(block_to_indices, group_blocks)
                    logits = _scatter_pooled_logits(
                        prediction_map, arm, replicate, block_to_indices, BLOCKS, len(raw.keys), epoch_index
                    )[indices]
                    score = _weighted_error(logits, truth.y[indices], inverse_inclusion[indices])
                    assignment_values.append(score)
                replicate_scores.append(math.fsum(value for value in assignment_values if value is not None) / 6 if all(value is not None for value in assignment_values) else None)
            by_arm[arm] = replicate_scores
        checkpoints[str(epoch)] = {"macro_error_by_replicate": by_arm, "primary_endpoint": epoch == 200}

    secondary: dict[str, Any] = {"checkpoint_diagnostics": checkpoints, "polarity_and_delivery": {}}
    for assignment, group_blocks in assignment_to_blocks.items():
        indices = _subset_indices(block_to_indices, group_blocks)
        for replicate in REPLICATES:
            for arm in ARMS:
                logits = np.concatenate([prediction_map[(arm, replicate, block)][-1] for block in group_blocks])
                key = f"assignment-{assignment}/replicate-{replicate}/{arm}"
                psi = _psi(logits, indices, truth, inverse_inclusion, raw.keys)
                secondary["polarity_and_delivery"][key] = {
                    **psi,
                    "eta_delivery_cosine": _delivery_alignment(logits, indices, truth),
                }

    global_indices = np.arange(len(raw.keys), dtype=np.int64)
    pooled_secondary = {}
    for replicate in REPLICATES:
        pooled_secondary[str(replicate)] = {}
        for arm in ARMS:
            logits = _scatter_pooled_logits(prediction_map, arm, replicate, block_to_indices, BLOCKS, len(raw.keys))
            pooled_secondary[str(replicate)][arm] = _score(logits, global_indices, truth, inverse_inclusion)
    secondary["pooled_all_rows_secondary"] = pooled_secondary

    result = {
        "schema": "F4-PRESENTATION-03-analysis-v1",
        "run_id": RUN_ID,
        "analysis_status": "ANALYSIS_COMPLETE_AFTER_SUPPORT_ONLY_TARGET_ACCESS",
        "truth_access_provenance": {
            "target_polarity_opened_before_fitting_for_support_only": True,
            "comparative_scoring_fields_opened_before_integrity": [],
            "remaining_truth_fields_opened_only_after_integrity_pass": ["native_delta", "preweight", "reference_value"],
            "support_receipt_sha256": sha(Path(STUDY / "runs" / "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1" / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json").read_bytes()),
        },
        "integrity_receipt_sha256": sha_file(RUN / "INTEGRITY-RECEIPT.json"),
        "prediction_lock_sha256": sha_file(RUN / "PREDICTION-LOCK.json"),
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "truth_file_sha256": sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin"),
        "analysis_source_sha256": sha_file(Path(__file__).resolve()),
        "prediction_count": len(prediction_map),
        "row_count": len(raw.keys),
        "task_assignment_rule": "12 unscreened blocks; two independent blocks per six balanced cue-label assignments",
        "inclusion_probability_audit": {
            "stored_field_semantics": "p_inclusion_j",
            "analysis_weight": "q_j=1/p_inclusion_j",
            "archived_comparison_caveat": "Not directly comparable to archived analyses that fed the stored p field to q-weighted helper functions.",
            "minimum_probability": float(np.min(p)),
            "maximum_probability": float(np.max(p)),
        },
        "primary": primary,
        "secondary": secondary,
        "interpretation_limits": [
            "Engineering-only comparison on this frozen 12-block panel and fixed 200-epoch training budget.",
            "Assignment is balanced and stratified; two blocks per assignment do not identify leave-one-assignment-out transfer.",
            "Checkpoint diagnostics are descriptive and did not select a checkpoint.",
            "No result authorizes F4 calibration, measured REACH-03, a polarity controller, PHENO, or biological promotion.",
        ],
        "qualification_only": True,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    raw_json = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_new_bytes(analysis_path, raw_json)
    markdown = _render_results(result)
    write_new_bytes(results_path, markdown.encode("utf-8"))
    terminal = {
        "schema": "F4-PRESENTATION-03-terminal-receipt-v1",
        "status": "PASS_ANALYSIS_COMPLETE_ENGINEERING_ONLY",
        "run_id": RUN_ID,
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "truth_access_provenance": "target polarity opened before fits for the support gate; remaining comparative truth was opened only after integrity PASS",
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "collection_receipt_sha256": sha_file(RUN / "COLLECTION-RECEIPT.json"),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.csv"),
        "prediction_lock_sha256": sha_file(RUN / "PREDICTION-LOCK.json"),
        "integrity_receipt_sha256": sha_file(RUN / "INTEGRITY-RECEIPT.json"),
        "analysis_sha256": sha_bytes(raw_json),
        "results_sha256": sha_file(results_path),
        "fit_count": 144,
        "block_count": 12,
        "assignment_count": 6,
        "primary_engineering_disposition": primary["engineering_nomination"]["disposition"],
        "qualification_only": True,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    terminal_raw = (json.dumps(terminal, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_new_bytes(RUN / "F4-PRESENTATION-03-TERMINAL-RECEIPT.json", terminal_raw)
    return result


def _render_results(result: dict[str, Any]) -> str:
    primary = result["primary"]
    lines = [
        "# F4-PRESENTATION-03 Engineering Screen",
        "",
        "**Identity:** `F4-PRESENTATION-03-ENG1`  ",
        "**Status:** Engineering-only comparison; no scientific promotion.  ",
        f"**Rows:** {result['row_count']:,}; **fits:** {result['prediction_count']}; **assignments:** 6, two blocks each.",
        "",
        "## Primary endpoint",
        "",
        "Epoch 200, class-balanced within each assignment using inverse inclusion weights, then equally weighted across the six assignments. Negative CΦ-minus-control differences favor CΦ.",
        "",
        "| Arm | Macro balanced error |",
        "| --- | ---: |",
    ]
    for arm in ARMS:
        value = primary["mean_macro_error"][arm]
        lines.append(f"| {arm} | {'null' if value is None else f'{value:.6f}'} |")
    lines.extend(["", "## CΦ contrasts", "", "| Contrast | Replicate values | Mean |", "| --- | --- | ---: |"])
    for name, values in primary["replicate_contrasts"].items():
        valid = [value for value in values if value is not None]
        mean = math.fsum(valid) / len(valid) if len(valid) == 3 else None
        printable = ", ".join("null" if value is None else f"{value:+.6f}" for value in values)
        lines.append(f"| {name} | {printable} | {'null' if mean is None else f'{mean:+.6f}'} |")
    lines.extend(["", "## Assignment support", "", "| Assignment | Blocks | + rows | − rows | Evaluable | CΦ−D |", "| --- | --- | ---: | ---: | --- | ---: |"])
    support = primary["support"]["assignment_details"]
    for index in range(6):
        item = support[str(index)]
        contrast = primary["assignment_contrasts"][str(index)]["Cphi_minus_D"]
        lines.append(f"| {item['assignment_bits']} | {item['blocks'][0]}, {item['blocks'][1]} | {item['positive_count']} | {item['negative_count']} | {item['evaluable']} | {'null' if contrast is None else f'{contrast:+.6f}'} |")
    lines.extend([
        "",
        "## Leverage concentration",
        "",
        "Each Ψ report is stored with leverage ESS and top 1%, 5%, and 20% leverage shares in `ANALYSIS.json`. Classification error, margin orientation, Ψ, and delivery alignment remain separate measures.",
        "",
        "## Disposition",
        "",
        f"Engineering nomination: `{primary['engineering_nomination']['disposition']}`. This does not authorize F4 calibration, measured REACH-03, controller work, PHENO, or biological promotion.",
        "",
        "The raw truth field stores the inclusion probability p; this analysis uses q=1/p as required by the frozen REACH math contract. Archived scorer outputs that used p directly are not directly comparable.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    run()
