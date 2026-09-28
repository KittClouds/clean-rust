"""Independent standard-library reviewer for Q10-SM Stage 1 safety receipts."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

PROTOCOL = "Q10-SM"
ALLOWED_STATUS = {
    "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT",
    "Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED",
}
FORBIDDEN = ("accuracy", "reward", "action", "probe", "behavior", "correct")
TOL = 2.0e-8
RESERVE_ULPS = 32


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_scope(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(word in key.lower() for word in FORBIDDEN):
                fail(f"forbidden scientific field at {path}.{key}")
            reject_scope(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_scope(child, f"{path}[{index}]")


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", value))[0]


def nextafter32(value: float, toward_lower: bool) -> float:
    value = f32(value)
    if not math.isfinite(value) or value <= 0.0 or value >= 2.0:
        fail("nextafter32 received a non-interior value")
    return from_bits(bits(value) - 1 if toward_lower else bits(value) + 1)


def safety_data(reference: float) -> tuple[float, float, float, float]:
    down = nextafter32(reference, True)
    up = nextafter32(reference, False)
    down_ulp = f32(reference) - down
    up_ulp = up - f32(reference)
    return (32.0 * down_ulp, 2.0 - 32.0 * up_ulp, down_ulp, up_ulp)


def steps(value: float, toward_lower: bool) -> int:
    current = f32(value)
    count = 0
    while count < RESERVE_ULPS:
        current = nextafter32(current, toward_lower)
        if not math.isfinite(current) or current <= 0.0 or current >= 2.0:
            break
        count += 1
    return count


def vec(value: object) -> list[float]:
    if not isinstance(value, list):
        fail("replay vector is not a list")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        fail("non-finite replay vector")
    return result


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def norm(a: list[float]) -> float:
    return math.sqrt(dot(a, a))


def max_abs(a: list[float]) -> float:
    return max((abs(x) for x in a), default=0.0)


def direct_drive(operator: dict, values: list[float]) -> list[float]:
    return [sum(values[index] for index in row) for row in operator["rows"]]


def check_replay(path: Path) -> None:
    replay = json.loads(path.read_text())
    snapshot = replay["snapshot"]
    base32 = [f32(float(value)) for value in snapshot["base"]]
    target32 = [f32(float(value)) for value in snapshot["target"]]
    base = [float(value) for value in base32]
    target = [float(value) for value in target32]
    permitted = [bool(value) for value in snapshot["permitted"]]
    axis = vec(snapshot["axis"])
    true_d = [t - b for t, b in zip(target, base)]
    constrained = vec(replay["constrained_displacement"])
    true_null = vec(replay["true_null"])
    alternate_null = vec(replay["alternate_null"])
    alternate_d = [c + z for c, z in zip(constrained, alternate_null)]
    operator = replay["operator"]
    if len(base) != operator["coordinates"] or len(axis) != len(base):
        fail("replay coordinate dimension mismatch")
    if len(operator["rows"]) != 16 * operator["posts"]:
        fail("operator is not complete cue-by-MBON")
    if max_abs([t - c - z for t, c, z in zip(true_d, constrained, true_null)]) > TOL:
        fail("true displacement decomposition mismatch")
    endpoint = [b + d for b, d in zip(base, alternate_d)]
    if max_abs([d for d, allowed in zip(alternate_d, permitted) if not allowed]) > TOL:
        fail("alternate displacement escaped permitted support")
    interior = [allowed and bits(t) not in (bits(0.0), bits(2.0))
                for allowed, t in zip(permitted, target32)]
    for index, value in enumerate(endpoint):
        if not math.isfinite(value) or value < 0.0 or value > 2.0:
            fail(f"alternate endpoint outside weight box at {index}")
        true_lower = bits(target32[index]) == bits(0.0)
        true_upper = bits(target32[index]) == bits(2.0)
        committed = f32(value)
        alt_lower = bits(committed) == bits(0.0)
        alt_upper = bits(committed) == bits(2.0)
        if true_lower != alt_lower or true_upper != alt_upper:
            fail(f"continuous/f32 boundary membership changed at {index}")
        if interior[index]:
            low, high, _, _ = safety_data(target32[index])
            if value < low or value > high:
                fail(f"continuous safety reserve failed at {index}")
            if steps(committed, True) < RESERVE_ULPS or steps(committed, False) < RESERVE_ULPS:
                fail(f"committed safety capacity failed at {index}")
    drive_true = direct_drive(operator, true_d)
    drive_alt = direct_drive(operator, alternate_d)
    null_drive = direct_drive(operator, alternate_null)
    if max_abs([a - t for a, t in zip(drive_alt, drive_true)]) > TOL:
        fail("alternate cue-by-MBON drives differ")
    if abs(dot([a - t for a, t in zip(alternate_d, true_d)], axis)) > TOL:
        fail("alternate acquisition-axis displacement differs")
    if max_abs(null_drive) > TOL or abs(dot(alternate_null, axis)) > TOL:
        fail("alternate null is not annihilated")
    if abs(norm(alternate_d) - norm(true_d)) > TOL:
        fail("alternate total norm differs")
    if norm(true_null) > 1.0e-12 and abs(norm(true_null) - norm(alternate_null)) > TOL:
        fail("alternate residual norm differs")


def expected(stage: str) -> tuple[list[int], int, int]:
    if stage == "stage1-a":
        return [9401], 1024, 1024
    if stage == "stage1-b":
        return [9402, 9403, 9404, 9405], 4096, 5120
    fail(f"unsupported stage {stage}")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: review_q10_sm.py OUTPUT_DIRECTORY")
    out = Path(sys.argv[1]).resolve()
    execution = json.loads((out / "execution.json").read_text())
    stage = execution.get("stage")
    seeds, new_states, cumulative = expected(stage)
    root = out.parents[1]
    contract = json.loads((root / "CONTRACT.json").read_text())
    if contract["status"] != "FROZEN_PRE_QUALIFICATION_CONTRACT":
        fail("Q10-SM contract is not frozen")
    if sha256(root / "PLAN.md") != contract["plan_sha256"].lower():
        fail("PLAN hash mismatch")
    if contract["f32_safety_reserve"]["reserve_ulps_each_direction"] != RESERVE_ULPS:
        fail("reserve mismatch")
    lineage = contract["lineage"]
    parent = root.parent / "q10-bounded-geometry-v1"
    for field, filename in (("parent_contract_sha256", "CONTRACT.json"),
                            ("parent_plan_sha256", "PLAN.md"),
                            ("parent_result_sha256", "RESULT.md"),
                            ("parent_status_sha256", "STATUS.json")):
        if sha256(parent / filename) != lineage[field].lower():
            fail(f"Q10-BG lineage changed: {filename}")
    expected_execution = {
        "protocol": PROTOCOL, "schema_version": 1, "stage": stage,
        "status": execution["status"], "complete": True,
        "audited_states": new_states, "freedom_events": execution["freedom_events"],
        "cumulative_audited_states": cumulative, "scientific_seed_bundles": 0,
        "behavioral_inference": False,
        "box_feasibility": "TESTED_CONTINUOUS_WITH_F32_SAFETY_RESERVE",
        "sequential_f32_endpoint_equality": "NOT_TESTED",
        "stage2_authorized_by_this_receipt": False, "reserve_ulps": RESERVE_ULPS,
    }
    if execution != expected_execution:
        fail("execution receipt contains unexpected fields")
    all_events = 0
    statuses: set[str] = set()
    for seed in seeds:
        for side in ("R", "L"):
            for tau in (4, 16):
                batch_path = out / f"seed{seed}-{side}-tau{tau}.json"
                batch = json.loads(batch_path.read_text())
                reject_scope(batch)
                if batch["protocol"] != PROTOCOL or batch["seed"] != seed:
                    fail(f"bad batch identity: {batch_path.name}")
                if batch["drive_rows"] != 16 * batch["post_len"] or len(batch["events"]) != 256:
                    fail(f"batch shape mismatch: {batch_path.name}")
                for event in batch["events"]:
                    all_events += 1
                    statuses.add(event["status"])
                    if event["status"] not in ALLOWED_STATUS:
                        fail(f"invalid event status: {batch_path.name}")
                    accepted = event["status"].endswith("F32_SAFE_FREEDOM_PRESENT")
                    expected_commit = (
                        "SAFETY_AUDITED_ONLY"
                        if event["exhaustion_status"] == "ACCEPTED"
                        else "NOT_CONSTRUCTED"
                    )
                    if event["f32_commit_status"] != expected_commit:
                        fail("unexpected f32 diagnostic status")
                    numeric = ("cue_drive_max_abs_error", "normalized_cue_drive_error",
                               "axis_displacement_error", "normalized_axis_error",
                               "null_annihilation_max_abs", "normalized_null_annihilation_error",
                               "total_norm_error", "normalized_total_norm_error",
                               "reconstruction_error", "normalized_reconstruction_error",
                               "true_minimum_safety_slack", "continuous_minimum_down_surplus",
                               "continuous_minimum_up_surplus", "continuous_minimum_down_surplus_ulps",
                               "continuous_minimum_up_surplus_ulps", "minimum_safety_slack",
                               "f32_minimum_safety_slack", "f32_cue_drive_drift", "f32_axis_drift",
                               "f32_total_norm_drift", "f32_storage_displacement_drift",
                               "f32_residual_cosine_drift")
                    if not all(math.isfinite(float(event[key])) for key in numeric):
                        fail(f"nonfinite event field: {batch_path.name}")
                    if event["outside_support_changes"] != 0 or event["new_boundary_memberships"] != 0:
                        fail("support or continuous boundary integrity failed")
                    if event["lower_boundary_membership_difference"] != 0 or event["upper_boundary_membership_difference"] != 0:
                        fail("continuous lower/upper boundary integrity failed")
                    if event["bounds_violation_count"] != 0:
                        fail("continuous box feasibility failed")
                    if accepted:
                        if event["f32_safety_violation_count"] != 0 or event["f32_boundary_membership_symmetric_difference"] != 0:
                            fail("committed f32 safety or boundary failed")
                        if event["f32_lower_boundary_membership_difference"] != 0 or event["f32_upper_boundary_membership_difference"] != 0:
                            fail("committed f32 lower/upper boundary failed")
                        if event["f32_minimum_down_steps_capped"] < RESERVE_ULPS or event["f32_minimum_up_steps_capped"] < RESERVE_ULPS:
                            fail("committed f32 capacity below reserve")
                        if event["residual_cosine"] >= 1.0 - 1.0e-8:
                            fail("accepted event is identity")
    if all_events != new_states:
        fail(f"audited events {all_events}, expected {new_states}")
    if not statuses.intersection(ALLOWED_STATUS):
        fail("no valid Stage 1 status")
    check_replay(out / "replay-R-tau4-trial1.json")
    pre = json.loads((out / "pre-execution.json").read_text())
    if pre["scientific_seed_bundles"] != 0 or pre["behavioral_inference"]:
        fail("pre-execution scope includes scientific work")
    if pre["seeds"] != seeds or pre["stage"] != stage:
        fail("pre-execution seed or stage mismatch")
    print(json.dumps({"status": "VERIFIED", "stage": stage,
                      "new_audited_states": all_events,
                      "cumulative_audited_states": cumulative,
                      "event_statuses": sorted(statuses),
                      "replay": "VERIFIED_BY_STDLIB_F32",
                      "behavioral_inference": False}, indent=2))


if __name__ == "__main__":
    main()
