"""Read-only constraint-space audit for MAT1-R1's 61 two-invalid pairs."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_exclusive(path: Path, text: str) -> None:
    require(not path.exists(), f"CG1 refuses overwrite: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"CG1 orphan temporary file: {temporary}")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def vector(state: dict) -> list[float]:
    signed = state["signed_geometry"]
    return [
        float(signed["axis_debt"]),
        float(signed["norm_debt"]),
        *[float(x) for x in signed["linear_drive_debt"]],
    ]


def delta(left: list[float], right: list[float]) -> list[float]:
    return [a - b for a, b in zip(left, right)]


def max_abs(values: list[float]) -> float:
    return max((abs(x) for x in values), default=0.0)


def l2(values: list[float]) -> float:
    return math.sqrt(math.fsum(x * x for x in values))


def cosine(left: list[float], right: list[float]) -> float | None:
    den = l2(left) * l2(right)
    return None if den == 0.0 else math.fsum(a * b for a, b in zip(left, right)) / den


def toward_zero_cosine(change: float, current: float) -> float | None:
    needed = -current
    if change == 0.0 or needed == 0.0:
        return None
    return 1.0 if change * needed > 0.0 else (-1.0 if change * needed < 0.0 else 0.0)


def excess(geometry: dict, thresholds: dict) -> dict:
    return {
        "axis": max(0.0, float(geometry["axis_normalized_error"]) - thresholds["axis"]),
        "norm": max(0.0, float(geometry["norm_normalized_error"]) - thresholds["norm"]),
        "linear": max(0.0, float(geometry["cue_linear_normalized_error"]) - thresholds["linear"]),
    }


def gate_role(s: float, a: float, b: float, pair: float, tol: float = 1e-15) -> str:
    if s <= tol:
        return "NOT_VIOLATED_AT_S"
    reduces = [label for label, value in (("A", a), ("B", b)) if value < s - tol]
    if pair > tol:
        return "NOT_CROSSED_BY_PAIR"
    if not reduces:
        return "PAIR_ONLY_CROSSING"
    if len(reduces) == 2:
        return "BOTH_MOVE_TOWARD_FACE_AND_PAIR_CROSSES"
    return f"{reduces[0]}_MOVES_TOWARD_FACE_AND_PAIR_CROSSES"


def run() -> None:
    contract = read_json(ROOT / "CONTRACT.json")
    for binding in contract["parent_bindings"]:
        path = REPO / str(binding["path"])
        require(path.exists(), f"CG1 missing parent: {path}")
        require(digest(path) == str(binding["sha256"]).upper(), f"CG1 parent drift: {binding['label']}")

    pf5 = read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    gates = pf5["geometry"]["final_da2_gates"]
    thresholds = {
        "axis": float(gates["axis_normalized_abs"]),
        "norm": float(gates["norm_normalized_abs"]),
        "linear": float(gates["cue_linear_normalized_abs"]),
    }
    source_path = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-mat1-r1-v1/qualification/materialized-pairs.jsonl"
    source = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    source = [r for r in source if r["component_geometry_class"] == "BOTH_COMPONENTS_INVALID"]
    require(len(source) == 61, f"CG1 two-invalid cohort drift: {len(source)}")

    observations = []
    face_counts = Counter()
    failure_patterns = Counter()
    max_residual = {"axis": 0.0, "norm": 0.0, "linear": 0.0}
    for record in source:
        states = record["states"]
        s = vector(states["invalid_search"])
        a = vector(states["single_a"])
        b = vector(states["single_b"])
        pair = vector(states["pair_ab"])
        da = delta(a, s)
        db = delta(b, s)
        dp = delta(pair, s)
        additive_residual = delta(dp, [x + y for x, y in zip(da, db)])
        max_residual["axis"] = max(max_residual["axis"], abs(additive_residual[0]))
        max_residual["norm"] = max(max_residual["norm"], abs(additive_residual[1]))
        max_residual["linear"] = max(max_residual["linear"], max_abs(additive_residual[2:]))

        ex_s = excess(states["invalid_search"]["geometry"], thresholds)
        ex_a = excess(states["single_a"]["geometry"], thresholds)
        ex_b = excess(states["single_b"]["geometry"], thresholds)
        ex_pair = excess(states["pair_ab"]["geometry"], thresholds)
        roles = {
            gate: gate_role(ex_s[gate], ex_a[gate], ex_b[gate], ex_pair[gate])
            for gate in ("axis", "norm", "linear")
        }
        for gate, role in roles.items():
            face_counts[f"{gate}:{role}"] += 1

        failed_a = tuple(record["component_gate_signatures"]["single_a"])
        failed_b = tuple(record["component_gate_signatures"]["single_b"])
        failure_pattern = "SAME_FAILED_GATES" if failed_a == failed_b else "DIFFERENT_FAILED_GATES"
        failure_patterns[failure_pattern] += 1
        observations.append({
            "case": record["case"],
            "pair_domain_index": int(record["pair_domain_index"]),
            "failed_gates": {"A": list(failed_a), "B": list(failed_b)},
            "failure_pattern": failure_pattern,
            "constraint_vectors": {"S": s, "A": a, "B": b, "AB": pair},
            "action_vectors": {"A_from_S": da, "B_from_S": db, "AB_from_S": dp},
            "additive_residual": additive_residual,
            "additivity_metrics": {
                "max_abs_axis": abs(additive_residual[0]),
                "max_abs_norm": abs(additive_residual[1]),
                "max_abs_linear": max_abs(additive_residual[2:]),
            },
            "gate_excess": {"S": ex_s, "A": ex_a, "B": ex_b, "AB": ex_pair},
            "face_roles": roles,
            "direction_to_zero": {
                "axis_A": toward_zero_cosine(da[0], s[0]),
                "axis_B": toward_zero_cosine(db[0], s[0]),
                "norm_A": toward_zero_cosine(da[1], s[1]),
                "norm_B": toward_zero_cosine(db[1], s[1]),
                "linear_A": cosine(da[2:], [-x for x in s[2:]]),
                "linear_B": cosine(db[2:], [-x for x in s[2:]]),
            },
        })

    output = ROOT / "qualification"
    output.mkdir(parents=True, exist_ok=True)
    observations_path = output / "constraint-observations.jsonl"
    execution_path = output / "execution.json"
    write_exclusive(observations_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in observations))
    execution = {
        "identity": contract["identity"],
        "protocol": contract["protocol"],
        "scope": "derived_read_only_constraint_geometry_audit",
        "source_two_invalid_pairs": len(observations),
        "final_pair_validity_required": True,
        "thresholds": thresholds,
        "failure_patterns": dict(sorted(failure_patterns.items())),
        "face_role_counts": dict(sorted(face_counts.items())),
        "max_additivity_residual": max_residual,
        "observations_sha256": digest(observations_path),
        "checks_passed": True,
        "causal_allocation": False,
    }
    write_exclusive(execution_path, json.dumps(execution, indent=2, sort_keys=True) + "\n")
    print(json.dumps(execution, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    run()
