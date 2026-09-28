"""Frozen descriptive Q10-WC analysis over geometry-only Q10-SM-style receipts."""
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
ELIGIBLE = {ACCEPTED, DOMINATED}
SIDES = ("R", "L")
TAUS = (4, 16)
STAGES = {
    "stage-a": ([9701], [("stage-a-9701", [9701])]),
    "combined": (
        [9701, 9702, 9703, 9704, 9705],
        [("stage-a-9701", [9701]), ("stage-b-9702-9705", [9702, 9703, 9704, 9705])],
    ),
}
PREDICTORS = ("x_slack", "f_boundary_active", "n_support", "n_null", "f_null_energy", "t")
WINDOWS = (("early-1", 1, 16), ("early-2", 17, 32), ("middle-1", 33, 64),
           ("middle-2", 65, 128), ("late", 129, 256))
FORBIDDEN_RECEIPT_KEYS = ("accuracy", "reward", "action", "probe", "margin", "behavior", "correct")
EPSILON = sys.float_info.epsilon
RANK_MULTIPLIER = 1000.0


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        fail("nonfinite numeric receipt value")
    return result


def reject_forbidden(value: object, path: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(word in key.lower() for word in FORBIDDEN_RECEIPT_KEYS):
                fail(f"forbidden field {path}.{key}")
            reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_forbidden(child, f"{path}[{index}]")


def bit_key(value: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(finite(value) for value in values)
    result: dict[str, float] = {}
    for label, q in (("min", 0.0), ("q25", 0.25), ("median", 0.5), ("q75", 0.75), ("max", 1.0)):
        h = (len(ordered) - 1) * q
        lower = math.floor(h)
        upper = math.ceil(h)
        result[label] = ordered[lower] + (ordered[upper] - ordered[lower]) * (h - lower)
    return result


def average_ranks(values: list[float]) -> tuple[list[float], int, int]:
    indexed = sorted(enumerate(values), key=lambda item: (item[1], bit_key(item[1])))
    ranks = [0.0] * len(values)
    groups = 0
    tied_rows = 0
    start = 0
    while start < len(indexed):
        stop = start + 1
        bits = bit_key(indexed[start][1])
        while stop < len(indexed) and bit_key(indexed[stop][1]) == bits:
            stop += 1
        rank = ((start + 1) + stop) * 0.5
        for offset in range(start, stop):
            ranks[indexed[offset][0]] = rank
        if stop - start > 1:
            groups += 1
            tied_rows += stop - start
        start = stop
    return ranks, groups, tied_rows


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or not x:
        return None
    mx = math.fsum(x) / len(x)
    my = math.fsum(y) / len(y)
    dx = [value - mx for value in x]
    dy = [value - my for value in y]
    xx = math.fsum(value * value for value in dx)
    yy = math.fsum(value * value for value in dy)
    if xx == 0.0 or yy == 0.0:
        return None
    return math.fsum(a * b for a, b in zip(dx, dy)) / math.sqrt(xx * yy)


def spearman(rows: list[dict], x_name: str, y_name: str, minimum: int = 2) -> dict:
    pairs = [(row.get(x_name), row.get(y_name)) for row in rows]
    pairs = [(finite(x), finite(y)) for x, y in pairs if x is not None and y is not None]
    if len(pairs) < minimum:
        return {"status": "UNDEFINED_INSUFFICIENT_ROWS", "n": len(pairs)}
    x, y = map(list, zip(*pairs))
    xr, x_groups, x_rows = average_ranks(x)
    yr, y_groups, y_rows = average_ranks(y)
    rho = pearson(xr, yr)
    if rho is None:
        return {"status": "UNDEFINED_ZERO_RANK_VARIANCE", "n": len(pairs),
                "x_tie_groups": x_groups, "x_tied_rows": x_rows,
                "y_tie_groups": y_groups, "y_tied_rows": y_rows}
    direction = "positive" if rho > 0.0 else "negative" if rho < 0.0 else "zero"
    return {"status": "DEFINED", "n": len(pairs), "rho": rho, "abs_rho": abs(rho),
            "direction": direction, "x_tie_groups": x_groups, "x_tied_rows": x_rows,
            "y_tie_groups": y_groups, "y_tied_rows": y_rows}


def timing_window(trial: int) -> str:
    for name, first, last in WINDOWS:
        if first <= trial <= last:
            return name
    fail(f"trial outside frozen windows: {trial}")


def derive(event: dict, seed: int, side: str, tau: int) -> dict:
    trial = int(event["trial"])
    if trial < 1 or trial > 256:
        fail("trial outside 1..256")
    support = int(event["support_count"])
    interior = int(event["interior_variable_count"])
    if support <= 0 or interior < 0 or interior > support:
        fail("invalid support geometry")
    slack = finite(event["true_minimum_safety_slack"])
    if slack <= 0.0:
        fail("true endpoint slack is not positive")
    true_norm = finite(event["true_norm"])
    null_norm = finite(event["true_null_norm"])
    null_energy = None if true_norm <= 0.0 else (null_norm / true_norm) ** 2
    row = dict(event)
    row.update({
        "seed": seed, "side": side, "tau": tau, "t": float(trial),
        "t_norm": (trial - 1) / 255.0, "window": timing_window(trial),
        "theta": finite(event["rotation_angle"]),
        "c": abs(finite(event["residual_cosine"])),
        "one_minus_c": 1.0 - abs(finite(event["residual_cosine"])),
        "x_slack": math.log10(slack),
        "n_boundary_active": support - interior,
        "f_boundary_active": (support - interior) / support,
        "n_support": float(support), "f_interior_support": interior / support,
        "n_null": finite(event["combined_nullity"]), "f_null_energy": null_energy,
    })
    if row["status"] == ACCEPTED:
        if not (0.0 < row["theta"] <= math.pi / 2.0):
            fail("accepted angle outside domain")
        if abs(math.cos(row["theta"]) - row["c"]) > 2.0e-10:
            fail("rotation/cosine identity failed")
    return row


def verify_lineage(root: Path, contract: dict) -> dict[str, str]:
    if contract["document_state"] != "FINAL" or contract["protocol"] != PROTOCOL:
        fail("Q10-WC contract is not final")
    if sha256(root / "PLAN.md").upper() != contract["plan_sha256"]:
        fail("Q10-WC PLAN hash mismatch")
    parent = root.parent / "q10-safety-margin-v1"
    mapping = {
        "parent_contract_sha256": "CONTRACT.json", "parent_plan_sha256": "PLAN.md",
        "parent_result_sha256": "RESULT.md", "parent_status_sha256": "STATUS.json",
        "parent_summary_sha256": "Q10-SM-SUMMARY.json",
    }
    result = {}
    for field, filename in mapping.items():
        actual = sha256(parent / filename)
        if actual.upper() != contract["lineage"][field]:
            fail(f"parent lineage mismatch: {filename}")
        result[filename] = actual
    return result


def load_events(root: Path, stage: str) -> tuple[list[dict], list[dict], dict[str, str]]:
    seeds, directories = STAGES[stage]
    events: list[dict] = []
    manifest: list[dict] = []
    for dirname, directory_seeds in directories:
        directory = root / "qualification" / dirname
        pre = json.loads((directory / "pre-execution.json").read_text())
        execution = json.loads((directory / "execution.json").read_text())
        if pre["protocol"] != PROTOCOL or execution["protocol"] != PROTOCOL:
            fail("receipt protocol mismatch")
        if pre["seeds"] != directory_seeds or execution["audited_states"] != 1024 * len(directory_seeds):
            fail("stage receipt coverage mismatch")
        if pre["scientific_seed_bundles"] != 0 or pre["behavioral_inference"]:
            fail("scope firewall failed")
        for seed in directory_seeds:
            for side in SIDES:
                for tau in TAUS:
                    path = directory / f"seed{seed}-{side}-tau{tau}.json"
                    batch = json.loads(path.read_text())
                    reject_forbidden(batch)
                    if (batch["protocol"] != PROTOCOL or batch["seed"] != seed
                            or batch["side"] != side or int(batch["tau"]) != tau
                            or len(batch["events"]) != 256
                            or batch["drive_rows"] != 16 * batch["post_len"]):
                        fail(f"batch identity or shape mismatch: {path.name}")
                    seen_trials = set()
                    for event in batch["events"]:
                        if event["status"] not in ELIGIBLE:
                            fail(f"non-eligible event status: {event['status']}")
                        trial = int(event["trial"])
                        if trial in seen_trials:
                            fail(f"duplicate trial in {path.name}")
                        seen_trials.add(trial)
                        events.append(derive(event, seed, side, tau))
                    if seen_trials != set(range(1, 257)):
                        fail(f"incomplete trial coverage: {path.name}")
                    manifest.append({"path": str(path.relative_to(root)).replace("\\", "/"),
                                     "sha256": sha256(path)})
    if len(events) != 1024 * len(seeds):
        fail("cumulative event count mismatch")
    keys = {(row["seed"], row["side"], row["tau"], int(row["trial"])) for row in events}
    if len(keys) != len(events):
        fail("duplicate event key")
    return events, manifest, {"expected_seeds": ",".join(map(str, seeds))}


def summary(values: list[float | None]) -> dict:
    finite_values = [finite(value) for value in values if value is not None]
    return {"available": len(finite_values), "missing": len(values) - len(finite_values),
            "quantiles": quantiles(finite_values)}


def grouped_acceptance(events: list[dict], key) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in events:
        groups[str(key(row))].append(row)
    return {name: {"total": len(rows), "accepted": sum(row["status"] == ACCEPTED for row in rows),
                   "accepted_fraction": sum(row["status"] == ACCEPTED for row in rows) / len(rows)}
            for name, rows in sorted(groups.items())}


def association_bundle(rows: list[dict], predictor: str, minimum: int = 2) -> dict:
    return {outcome: spearman(rows, predictor, outcome, minimum)
            for outcome in ("theta", "c", "one_minus_c")}


def trajectory_associations(accepted: list[dict], predictor: str) -> dict:
    entries = []
    for seed in sorted({row["seed"] for row in accepted}):
        for side in SIDES:
            for tau in TAUS:
                rows = [row for row in accepted if row["seed"] == seed and row["side"] == side and row["tau"] == tau]
                entry = {"seed": seed, "side": side, "tau": tau}
                entry.update(spearman(rows, predictor, "theta", 16))
                entries.append(entry)
    valid = [entry["rho"] for entry in entries if entry["status"] == "DEFINED"]
    return {"entries": entries, "valid_trajectories": len(valid),
            "rho_summary": quantiles(valid)}


def leave_one_seed_out(accepted: list[dict], predictor: str) -> list[dict]:
    seeds = sorted({row["seed"] for row in accepted})
    if len(seeds) < 2:
        return []
    result = []
    for seed in seeds:
        entry = {"omitted_seed": seed}
        entry.update(spearman([row for row in accepted if row["seed"] != seed], predictor, "theta"))
        result.append(entry)
    return result


def standardized_ranks(values: list[float]) -> list[float]:
    ranks, _, _ = average_ranks(values)
    mean = math.fsum(ranks) / len(ranks)
    centered = [value - mean for value in ranks]
    variance = math.fsum(value * value for value in centered) / len(centered)
    if variance == 0.0:
        fail("zero variance in model variable")
    scale = math.sqrt(variance)
    return [value / scale for value in centered]


def jacobi_svd_solve(columns: list[list[float]], y: list[float]) -> tuple[list[float], list[float], int, float]:
    n = len(columns)
    m = len(y)
    b = [column[:] for column in columns]
    v = [[1.0 if row == col else 0.0 for col in range(n)] for row in range(n)]
    for _ in range(100):
        changed = False
        for p in range(n - 1):
            for q in range(p + 1, n):
                alpha = math.fsum(value * value for value in b[p])
                beta = math.fsum(value * value for value in b[q])
                gamma = math.fsum(x * z for x, z in zip(b[p], b[q]))
                if alpha == 0.0 or beta == 0.0 or abs(gamma) <= 1.0e-14 * math.sqrt(alpha * beta):
                    continue
                changed = True
                tau = (beta - alpha) / (2.0 * gamma)
                t = math.copysign(1.0, tau) / (abs(tau) + math.sqrt(1.0 + tau * tau))
                c = 1.0 / math.sqrt(1.0 + t * t)
                s = c * t
                bp, bq = b[p], b[q]
                b[p] = [c * x - s * z for x, z in zip(bp, bq)]
                b[q] = [s * x + c * z for x, z in zip(bp, bq)]
                for row in range(n):
                    vp, vq = v[row][p], v[row][q]
                    v[row][p] = c * vp - s * vq
                    v[row][q] = s * vp + c * vq
        if not changed:
            break
    singular = [math.sqrt(max(0.0, math.fsum(value * value for value in column))) for column in b]
    sigma_max = max(singular, default=0.0)
    cutoff = sigma_max * max(m, n) * EPSILON * RANK_MULTIPLIER
    retained = [index for index, sigma in enumerate(singular) if sigma > cutoff]
    coeff = [0.0] * n
    for index in retained:
        scale = math.fsum(value * target for value, target in zip(b[index], y)) / (singular[index] ** 2)
        for row in range(n):
            coeff[row] += v[row][index] * scale
    sigma_min = min((singular[index] for index in retained), default=0.0)
    condition = math.inf if sigma_min == 0.0 else sigma_max / sigma_min
    return coeff, singular, len(retained), condition


def fit_model(rows: list[dict], include_null: bool) -> dict:
    core = ("x_slack", "f_boundary_active", "n_support", "n_null", "t")
    predictors = core + (("f_null_energy",) if include_null else ())
    if include_null and any(row["f_null_energy"] is None for row in rows):
        return {"status": "UNAVAILABLE_NULL_ENERGY_MISSING", "n": len(rows)}
    model_rows = [row for row in rows if all(row[name] is not None for name in predictors)]
    if len(model_rows) != len(rows):
        fail("core model silently lost rows")
    names = ["intercept", *predictors, "seed_9702", "seed_9703", "seed_9704", "seed_9705", "side_L", "tau_16"]
    columns = [[1.0] * len(model_rows)]
    columns.extend(standardized_ranks([finite(row[name]) for row in model_rows]) for name in predictors)
    columns.extend([1.0 if row["seed"] == seed else 0.0 for row in model_rows] for seed in (9702, 9703, 9704, 9705))
    columns.append([1.0 if row["side"] == "L" else 0.0 for row in model_rows])
    columns.append([1.0 if row["tau"] == 16 else 0.0 for row in model_rows])
    y = standardized_ranks([row["theta"] for row in model_rows])
    coeff, singular, rank, condition = jacobi_svd_solve(columns, y)
    predictions = [math.fsum(coeff[col] * columns[col][row] for col in range(len(columns)))
                   for row in range(len(model_rows))]
    residual = math.fsum((target - predicted) ** 2 for target, predicted in zip(y, predictions))
    mean_y = math.fsum(y) / len(y)
    total = math.fsum((target - mean_y) ** 2 for target in y)
    unstable = total == 0.0 or rank < len(columns) or condition > 1.0e10
    return {"status": "NUMERICALLY_UNSTABLE" if unstable else "STABLE_DESCRIPTIVE",
            "n": len(model_rows), "column_names": names,
            "coefficients": {name: value for name, value in zip(names, coeff)},
            "matrix_rank": rank, "column_count": len(columns), "condition_number": condition,
            "r_squared": None if total == 0.0 else 1.0 - residual / total,
            "singular_values": sorted(singular, reverse=True)}


def analyze(root: Path, stage: str) -> dict:
    contract = json.loads((root / "CONTRACT.json").read_text())
    lineage = verify_lineage(root, contract)
    events, manifest, metadata = load_events(root, stage)
    accepted = [row for row in events if row["status"] == ACCEPTED]
    dominated = [row for row in events if row["status"] == DOMINATED]
    status_counts = Counter(row["status"] for row in events)
    predictor_summary = {
        name: {"accepted": summary([row[name] for row in accepted]),
               "dominated": summary([row[name] for row in dominated])}
        for name in PREDICTORS
    }
    pairwise = {name: association_bundle(accepted, name) for name in PREDICTORS}
    trajectories = {name: trajectory_associations(accepted, name) for name in PREDICTORS}
    leave_out = {name: leave_one_seed_out(accepted, name) for name in PREDICTORS}
    timing: dict[str, dict] = {}
    for window, _, _ in WINDOWS:
        for side in SIDES:
            for tau in TAUS:
                rows = [row for row in accepted if row["window"] == window and row["side"] == side and row["tau"] == tau]
                timing[f"{window}|{side}|tau{tau}"] = {
                    "n": len(rows), "theta": summary([row["theta"] for row in rows]),
                    "c": summary([row["c"] for row in rows])}
    undefined = sum(bundle["theta"]["status"] != "DEFINED" for bundle in pairwise.values())
    final_status = ("Q10_WC_VALID__DESCRIPTIVE_ASSOCIATIONS_REPORTED" if undefined == 0
                    else "Q10_WC_VALID__INSUFFICIENT_VARIATION")
    if stage == "stage-a":
        final_status = "Q10_WC_STAGE_A_VALID__DESCRIPTIVE_PIPELINE_QUALIFIED"
    return {
        "protocol": PROTOCOL, "schema_version": 1, "stage": stage, "status": final_status,
        "scope": {"scientific_seed_bundles": 0, "behavioral_inference": False,
                  "causal_inference": False, "direction_claim": False,
                  "future_learning_claim": False, "future_gate_selected": False},
        "lineage_hashes": lineage, "receipt_manifest": manifest, "metadata": metadata,
        "coverage": {"total_events": len(events), "accepted": len(accepted),
                     "dominated": len(dominated), "accepted_fraction": len(accepted) / len(events),
                     "status_counts": dict(sorted(status_counts.items())),
                     "by_seed": grouped_acceptance(events, lambda row: row["seed"]),
                     "by_side": grouped_acceptance(events, lambda row: row["side"]),
                     "by_tau": grouped_acceptance(events, lambda row: row["tau"]),
                     "by_timing_window": grouped_acceptance(events, lambda row: row["window"])},
        "accepted_width": {"theta": summary([row["theta"] for row in accepted]),
                           "c": summary([row["c"] for row in accepted]),
                           "one_minus_c": summary([row["one_minus_c"] for row in accepted])},
        "selection_audit": predictor_summary, "pairwise_associations": pairwise,
        "within_trajectory_associations": trajectories,
        "leave_one_seed_out_associations": leave_out, "timing_windows": timing,
        "models": {"core": fit_model(accepted, False), "null_energy": fit_model(accepted, True)},
        "interpretation_firewall": "DESCRIPTIVE_GEOMETRY_ONLY__NO_CAUSAL_OR_BEHAVIORAL_CLAIM",
    }


def self_test() -> None:
    assert quantiles([1.0, 2.0, 3.0, 4.0])["median"] == 2.5
    rows = [{"x": value, "y": value} for value in (3.0, 1.0, 2.0, 2.0)]
    assert abs(spearman(rows, "x", "y")["rho"] - 1.0) < 1.0e-15
    columns = [[1.0] * 5, [float(value) for value in range(5)]]
    y = [1.0 + 2.0 * value for value in range(5)]
    coeff, _, rank, _ = jacobi_svd_solve(columns, y)
    assert rank == 2 and abs(coeff[0] - 1.0) < 1.0e-10 and abs(coeff[1] - 2.0) < 1.0e-10


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        print("Q10-WC analysis self-test: PASS")
        return
    if len(sys.argv) != 4 or sys.argv[1] not in STAGES:
        fail("usage: analyze_q10_wc.py stage-a|combined ROOT OUTPUT_JSON")
    root = Path(sys.argv[2]).resolve()
    output = Path(sys.argv[3]).resolve()
    result = analyze(root, sys.argv[1])
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "stage": result["stage"],
                      "events": result["coverage"]["total_events"],
                      "accepted": result["coverage"]["accepted"]}, indent=2))


if __name__ == "__main__":
    main()
