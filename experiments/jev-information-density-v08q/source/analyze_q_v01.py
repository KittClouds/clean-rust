"""Frozen Q analysis; target rows are read only after the prediction seal."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
N_ANALYZER = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
TRAIN = RUN / "training"
OUTPUT = RUN / "evaluation"
SEEDS = (2540205348, 2603246505, 3565067208)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
STEPS = (40, 80, 100, 120)
METRIC_NAMES = (
    "sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip", "anchor_old_map",
    "fact_new_map", "strict_transition", "correct_direction", "new_probability_delta",
    "exact_new_probability_delta", "delta_mae", "new_rank_gain", "anchor_nll", "anchor_brier",
    "anchor_gold_map_accuracy", "sham_gold_probability_movement", "sham_new_probability_movement",
    "sham_margin_movement", "sham_exact_gold_l1", "matched_gold_probability_movement",
    "matched_new_probability_movement", "matched_margin_movement", "matched_exact_gold_l1",
)
BOOTSTRAP_METRICS = (
    "new_probability_delta", "correct_direction", "fact_new_map", "strict_transition",
    "anchor_old_map", "sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip",
    "anchor_nll", "anchor_brier", "delta_mae",
)
PAIRWISE = (("B-SHAM-LOW", "B-SHAM"), ("B-SHAM-LOW", "B-DUP"), ("B-MATCHED", "B-DUP"))


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(payload); f.flush(); os.fsync(f.fileno())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_metrics() -> Any:
    spec = importlib.util.spec_from_file_location("q_frozen_n_metrics", N_ANALYZER)
    require(spec is not None and spec.loader is not None, "frozen N neighborhood metrics unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.VIEWS == ("anchor", "fact_flip", "matched_neutral", "sham"), "frozen neighborhood metric view contract changed")
    return module


def expected_cells() -> list[tuple[int, str, int]]:
    cells = []
    for seed in SEEDS:
        cells.append((seed, "COMMON_INIT", 0))
        for step in STEPS:
            cells.extend((seed, arm, step) for arm in ARMS)
    return cells


def ordered_neighborhoods(targets: dict[str, dict[str, Any]]) -> list[str]:
    family_by_nid: dict[str, str] = {}
    for row in targets.values():
        family_by_nid[str(row["neighborhood_id"])] = str(row["family_slug"])
    require(len(family_by_nid) == 2_000, "Q exact-target table does not cover 2,000 neighborhoods")
    return [nid for family in FAMILIES for nid in sorted(n for n, f in family_by_nid.items() if f == family)]


def build_target_maps() -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, str]]:
    target_path = PANEL / "target-joins/q-exact-world-targets.jsonl"
    target_receipt_path = PANEL / "target-joins/q-exact-world-target-join-receipt.json"
    seal = read_json(PANEL / "seals/q-panel-phase-terminal-seal-v01.json")
    entries = {row["path"]: row for row in seal["entries"]}
    for path in (target_path, target_receipt_path):
        rel = path.relative_to(PANEL).as_posix()
        row = entries.get(rel)
        require(row is not None and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"Q exact-target input not bound by panel seal: {rel}")
    receipt = read_json(target_receipt_path)
    require(receipt.get("status") == "Q_EXACT_WORLD_TARGET_JOIN_PASS" and receipt.get("target_rows") == 22_000 and receipt.get("target_rows_sha256") == sha(target_path) and receipt.get("pretraining_evaluation_target_rows") == 8_000, "Q exact-world target receipt mismatch")
    rows = read_jsonl(target_path)
    require(len(rows) == 22_000, "Q exact-world target row count mismatch")
    by_episode: dict[str, dict[str, Any]] = {}
    for row in rows:
        episode = str(row["episode_id"])
        require(episode not in by_episode, f"duplicate Q exact target episode: {episode}")
        target = [float(value) for value in row["target"]]
        require(len(target) == 4 and all(np.isfinite(target)) and abs(sum(target) - 1.0) <= 1e-12, f"invalid Q target distribution: {episode}")
        by_episode[episode] = {**row, "target": target}
    joins = read_jsonl(PANEL / "matching/whole-panel-candidate-join.jsonl")
    require(len(joins) == 8_000, "Q candidate join row count changed")
    candidates: dict[str, list[str]] = {}
    family_by_nid: dict[str, str] = {}
    for row in joins:
        nid = str(row["neighborhood_id"])
        order = int(row["candidate_order"])
        vector = candidates.setdefault(nid, [""] * 4)
        require(0 <= order < 4 and vector[order] == "", f"duplicate Q candidate slot {nid}/{order}")
        vector[order] = str(row["candidate_semantic_id"])
        family_by_nid[nid] = str(row["schema_family_id"]).split(":")[-1]
    require(len(candidates) == 2_000 and all(len(set(ids)) == 4 and all(ids) for ids in candidates.values()), "Q candidate IDs are not exact four-tuples")
    require(len(family_by_nid) == 2_000, "Q candidate join neighborhood coverage mismatch")
    return by_episode, candidates, family_by_nid


def make_metric_views(raw_views: dict[str, dict[str, Any]], targets: dict[str, dict[str, Any]], candidates: dict[str, list[str]], family_by_nid: dict[str, str], nid: str, metric: Any) -> dict[str, Any]:
    ids = candidates[nid]
    aligned: dict[str, dict[str, Any]] = {}
    for view in VIEWS:
        row = raw_views[view]
        require(row["candidate_semantic_ids"] == ids, f"candidate order drift at {nid}/{view}")
        target_row = targets.get(str(row["episode_id"]))
        require(target_row is not None and target_row["neighborhood_id"] == nid and target_row["role"] == ("fact_flip" if view == "fact_flip" else "matched_neutral" if view == "matched_neutral" else view), f"exact target/view identity mismatch: {nid}/{view}")
        require(str(target_row["family_slug"]) == family_by_nid[nid], f"target family mismatch: {nid}/{view}")
        aligned[view] = {**row, "gold": target_row["target"], "family_id": f"jev-v08q-family:{family_by_nid[nid]}"}
    gold_a = aligned["anchor"]["gold"]
    gold_f = aligned["fact_flip"]["gold"]
    for invariant in ("sham", "matched_neutral"):
        require(max(abs(a - b) for a, b in zip(gold_a, aligned[invariant]["gold"], strict=True)) <= 1e-12, f"Q same-target truth changed: {nid}/{invariant}")
    map_a = metric.winner(dict(zip(ids, gold_a, strict=True)))
    map_f = metric.winner(dict(zip(ids, gold_f, strict=True)))
    require(map_a != map_f, f"Q fact target does not change MAP: {nid}")
    for row in aligned.values():
        row["old_candidate_id"] = map_a
        row["new_candidate_id"] = map_f
    return metric.neighborhood_metrics(aligned)


def metric_for_cell(stream: Any, cell: tuple[int, str, int], neighborhood_order: list[str], targets: dict[str, dict[str, Any]], candidates: dict[str, list[str]], family_by_nid: dict[str, str], metric: Any) -> list[dict[str, Any]]:
    seed, arm, step = cell
    result = []
    for nid in neighborhood_order:
        views: dict[str, dict[str, Any]] = {}
        for expected_view in VIEWS:
            line = stream.readline()
            require(bool(line), f"Q prediction stream ended at {cell}/{nid}/{expected_view}")
            row = json.loads(line)
            require((int(row["seed"]), str(row["arm"]), int(row["global_step"])) == cell, f"Q prediction cell ordering error: {cell}")
            require(row.get("neighborhood_id") == nid and row.get("view") == expected_view, f"Q prediction neighborhood/view ordering error: {cell}/{nid}")
            require(row.get("family_id", "").split(":")[-1] == family_by_nid[nid], f"Q prediction family mismatch: {nid}")
            prediction = [float(x) for x in row["prediction"]]
            require(len(prediction) == 4 and all(np.isfinite(prediction)) and abs(sum(prediction) - 1.0) <= 1e-6, f"invalid Q sealed prediction: {cell}/{nid}/{expected_view}")
            views[expected_view] = row
        values = make_metric_views(views, targets, candidates, family_by_nid, nid, metric)
        result.append({"neighborhood_id": nid, **values})
    return result


def make_bootstrap_plan(path: Path, contract: dict[str, Any]) -> tuple[np.memmap, str]:
    block = contract["bootstrap"]
    require(block["replicates"] == 10_000 and block["resamples_per_family"] == 500 and block["family_order"] == list(FAMILIES) and block["rng"] == "NumPy PCG64" and block["quantile_method"] == "linear", "Q frozen bootstrap contract mismatch")
    rng = np.random.Generator(np.random.PCG64(int(block["seed"])))
    plan = np.lib.format.open_memmap(path, mode="w+", dtype=np.uint16, shape=(4, 10_000, 500))
    for family_index in range(4):
        draws = rng.integers(0, 500, size=(10_000, 500), endpoint=False)
        plan[family_index] = draws.astype(np.uint16, copy=False)
    plan.flush()
    del plan
    return np.load(path, mmap_mode="r", allow_pickle=False), sha(path)


def bootstrap_interval(values_by_family: dict[str, np.ndarray], plan: np.ndarray) -> dict[str, Any]:
    samples = np.zeros(plan.shape[1], dtype=np.float64)
    for family_index, family in enumerate(FAMILIES):
        values = values_by_family[family]
        require(values.shape == (500,), f"Q bootstrap family support mismatch: {family}")
        samples += values[plan[family_index]].mean(axis=1) / 4.0
    low, high = np.quantile(samples, [0.025, 0.975], method="linear")
    return {"ci95": [float(low), float(high)], "replicates": len(samples), "shared_plan": True, "quantile_method": "linear"}


def values_by_family(rows: list[dict[str, Any]], name: str) -> dict[str, np.ndarray]:
    return {family: np.asarray([float(row[name]) for row in rows if str(row["family_id"]).split(":")[-1] == family], dtype=np.float64) for family in FAMILIES}


def main() -> int:
    contract_path = Q / "contracts/q-analysis-contract-v02.json"
    contract = read_json(contract_path)
    opening = read_json(OUTPUT / "q-panel-opening-receipt-v01.json")
    inference = read_json(OUTPUT / "q-inference-receipt-v01.json")
    prediction_tree = read_json(OUTPUT / "raw-prediction-hash-tree-v01.json")
    prediction_path = OUTPUT / "raw-predictions-v01.jsonl"
    require(opening.get("opening_count") == 1 and opening.get("status") == "Q_FRESH_PANEL_OPENED_AFTER_COMPLETE_TRAINING_SEAL", "Q one-use opening receipt missing")
    require(inference.get("all_predictions_before_metrics") is True and prediction_tree.get("status") == "Q_COMPLETE_RAW_PREDICTION_MATRIX_SEALED_BEFORE_ANALYSIS", "Q raw prediction seal is not complete")
    require(prediction_tree.get("prediction_rows") == 408_000 and prediction_tree.get("cell_count") == 51 and prediction_tree["raw_prediction"]["sha256"] == sha(prediction_path) and inference.get("prediction_sha256") == sha(prediction_path), "Q prediction bytes/count do not match seal")
    require(inference.get("prediction_hash_tree_sha256") == sha(OUTPUT / "raw-prediction-hash-tree-v01.json"), "Q inference receipt does not bind prediction tree")
    metric = load_metrics()
    targets, candidate_ids, family_by_nid = build_target_maps()
    neighborhood_order = ordered_neighborhoods(targets)
    require(set(neighborhood_order) == set(candidate_ids) == set(family_by_nid), "Q targets/candidates/families have different neighborhood identity sets")
    metric_rows: dict[tuple[int, str, int], list[dict[str, Any]]] = {}
    cells = expected_cells()
    require(len(cells) == 51, "Q frozen analysis cell inventory mismatch")
    with prediction_path.open("r", encoding="utf-8") as stream:
        for cell_index, cell in enumerate(cells, start=1):
            metric_rows[cell] = metric_for_cell(stream, cell, neighborhood_order, targets, candidate_ids, family_by_nid, metric)
            if cell_index % 6 == 0 or cell_index == len(cells):
                print(json.dumps({"event": "q_analysis_cell_validated", "cell": cell_index, "cells": len(cells)}, separators=(",", ":")), flush=True)
        require(stream.readline() == "", "extra rows after complete Q prediction matrix")

    family_matrix = {nid: family_by_nid[nid] for nid in neighborhood_order}
    response: dict[str, Any] = {}
    metric_names = [name for name in METRIC_NAMES]
    for seed in SEEDS:
        response[str(seed)] = {}
        for arm, step in [("COMMON_INIT", 0), *[(arm, step) for step in STEPS for arm in ARMS]]:
            rows = metric_rows[(seed, arm, step)]
            values = {}
            for name in metric_names:
                arr = np.asarray([float(row[name]) for row in rows], dtype=np.float64)
                values[name] = {"mean": float(arr.mean()), "median": float(np.median(arr)), "q05_q95": [float(x) for x in np.quantile(arr, [0.05, 0.95], method="linear")], "by_family": {family: float(np.mean([float(row[name]) for row in rows if family_matrix[row["neighborhood_id"]] == family])) for family in FAMILIES}}
            counts = {"A_AND_F": 0, "A_AND_NOT_F": 0, "NOT_A_AND_F": 0, "NOT_A_AND_NOT_F": 0}
            by_family = {family: dict.fromkeys(counts, 0) for family in FAMILIES}
            for row in rows:
                a = bool(row["anchor_old_map"]); f = bool(row["fact_new_map"])
                key = "A_AND_F" if a and f else "A_AND_NOT_F" if a else "NOT_A_AND_F" if f else "NOT_A_AND_NOT_F"
                counts[key] += 1; by_family[family_matrix[row["neighborhood_id"]]][key] += 1
            response[str(seed)][f"{arm}/step-{step:03}"] = {"n": len(rows), "metrics": values, "A_F_four_cell_counts": counts, "A_F_four_cell_rates": {key: value / len(rows) for key, value in counts.items()}, "A_F_four_cell_counts_by_family": by_family}

    plan_path = OUTPUT / "shared-neighborhood-bootstrap-plan-v01.npy"
    plan, plan_hash = make_bootstrap_plan(plan_path, contract)
    bootstrap: dict[str, Any] = {"plan_sha256": plan_hash, "plan_shape": list(plan.shape), "rng": "NumPy PCG64", "seed": contract["bootstrap"]["seed"], "family_order": list(FAMILIES), "resampling_unit": "neighborhood within family", "shared_across_all_reported_series": True, "quantile_method": "linear", "primary_step": 120, "by_seed": {}}
    for seed in SEEDS:
        seed_result: dict[str, Any] = {"arm_metrics": {}, "paired_contrasts": {}}
        for arm in ARMS:
            rows = metric_rows[(seed, arm, 120)]
            seed_result["arm_metrics"][arm] = {name: bootstrap_interval(values_by_family(rows, name), plan) for name in BOOTSTRAP_METRICS}
        for left, right in PAIRWISE:
            left_rows = metric_rows[(seed, left, 120)]
            right_rows = metric_rows[(seed, right, 120)]
            right_by_id = {row["neighborhood_id"]: row for row in right_rows}
            contrasts = {}
            for name in BOOTSTRAP_METRICS:
                differences = [{"neighborhood_id": row["neighborhood_id"], "family_id": row["family_id"], "value": float(row[name]) - float(right_by_id[row["neighborhood_id"]][name])} for row in left_rows]
                by_family = {family: np.asarray([row["value"] for row in differences if str(row["family_id"]).split(":")[-1] == family], dtype=np.float64) for family in FAMILIES}
                mean = float(np.mean([row["value"] for row in differences]))
                interval = bootstrap_interval(by_family, plan)
                contrasts[name] = {"left_minus_right_mean": mean, **interval, "paired_interval_excludes_zero": interval["ci95"][0] > 0 or interval["ci95"][1] < 0}
            seed_result["paired_contrasts"][f"{left} - {right}"] = contrasts
        bootstrap["by_seed"][str(seed)] = seed_result

    gate_inputs: dict[str, dict[str, Any]] = {}
    for seed in SEEDS:
        by_arm = {arm: metric_rows[(seed, arm, 120)] for arm in ARMS}
        means = {arm: {name: float(np.mean([float(row[name]) for row in rows])) for name in METRIC_NAMES} for arm, rows in by_arm.items()}
        def family_delta(name: str, left: str, right: str) -> dict[str, float]:
            return {family: means[left][name] - means[right][name] for family in FAMILIES}
        gate_inputs[str(seed)] = {
            "delta_p_new_low_minus_sham": means["B-SHAM-LOW"]["new_probability_delta"] - means["B-SHAM"]["new_probability_delta"],
            "sham_low_correct_direction": means["B-SHAM-LOW"]["correct_direction"],
            "sham_correct_direction": means["B-SHAM"]["correct_direction"],
            "a_old_low_minus_sham": means["B-SHAM-LOW"]["anchor_old_map"] - means["B-SHAM"]["anchor_old_map"],
            "family_a_old_low_minus_sham": family_delta("anchor_old_map", "B-SHAM-LOW", "B-SHAM"),
            "dup_sham_l1": means["B-DUP"]["sham_l1"], "dup_matched_neutral_l1": means["B-DUP"]["matched_l1"],
            "sham_low_sham_l1": means["B-SHAM-LOW"]["sham_l1"], "sham_low_matched_neutral_l1": means["B-SHAM-LOW"]["matched_l1"],
            "dup_sham_map_flip_rate": means["B-DUP"]["sham_map_flip"], "dup_matched_neutral_map_flip_rate": means["B-DUP"]["matched_map_flip"],
            "sham_low_sham_map_flip_rate": means["B-SHAM-LOW"]["sham_map_flip"], "sham_low_matched_neutral_map_flip_rate": means["B-SHAM-LOW"]["matched_map_flip"],
            "f_new_low_minus_sham": means["B-SHAM-LOW"]["fact_new_map"] - means["B-SHAM"]["fact_new_map"],
            "strict_low_minus_sham": means["B-SHAM-LOW"]["strict_transition"] - means["B-SHAM"]["strict_transition"],
        }
    rules_spec = importlib.util.spec_from_file_location("q_frozen_gate_rules", Q / "source/q_analysis_rules_v02.py")
    require(rules_spec is not None and rules_spec.loader is not None, "Q frozen seed-gate rules unavailable")
    rules = importlib.util.module_from_spec(rules_spec); sys.modules[rules_spec.name] = rules; rules_spec.loader.exec_module(rules)
    gate_result = rules.cohort_labels(gate_inputs)

    result = {
        "identity": "JEV v0.8Q single-dose gain intervention",
        "status": "Q_ANALYSIS_COMPLETE_NO_COMPOSITE_SCORE",
        "question": "Does half-weight SHAM increase target-response gain while retaining a material locality advantage over concurrent DUP?",
        "scope": {"panel_root_sha256": read_json(OUTPUT / "q-panel-opening-receipt-v01.json")["panel_root_sha256"], "neighborhoods": 2_000, "families": {family: 500 for family in FAMILIES}, "seeds": list(SEEDS), "seed_population_inference": False},
        "response_matrix": response,
        "seed_gate_inputs": gate_inputs,
        "seed_gate_labels": gate_result,
        "bootstrap": bootstrap,
        "interpretation_limits": ["The operating-point and stiff-coupling labels require same-seed joint predicates.", "Material locality advantage over DUP does not mean SHAM-level locality was retained.", "Three observed seeds are trajectories, not a seed-population estimate.", "Family/template distribution is fixed; no novel-template or novel-family generalization is claimed.", "No capability coordinate is collapsed into a composite score."],
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
    }
    result_path = OUTPUT / "q-analysis-result-v01.json"
    write_json(result_path, result)
    write_json(OUTPUT / "q-result-writeup-v01.md", writeup(result))
    files = ["preinference-verification-v01.json", "q-panel-opening-receipt-v01.json", "opened-panel-validation-v01.json", "raw-predictions-v01.jsonl", "raw-prediction-hash-tree-v01.json", "q-inference-receipt-v01.json", "shared-neighborhood-bootstrap-plan-v01.npy", "q-analysis-result-v01.json", "q-result-writeup-v01.md"]
    seal = {"status": "Q_RESULT_SEALED", "identity": result["identity"], "opening_count": 1, "files": {name: {"bytes": (OUTPUT / name).stat().st_size, "sha256": sha(OUTPUT / name)} for name in files}, "prediction_rows": 408_000, "analysis_cells": 51, "prediction_before_metrics": True, "checkpoint_selection": False, "newtight": False, "legacy_evaluation": False, "phoenix_access": False, "sealed_at_utc": datetime.now(timezone.utc).isoformat()}
    write_json(OUTPUT / "q-result-seal-v01.json", seal)
    print(json.dumps({"status": seal["status"], "result_sha256": sha(result_path), "result_seal_sha256": sha(OUTPUT / "q-result-seal-v01.json"), "operating_point": gate_result["tunable_gain_locality_operating_point"], "stiff_coupling": gate_result["stiff_coupling_pattern"]}, indent=2), flush=True)
    return 0


def writeup(result: dict[str, Any]) -> str:
    lines = ["# JEV v0.8Q result", "", "Status: `Q_ANALYSIS_COMPLETE_NO_COMPOSITE_SCORE`.", "", "The primary endpoint is step 120. Values below are means over the same 2,000 held-out neighborhoods, shown separately by seed; the three seeds are not treated as a population sample.", "", "| Seed | Arm | Δp new (mean) | Correct direction | F_new | Strict | Sham L1 | Sham flips | Matched L1 | Matched flips | A_old |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for seed in SEEDS:
        for arm in ARMS:
            cell = result["response_matrix"][str(seed)][f"{arm}/step-120"]["metrics"]
            vals = [cell[name]["mean"] for name in ("new_probability_delta", "correct_direction", "fact_new_map", "strict_transition", "sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip", "anchor_old_map")]
            lines.append(f"| {seed} | {arm} | {vals[0]:.6f} | {vals[1]:.4%} | {vals[2]:.4%} | {vals[3]:.4%} | {vals[4]:.6f} | {vals[5]:.4%} | {vals[6]:.6f} | {vals[7]:.4%} | {vals[8]:.4%} |")
    lines += ["", "## Same-seed labels", "", f"- Tunable gain/locality operating point: **{result['seed_gate_labels']['tunable_gain_locality_operating_point']}**.", f"- Stiff-coupling pattern: **{result['seed_gate_labels']['stiff_coupling_pattern']}**.", f"- Meaningful MAP response: **{result['seed_gate_labels']['meaningful_map_response']}**.", "", "Each cohort label counts only seeds whose complete preregistered conjunction passes in that same seed. A material locality advantage over DUP is not described as SHAM-level locality retention.", "", "## Reading boundary", "", "The five response coordinates—direction, gain, boundary crossing, locality, and preservation—remain separate. The fixed four-family panel supports conditional held-out-neighborhood uncertainty, not optimizer-seed population inference. Family/template scope is unchanged; this does not establish novel-family or novel-template generalization.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
