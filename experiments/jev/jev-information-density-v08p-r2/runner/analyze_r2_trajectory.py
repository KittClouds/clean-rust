"""Analyze the sealed P-R2 full-step response matrix with frozen P semantics."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
P_PHASE = ROOT / "experiments/jev-information-density-v08p/phase_b"
R2_WORK = ROOT / "experiments/jev-information-density-v08p-r2"
R2_ROOT = Path(r"D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2")
OUTPUT = R2_ROOT / "evaluation"
PREDICTIONS = OUTPUT / "raw-predictions-v01.jsonl"
PREDICTION_TREE = OUTPUT / "raw-prediction-hash-tree-v01.json"
INFERENCE_RECEIPT = OUTPUT / "inference-receipt-v01.json"
OPENING_RECEIPT = OUTPUT / "r2-panel-opening-receipt-v01.json"
RUN_CONTRACT = P_PHASE / "phase-b-p-run-contract-v01.json"
ANALYSIS_CONTRACT = P_PHASE / "phase-b-p-analysis-contract-v01.json"
R2_CONTRACT = R2_WORK / "contracts/r2-execution-contract-v01.json"
ADDENDUM = R2_WORK / "contracts/p-r2-analysis-addendum-v01.json"
TRAINER = R2_WORK / "runner/train_r2.py"
EVALUATOR = R2_WORK / "runner/evaluate_r2_trajectory.py"
ADAPTER_PATH = R2_WORK / "runner/r2_analysis_adapter.py"
TEST_PATH = R2_WORK / "runner/test_r2_trajectory_analysis.py"
METRIC_SOURCE = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
TRAJECTORY_HELPER = P_PHASE / "trajectory_analysis.py"

SEEDS = (3243871208, 669993655, 3076094663)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
METRICS = (
    "sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip", "anchor_old_map",
    "fact_new_map", "strict_transition", "correct_direction", "new_probability_delta",
    "delta_mae", "anchor_nll", "anchor_brier", "anchor_gold_map_accuracy",
    "sham_gold_probability_movement", "sham_margin_movement",
    "matched_gold_probability_movement", "matched_margin_movement",
)
TRAJECTORY_COORDINATES = (
    "new_probability_delta", "anchor_old_map", "sham_l1", "matched_l1",
    "fact_new_map", "strict_transition",
)
CHECKPOINT_STEPS = (40, 80, *range(81, 121))
EXPECTED_PREDICTIONS = 3_048_000
CELL_ROWS = 8_000
NEIGHBORHOODS = 2_000
TRANSITION_CELLS = (
    ("A_AND_F", True, True), ("A_AND_NOT_F", True, False),
    ("NOT_A_AND_F", False, True), ("NOT_A_AND_NOT_F", False, False),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite sealed analysis output: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with temporary.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load sealed analysis implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def expected_cells() -> list[tuple[int, str, int]]:
    result = []
    for seed in SEEDS:
        result.append((seed, "COMMON_INIT", 0))
        for step in CHECKPOINT_STEPS:
            result.extend((seed, arm, step) for arm in ARMS)
    return result


def verify_prediction_seal() -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    require(PREDICTIONS.is_file() and PREDICTION_TREE.is_file() and INFERENCE_RECEIPT.is_file()
            and OPENING_RECEIPT.is_file(), "P-R2 raw prediction seal is incomplete")
    tree, receipt, opening = read_json(PREDICTION_TREE), read_json(INFERENCE_RECEIPT), read_json(OPENING_RECEIPT)
    pred_hash = sha256_file(PREDICTIONS)
    require(tree.get("status") == "P_R2_COMPLETE_RAW_PREDICTION_MATRIX_SEALED_BEFORE_METRICS"
            and tree.get("prediction_rows") == EXPECTED_PREDICTIONS and tree.get("cell_count") == 381,
            "P-R2 prediction hash tree is incomplete")
    require(tree["raw_predictions"]["sha256"] == pred_hash
            and tree["raw_predictions"]["bytes"] == PREDICTIONS.stat().st_size,
            "raw prediction bytes differ from sealed prediction tree")
    require(receipt.get("prediction_hash_tree_sha256") == sha256_file(PREDICTION_TREE)
            and receipt.get("prediction_sha256") == pred_hash
            and receipt.get("prediction_rows") == EXPECTED_PREDICTIONS
            and receipt.get("predictions_before_metrics") is True,
            "inference receipt does not bind the complete raw prediction set")
    require(opening.get("status") == "P_R2_FRESH_PANEL_OPENED_AFTER_COMPLETE_TRAINING_SEAL"
            and opening.get("opening_count") == 1
            and opening.get("training_seal_sha256") == tree["training_seal_sha256"],
            "P-R2 panel opening receipt does not bind the sealed training tree")
    return tree, receipt, {"raw_predictions": pred_hash, "prediction_tree": sha256_file(PREDICTION_TREE),
                           "inference_receipt": sha256_file(INFERENCE_RECEIPT),
                           "opening_receipt": sha256_file(OPENING_RECEIPT)}


def read_cell(stream: TextIO, expected: tuple[int, str, int], metric: Any) -> list[dict[str, Any]]:
    seed, arm, step = expected
    records = []
    seen: set[str] = set()
    for _ in range(NEIGHBORHOODS):
        views: dict[str, dict[str, Any]] = {}
        neighborhood_id: str | None = None
        for expected_view in VIEWS:
            line = stream.readline()
            if not line:
                raise RuntimeError(f"prediction stream ended in cell {seed}/{arm}/{step}")
            row = json.loads(line)
            require((int(row["seed"]), str(row["arm"]), int(row["global_step"])) == expected,
                    f"raw response-matrix order mismatch at {seed}/{arm}/{step}")
            require(row.get("view") == expected_view,
                    f"view order mismatch at {seed}/{arm}/{step}: expected {expected_view}")
            current = str(row["neighborhood_id"])
            neighborhood_id = current if neighborhood_id is None else neighborhood_id
            require(current == neighborhood_id, "a neighborhood's four view predictions are not contiguous")
            require(expected_view not in views, "duplicate view identity in prediction cell")
            views[expected_view] = row
        require(neighborhood_id is not None and set(views) == set(VIEWS) and neighborhood_id not in seen,
                f"duplicate/incomplete neighborhood block in {seed}/{arm}/{step}")
        seen.add(neighborhood_id)
        computed = metric.neighborhood_metrics(views)
        family = str(computed["family_id"])
        require(family in FAMILIES, f"unexpected P-R2 evaluation family: {family}")
        records.append({"seed": seed, "arm": arm, "global_step": step,
                        "neighborhood_id": neighborhood_id, "family_id": family,
                        **{name: float(computed[name]) for name in METRICS}})
    require(len(records) == NEIGHBORHOODS and len(seen) == NEIGHBORHOODS,
            f"cell {seed}/{arm}/{step} does not have 2000 neighborhoods")
    counts = Counter(row["family_id"] for row in records)
    require(counts == Counter({family: 500 for family in FAMILIES}),
            f"four-family allocation changed in cell {seed}/{arm}/{step}: {counts}")
    return records


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(rows),
        "overall": {name: float(np.mean([row[name] for row in rows], dtype=np.float64)) for name in METRICS},
        "by_family": {
            family: {name: float(np.mean([row[name] for row in rows if row["family_id"] == family], dtype=np.float64))
                     for name in METRICS}
            for family in FAMILIES
        },
    }


def transition_decomposition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"n": len(rows), "overall": {}, "by_family": {family: {} for family in FAMILIES}}
    for name, old, new in TRANSITION_CELLS:
        selected = [row for row in rows if bool(row["anchor_old_map"]) is old and bool(row["fact_new_map"]) is new]
        result["overall"][name] = {"count": len(selected), "proportion": len(selected) / len(rows)}
        for family in FAMILIES:
            subset = [row for row in selected if row["family_id"] == family]
            result["by_family"][family][name] = {"count": len(subset), "proportion": len(subset) / 500}
    require(sum(value["count"] for value in result["overall"].values()) == len(rows),
            "A/F transition cells do not exhaust the neighborhood set")
    for family in FAMILIES:
        require(sum(value["count"] for value in result["by_family"][family].values()) == 500,
                f"A/F transition cells do not exhaust family {family}")
    strict = result["overall"]["A_AND_F"]["proportion"]
    require(abs(strict - float(np.mean([row["strict_transition"] for row in rows]))) <= 1e-15,
            "strict transition does not equal the A_AND_F cell")
    return result


def build_report(response: dict[str, Any], event_results: dict[str, Any], plan_hash: str,
                 tree_hashes: dict[str, str]) -> str:
    lines = [
        "# JEV v0.8P-R2: Late Transition Localization",
        "",
        "**Disposition:** fresh-panel, instrumented P-R2 trajectory result. The original v0.8P line remains closed; R1 remains a construction failure. This is a new training trajectory and a fresh-world draw under the same four families and p0-p3 measurement surfaces, not novel-family or novel-template generalization.",
        "",
        "All nine DUP/MATCHED/SHAM runs completed the frozen 120-step recipe. The evaluator consumed the three common initialization baselines plus every contracted trained checkpoint: step 40, step 80, and each step 81-120. No checkpoint was selected or promoted. The complete raw prediction set was sealed before metrics were computed.",
        "",
        "## Terminal coordinates (step 120)",
        "",
        "Rates are proportions. Locality, fact response, anchor preservation, probability movement, and exact-delta error are kept separate; there is no composite score. The three seeds are three observed trajectories, not a population estimate.",
        "",
        "| Seed | Arm | Sham L1 | Sham flip | Matched L1 | Matched flip | A_old | F_new | Strict A→F | Δp_new | Δ MAE | Anchor NLL | Anchor Brier |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for seed in SEEDS:
        for arm in ARMS:
            metric = response[str(seed)][arm]["120"]["overall"]
            lines.append(
                f"| {seed} | {arm} | {metric['sham_l1']:.6f} | {metric['sham_map_flip']:.4f} | "
                f"{metric['matched_l1']:.6f} | {metric['matched_map_flip']:.4f} | "
                f"{metric['anchor_old_map']:.4f} | {metric['fact_new_map']:.4f} | "
                f"{metric['strict_transition']:.4f} | {metric['new_probability_delta']:.6f} | "
                f"{metric['delta_mae']:.6f} | {metric['anchor_nll']:.6f} | {metric['anchor_brier']:.6f} |"
            )
    lines.extend(["", "## Descriptive event timing", "",
                  "Onsets are properties of the sampled step-80-to-120 checkpoint path under the frozen simultaneous-band and persistence rule. They are not claims about the unobserved continuous-time moment when a capability emerged, and they are not checkpoint-selection criteria.",
                  "", "| Seed | Arm | Fact Δp rise | Anchor old-MAP loss | Sham L1 decrease / increase | Matched L1 decrease / increase | Fact-new MAP persistent | Strict transition persistent |",
                  "|---:|---|---|---|---|---|---|---|"])
    for seed in SEEDS:
        for arm in ARMS:
            ev = event_results[str(seed)][arm]
            def onset_text(obj: dict[str, Any]) -> str:
                return f"{obj.get('status')}@{obj.get('onset_step')}" if obj.get("onset_step") is not None else str(obj.get("status"))
            fact = onset_text(ev["new_probability_delta"]["onsets"]["positive_rise"])
            anchor = onset_text(ev["anchor_old_map"]["onsets"]["anchor_loss"])
            sham_dec = onset_text(ev["sham_l1"]["onsets"]["decrease"])
            sham_inc = onset_text(ev["sham_l1"]["onsets"]["increase"])
            mat_dec = onset_text(ev["matched_l1"]["onsets"]["decrease"])
            mat_inc = onset_text(ev["matched_l1"]["onsets"]["increase"])
            fact_map = onset_text(ev["fact_new_map"]["overall"]["first_three_consecutive_nonzero"])
            strict_map = onset_text(ev["strict_transition"]["overall"]["first_three_consecutive_nonzero"])
            lines.append(f"| {seed} | {arm} | {fact} | {anchor} | {sham_dec} / {sham_inc} | {mat_dec} / {mat_inc} | {fact_map} | {strict_map} |")
    lines.extend([
        "", "## Reading boundary", "",
        "Interpret timing differences together with all capability coordinates and the family-stratified trajectories in the sealed JSON. The primary observational unit here is the fixed neighborhood panel conditional on each of the three optimizer seeds. This analysis does not establish mechanism, does not imply a universally optimal training duration, and does not validate any intermediate checkpoint as an operating point.",
        "",
        f"Raw prediction SHA-256: `{tree_hashes['raw_predictions']}`  ",
        f"Shared bootstrap-plan SHA-256: `{plan_hash}`",
        "",
        "NewTight, legacy evaluation, Phoenix, and any follow-on training were not accessed.",
    ])
    return "\n".join(lines) + "\n"


def execute() -> None:
    stage = "sealed_prediction_verification"
    started = time.perf_counter()
    try:
        prediction_tree, inference_receipt, tree_hashes = verify_prediction_seal()
        contract = json.loads(ANALYSIS_CONTRACT.read_text(encoding="utf-8"))
        addendum = json.loads(ADDENDUM.read_text(encoding="utf-8"))
        metric = import_module(METRIC_SOURCE, "jev_r2_frozen_metric_analyzer")
        helper = import_module(TRAJECTORY_HELPER, "jev_r2_frozen_trajectory_helper")
        adapter = import_module(ADAPTER_PATH, "jev_r2_analysis_adapter")
        runtime_contract = adapter.prepare_runtime_contract(contract, addendum, helper)

        metric_rows_path = OUTPUT / "neighborhood-metrics-v01.jsonl"
        response: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        transitions: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        checkpoint_keys: list[tuple[int, str, int]] = []
        trajectory_arrays: dict[tuple[int, str, str], np.ndarray] = {}
        canonical_ids: list[str] | None = None
        canonical_index: dict[str, int] = {}
        family_labels: list[str] = []

        stage = "full_prediction_matrix_analysis"
        with PREDICTIONS.open("r", encoding="utf-8") as pred_stream, metric_rows_path.open("x", encoding="utf-8", newline="\n") as metric_stream:
            for cell in expected_cells():
                seed, arm, step = cell
                rows = read_cell(pred_stream, cell, metric)
                if canonical_ids is None:
                    ordered, labels = adapter.canonical_panel_order(
                        [{"neighborhood_id": row["neighborhood_id"], "family_id": row["family_id"]} for row in rows],
                        addendum["bootstrap_implementation"]["family_order"],
                    )
                    canonical_ids = ordered
                    family_labels = labels
                    canonical_index = {nid: index for index, nid in enumerate(canonical_ids)}
                    for current_seed in SEEDS:
                        for current_arm in ARMS:
                            for coordinate in TRAJECTORY_COORDINATES:
                                trajectory_arrays[(current_seed, current_arm, coordinate)] = np.full(
                                    (41, NEIGHBORHOODS), np.nan, dtype=np.float64)
                require(set(row["neighborhood_id"] for row in rows) == set(canonical_index),
                        f"neighborhood identity set changed in {seed}/{arm}/{step}")
                for row in rows:
                    metric_stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                summary = summarize(rows)
                transition = transition_decomposition(rows)
                response.setdefault(str(seed), {}).setdefault(arm, {})[str(step)] = summary
                transitions.setdefault(str(seed), {}).setdefault(arm, {})[str(step)] = transition
                checkpoint_keys.append(cell)
                if arm in ARMS and step >= 80:
                    matrix_row = 0 if step == 80 else step - 80
                    row_arrays = trajectory_arrays
                    for record in rows:
                        column = canonical_index[record["neighborhood_id"]]
                        for coordinate in TRAJECTORY_COORDINATES:
                            row_arrays[(seed, arm, coordinate)][matrix_row, column] = float(record[coordinate])
                if len(checkpoint_keys) % 15 == 0:
                    print(json.dumps({"event": "r2_metric_cell_complete", "cells": len(checkpoint_keys),
                                      "expected_cells": 381, "elapsed_seconds": round(time.perf_counter() - started, 2)},
                                     separators=(",", ":")), flush=True)
            require(not pred_stream.readline(), "extra rows exist after the contracted 381-cell matrix")
            metric_stream.flush(); os.fsync(metric_stream.fileno())
        require(len(checkpoint_keys) == 381 and all(np.isfinite(values).all() for values in trajectory_arrays.values()),
                "trajectory analysis did not consume all cells or left a step/neighborhood coordinate missing")
        metric_sha = sha256_file(metric_rows_path)

        stage = "shared_bootstrap_and_event_time_analysis"
        plan, plan_hash = adapter.resample_plan(helper, runtime_contract, family_labels, addendum)
        plan_path = OUTPUT / "shared-bootstrap-resample-plan-v01.npy"
        if plan_path.exists():
            raise FileExistsError("shared R2 bootstrap plan already exists; no alternate plan")
        with plan_path.open("xb") as stream:
            np.save(stream, plan, allow_pickle=False)
            stream.flush(); os.fsync(stream.fileno())
        saved_plan = np.load(plan_path, mmap_mode="r", allow_pickle=False)
        require(saved_plan.shape == (10_000, 2_000) and saved_plan.dtype == np.int32
                and hashlib.sha256(np.asarray(saved_plan, dtype="<i4").tobytes(order="C")).hexdigest() == plan_hash,
                "persisted shared bootstrap plan failed byte/value validation")

        event_results: dict[str, dict[str, Any]] = {}
        for seed in SEEDS:
            event_results[str(seed)] = {}
            for arm in ARMS:
                result: dict[str, Any] = {}
                for coordinate in ("new_probability_delta", "anchor_old_map", "sham_l1", "matched_l1"):
                    result[coordinate] = adapter.continuous_analysis(
                        helper, coordinate, trajectory_arrays[(seed, arm, coordinate)], family_labels,
                        plan, runtime_contract, addendum,
                    )
                for coordinate in ("fact_new_map", "strict_transition"):
                    result[coordinate] = helper.binary_appearance_events(
                        coordinate, trajectory_arrays[(seed, arm, coordinate)], family_labels, runtime_contract)
                event_results[str(seed)][arm] = result
                print(json.dumps({"event": "r2_seed_arm_event_times_complete", "seed": seed, "arm": arm,
                                  "elapsed_seconds": round(time.perf_counter() - started, 2)},
                                 separators=(",", ":")), flush=True)

        pairwise: dict[str, Any] = {}
        for seed in SEEDS:
            pairwise[str(seed)] = {}
            for step in (40, 80, *range(81, 121)):
                dup = response[str(seed)]["B-DUP"][str(step)]["overall"]
                matched = response[str(seed)]["B-MATCHED"][str(step)]["overall"]
                sham = response[str(seed)]["B-SHAM"][str(step)]["overall"]
                pairwise[str(seed)][str(step)] = {
                    "B-MATCHED_minus_B-DUP": {name: matched[name] - dup[name] for name in METRICS},
                    "B-SHAM_minus_B-MATCHED": {name: sham[name] - matched[name] for name in METRICS},
                }

        stage = "seal_analysis_outputs"
        summary_path = OUTPUT / "trajectory-response-matrix-v01.json"
        write_json(summary_path, {
            "status": "P_R2_ALL_381_CELLS_ANALYZED_DESCRIPTIVELY",
            "response_matrix": response,
            "four_cell_A_F_decomposition": transitions,
            "paired_arm_coordinate_differences": pairwise,
            "cell_count": 381, "neighborhood_metric_rows": 762_000,
            "metric_row_sha256": metric_sha,
            "aggregate_seed_inference": False,
            "intermediate_checkpoint_selection_or_promotion": False,
        })
        event_path = OUTPUT / "descriptive-event-time-analysis-v01.json"
        write_json(event_path, {
            "status": "P_R2_DESCRIPTIVE_EVENT_TIMES_COMPLETE",
            "contract_sha256": sha256_file(ANALYSIS_CONTRACT),
            "addendum_sha256": sha256_file(ADDENDUM),
            "trajectory_helper_sha256": sha256_file(TRAJECTORY_HELPER),
            "adapter_sha256": sha256_file(ADAPTER_PATH),
            "shared_resample_plan_sha256": plan_hash,
            "shared_resample_plan_file_sha256": sha256_file(plan_path),
            "event_results": event_results,
            "family_trajectories_in_response_matrix": True,
            "family_specific_event_times_confirmatory": False,
            "onset_is_true_emergence_time": False,
            "checkpoint_selection": False,
        })
        report_path = OUTPUT / "v08p-r2-trajectory-results-v01.md"
        report_path.write_text(build_report(response, event_results, plan_hash, tree_hashes), encoding="utf-8")
        with report_path.open("r+b") as stream:
            stream.flush(); os.fsync(stream.fileno())
        outputs = [metric_rows_path, plan_path, summary_path, event_path, report_path]
        seal = {
            "status": "POST_REGISTERED_V08P_R2_FRESH_PANEL_TRAJECTORY_RESULT_SEALED",
            "identity": "v0.8P-R2-late-transition-localization-v01",
            "raw_prediction_tree_sha256": tree_hashes["prediction_tree"],
            "inference_receipt_sha256": tree_hashes["inference_receipt"],
            "opening_receipt_sha256": tree_hashes["opening_receipt"],
            "training_seal_sha256": prediction_tree["training_seal_sha256"],
            "panel_feature_receipt_sha256": prediction_tree["feature_receipt_sha256"],
            "metric_implementation_sha256": sha256_file(METRIC_SOURCE),
            "analysis_contract_sha256": sha256_file(ANALYSIS_CONTRACT),
            "analysis_addendum_sha256": sha256_file(ADDENDUM),
            "analysis_adapter_sha256": sha256_file(ADAPTER_PATH),
            "trajectory_helper_sha256": sha256_file(TRAJECTORY_HELPER),
            "analysis_source_sha256": sha256_file(Path(__file__).resolve()),
            "outputs": [{"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                        for path in outputs],
            "prediction_count": EXPECTED_PREDICTIONS, "cell_count": 381,
            "checkpoint_selection": False, "newtight": False,
            "legacy_evaluation": False, "phoenix_access": False,
            "result_sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        seal_path = OUTPUT / "p-r2-result-seal-v01.json"
        write_json(seal_path, seal)
        print(json.dumps({"status": seal["status"], "result_seal": str(seal_path),
                          "seal_sha256": sha256_file(seal_path), "prediction_rows": EXPECTED_PREDICTIONS,
                          "metric_rows": 762_000, "elapsed_seconds": round(time.perf_counter() - started, 2)},
                         separators=(",", ":")), flush=True)
    except BaseException as exc:
        failure_path = OUTPUT / "analysis-failure-receipt-v01.json"
        if OUTPUT.exists() and not failure_path.exists():
            write_json(failure_path, {
                "status": "P_R2_ANALYSIS_FAILED_CLOSED_PARTIAL_OUTPUTS_PRESERVED",
                "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc),
                "prediction_tree_sha256": sha256_file(PREDICTION_TREE) if PREDICTION_TREE.exists() else None,
                "automatic_retry": False, "newtight": False, "phoenix_access": False,
                "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            })
        raise


def main() -> int:
    execute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
