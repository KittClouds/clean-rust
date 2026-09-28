"""Independent, target-after-seal replay and final-result sealing for JEV R3."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
PANEL = RUN / "panel-v03"
TRAINING = RUN / "training-v01/artifacts-v01"
EVAL = RUN / "evaluation-v01"
PRED = EVAL / "predictions-v01"
ANALYSIS = EVAL / "analysis-v01"
LOCK = EXP / "seals/r3-phase-packet-seal-v01.json"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
DIRECTIONS = ("high_to_low", "low_to_high")
BRANCHES = ("ONE_X", "HALF")
N_CELLS, N_ROWS, N_CANDIDATES = 1_080, 4_000, 4
S_MIN, MIN_RATIO = 0.01, 173
T_CRIT_190 = 1.97253
TOL = 3e-6


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def close(actual: float, expected: float, label: str) -> float:
    error = abs(float(actual) - float(expected))
    require(error <= TOL, f"independent replay differs for {label}: {actual} != {expected} (abs={error})")
    return error


def verify_lock() -> dict[str, Any]:
    lock = read_json(LOCK)
    body = {key: value for key, value in lock.items() if key != "contract_bundle_root_sha256"}
    root = sha_bytes(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    require(lock.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION"
        and lock.get("contract_bundle_root_sha256") == root, "R3 packet lock/root mismatch")
    for item in [*lock.get("contracts", []), *lock.get("execution_sources", [])]:
        require(sha_file(Path(item["path"])) == item["sha256"], f"locked source changed: {item['name']}")
    require(any(Path(item["path"]).resolve() == Path(__file__).resolve()
        for item in lock.get("execution_sources", [])), "independent replay source is not locked")
    return lock


def verify_prediction_and_analysis_roots() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    seal = read_json(PRED / "prediction-seal-v01.json")
    entries = seal.get("entries", [])
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    require(seal.get("status") == "R3_V03_COMPLETE_RAW_PREDICTIONS_SEALED_PRE_ANALYSIS"
        and sha_bytes(body.encode()) == seal.get("entries_root_sha256")
        and seal.get("targets_read") is False and seal.get("metrics_computed") is False,
        "prediction seal is not valid/pre-analysis")
    entry_map = {row["path"]: row for row in entries}
    require(len(entry_map) == len(entries), "prediction seal has duplicate paths")
    for name, item in entry_map.items():
        path = PRED / name
        require(path.is_file() and path.stat().st_size == item["bytes"] and sha_file(path) == item["sha256"],
            f"prediction artifact changed: {name}")
    manifest = read_json(PRED / "prediction-manifest.json")
    require(sha_file(PRED / "prediction-manifest.json") == seal["manifest_sha256"]
        and manifest.get("shape") == [N_CELLS, N_ROWS, N_CANDIDATES]
        and manifest.get("all_predictions_complete") is True and manifest.get("targets_read") is False,
        "prediction manifest mismatch")
    cells = read_jsonl(PRED / "prediction-cells.jsonl")
    require(len(cells) == N_CELLS and [row["cell_index"] for row in cells] == list(range(N_CELLS)),
        "prediction cells are incomplete/reordered")

    root = read_json(ANALYSIS / "analysis-root-v01.json")
    outputs = root.get("entries", [])
    output_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in outputs)
    require(root.get("status") == "R3_V03_PRIMARY_ANALYSIS_COMPLETE_AWAITING_INDEPENDENT_REPLAY"
        and sha_bytes(output_body.encode()) == root.get("entries_root_sha256"), "analysis root invalid")
    for item in outputs:
        path = ANALYSIS / item["path"]
        require(path.is_file() and path.stat().st_size == item["bytes"] and sha_file(path) == item["sha256"],
            f"analysis artifact changed: {item['path']}")
    require(root.get("prediction_seal_sha256") == sha_file(PRED / "prediction-seal-v01.json"),
        "analysis was computed against another prediction seal")
    return manifest, cells


def exact_target_join() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # First target-bearing bytes are opened only after the complete prediction tree is verified.
    seal = read_json(PANEL / "seals/r3-panel-seal-v01.json")
    target_name = "r3-panel-targets-v01.jsonl"
    item = next((row for row in seal["entries"] if row["path"] == target_name), None)
    require(item is not None, "sealed R3 target join absent")
    target_path = PANEL / target_name
    require(target_path.is_file() and target_path.stat().st_size == item["bytes"]
        and sha_file(target_path) == item["sha256"], "R3 target join identity mismatch")
    inference = read_jsonl(PANEL / "r3-panel-inference-manifest.jsonl")
    targets = read_jsonl(target_path)
    require(len(inference) == len(targets) == N_ROWS, "R3 inference/target row count mismatch")
    for index, (meta, target) in enumerate(zip(inference, targets, strict=True)):
        for field in ("row_index", "neighborhood_id", "family_slug", "direction", "view", "candidate_semantic_ids"):
            require(meta[field] == target[field], f"target join identity mismatch at row {index}: {field}")
        candidate_ids = meta["candidate_semantic_ids"]
        old_index = candidate_ids.index(meta["old_semantic_id"])
        new_index = candidate_ids.index(meta["new_semantic_id"])
        winner = max(range(4), key=lambda slot: (float(target["target"][slot]), -slot))
        require(winner == (old_index if meta["view"] == "anchor" else new_index),
            f"semantic target role mismatch at row {index}")
    return inference, targets


def cell_groups(inference: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for index, meta in enumerate(inference):
        neighborhood = meta["neighborhood_id"]
        row = groups.setdefault(neighborhood, {"family": meta["family_slug"], "direction": meta["direction"],
            "anchor": None, "fact": None, "old": None, "new": None, "ids": meta["candidate_semantic_ids"]})
        old_index = row["ids"].index(meta["old_semantic_id"])
        new_index = row["ids"].index(meta["new_semantic_id"])
        require(row["family"] == meta["family_slug"] and row["direction"] == meta["direction"]
            and row["old"] in (None, old_index) and row["new"] in (None, new_index),
            "paired neighborhood metadata drift")
        row["old"], row["new"] = old_index, new_index
        view = meta["view"]
        require(view in ("anchor", "fact") and row[view] is None, "duplicate/unrecognized paired view")
        row[view] = index
    require(len(groups) == 2_000 and all(row["anchor"] is not None and row["fact"] is not None for row in groups.values()),
        "R3 neighborhood view pairs incomplete")
    for family in FAMILIES:
        for direction in DIRECTIONS:
            count = sum(row["family"] == family and row["direction"] == direction for row in groups.values())
            require(count == 250, f"R3 family/direction cell count mismatch: {family}/{direction}")
    require(len(targets) == N_ROWS, "target join lost rows")
    return groups


def independent_cell(logits: np.ndarray, groups: dict[str, Any], inference: list[dict[str, Any]]) -> dict[str, Any]:
    require(logits.shape == (N_ROWS, N_CANDIDATES) and bool(np.isfinite(logits).all()), "invalid replay logits")
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for family in FAMILIES:
        for direction in DIRECTIONS:
            selected = [row for row in groups.values() if row["family"] == family and row["direction"] == direction]
            a_idx = np.asarray([row["anchor"] for row in selected], dtype=np.int64)
            f_idx = np.asarray([row["fact"] for row in selected], dtype=np.int64)
            old_idx = np.asarray([row["old"] for row in selected], dtype=np.int64)
            new_idx = np.asarray([row["new"] for row in selected], dtype=np.int64)
            a_gap = logits[a_idx, new_idx].astype(np.float64) - logits[a_idx, old_idx].astype(np.float64)
            f_gap = logits[f_idx, new_idx].astype(np.float64) - logits[f_idx, old_idx].astype(np.float64)
            a_winner = logits[a_idx].argmax(axis=1)
            f_winner = logits[f_idx].argmax(axis=1)
            a_ok, f_ok = a_winner == old_idx, f_winner == new_idx
            wrong = [groups[key]["ids"][int(winner)] for key, winner, expected in
                zip([key for key, row in groups.items() if row["family"] == family and row["direction"] == direction],
                    f_winner, new_idx, strict=True)]
            cells[(family, direction)] = {
                "n": len(selected), "anchor_new_old_logit_mean": float(a_gap.mean()),
                "fact_new_old_logit_mean": float(f_gap.mean()), "fact_minus_anchor_mean": float((f_gap-a_gap).mean()),
                "A_old": float(a_ok.mean()), "F_new": float(f_ok.mean()), "Strict": float((a_ok & f_ok).mean()),
                "AF_cells": {"A_and_F": int(np.sum(a_ok & f_ok)), "A_and_not_F": int(np.sum(a_ok & ~f_ok)),
                    "not_A_and_F": int(np.sum(~a_ok & f_ok)), "not_A_and_not_F": int(np.sum(~a_ok & ~f_ok))},
                "fact_winner_ids": sorted(set(wrong)),
            }
    separation = float(np.mean([cells[key]["fact_minus_anchor_mean"] for key in cells]))
    return {"cells": cells, "S": separation,
        "anchor_A_old": float(np.mean([value["A_old"] for value in cells.values()])),
        "fact_F_new": float(np.mean([value["F_new"] for value in cells.values()])),
        "Strict": float(np.mean([value["Strict"] for value in cells.values()]))}


def independent_contrast(one: dict[str, Any], half: dict[str, Any]) -> dict[str, Any]:
    c = {direction: float(np.mean([half["cells"][(family, direction)]["anchor_new_old_logit_mean"]
        - one["cells"][(family, direction)]["anchor_new_old_logit_mean"] for family in FAMILIES]))
        for direction in DIRECTIONS}
    d_direction = {direction: float(np.mean([half["cells"][(family, direction)]["fact_minus_anchor_mean"]
        - one["cells"][(family, direction)]["fact_minus_anchor_mean"] for family in FAMILIES]))
        for direction in DIRECTIONS}
    d = half["S"] - one["S"]
    eligible = one["S"] >= S_MIN and half["S"] >= S_MIN
    return {"C_direction": c, "M_C": (c[DIRECTIONS[0]]+c[DIRECTIONS[1]])/2,
        "P_C": (c[DIRECTIONS[0]]-c[DIRECTIONS[1]])/2, "D_direction": d_direction, "D": d,
        "M_D": (d_direction[DIRECTIONS[0]]+d_direction[DIRECTIONS[1]])/2,
        "P_D": (d_direction[DIRECTIONS[0]]-d_direction[DIRECTIONS[1]])/2,
        "S_1X": one["S"], "S_HALF": half["S"], "ratio_eligible": eligible,
        "R": math.log(half["S"]/one["S"]) if eligible else None}


def median_interval(values: list[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    require(bool(ordered), "cannot replay empty median interval")
    n, tail = len(ordered), 0
    rank, coverage = 1, 0.0
    for current in range(1, n // 2 + 1):
        tail = 1 if current == 1 else tail + math.comb(n, current - 1)
        current_coverage = 1.0 - 2.0 * tail / (1 << n)
        if current_coverage + 1e-15 >= 0.95:
            rank, coverage = current, current_coverage
        else:
            break
    return {"n": n, "median": float(np.median(np.asarray(ordered, dtype=np.float64))),
        "lower": ordered[rank-1], "upper": ordered[n-rank], "lower_order": rank,
        "upper_order": n-rank+1, "nominal_coverage": coverage}


def compare_interval(actual: dict[str, Any], expected: dict[str, Any], label: str, errors: list[float]) -> None:
    for key in ("n", "lower_order", "upper_order"):
        require(actual[key] == expected[key], f"independent {label} interval {key} mismatch")
    for key in ("median", "lower", "upper", "nominal_coverage"):
        errors.append(close(actual[key], expected[key], f"{label}.{key}"))


def hc3(values_x: list[float], values_y: list[float]) -> dict[str, float]:
    x, y = np.asarray(values_x, dtype=np.float64), np.asarray(values_y, dtype=np.float64)
    design = np.column_stack((np.ones(len(x)), x))
    inverse = np.linalg.inv(design.T @ design)
    coef = inverse @ design.T @ y
    resid = y - design @ coef
    leverage = np.einsum("ij,jk,ik->i", design, inverse, design)
    adj = resid / (1.0 - leverage)
    meat = design.T @ ((adj * adj)[:, None] * design)
    variance = inverse @ meat @ inverse
    return {"intercept": float(coef[0]), "beta": float(coef[1]), "se": float(math.sqrt(variance[1, 1]))}


def compare_cell_serialized(actual: dict[str, Any], expected: dict[str, Any], label: str,
                            errors: list[float]) -> None:
    for family in FAMILIES:
        for direction in DIRECTIONS:
            key = f"{family}|{direction}"
            left, right = actual[key], expected["cells"][(family, direction)]
            require(left["n"] == right["n"] and left["AF_cells"] == right["AF_cells"]
                and left["fact_winner_ids"] == right["fact_winner_ids"], f"replay cell identity/count mismatch: {label}/{key}")
            for field in ("anchor_new_old_logit_mean", "fact_new_old_logit_mean", "fact_minus_anchor_mean",
                          "A_old", "F_new", "Strict"):
                errors.append(close(left[field], right[field], f"{label}/{key}/{field}"))


def main() -> int:
    require(platform.python_version() == "3.13.15" and np.__version__ == "2.5.3",
        "R3 independent replay Python/NumPy runtime mismatch")
    lock = verify_lock()
    prediction_manifest, cells = verify_prediction_and_analysis_roots()
    require(prediction_manifest.get("phase_lock_root_sha256") == lock["contract_bundle_root_sha256"],
        "predictions belong to another packet lock")
    inference, targets = exact_target_join()
    groups = cell_groups(inference, targets)
    raw = np.memmap(PRED / "raw-logits.f32le", mode="r", dtype="<f4", shape=(N_CELLS, N_ROWS, N_CANDIDATES))
    specs = {(row["cohort"], int(row["seed"]), row["branch"], int(row["global_step"])): int(row["cell_index"])
        for row in cells}
    require(len(specs) == N_CELLS, "duplicate prediction cell key")
    trajectory = read_jsonl(ANALYSIS / "trajectory-points.jsonl")
    traj_map = {(row["cohort"], int(row["seed"]), row["branch"], int(row["step"])): row for row in trajectory}
    require(len(traj_map) == N_CELLS, "trajectory output cell coverage mismatch")
    histories = read_jsonl(ANALYSIS / "history-level-results.jsonl")
    history_map = {(row["cohort"], int(row["seed"])): row for row in histories}
    require(len(history_map) == 216, "history output coverage mismatch")
    replayed: dict[tuple[str, int], dict[str, Any]] = {}
    errors: list[float] = []
    for key in sorted(history_map):
        cohort, seed = key
        baseline = independent_cell(raw[specs[(cohort, seed, "COMMON", 80)]], groups, inference)
        baseline_row = traj_map[(cohort, seed, "COMMON", 80)]
        compare_cell_serialized(baseline_row["cells"], baseline, f"{cohort}/{seed}/COMMON/80", errors)
        errors.append(close(baseline_row["S"], baseline["S"], f"{cohort}/{seed}/S80"))
        endpoint: dict[tuple[str, int], dict[str, Any]] = {}
        for step in (100, 120):
            for branch in BRANCHES:
                metric = independent_cell(raw[specs[(cohort, seed, branch, step)]], groups, inference)
                endpoint[(branch, step)] = metric
                trajectory_row = traj_map[(cohort, seed, branch, step)]
                compare_cell_serialized(trajectory_row["cells"], metric, f"{cohort}/{seed}/{branch}/{step}", errors)
                for field, actual in (("S", metric["S"]), ("A_old", metric["anchor_A_old"]),
                                      ("F_new", metric["fact_F_new"]), ("Strict", metric["Strict"])):
                    errors.append(close(trajectory_row[field], actual, f"trajectory/{cohort}/{seed}/{branch}/{step}/{field}"))
        expected_history = history_map[key]
        errors.append(close(expected_history["S80"], baseline["S"], f"history/{cohort}/{seed}/S80"))
        for step in (100, 120):
            contrast = independent_contrast(endpoint[("ONE_X", step)], endpoint[("HALF", step)])
            recorded = expected_history[f"step{step}"]
            for field in ("M_C", "P_C", "D", "M_D", "P_D", "S_1X", "S_HALF"):
                errors.append(close(recorded[field], contrast[field], f"history/{cohort}/{seed}/{step}/{field}"))
            require(recorded["ratio_eligible"] == contrast["ratio_eligible"], "history ratio eligibility mismatch")
            if contrast["R"] is not None:
                errors.append(close(recorded["R"], contrast["R"], f"history/{cohort}/{seed}/{step}/R"))
            else:
                require(recorded["R"] is None, "ineligible history has a ratio value")
            for direction in DIRECTIONS:
                errors.append(close(recorded["C_direction"][direction], contrast["C_direction"][direction],
                    f"history/{cohort}/{seed}/{step}/C/{direction}"))
                errors.append(close(recorded["D_direction"][direction], contrast["D_direction"][direction],
                    f"history/{cohort}/{seed}/{step}/D/{direction}"))
        endpoint_one, endpoint_half = endpoint[("ONE_X", 120)], endpoint[("HALF", 120)]
        for field, expected in (("step120_A_old_1X", endpoint_one["anchor_A_old"]),
            ("step120_A_old_HALF", endpoint_half["anchor_A_old"]),
            ("step120_F_new_1X", endpoint_one["fact_F_new"]),
            ("step120_F_new_HALF", endpoint_half["fact_F_new"]),
            ("step120_Strict_1X", endpoint_one["Strict"]),
            ("step120_Strict_HALF", endpoint_half["Strict"])):
            errors.append(close(expected_history[field], expected, f"history/{cohort}/{seed}/{field}"))
        compare_cell_serialized(expected_history["family_direction_cells_1X"], endpoint_one,
            f"history/{cohort}/{seed}/ONE_X/120", errors)
        compare_cell_serialized(expected_history["family_direction_cells_HALF"], endpoint_half,
            f"history/{cohort}/{seed}/HALF/120", errors)
        replayed[key] = {"S80": baseline["S"], "step100": independent_contrast(endpoint[("ONE_X", 100)], endpoint[("HALF", 100)]),
            "step120": independent_contrast(endpoint[("ONE_X", 120)], endpoint[("HALF", 120)])}

    summary = read_json(ANALYSIS / "analysis-summary.json")
    balanced = [replayed[key] for key in sorted(replayed) if key[0] == "balanced"]
    bridge = [replayed[key] for key in sorted(replayed) if key[0] == "high_to_low_bridge"]
    require(len(balanced) == 192 and len(bridge) == 24, "replay cohort size mismatch")
    mc = median_interval([row["step120"]["M_C"] for row in balanced])
    d_interval = median_interval([row["step120"]["D"] for row in balanced])
    p_interval = median_interval([row["step120"]["P_C"] for row in balanced])
    r_values = [row["step120"]["R"] for row in balanced if row["step120"]["ratio_eligible"]]
    r_interval = median_interval(r_values) if len(r_values) >= MIN_RATIO else None
    compare_interval(summary["median_M_C"], mc, "median_M_C", errors)
    compare_interval(summary["median_D"], d_interval, "median_D", errors)
    compare_interval(summary["median_P_C_secondary"], p_interval, "median_P_C", errors)
    require(summary["fixed_sequence"][2]["eligible_count"] == len(r_values), "fixed-sequence R eligible count mismatch")
    require(summary["ratio_coverage"]["eligible_count"] == sum(row["step120"]["ratio_eligible"] for row in balanced)
        and summary["ratio_coverage"]["denominator"] == 192, "ratio denominator/count mismatch")
    if r_interval is None:
        require(summary["median_R_if_estimable"] is None
            and summary["fixed_sequence"][2]["decision"] == "NOT_ESTIMABLE_FOR_COHORT",
            "R under-coverage disposition mismatch")
    else:
        compare_interval(summary["median_R_if_estimable"], r_interval, "median_R", errors)

    beta = hc3([row["S80"] for row in balanced], [row["step120"]["D"] for row in balanced])
    c_s80 = hc3([row["S80"] for row in balanced], [row["step120"]["M_C"] for row in balanced])
    for label, observed, expected in (("beta_HC3", summary["beta_HC3"], beta),
                                     ("C_vs_S80_descriptive_HC3", summary["C_vs_S80_descriptive_HC3"], c_s80)):
        errors.append(close(observed["intercept"], expected["intercept"], f"{label}/intercept"))
        errors.append(close(observed["beta"], expected["beta"], f"{label}/beta"))
        errors.append(close(observed["standard_error_HC3"], expected["se"], f"{label}/se"))
        require(abs(float(observed["critical_t"]) - T_CRIT_190) < 1e-4, f"{label} t critical mismatch")
        errors.append(close(observed["lower_95"], expected["beta"] - T_CRIT_190 * expected["se"], f"{label}/lower"))
        errors.append(close(observed["upper_95"], expected["beta"] + T_CRIT_190 * expected["se"], f"{label}/upper"))

    sequence = summary["fixed_sequence"]
    require(sequence[0]["decision"] == ("PASS" if mc["lower"] > 0 else "FAIL")
        and sequence[1]["decision"] == ("PASS" if d_interval["upper"] < 0 else "FAIL"),
        "fixed-sequence median decision replay mismatch")
    if r_interval is not None:
        require(sequence[2]["decision"] == ("PASS" if r_interval["upper"] < 0 else "FAIL"),
            "fixed-sequence R decision replay mismatch")
    require(sequence[3]["decision"] == ("PASS" if beta["beta"] - T_CRIT_190*beta["se"] > 0
        or beta["beta"] + T_CRIT_190*beta["se"] < 0 else "FAIL"), "fixed-sequence beta decision replay mismatch")
    confirmatory_open = True
    for step in sequence:
        expected_state = "CONFIRMATORY" if confirmatory_open else "DESCRIPTIVE_AFTER_PRIOR_FAILURE"
        require(step.get("sequence_status") == expected_state, "fixed-sequence status propagation mismatch")
        if step["decision"] != "PASS":
            confirmatory_open = False
    s1x_median = float(np.median([row["step120"]["S_1X"] for row in balanced]))
    d_crosses_zero = d_interval["lower"] <= 0 <= d_interval["upper"]
    expected_floor_reading = ("discrimination too weak at baseline to assess attenuation"
        if s1x_median < S_MIN and d_crosses_zero
        else "signed additive discrimination contrast; interpret by interval and fixed sequence")
    require(summary["D_floor_interpretation"] == expected_floor_reading, "baseline-floor interpretation mismatch")
    for field, value in (("M_C_positive", sum(row["step120"]["M_C"] > 0 for row in balanced)),
        ("M_C_negative", sum(row["step120"]["M_C"] < 0 for row in balanced)),
        ("D_positive", sum(row["step120"]["D"] > 0 for row in balanced)),
        ("D_negative", sum(row["step120"]["D"] < 0 for row in balanced))):
        require(summary["history_effects"][field] == value, f"history sign count mismatch: {field}")
    for field, values in (("M_C", [row["step120"]["M_C"] for row in balanced]),
        ("D", [row["step120"]["D"] for row in balanced])):
        errors.append(close(summary["mean_history_effects_secondary"][field], float(np.mean(values)),
            f"mean_history_effects_secondary/{field}"))
    if r_interval is not None:
        errors.append(close(summary["mean_history_effects_secondary"]["R"], float(np.mean(r_values)),
            "mean_history_effects_secondary/R"))

    bridge_rows = read_jsonl(ANALYSIS / "bridge-paired-differences.jsonl")
    bridge_map = {int(row["seed"]): row for row in bridge_rows}
    require(len(bridge_map) == 24 and len(set(bridge_map)) == 24, "bridge pairing receipt malformed")
    history_by_seed = {int(row["seed"]): row for row in histories if row["cohort"] == "balanced"}
    bridge_by_seed = {int(row["seed"]): row for row in histories if row["cohort"] == "high_to_low_bridge"}
    for seed in sorted(bridge_by_seed):
        require(seed in history_by_seed and seed in bridge_map, "bridge seed lacks paired balanced history")
        for metric in ("M_C", "P_C"):
            field = f"balanced_minus_high_to_low_{metric}"
            expected = history_by_seed[seed]["step120"][metric] - bridge_by_seed[seed]["step120"][metric]
            errors.append(close(bridge_map[seed][field], expected, f"bridge/{seed}/{metric}"))
    bridge_summary = summary["bridge_secondary"]
    for metric in ("M_C", "P_C"):
        field = f"balanced_minus_high_to_low_{metric}"
        differences = [bridge_map[seed][field] for seed in sorted(bridge_map)]
        interval = median_interval(differences)
        compare_interval(bridge_summary[field], interval, f"bridge/{metric}", errors)
        errors.append(close(bridge_summary[field]["mean_secondary"], float(np.mean(differences)),
            f"bridge/{metric}/mean"))

    receipt = {"schema": "jev-r3-independent-replay-receipt-v01", "status": "R3_V03_INDEPENDENT_ANALYSIS_REPLAY_PASS",
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "prediction_seal_sha256": sha_file(PRED / "prediction-seal-v01.json"),
        "analysis_root_sha256": sha_file(ANALYSIS / "analysis-root-v01.json"),
        "target_join_sha256": sha_file(PANEL / "r3-panel-targets-v01.jsonl"),
        "balanced_histories_replayed": len(balanced), "bridge_histories_replayed": len(bridge),
        "trajectory_cells_replayed": len(traj_map), "family_direction_cells_per_trajectory": 8,
        "maximum_absolute_metric_difference": max(errors, default=0.0), "comparison_tolerance": TOL,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__},
        "prediction_seal_verified_before_target_open": True, "analyzer_module_imported": False,
        "scientific_metrics_recomputed_independently": True}
    receipt_path = ANALYSIS / "independent-replay-receipt-v01.json"
    write_json(receipt_path, receipt)

    final_inputs = [PRED / "prediction-seal-v01.json", PANEL / "seals/r3-panel-seal-v01.json",
        TRAINING / "training-seal-v01.json", ANALYSIS / "analysis-root-v01.json", receipt_path,
        ANALYSIS / "analysis-summary.json", ANALYSIS / "history-level-results.jsonl",
        ANALYSIS / "trajectory-points.jsonl", ANALYSIS / "bridge-paired-differences.jsonl",
        ANALYSIS / "analysis-inputs.json"]
    entries = [{"path": str(path.relative_to(RUN)).replace("\\", "/"), "bytes": path.stat().st_size,
        "sha256": sha_file(path)} for path in final_inputs]
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda row: row["path"]))
    final = {"schema": "jev-r3-final-result-seal-v01", "status": "POST_REGISTERED_R3_RESULT_SEALED",
        "identity": "JEV-V08Q-R3-SELECTIVITY-V03", "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "panel_opening_count": 1, "training_seal_sha256": sha_file(TRAINING / "training-seal-v01.json"),
        "prediction_seal_sha256": sha_file(PRED / "prediction-seal-v01.json"),
        "analysis_root_sha256": sha_file(ANALYSIS / "analysis-root-v01.json"),
        "independent_replay_receipt_sha256": sha_file(receipt_path), "entries": entries,
        "entries_root_sha256": sha_bytes(payload.encode()), "result_metrics": summary["fixed_sequence"],
        "exploratory_or_secondary_metrics_not_used_for_gates": True}
    final_path = ANALYSIS / "final-result-seal-v01.json"
    write_json(final_path, final)
    print(json.dumps({"status": final["status"], "final_result_root_sha256": final["entries_root_sha256"],
        "max_replay_diff": receipt["maximum_absolute_metric_difference"],
        "fixed_sequence": final["result_metrics"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
