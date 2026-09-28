"""RH1-Q0 canonical-runtime and RH1-AC authority-coverage qualification.

This is qualification-only.  It does not run the RH1 factorial, replay a
learner, consume scientific seeds, or authorize behavioral work.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import common_runtime as CQ


ROOT = Path(__file__).resolve().parents[1]
RMT_ROOT = CQ.RMT_ROOT
OUT_ROOT = ROOT / "qualification/rh1-q0-ac"


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def f32_add(left: float, right: float) -> float:
    return f32(f32(left) + f32(right))


def f32_mul(left: float, right: float) -> float:
    return f32(f32(left) * f32(right))


def tie_hash(mapping: dict[int, int] | Iterable[tuple[int, int]]) -> str:
    return hashlib.sha256(b"rh1-tie-v1\0" + CQ.canonical_bytes(mapping)).hexdigest().upper()


def commit_fixture(
    mapping: dict[int, int] | Iterable[tuple[int, int]],
    base: tuple[float, ...],
    increments: dict[tuple[int, int], float],
) -> tuple[float, ...]:
    """Commit a tiny deterministic model in canonical coordinate order."""
    values = [f32(value) for value in base]
    for coordinate, choice in CQ.canonical_state(mapping):
        delta = increments.get((coordinate, choice), 0.0)
        slot = coordinate % len(values)
        values[slot] = f32_add(values[slot], delta)
    return tuple(values)


def sequential_readout(weights: tuple[float, ...], cues: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
    outputs: list[float] = []
    for cue in cues:
        accumulator = 0.0
        for weight, input_value in zip(weights, cue):
            accumulator = f32_add(accumulator, f32_mul(weight, input_value))
        outputs.append(accumulator)
    return tuple(outputs)


def geometry_metrics(
    committed: tuple[float, ...],
    baseline: tuple[float, ...],
    axis: tuple[float, ...],
    cues: tuple[tuple[float, ...], ...],
) -> dict[str, Any]:
    displacement = tuple(float(value) - float(base) for value, base in zip(committed, baseline))
    axis_projection = sum(delta * component for delta, component in zip(displacement, axis))
    norm = math.sqrt(sum(delta * delta for delta in displacement))
    return {
        "axis_projection": axis_projection,
        "l2_norm": norm,
        "linear_drive": list(sequential_readout(committed, cues)),
    }


def run_q0() -> dict[str, Any]:
    left_visit = [(91, 2), (17, -4), (43, 0)]
    right_visit = [(43, 0), (91, 2), (17, -4)]
    baseline = tuple(f32(value) for value in (0.125, -0.25, 0.5, 0.75, -1.0, 1.25, -1.5, 1.75))
    increments = {
        (17, -4): 0.03125,
        (43, 0): 0.0,
        (91, 2): -0.0625,
    }
    cues = (
        tuple(f32(value) for value in (0.25, -0.5, 0.75, -1.0, 1.25, -1.5, 1.75, -2.0)),
        tuple(f32(value) for value in (-0.375, 0.625, -0.875, 1.125, -1.375, 1.625, -1.875, 2.125)),
    )
    axis = tuple(f32(value) for value in (1.0, -1.0, 0.5, -0.5, 0.25, -0.25, 0.125, -0.125))
    left = dict(left_visit)
    right = dict(right_visit)
    canonical_left = CQ.canonical_state(left)
    canonical_right = CQ.canonical_state(right)
    committed_left = commit_fixture(left, baseline, increments)
    committed_right = commit_fixture(right, baseline, increments)
    readout_left = sequential_readout(committed_left, cues)
    readout_right = sequential_readout(committed_right, cues)
    metrics_left = geometry_metrics(committed_left, baseline, axis, cues)
    metrics_right = geometry_metrics(committed_right, baseline, axis, cues)
    checks = {
        "canonical_state_equal": canonical_left == canonical_right,
        "canonical_bytes_equal": CQ.canonical_bytes(left) == CQ.canonical_bytes(right),
        "state_identity_equal": CQ.state_identity(left) == CQ.state_identity(right),
        "tie_hash_equal": tie_hash(left) == tie_hash(right),
        "committed_bytes_equal": committed_left == committed_right,
        "sequential_f32_readout_equal": readout_left == readout_right,
        "geometry_metrics_equal": metrics_left == metrics_right,
    }
    CQ.require(all(checks.values()), "RH1-Q0 canonical runtime invariant failed")
    return {
        "status": "RH1_Q0_CANONICAL_RUNTIME_QUALIFIED_FIXTURE_ONLY",
        "checks": checks,
        "canonical_state": [list(item) for item in canonical_left],
        "state_identity": CQ.state_identity(left),
        "tie_hash": tie_hash(left),
        "sequential_f32_readout": list(readout_left),
        "geometry_metrics": metrics_left,
        "fixture_scope": "synthetic canonical commit and sequential-f32 readout; no learner replay",
    }


def load_detailed_authority() -> dict[tuple[str, int, int], dict[str, Any]]:
    observations: dict[tuple[str, int, int], dict[str, Any]] = {}
    with (RMT_ROOT / "moves.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            move = json.loads(line)
            key = (str(move["endpoint"]), int(move["set_index"]), int(move["coordinate"]))
            item = observations.setdefault(key, {
                "observed_steps": set(),
                "helpful_steps": set(),
                "helpful_rows": set(),
                "raw_rows": set(),
                "raw_rows_by_step": {},
            })
            step = int(move["step"])
            raw_rows = {int(row) for row in move.get("raw_rows", [])}
            helpful_rows = {int(row) for row in move.get("helpful_rows", [])}
            item["observed_steps"].add(step)
            item["helpful_steps"].update([step] if helpful_rows else [])
            item["helpful_rows"].update(helpful_rows)
            item["raw_rows"].update(raw_rows)
            item["raw_rows_by_step"].setdefault(step, set()).update(raw_rows)
    return observations


def authority_record(observation: dict[str, Any] | None) -> dict[str, Any]:
    expected = set(CQ.AUTHORITY_STEPS)
    if observation is None:
        return {
            "coverage_tier": "UNKNOWN",
            "observed_prefixes": [],
            "helpful_prefixes": [],
            "nonhelpful_prefixes": [],
            "unknown_prefixes": sorted(expected),
            "raw_row_count": 0,
            "row_authority_coverage": None,
            "minimum_helpful_prefix": None,
            "ranking_features_complete": False,
        }
    observed = set(observation["observed_steps"])
    helpful = set(observation["helpful_steps"])
    unknown = expected - observed
    nonhelpful = observed - helpful
    raw_rows = set(observation["raw_rows"])
    expected_row_steps = len(raw_rows) * len(expected)
    observed_row_steps = sum(len(set(observation["raw_rows_by_step"].get(step, set())) & raw_rows) for step in expected)
    row_coverage = observed_row_steps / expected_row_steps if expected_row_steps else None
    complete = not unknown and (row_coverage is None or row_coverage == 1.0)
    tier = "MEASURED_COMPLETE" if complete else "MEASURED_PARTIAL"
    min_helpful = min((abs(step) for step in helpful), default=None)
    return {
        "coverage_tier": tier,
        "observed_prefixes": sorted(observed),
        "helpful_prefixes": sorted(helpful),
        "nonhelpful_prefixes": sorted(nonhelpful),
        "unknown_prefixes": sorted(unknown),
        "raw_row_count": len(raw_rows),
        "row_authority_coverage": row_coverage,
        "minimum_helpful_prefix": min_helpful,
        "ranking_features_complete": complete,
    }


def run_ac() -> dict[str, Any]:
    common = CQ.qualify()
    groups = CQ.load_groups()
    observations = load_detailed_authority()
    records: list[dict[str, Any]] = []
    tier_counts: Counter[str] = Counter()
    complete_counts = Counter()
    aggregate = Counter()
    coverage_values: list[float] = []
    for group in groups:
        group_records = []
        for coordinate in group["coordinates"]:
            key = (group["endpoint"], group["set_index"], coordinate)
            record = authority_record(observations.get(key))
            record["coordinate"] = coordinate
            group_records.append(record)
            tier_counts[record["coverage_tier"]] += 1
            complete_counts["complete" if record["ranking_features_complete"] else "incomplete"] += 1
            aggregate["observed_prefixes"] += len(record["observed_prefixes"])
            aggregate["helpful_prefixes"] += len(record["helpful_prefixes"])
            aggregate["nonhelpful_prefixes"] += len(record["nonhelpful_prefixes"])
            aggregate["unknown_prefixes"] += len(record["unknown_prefixes"])
            if record["row_authority_coverage"] is not None:
                coverage_values.append(float(record["row_authority_coverage"]))
        records.append({
            "identity": group["identity"],
            "coordinates_total": group["coordinates_total"],
            "authority_records": group_records,
            "unknown_coordinate_fraction": sum(item["coverage_tier"] == "UNKNOWN" for item in group_records) / len(group_records),
            "complete_feature_fraction": sum(item["ranking_features_complete"] for item in group_records) / len(group_records),
        })
    total_coordinates = sum(len(group["coordinates"]) for group in groups)
    summary = {
        "status": "RH1_AC_AUTHORITY_COVERAGE_AUDIT_COMPLETE",
        "parent_qualification_status": common["status"],
        "groups": len(groups),
        "cohorts": common["cohorts"],
        "total_endpoint_coordinate_pairs": total_coordinates,
        "coverage_tiers": dict(sorted(tier_counts.items())),
        "ranking_feature_completeness": dict(sorted(complete_counts.items())),
        "authority_arm_gate": "ALL_COORDINATE_PREFIX_AND_ROW_COVERAGE_COMPLETE",
        "authority_arm_ready": complete_counts["complete"] == total_coordinates,
        "authority_arm_block_reason": "partial prefix or row-level authority is not promoted to measured authority",
        "unknown_coordinate_fraction": complete_counts["unknown"] / total_coordinates if total_coordinates else 0.0,
        "aggregate_prefix_counts": dict(aggregate),
        "row_authority_coverage": {
            "minimum": min(coverage_values) if coverage_values else None,
            "maximum": max(coverage_values) if coverage_values else None,
            "mean": sum(coverage_values) / len(coverage_values) if coverage_values else None,
            "records_with_row_coverage": len(coverage_values),
        },
        "missing_is_unknown": True,
        "authority_ranking_interpretation": "endpoint-coordinate coverage is complete; prefix and row-level completeness remain separately reported",
        "scope": {
            "measured_factorial_started": False,
            "scientific_seed_bundles": 0,
            "behavioral_probe": False,
            "dh08b_authorized": False,
        },
        "groups_detail": records,
    }
    return summary


def write_outputs() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    q0 = run_q0()
    ac = run_ac()
    result = {"protocol": "Q10-PF6-RH1-Q0-AC", "q0": q0, "ac": ac}
    (OUT_ROOT / "REPORT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# RH1-Q0 / RH1-AC qualification report",
        "",
        "Qualification-only canonical-runtime fixture and authority-coverage audit.",
        "",
        f"Q0 status: `{q0['status']}`.",
        f"Q0 checks: `{json.dumps(q0['checks'], sort_keys=True)}`.",
        f"AC status: `{ac['status']}`.",
        f"Groups: {ac['groups']}; endpoint-coordinate pairs: {ac['total_endpoint_coordinate_pairs']}.",
        f"Coverage tiers: `{json.dumps(ac['coverage_tiers'], sort_keys=True)}`.",
        f"Ranking-feature completeness: `{json.dumps(ac['ranking_feature_completeness'], sort_keys=True)}`.",
        f"Authority arm ready under strict gate: `{ac['authority_arm_ready']}`.",
        f"Unknown-coordinate fraction: {ac['unknown_coordinate_fraction']:.6f}.",
        f"Row-authority coverage summary: `{json.dumps(ac['row_authority_coverage'], sort_keys=True)}`.",
        "",
        "Q0 uses a synthetic fixture for canonical commit and sequential-f32 invariance; it is not learner replay.",
        "Partial prefix/row authority is not promoted to measured authority; the authority arm is gated pending a revised coverage-qualified identity.",
        "RH1 measured factorial execution, scientific seeds, behavioral probes, and DH08B remain unstarted.",
    ]
    (OUT_ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = {
        "protocol": "Q10-PF6-RH1-Q0-AC",
        "status": "QUALIFICATION_COMPLETE_AUTHORITY_ARM_BLOCKED_NO_MEASURED_FACTORIAL",
        "report_sha256": CQ.digest(OUT_ROOT / "REPORT.json"),
        "q0_status": q0["status"],
        "ac_status": ac["status"],
        "authority_arm_ready": ac["authority_arm_ready"],
        "measured_factorial_started": False,
        "scientific_seed_bundles": 0,
        "behavioral_probe": False,
        "dh08b_authorized": False,
    }
    (OUT_ROOT / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status["status"], "q0": q0["status"], "ac": ac["status"], "coverage_tiers": ac["coverage_tiers"]}, indent=2))


if __name__ == "__main__":
    write_outputs()
