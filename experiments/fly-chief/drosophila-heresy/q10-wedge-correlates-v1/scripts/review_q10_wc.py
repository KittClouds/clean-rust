"""Independent standard-library reviewer for Q10-WC geometry and descriptions."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROTOCOL = "Q10-WC"
ACCEPTED = "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT"
DOMINATED = "Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED"
ALLOWED = {ACCEPTED, DOMINATED}
SIDES = ("R", "L")
TAUS = (4, 16)
WINDOWS = (("early-1", 1, 16), ("early-2", 17, 32), ("middle-1", 33, 64),
           ("middle-2", 65, 128), ("late", 129, 256))
STAGES = {
    "stage-a": [("stage-a-9701", [9701])],
    "combined": [("stage-a-9701", [9701]), ("stage-b-9702-9705", [9702, 9703, 9704, 9705])],
}
PREDICTORS = ("x_slack", "f_boundary_active", "n_support", "n_null", "f_null_energy", "t")
FORBIDDEN = ("accuracy", "reward", "action", "probe", "margin", "behavior", "correct")
GEOMETRY_TOL = 2.0e-8


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        fail("nonfinite number")
    return result


def bits(value: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def scan_keys(value: object, location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(word in key.lower() for word in FORBIDDEN):
                fail(f"forbidden field {location}.{key}")
            scan_keys(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_keys(child, f"{location}[{index}]")


def percentile(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(number(value) for value in values)
    result = {}
    for label, q in (("min", 0.0), ("q25", 0.25), ("median", 0.5), ("q75", 0.75), ("max", 1.0)):
        h = (len(ordered) - 1) * q
        low, high = math.floor(h), math.ceil(h)
        result[label] = ordered[low] * (high - h) + ordered[high] * (h - low) if high != low else ordered[low]
    return result


def ranks(values: list[float]) -> tuple[list[float], int, int]:
    order = sorted(range(len(values)), key=lambda index: (values[index], bits(values[index])))
    output = [0.0] * len(values)
    tie_groups = tied_rows = 0
    begin = 0
    while begin < len(order):
        end = begin + 1
        token = bits(values[order[begin]])
        while end < len(order) and bits(values[order[end]]) == token:
            end += 1
        average = ((begin + 1) + end) / 2.0
        for position in range(begin, end):
            output[order[position]] = average
        if end - begin > 1:
            tie_groups += 1
            tied_rows += end - begin
        begin = end
    return output, tie_groups, tied_rows


def correlation(x: list[float], y: list[float]) -> float | None:
    mx, my = math.fsum(x) / len(x), math.fsum(y) / len(y)
    dx, dy = [value - mx for value in x], [value - my for value in y]
    xx = math.fsum(value * value for value in dx)
    yy = math.fsum(value * value for value in dy)
    return None if xx == 0.0 or yy == 0.0 else math.fsum(a * b for a, b in zip(dx, dy)) / math.sqrt(xx * yy)


def rho(rows: list[dict], x_name: str, y_name: str, minimum: int = 2) -> dict:
    pairs = [(row.get(x_name), row.get(y_name)) for row in rows]
    pairs = [(number(x), number(y)) for x, y in pairs if x is not None and y is not None]
    if len(pairs) < minimum:
        return {"status": "UNDEFINED_INSUFFICIENT_ROWS", "n": len(pairs)}
    x, y = map(list, zip(*pairs))
    xr, x_groups, x_rows = ranks(x)
    yr, y_groups, y_rows = ranks(y)
    value = correlation(xr, yr)
    if value is None:
        return {"status": "UNDEFINED_ZERO_RANK_VARIANCE", "n": len(pairs),
                "x_tie_groups": x_groups, "x_tied_rows": x_rows,
                "y_tie_groups": y_groups, "y_tied_rows": y_rows}
    return {"status": "DEFINED", "n": len(pairs), "rho": value, "abs_rho": abs(value),
            "direction": "positive" if value > 0 else "negative" if value < 0 else "zero",
            "x_tie_groups": x_groups, "x_tied_rows": x_rows,
            "y_tie_groups": y_groups, "y_tied_rows": y_rows}


def window(trial: int) -> str:
    for name, first, last in WINDOWS:
        if first <= trial <= last:
            return name
    fail("trial outside timing windows")


def derive(event: dict, seed: int, side: str, tau: int) -> dict:
    support = int(event["support_count"])
    interior = int(event["interior_variable_count"])
    trial = int(event["trial"])
    slack = number(event["true_minimum_safety_slack"])
    if not (support > 0 and 0 <= interior <= support and 1 <= trial <= 256 and slack > 0.0):
        fail("derived-variable admission failed")
    true_norm, null_norm = number(event["true_norm"]), number(event["true_null_norm"])
    c = abs(number(event["residual_cosine"]))
    row = dict(event)
    row.update({"seed": seed, "side": side, "tau": tau, "t": float(trial), "window": window(trial),
                "theta": number(event["rotation_angle"]), "c": c, "one_minus_c": 1.0 - c,
                "x_slack": math.log10(slack), "f_boundary_active": (support - interior) / support,
                "n_support": float(support), "n_null": number(event["combined_nullity"]),
                "f_null_energy": None if true_norm <= 0.0 else (null_norm / true_norm) ** 2})
    return row


def check_geometry(event: dict) -> None:
    if event["status"] not in ALLOWED:
        fail(f"unusable geometry status: {event['status']}")
    for field in ("cue_drive_max_abs_error", "axis_displacement_error", "null_annihilation_max_abs",
                  "total_norm_error", "reconstruction_error"):
        if number(event[field]) > GEOMETRY_TOL:
            fail(f"geometry tolerance failed: {field}")
    for field in ("outside_support_changes", "boundary_membership_symmetric_difference",
                  "lower_boundary_membership_difference", "upper_boundary_membership_difference",
                  "new_boundary_memberships", "bounds_violation_count"):
        if int(event[field]) != 0:
            fail(f"continuous integrity failed: {field}")
    expected_commit = "SAFETY_AUDITED_ONLY" if event["exhaustion_status"] == "ACCEPTED" else "NOT_CONSTRUCTED"
    if event["f32_commit_status"] != expected_commit:
        fail("f32 commitment status mismatch")
    if event["status"] == ACCEPTED:
        if event["exhaustion_status"] != "ACCEPTED" or int(event["candidate_count"]) != 16 or int(event["reserve_ulps"]) != 32:
            fail("accepted constructor metadata mismatch")
        for field in ("f32_safety_violation_count", "f32_boundary_membership_symmetric_difference",
                      "f32_lower_boundary_membership_difference", "f32_upper_boundary_membership_difference",
                      "f32_new_boundary_memberships"):
            if int(event[field]) != 0:
                fail(f"committed integrity failed: {field}")
        if int(event["f32_minimum_down_steps_capped"]) < 32 or int(event["f32_minimum_up_steps_capped"]) < 32:
            fail("f32 reserve failed")
        theta, c = number(event["rotation_angle"]), abs(number(event["residual_cosine"]))
        if not (0.0 < theta <= math.pi / 2.0 and c < 1.0 - 1.0e-8 and abs(math.cos(theta) - c) <= 2.0e-10):
            fail("accepted wedge identity failed")


def verify_parent(root: Path, contract: dict) -> None:
    if contract["protocol"] != PROTOCOL or contract["document_state"] != "FINAL":
        fail("contract identity mismatch")
    if sha256(root / "PLAN.md").upper() != contract["plan_sha256"]:
        fail("plan hash mismatch")
    parent = root.parent / "q10-safety-margin-v1"
    for field, filename in (("parent_contract_sha256", "CONTRACT.json"),
                            ("parent_plan_sha256", "PLAN.md"),
                            ("parent_result_sha256", "RESULT.md"),
                            ("parent_status_sha256", "STATUS.json"),
                            ("parent_summary_sha256", "Q10-SM-SUMMARY.json")):
        if sha256(parent / filename).upper() != contract["lineage"][field]:
            fail(f"parent hash mismatch: {filename}")


def load(root: Path, stage: str) -> tuple[list[dict], list[dict]]:
    output = []
    manifest = []
    for dirname, seeds in STAGES[stage]:
        directory = root / "qualification" / dirname
        pre = json.loads((directory / "pre-execution.json").read_text())
        execution = json.loads((directory / "execution.json").read_text())
        if (pre["protocol"] != PROTOCOL or pre["seeds"] != seeds or pre["scientific_seed_bundles"] != 0
                or pre["behavioral_inference"] or pre["receipt_scope"] != "GEOMETRY_ONLY"):
            fail("pre-execution firewall mismatch")
        if pre["plan_sha256"].upper() != sha256(root / "PLAN.md").upper():
            fail("pre-execution plan identity mismatch")
        if pre["contract_sha256"].upper() != sha256(root / "CONTRACT.json").upper():
            fail("pre-execution contract identity mismatch")
        if pre["analysis_sha256"].lower() != sha256(root / "scripts" / "analyze_q10_wc.py"):
            fail("analysis identity mismatch")
        if pre["reviewer_sha256"].lower() != sha256(root / "scripts" / "review_q10_wc.py"):
            fail("reviewer identity mismatch")
        if execution["protocol"] != PROTOCOL or not execution["complete"] or execution["audited_states"] != 1024 * len(seeds):
            fail("execution coverage mismatch")
        for seed in seeds:
            for side in SIDES:
                for tau in TAUS:
                    path = directory / f"seed{seed}-{side}-tau{tau}.json"
                    batch = json.loads(path.read_text())
                    scan_keys(batch)
                    if (batch["protocol"] != PROTOCOL or batch["seed"] != seed or batch["side"] != side
                            or int(batch["tau"]) != tau or len(batch["events"]) != 256
                            or batch["drive_rows"] != 16 * batch["post_len"]):
                        fail(f"batch mismatch: {path.name}")
                    trials = set()
                    for event in batch["events"]:
                        check_geometry(event)
                        trials.add(int(event["trial"]))
                        output.append(derive(event, seed, side, tau))
                    if trials != set(range(1, 257)):
                        fail("trial coverage mismatch")
                    manifest.append({"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha256(path)})
    keys = {(row["seed"], row["side"], row["tau"], int(row["trial"])) for row in output}
    if len(keys) != len(output):
        fail("duplicate event keys")
    return output, manifest


def brief(values: list[float | None]) -> dict:
    available = [number(value) for value in values if value is not None]
    return {"available": len(available), "missing": len(values) - len(available), "quantiles": percentile(available)}


def compare(expected: object, actual: object, location: str = "root") -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            fail(f"mapping mismatch at {location}")
        for key in expected:
            compare(expected[key], actual[key], f"{location}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            fail(f"list mismatch at {location}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            compare(left, right, f"{location}[{index}]")
    elif isinstance(expected, float):
        if actual is None or not math.isclose(expected, float(actual), rel_tol=2.0e-10, abs_tol=2.0e-12):
            fail(f"float mismatch at {location}: {expected} != {actual}")
    elif expected != actual:
        fail(f"value mismatch at {location}: {expected} != {actual}")


def expected_pairwise(accepted: list[dict]) -> dict:
    return {name: {outcome: rho(accepted, name, outcome) for outcome in ("theta", "c", "one_minus_c")}
            for name in PREDICTORS}


def expected_trajectories(accepted: list[dict], predictor: str) -> dict:
    entries = []
    for seed in sorted({row["seed"] for row in accepted}):
        for side in SIDES:
            for tau in TAUS:
                subset = [row for row in accepted if row["seed"] == seed and row["side"] == side and row["tau"] == tau]
                entry = {"seed": seed, "side": side, "tau": tau}
                entry.update(rho(subset, predictor, "theta", 16))
                entries.append(entry)
    valid = [entry["rho"] for entry in entries if entry["status"] == "DEFINED"]
    return {"entries": entries, "valid_trajectories": len(valid), "rho_summary": percentile(valid)}


def expected_leave_out(accepted: list[dict], predictor: str) -> list[dict]:
    seeds = sorted({row["seed"] for row in accepted})
    if len(seeds) < 2:
        return []
    result = []
    for seed in seeds:
        entry = {"omitted_seed": seed}
        entry.update(rho([row for row in accepted if row["seed"] != seed], predictor, "theta"))
        result.append(entry)
    return result


def standard_rank(values: list[float]) -> list[float]:
    ranked, _, _ = ranks(values)
    mean = math.fsum(ranked) / len(ranked)
    centered = [value - mean for value in ranked]
    scale = math.sqrt(math.fsum(value * value for value in centered) / len(centered))
    if scale == 0.0:
        fail("zero model scale")
    return [value / scale for value in centered]


def gaussian_solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    n = len(rhs)
    augmented = [row[:] + [target] for row, target in zip(matrix, rhs)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1.0e-10:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        for j in range(column, n + 1):
            augmented[column][j] /= divisor
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            for j in range(column, n + 1):
                augmented[row][j] -= factor * augmented[column][j]
    return [augmented[row][n] for row in range(n)]


def review_model(rows: list[dict], model: dict, include_null: bool, stage: str) -> None:
    predictors = ["x_slack", "f_boundary_active", "n_support", "n_null", "t"]
    if include_null:
        predictors.append("f_null_energy")
    if include_null and any(row["f_null_energy"] is None for row in rows):
        if model["status"] != "UNAVAILABLE_NULL_ENERGY_MISSING":
            fail("null model availability mismatch")
        return
    columns = [[1.0] * len(rows)]
    columns.extend(standard_rank([number(row[name]) for row in rows]) for name in predictors)
    columns.extend([1.0 if row["seed"] == seed else 0.0 for row in rows] for seed in (9702, 9703, 9704, 9705))
    columns.append([1.0 if row["side"] == "L" else 0.0 for row in rows])
    columns.append([1.0 if row["tau"] == 16 else 0.0 for row in rows])
    y = standard_rank([row["theta"] for row in rows])
    gram = [[math.fsum(a * b for a, b in zip(left, right)) for right in columns] for left in columns]
    rhs = [math.fsum(value * target for value, target in zip(column, y)) for column in columns]
    solution = gaussian_solve(gram, rhs)
    if stage == "stage-a":
        if model["status"] != "NUMERICALLY_UNSTABLE":
            fail("Stage A model should expose absent seed levels as rank deficiency")
        return
    if model["status"] == "STABLE_DESCRIPTIVE":
        if solution is None:
            fail("independent model solve failed")
        names = model["column_names"]
        for name, expected in zip(names, solution):
            if not math.isclose(expected, model["coefficients"][name], rel_tol=2.0e-7, abs_tol=2.0e-8):
                fail(f"model coefficient mismatch: {name}")
        predictions = [math.fsum(solution[col] * columns[col][row] for col in range(len(columns))) for row in range(len(rows))]
        sse = math.fsum((target - predicted) ** 2 for target, predicted in zip(y, predictions))
        mean = math.fsum(y) / len(y)
        sst = math.fsum((target - mean) ** 2 for target in y)
        if not math.isclose(1.0 - sse / sst, model["r_squared"], rel_tol=2.0e-8, abs_tol=2.0e-9):
            fail("model R-squared mismatch")


def review(root: Path, stage: str, analysis_path: Path) -> dict:
    contract = json.loads((root / "CONTRACT.json").read_text())
    verify_parent(root, contract)
    analysis = json.loads(analysis_path.read_text())
    events, manifest = load(root, stage)
    accepted = [row for row in events if row["status"] == ACCEPTED]
    dominated = [row for row in events if row["status"] == DOMINATED]
    if analysis["protocol"] != PROTOCOL or analysis["stage"] != stage:
        fail("analysis identity mismatch")
    compare(manifest, analysis["receipt_manifest"], "receipt_manifest")
    expected_width = {"theta": brief([row["theta"] for row in accepted]),
                      "c": brief([row["c"] for row in accepted]),
                      "one_minus_c": brief([row["one_minus_c"] for row in accepted])}
    compare(expected_width, analysis["accepted_width"], "accepted_width")
    expected_selection = {name: {"accepted": brief([row[name] for row in accepted]),
                                 "dominated": brief([row[name] for row in dominated])}
                          for name in PREDICTORS}
    compare(expected_selection, analysis["selection_audit"], "selection_audit")
    compare(expected_pairwise(accepted), analysis["pairwise_associations"], "pairwise")
    for predictor in PREDICTORS:
        compare(expected_trajectories(accepted, predictor), analysis["within_trajectory_associations"][predictor], f"trajectory.{predictor}")
        compare(expected_leave_out(accepted, predictor), analysis["leave_one_seed_out_associations"][predictor], f"leave_out.{predictor}")
    expected_timing = {}
    for label, _, _ in WINDOWS:
        for side in SIDES:
            for tau in TAUS:
                subset = [row for row in accepted if row["window"] == label and row["side"] == side and row["tau"] == tau]
                expected_timing[f"{label}|{side}|tau{tau}"] = {
                    "n": len(subset), "theta": brief([row["theta"] for row in subset]),
                    "c": brief([row["c"] for row in subset])}
    compare(expected_timing, analysis["timing_windows"], "timing")
    coverage = analysis["coverage"]
    if (coverage["total_events"] != len(events) or coverage["accepted"] != len(accepted)
            or coverage["dominated"] != len(dominated)
            or coverage["status_counts"] != dict(sorted(Counter(row["status"] for row in events).items()))):
        fail("coverage aggregate mismatch")
    review_model(accepted, analysis["models"]["core"], False, stage)
    review_model(accepted, analysis["models"]["null_energy"], True, stage)
    scope = analysis["scope"]
    if any((scope["scientific_seed_bundles"] != 0, scope["behavioral_inference"], scope["causal_inference"],
            scope["direction_claim"], scope["future_learning_claim"], scope["future_gate_selected"])):
        fail("analysis scope firewall failed")
    return {"protocol": PROTOCOL, "review_status": "VERIFIED_BY_INDEPENDENT_STDLIB",
            "stage": stage, "events": len(events), "accepted": len(accepted), "dominated": len(dominated),
            "analysis_sha256": sha256(analysis_path), "contract_sha256": sha256(root / "CONTRACT.json"),
            "plan_sha256": sha256(root / "PLAN.md"), "receipt_manifest_entries": len(manifest),
            "geometry_integrity": "VERIFIED", "aggregate_tables": "INDEPENDENTLY_RECOMPUTED",
            "correlations": "INDEPENDENTLY_RECOMPUTED", "models": "INDEPENDENTLY_CHECKED",
            "scientific_seed_bundles": 0, "behavioral_inference": False,
            "causal_inference": False, "future_gate_selected": False}


def self_test() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0])["median"] == 2.5
    rows = [{"x": value, "y": value} for value in (2.0, 1.0, 2.0, 4.0)]
    assert abs(rho(rows, "x", "y")["rho"] - 1.0) < 1.0e-15
    matrix = [[2.0, 1.0], [1.0, 3.0]]
    solution = gaussian_solve(matrix, [1.0, 2.0])
    assert solution is not None and abs(solution[0] - 0.2) < 1.0e-12 and abs(solution[1] - 0.6) < 1.0e-12


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        print("Q10-WC independent reviewer self-test: PASS")
        return
    if len(sys.argv) != 5 or sys.argv[1] not in STAGES:
        fail("usage: review_q10_wc.py stage-a|combined ROOT ANALYSIS_JSON OUTPUT_RECEIPT")
    root = Path(sys.argv[2]).resolve()
    result = review(root, sys.argv[1], Path(sys.argv[3]).resolve())
    output = Path(sys.argv[4]).resolve()
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
