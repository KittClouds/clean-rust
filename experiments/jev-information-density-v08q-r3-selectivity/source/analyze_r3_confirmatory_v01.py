"""Analyze the sealed R3 raw-logit matrix under the fixed history-level contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
PANEL = RUN / "panel-v03"
EVAL = RUN / "evaluation-v01"
PREDICTIONS = EVAL / "predictions-v01"
ANALYSIS = EVAL / "analysis-v01"
LOCK = EXP / "seals/r3-phase-packet-seal-v01.json"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
DIRECTIONS = ("high_to_low", "low_to_high")
BRANCHES = ("ONE_X", "HALF")
EXPECTED_SHAPE = (1_080, 4_000, 4)
S_MIN = 0.01
MIN_RATIO_ELIGIBLE = 173
R_EQUIVALENCE = (math.log(0.9), math.log(1.1))
ALPHA = 0.05


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("xb") as stream:
        for row in rows:
            stream.write((json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def verify_runtime() -> dict[str, str]:
    require(platform.python_version() == "3.13.15" and np.__version__ == "2.5.3",
        "R3 analysis Python/NumPy runtime mismatch")
    return {"python": platform.python_version(), "numpy": np.__version__}


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1e-300 if abs(d) < 1e-300 else d
    d = 1.0 / d
    result = d
    for iteration in range(1, 201):
        twice = 2 * iteration
        term = iteration * (b - iteration) * x / ((qam + twice) * (a + twice))
        d = 1.0 + term * d
        d = 1e-300 if abs(d) < 1e-300 else d
        c = 1.0 + term / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        result *= d * c
        term = -(a + iteration) * (qab + iteration) * x / ((a + twice) * (qap + twice))
        d = 1.0 + term * d
        d = 1e-300 if abs(d) < 1e-300 else d
        c = 1.0 + term / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) < 3e-14:
            return result
    raise RuntimeError("incomplete beta continued fraction did not converge")


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def student_t_cdf(value: float, degrees: int) -> float:
    require(degrees > 0 and math.isfinite(value), "invalid Student-t CDF argument")
    x = degrees / (degrees + value * value)
    tail = 0.5 * regularized_incomplete_beta(degrees / 2.0, 0.5, x)
    return 1.0 - tail if value >= 0 else tail


def student_t_quantile(probability: float, degrees: int) -> float:
    require(0.5 < probability < 1.0 and degrees > 0, "invalid Student-t quantile request")
    low, high = 0.0, 16.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if student_t_cdf(middle, degrees) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def order_stat_median_interval(values: list[float], alpha: float = ALPHA) -> dict[str, Any]:
    require(bool(values) and all(math.isfinite(float(value)) for value in values), "median interval has invalid input")
    ordered = sorted(float(value) for value in values)
    n = len(ordered)
    denominator = 1 << n
    best_rank = 1
    best_coverage = 0.0
    tail_mass = 0
    for rank in range(1, n // 2 + 1):
        if rank == 1:
            tail_mass = 1
        else:
            tail_mass += math.comb(n, rank - 1)
        coverage = 1.0 - 2.0 * tail_mass / denominator
        if coverage + 1e-15 >= 1.0 - alpha:
            best_rank, best_coverage = rank, coverage
        else:
            break
    return {
        "n": n,
        "median": float(np.median(np.asarray(ordered, dtype=np.float64))),
        "lower": ordered[best_rank - 1],
        "upper": ordered[n - best_rank],
        "lower_order": best_rank,
        "upper_order": n - best_rank + 1,
        "nominal_coverage": best_coverage,
        "method": "narrowest_symmetric_exact_order_statistic_interval",
        "tie_pairs_at_bounds": int(ordered.count(ordered[best_rank - 1]) + ordered.count(ordered[n - best_rank])
            if ordered[best_rank - 1] == ordered[n - best_rank] else 0),
    }


def verify_lock() -> dict[str, Any]:
    lock = read_json(LOCK)
    body = {key: value for key, value in lock.items() if key != "contract_bundle_root_sha256"}
    expected = sha_bytes(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    require(lock.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION"
        and lock.get("contract_bundle_root_sha256") == expected, "R3 phase lock invalid")
    for item in [*lock.get("contracts", []), *lock.get("execution_sources", [])]:
        require(sha_file(Path(item["path"])) == item["sha256"], f"locked input drift: {item['name']}")
    for item in lock.get("sealed_inputs", []):
        require(Path(item["path"]).is_file() and sha_file(Path(item["path"])) == item["sha256"],
            f"locked pre-run input drift: {item['name']}")
    require(any(Path(item["path"]).resolve() == Path(__file__).resolve()
        for item in lock.get("execution_sources", [])), "R3 analysis source not bound by lock")
    return lock


def verify_prediction_seal() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    seal_path = PREDICTIONS / "prediction-seal-v01.json"
    seal = read_json(seal_path)
    entries = seal.get("entries", [])
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    require(seal.get("status") == "R3_V03_COMPLETE_RAW_PREDICTIONS_SEALED_PRE_ANALYSIS"
        and sha_bytes(body.encode()) == seal.get("entries_root_sha256")
        and seal.get("targets_read") is False and seal.get("metrics_computed") is False,
        "R3 prediction seal invalid")
    entry_map = {row["path"]: row for row in entries}
    require(len(entry_map) == len(entries), "duplicate prediction seal path")
    for name, entry in entry_map.items():
        path = PREDICTIONS / name
        require(path.is_file() and path.stat().st_size == entry["bytes"] and sha_file(path) == entry["sha256"],
            f"sealed prediction artifact changed: {name}")
    manifest = read_json(PREDICTIONS / "prediction-manifest.json")
    require(sha_file(PREDICTIONS / "prediction-manifest.json") == seal["manifest_sha256"]
        and tuple(manifest.get("shape", [])) == EXPECTED_SHAPE, "prediction manifest identity/shape mismatch")
    require(manifest.get("all_predictions_complete") is True and manifest.get("targets_read") is False,
        "prediction matrix is incomplete or targets were read before seal")
    cells = read_jsonl(PREDICTIONS / "prediction-cells.jsonl")
    require(len(cells) == EXPECTED_SHAPE[0] and [row["cell_index"] for row in cells] == list(range(EXPECTED_SHAPE[0])),
        "prediction cell manifest incomplete or reordered")
    return manifest, cells


def target_join() -> list[dict[str, Any]]:
    # This is the first target-bearing input opened; verify_prediction_seal ran before this call.
    panel_seal = read_json(PANEL / "seals/r3-panel-seal-v01.json")
    target_name = "r3-panel-targets-v01.jsonl"
    entry = next((row for row in panel_seal["entries"] if row["path"] == target_name), None)
    require(entry is not None, "sealed exact target join is absent")
    path = PANEL / target_name
    require(path.is_file() and path.stat().st_size == entry["bytes"] and sha_file(path) == entry["sha256"],
        "sealed exact target join identity mismatch")
    rows = read_jsonl(path)
    require(len(rows) == EXPECTED_SHAPE[1] and [row["row_index"] for row in rows] == list(range(EXPECTED_SHAPE[1])),
        "exact target join row count/order mismatch")
    return rows


def summarize_cell(logits: np.ndarray, inference: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    require(logits.shape == (EXPECTED_SHAPE[1], 4) and np.isfinite(logits).all(), "invalid cell logit array")
    by_neighborhood: dict[str, dict[str, Any]] = {}
    for index, (meta, target) in enumerate(zip(inference, targets, strict=True)):
        require(meta["row_index"] == target["row_index"] == index
            and meta["neighborhood_id"] == target["neighborhood_id"]
            and meta["family_slug"] == target["family_slug"]
            and meta["direction"] == target["direction"] and meta["view"] == target["view"]
            and meta["candidate_semantic_ids"] == target["candidate_semantic_ids"],
            "prediction/target exact identity join mismatch")
        ids = meta["candidate_semantic_ids"]
        old_index = ids.index(meta["old_semantic_id"])
        new_index = ids.index(meta["new_semantic_id"])
        target_values = [float(value) for value in target["target"]]
        expected_target = old_index if meta["view"] == "anchor" else new_index
        require(len(target_values) == 4 and max(range(4), key=lambda i: (target_values[i], -i)) == expected_target,
            "sealed target role mismatch at analysis join")
        group = by_neighborhood.setdefault(meta["neighborhood_id"], {
            "family": meta["family_slug"], "direction": meta["direction"], "old_index": old_index,
            "new_index": new_index, "anchor": None, "fact": None,
        })
        require(group["family"] == meta["family_slug"] and group["direction"] == meta["direction"]
            and group["old_index"] == old_index and group["new_index"] == new_index,
            "paired view semantic identity drift")
        view = meta["view"]
        require(view in ("anchor", "fact") and group[view] is None, "duplicate or unknown panel view")
        winner = int(np.argmax(logits[index]))
        group[view] = {"score": float(logits[index, new_index] - logits[index, old_index]), "winner": winner,
            "winner_id": ids[winner]}
    require(len(by_neighborhood) == 2_000, "neighborhood pair count mismatch in analysis")
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for family in FAMILIES:
        for direction in DIRECTIONS:
            grouped = [row for row in by_neighborhood.values() if row["family"] == family and row["direction"] == direction]
            require(len(grouped) == 250 and all(row["anchor"] is not None and row["fact"] is not None for row in grouped),
                f"family/direction panel cell invalid: {family}/{direction}")
            anchor = np.asarray([row["anchor"]["score"] for row in grouped], dtype=np.float64)
            fact = np.asarray([row["fact"]["score"] for row in grouped], dtype=np.float64)
            a_ok = np.asarray([row["anchor"]["winner"] == row["old_index"] for row in grouped], dtype=np.bool_)
            f_ok = np.asarray([row["fact"]["winner"] == row["new_index"] for row in grouped], dtype=np.bool_)
            cells[(family, direction)] = {
                "n": len(grouped), "anchor_new_old_logit_mean": float(anchor.mean()),
                "fact_new_old_logit_mean": float(fact.mean()), "fact_minus_anchor_mean": float((fact - anchor).mean()),
                "A_old": float(a_ok.mean()), "F_new": float(f_ok.mean()), "Strict": float((a_ok & f_ok).mean()),
                "AF_cells": {"A_and_F": int(np.sum(a_ok & f_ok)), "A_and_not_F": int(np.sum(a_ok & ~f_ok)),
                    "not_A_and_F": int(np.sum(~a_ok & f_ok)), "not_A_and_not_F": int(np.sum(~a_ok & ~f_ok))},
                "fact_winner_ids": sorted(set(row["fact"]["winner_id"] for row in grouped)),
            }
    s_value = float(np.mean([cells[key]["fact_minus_anchor_mean"] for key in cells]))
    return {"cells": cells, "S": s_value,
        "anchor_A_old": float(np.mean([cells[key]["A_old"] for key in cells])),
        "fact_F_new": float(np.mean([cells[key]["F_new"] for key in cells])),
        "Strict": float(np.mean([cells[key]["Strict"] for key in cells]))}


def branch_contrasts(one_x: dict[str, Any], half: dict[str, Any]) -> dict[str, Any]:
    c_dir: dict[str, float] = {}
    d_dir: dict[str, float] = {}
    for direction in DIRECTIONS:
        c_dir[direction] = float(np.mean([
            half["cells"][(family, direction)]["anchor_new_old_logit_mean"]
            - one_x["cells"][(family, direction)]["anchor_new_old_logit_mean"]
            for family in FAMILIES]))
        d_dir[direction] = float(np.mean([
            half["cells"][(family, direction)]["fact_minus_anchor_mean"]
            - one_x["cells"][(family, direction)]["fact_minus_anchor_mean"]
            for family in FAMILIES]))
    c_hl, c_lh = c_dir["high_to_low"], c_dir["low_to_high"]
    d_hl, d_lh = d_dir["high_to_low"], d_dir["low_to_high"]
    s_delta = float(half["S"] - one_x["S"])
    return {"C_direction": c_dir, "M_C": 0.5 * (c_hl + c_lh), "P_C": 0.5 * (c_hl - c_lh),
        "D_direction": d_dir, "D": s_delta, "M_D": 0.5 * (d_hl + d_lh),
        "P_D": 0.5 * (d_hl - d_lh), "S_1X": float(one_x["S"]), "S_HALF": float(half["S"]),
        "R": math.log(half["S"] / one_x["S"]) if one_x["S"] >= S_MIN and half["S"] >= S_MIN else None,
        "ratio_eligible": bool(one_x["S"] >= S_MIN and half["S"] >= S_MIN)}


def hc3_slope(x_values: list[float], y_values: list[float]) -> dict[str, Any]:
    x = np.asarray(x_values, dtype=np.float64)
    y = np.asarray(y_values, dtype=np.float64)
    require(len(x) == len(y) and len(x) > 3 and np.isfinite(x).all() and np.isfinite(y).all(),
        "HC3 input invalid or insufficient")
    design = np.column_stack((np.ones(len(x), dtype=np.float64), x))
    xtx_inv = np.linalg.inv(design.T @ design)
    coefficients = xtx_inv @ design.T @ y
    residual = y - design @ coefficients
    leverage = np.sum((design @ xtx_inv) * design, axis=1)
    require(np.all(leverage < 1.0), "HC3 leverage reached one")
    adjusted = residual / (1.0 - leverage)
    meat = design.T @ ((adjusted * adjusted)[:, None] * design)
    covariance = xtx_inv @ meat @ xtx_inv
    standard_error = float(math.sqrt(max(0.0, covariance[1, 1])))
    degrees = len(x) - design.shape[1]
    critical = student_t_quantile(1.0 - ALPHA / 2.0, degrees)
    lower = float(coefficients[1] - critical * standard_error)
    upper = float(coefficients[1] + critical * standard_error)
    variance = float(np.sum(residual * residual) / degrees)
    cooks = (residual * residual / (design.shape[1] * variance)) * (leverage / ((1.0 - leverage) ** 2)) if variance > 0 else np.zeros_like(x)
    return {"n": len(x), "intercept": float(coefficients[0]), "beta": float(coefficients[1]),
        "standard_error_HC3": standard_error, "lower_95": lower, "upper_95": upper,
        "degrees_freedom": degrees, "critical_t": critical, "max_leverage": float(leverage.max()),
        "max_cooks_distance": float(cooks.max()), "max_abs_studentized_residual": float(
            np.max(np.abs(residual / np.sqrt(np.maximum(1e-30, variance * (1.0 - leverage))))))}


def summarize_cohort(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    values = [float(row[metric]) for row in rows if row.get(metric) is not None]
    result = order_stat_median_interval(values)
    result.update({"mean": float(np.mean(values)), "positive_count": int(sum(value > 0 for value in values)),
        "negative_count": int(sum(value < 0 for value in values)), "zero_count": int(sum(value == 0 for value in values)),
        "minimum": min(values), "maximum": max(values)})
    return result


def serializable_cells(cells: dict[tuple[str, str], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Encode family/polarity keys as stable JSON strings at the artifact boundary."""
    return {f"{family}|{direction}": cells[(family, direction)]
        for family in FAMILIES for direction in DIRECTIONS}


def main() -> int:
    require(not ANALYSIS.exists(), f"refusing existing R3 analysis namespace: {ANALYSIS}")
    lock = verify_lock()
    runtime = verify_runtime()
    prediction_manifest, cells = verify_prediction_seal()
    require(prediction_manifest.get("phase_lock_root_sha256") == lock["contract_bundle_root_sha256"],
        "prediction matrix belongs to another R3 contract bundle")
    # The exact targets become readable only after the raw-logit tree is sealed.
    targets = target_join()
    inference = read_jsonl(PANEL / "r3-panel-inference-manifest.jsonl")
    logits = np.memmap(PREDICTIONS / "raw-logits.f32le", mode="r", dtype="<f4", shape=EXPECTED_SHAPE)
    cells_by_key = {(row["cohort"], int(row["seed"]), row["branch"], int(row["global_step"])): int(row["cell_index"])
        for row in cells}
    require(len(cells_by_key) == EXPECTED_SHAPE[0], "duplicate prediction cell identity")
    history_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    by_cohort_seed: dict[tuple[str, int], dict[str, Any]] = {}
    for (cohort, seed, _branch, _step), _ in cells_by_key.items():
        by_cohort_seed.setdefault((cohort, seed), {})
    for cohort, seed in sorted(by_cohort_seed):
        baseline_index = cells_by_key[(cohort, seed, "COMMON", 80)]
        baseline = summarize_cell(logits[baseline_index], inference, targets)
        by_cohort_seed[(cohort, seed)]["S80"] = baseline["S"]
        trajectory_rows.append({"cohort": cohort, "seed": seed, "branch": "COMMON", "step": 80,
            "S": baseline["S"], "A_old": baseline["anchor_A_old"], "F_new": baseline["fact_F_new"],
            "Strict": baseline["Strict"], "cells": serializable_cells(baseline["cells"])})
        endpoint_metrics: dict[tuple[str, int], dict[str, Any]] = {}
        for step in (100, 120):
            for branch in BRANCHES:
                index = cells_by_key[(cohort, seed, branch, step)]
                endpoint_metrics[(branch, step)] = summarize_cell(logits[index], inference, targets)
                item = endpoint_metrics[(branch, step)]
                trajectory_rows.append({"cohort": cohort, "seed": seed, "branch": branch, "step": step,
                    "S": item["S"], "A_old": item["anchor_A_old"], "F_new": item["fact_F_new"],
                    "Strict": item["Strict"], "cells": serializable_cells(item["cells"])})
        contrasts = {str(step): branch_contrasts(endpoint_metrics[("ONE_X", step)], endpoint_metrics[("HALF", step)])
            for step in (100, 120)}
        if cohort == "balanced":
            primary = contrasts["120"]
        else:
            primary = contrasts["120"]
        row = {"cohort": cohort, "seed": seed, "S80": baseline["S"],
            "step100": contrasts["100"], "step120": primary,
            "step120_A_old_1X": endpoint_metrics[("ONE_X", 120)]["anchor_A_old"],
            "step120_A_old_HALF": endpoint_metrics[("HALF", 120)]["anchor_A_old"],
            "step120_F_new_1X": endpoint_metrics[("ONE_X", 120)]["fact_F_new"],
            "step120_F_new_HALF": endpoint_metrics[("HALF", 120)]["fact_F_new"],
            "step120_Strict_1X": endpoint_metrics[("ONE_X", 120)]["Strict"],
            "step120_Strict_HALF": endpoint_metrics[("HALF", 120)]["Strict"],
            "family_direction_cells_1X": serializable_cells(endpoint_metrics[("ONE_X", 120)]["cells"]),
            "family_direction_cells_HALF": serializable_cells(endpoint_metrics[("HALF", 120)]["cells"])}
        history_rows.append(row)
        by_cohort_seed[(cohort, seed)].update({"metrics": row, "M_C": primary["M_C"], "P_C": primary["P_C"],
            "D": primary["D"], "R": primary["R"], "ratio_eligible": primary["ratio_eligible"]})

    balanced = [row for row in history_rows if row["cohort"] == "balanced"]
    bridge = [row for row in history_rows if row["cohort"] == "high_to_low_bridge"]
    require(len(balanced) == 192 and len(bridge) == 24, "analysis history cohort count mismatch")
    mc = summarize_cohort([{"M_C": row["step120"]["M_C"]} for row in balanced], "M_C")
    d_summary = summarize_cohort([{"D": row["step120"]["D"]} for row in balanced], "D")
    ratio_values = [row["step120"]["R"] for row in balanced if row["step120"]["ratio_eligible"]]
    ratio_coverage = len(ratio_values)
    ratio_summary = order_stat_median_interval(ratio_values) if ratio_coverage >= MIN_RATIO_ELIGIBLE else None
    if ratio_summary is not None:
        ratio_summary.update({"eligible_count": ratio_coverage, "registered_denominator": 192,
            "coverage_fraction": ratio_coverage / 192, "mean": float(np.mean(ratio_values)),
            "positive_count": int(sum(value > 0 for value in ratio_values)),
            "negative_count": int(sum(value < 0 for value in ratio_values))})
    beta = hc3_slope([row["S80"] for row in balanced], [row["step120"]["D"] for row in balanced])
    c_s80_descriptive = hc3_slope([row["S80"] for row in balanced],
        [row["step120"]["M_C"] for row in balanced])
    pc_summary = summarize_cohort([{"P_C": row["step120"]["P_C"]} for row in balanced], "P_C")
    m_decision = "PASS" if mc["lower"] > 0 else "FAIL"
    d_decision = "PASS" if d_summary["upper"] < 0 else "FAIL"
    if ratio_coverage < MIN_RATIO_ELIGIBLE:
        r_decision = "NOT_ESTIMABLE_FOR_COHORT"
    else:
        r_decision = "PASS" if ratio_summary["upper"] < 0 else "FAIL"
    beta_decision = "PASS" if beta["lower_95"] > 0 or beta["upper_95"] < 0 else "FAIL"
    sequence = [
        {"step": 1, "estimand": "median_M_C", "decision": m_decision, "interval": [mc["lower"], mc["upper"]],
            "rule": "lower 95% order-statistic bound > 0"},
        {"step": 2, "estimand": "median_D", "decision": d_decision, "interval": [d_summary["lower"], d_summary["upper"]],
            "rule": "upper 95% order-statistic bound < 0"},
        {"step": 3, "estimand": "median_R", "decision": r_decision,
            "eligible_count": ratio_coverage, "registered_denominator": 192,
            "interval": None if ratio_summary is None else [ratio_summary["lower"], ratio_summary["upper"]],
            "rule": "eligible count >=173 and upper 95% order-statistic bound < 0"},
        {"step": 4, "estimand": "beta_D_on_S80", "decision": beta_decision,
            "interval": [beta["lower_95"], beta["upper_95"]], "rule": "zero outside two-sided 95% HC3 interval"},
    ]
    confirmatory_open = True
    for item in sequence:
        item["sequence_status"] = "CONFIRMATORY" if confirmatory_open else "DESCRIPTIVE_AFTER_PRIOR_FAILURE"
        if item["decision"] != "PASS":
            confirmatory_open = False
    mean_d_zero_crossing = d_summary["lower"] <= 0 <= d_summary["upper"]
    if d_summary["median"] is not None and float(np.median([row["step120"]["S_1X"] for row in balanced])) < S_MIN and mean_d_zero_crossing:
        d_reading = "discrimination too weak at baseline to assess attenuation"
    else:
        d_reading = "signed additive discrimination contrast; interpret by interval and fixed sequence"

    bridge_lookup = {int(row["seed"]): row for row in bridge}
    bridge_differences = []
    for row in balanced:
        seed = int(row["seed"])
        if seed not in bridge_lookup:
            continue
        other = bridge_lookup[seed]
        bridge_differences.append({"seed": seed,
            "balanced_minus_high_to_low_M_C": row["step120"]["M_C"] - other["step120"]["M_C"],
            "balanced_minus_high_to_low_P_C": row["step120"]["P_C"] - other["step120"]["P_C"]})
    require(len(bridge_differences) == 24, "bridge pairing to balanced seed/init is incomplete")
    bridge_summary = {}
    for name in ("balanced_minus_high_to_low_M_C", "balanced_minus_high_to_low_P_C"):
        vals = [row[name] for row in bridge_differences]
        interval = order_stat_median_interval(vals)
        interval["mean_secondary"] = float(np.mean(vals))
        interval["paired_seed_count"] = len(vals)
        bridge_summary[name] = interval

    ANALYSIS.mkdir(parents=True, exist_ok=False)
    write_jsonl(ANALYSIS / "history-level-results.jsonl", history_rows)
    write_jsonl(ANALYSIS / "trajectory-points.jsonl", trajectory_rows)
    write_jsonl(ANALYSIS / "bridge-paired-differences.jsonl", bridge_differences)
    summary = {
        "schema": "jev-r3-confirmatory-analysis-summary-v01", "status": "R3_V03_FROZEN_ANALYSIS_COMPLETE",
        "identity": "JEV-V08Q-R3-SELECTIVITY-V03-ANALYSIS", "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "prediction_seal_sha256": sha_file(PREDICTIONS / "prediction-seal-v01.json"),
        "panel_opening_receipt_sha256": sha_file(EVAL / "panel-opening-receipt.json"),
        "target_join_read_after_prediction_seal": True, "balanced_histories": len(balanced), "bridge_histories": len(bridge),
        "fixed_sequence": sequence, "median_M_C": mc, "median_D": d_summary,
        "ratio_coverage": {"eligible_count": ratio_coverage, "denominator": 192,
            "minimum": MIN_RATIO_ELIGIBLE, "status": "ESTIMABLE" if ratio_coverage >= MIN_RATIO_ELIGIBLE else "NOT_ESTIMABLE_FOR_COHORT"},
        "median_R_if_estimable": ratio_summary, "median_P_C_secondary": pc_summary,
        "R_equivalence_secondary": ("PRACTICALLY_UNCHANGED" if ratio_summary is not None
            and ratio_summary["lower"] >= R_EQUIVALENCE[0] and ratio_summary["upper"] <= R_EQUIVALENCE[1]
            else "NOT_ESTIMABLE" if ratio_summary is None else "NOT_ESTABLISHED"),
        "R_equivalence_band": list(R_EQUIVALENCE), "S_min": S_MIN,
        "beta_HC3": beta, "C_vs_S80_descriptive_HC3": c_s80_descriptive,
        "C_vs_S80_confirmatory": False, "D_floor_interpretation": d_reading,
        "bridge_secondary": bridge_summary, "history_effects": {
            "M_C_positive": mc["positive_count"], "M_C_negative": mc["negative_count"],
            "D_positive": d_summary["positive_count"], "D_negative": d_summary["negative_count"],
            "R_positive": None if ratio_summary is None else ratio_summary["positive_count"],
            "R_negative": None if ratio_summary is None else ratio_summary["negative_count"]},
        "interval_method": "narrowest symmetric exact order-statistic interval for medians; HC3 t interval for beta",
        "runtime": runtime,
        "family_order": list(FAMILIES), "direction_order": list(DIRECTIONS),
        "mean_history_effects_secondary": {"M_C": mc["mean"], "D": d_summary["mean"],
            "R": None if ratio_summary is None else ratio_summary["mean"]},
        "all_history_rows_reported": True,
    }
    write_json(ANALYSIS / "analysis-summary.json", summary)
    inputs = [PREDICTIONS / "prediction-seal-v01.json", PREDICTIONS / "prediction-manifest.json",
        PREDICTIONS / "prediction-cells.jsonl", PREDICTIONS / "raw-logits.f32le",
        PANEL / "r3-panel-targets-v01.jsonl", PANEL / "r3-panel-inference-manifest.jsonl"]
    write_json(ANALYSIS / "analysis-inputs.json", {"status": "PREDICTION_SEAL_VERIFIED_BEFORE_TARGET_JOIN",
        "prediction_seal_sha256": sha_file(PREDICTIONS / "prediction-seal-v01.json"),
        "target_join_sha256": sha_file(PANEL / "r3-panel-targets-v01.jsonl"),
        "input_sha256": {path.name: sha_file(path) for path in inputs}, "metrics": True})
    output_names = ["history-level-results.jsonl", "trajectory-points.jsonl", "bridge-paired-differences.jsonl",
        "analysis-summary.json", "analysis-inputs.json"]
    entries = [{"path": name, "bytes": (ANALYSIS / name).stat().st_size, "sha256": sha_file(ANALYSIS / name)}
        for name in output_names]
    entries_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    result = {"schema": "jev-r3-analysis-root-v01", "status": "R3_V03_PRIMARY_ANALYSIS_COMPLETE_AWAITING_INDEPENDENT_REPLAY",
        "entries": entries, "entries_root_sha256": sha_bytes(entries_body.encode()),
        "prediction_seal_sha256": summary["prediction_seal_sha256"],
        "panel_target_join_sha256": sha_file(PANEL / "r3-panel-targets-v01.jsonl"),
        "analysis_contract_sha256": next(row["sha256"] for row in lock["contracts"] if row["name"] == "analysis")}
    write_json(ANALYSIS / "analysis-root-v01.json", result)
    print(json.dumps({"status": result["status"], "analysis_root_sha256": result["entries_root_sha256"],
        "fixed_sequence": sequence, "ratio_eligible": f"{ratio_coverage}/192",
        "D_floor_interpretation": d_reading}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
