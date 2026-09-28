"""Independent reviewer for Q10 continuous Stage 1 receipts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ALLOWED_STATUS = {
    "Q10_STAGE1_VALID__BOUNDED_FREEDOM_PRESENT",
    "Q10_STAGE1_VALID__BOX_CONSTRAINT_DOMINATED",
}
FORBIDDEN = ("accuracy", "margin", "reward", "action", "probe", "trajectory", "correct")
TOL = 2.0e-8


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_behavior(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(word in key.lower() for word in FORBIDDEN):
                fail(f"behavioral field exposed at {path}.{key}")
            reject_behavior(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_behavior(child, f"{path}[{index}]")


def vec(value: object, dtype: np.dtype = np.float64) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if not np.all(np.isfinite(array)):
        fail("non-finite replay vector")
    return array


def direct_drive(operator: dict, values: np.ndarray) -> np.ndarray:
    return np.asarray([sum(values[index] for index in row) for row in operator["rows"]])


def check_replay(path: Path) -> None:
    replay = json.loads(path.read_text())
    snapshot = replay["snapshot"]
    base = vec(snapshot["base"], np.float32).astype(np.float64)
    target = vec(snapshot["target"], np.float32).astype(np.float64)
    permitted = np.asarray(snapshot["permitted"], dtype=bool)
    axis = vec(snapshot["axis"])
    true_d = target - base
    constrained = vec(replay["constrained_displacement"])
    true_null = vec(replay["true_null"])
    alternate_null = vec(replay["alternate_null"])
    alternate_d = constrained + alternate_null
    operator = replay["operator"]
    if len(base) != operator["coordinates"] or len(axis) != len(base):
        fail("replay coordinate dimension mismatch")
    if len(operator["rows"]) != 16 * operator["posts"]:
        fail("operator is not the complete cue-by-MBON operator")
    if np.max(np.abs(true_d - constrained - true_null)) > TOL:
        fail("true displacement decomposition mismatch")
    if np.max(np.abs(alternate_d[~permitted])) > TOL:
        fail("alternate displacement escaped permitted support")
    for index, value in enumerate(base + alternate_d):
        if not np.isfinite(value) or value < 0.0 or value > 2.0:
            fail(f"alternate endpoint outside weight box at {index}")
        true_boundary = target[index] == 0.0 or target[index] == 2.0
        alternate_boundary = value == 0.0 or value == 2.0
        if true_boundary != alternate_boundary:
            fail(f"boundary membership changed at {index}")
        if permitted[index] and not true_boundary and not (0.0 < value < 2.0):
            fail(f"interior endpoint is not strict at {index}")
    drive_true = direct_drive(operator, true_d)
    drive_alt = direct_drive(operator, alternate_d)
    null_drive = direct_drive(operator, alternate_null)
    axis_true = float(np.dot(true_d, axis))
    axis_alt = float(np.dot(alternate_d, axis))
    if np.max(np.abs(drive_alt - drive_true)) > TOL:
        fail("alternate cue-by-MBON drives differ")
    if abs(axis_alt - axis_true) > TOL:
        fail("alternate acquisition-axis displacement differs")
    if np.max(np.abs(null_drive)) > TOL or abs(float(np.dot(alternate_null, axis))) > TOL:
        fail("alternate null is not annihilated")
    if abs(np.linalg.norm(alternate_d) - np.linalg.norm(true_d)) > TOL:
        fail("alternate total norm differs")
    true_norm = np.linalg.norm(true_null)
    alternate_norm = np.linalg.norm(alternate_null)
    if true_norm > 1.0e-12:
        if abs(true_norm - alternate_norm) > TOL:
            fail("alternate residual norm differs")
        cosine = float(np.dot(true_null, alternate_null) / (true_norm * alternate_norm))
        if abs(cosine - replay["event"]["residual_cosine"]) > 1.0e-7:
            fail("saved residual cosine differs from replay")


def expected(stage: str) -> tuple[list[int], int, int]:
    if stage == "stage1-a":
        return [9301], 1024, 1024
    if stage == "stage1-b":
        return [9302, 9303, 9304, 9305], 4096, 5120
    fail(f"unsupported stage {stage}")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: review_q10.py OUTPUT_DIRECTORY")
    out = Path(sys.argv[1]).resolve()
    execution = json.loads((out / "execution.json").read_text())
    stage = execution.get("stage")
    seeds, new_states, cumulative = expected(stage)
    root = out.parents[1]
    contract = json.loads((root / "CONTRACT.json").read_text())
    if contract["status"] != "FROZEN_PRE_QUALIFICATION_CONTRACT":
        fail("Q10 contract is not frozen")
    if sha256(root / "PLAN.md") != contract["plan_sha256"].lower():
        fail("PLAN hash mismatch")
    lineage = contract["lineage"]
    q09 = root.parent / "q09-lfa"
    if sha256(q09 / "PLAN.md") != lineage["parent_q09_plan_sha256"].lower():
        fail("Q09 PLAN lineage changed")
    if sha256(q09 / "CONTRACT.json") != lineage["parent_q09_contract_sha256"].lower():
        fail("Q09 CONTRACT lineage changed")
    if sha256(q09 / "RESULT.md") != lineage["parent_q09_result_sha256"].lower():
        fail("Q09 RESULT lineage changed")
    if sha256(q09 / "STATUS.json") != lineage["parent_q09_status_sha256"].lower():
        fail("Q09 STATUS lineage changed")
    expected_execution = {
        "protocol": "Q10-BG",
        "schema_version": 1,
        "stage": stage,
        "status": execution["status"],
        "complete": True,
        "audited_states": new_states,
        "freedom_events": execution["freedom_events"],
        "scientific_seed_bundles": 0,
        "behavioral_inference": False,
        "box_feasibility": "TESTED_CONTINUOUS_ONLY",
        "sequential_f32_endpoint_equality": "NOT_TESTED",
        "stage2_authorized_by_this_receipt": False,
        "cumulative_audited_states": cumulative,
    }
    if execution != expected_execution:
        if execution != expected_execution:
            fail("execution receipt contains unexpected fields")
    if stage == "stage1-b":
        if execution.get("cumulative_audited_states", cumulative) != cumulative:
            fail("Stage 1B cumulative count mismatch")
    all_events = 0
    statuses: set[str] = set()
    for seed in seeds:
        for side in ("R", "L"):
            for tau in (4, 16):
                batch_path = out / f"seed{seed}-{side}-tau{tau}.json"
                batch = json.loads(batch_path.read_text())
                reject_behavior(batch)
                if batch["protocol"] != "Q10-BG" or batch["seed"] != seed:
                    fail(f"bad batch identity: {batch_path.name}")
                if batch["drive_rows"] != 16 * batch["post_len"]:
                    fail(f"incomplete drive rows: {batch_path.name}")
                events = batch["events"]
                if len(events) != 256:
                    fail(f"event count mismatch: {batch_path.name}")
                for event in events:
                    all_events += 1
                    statuses.add(event["status"])
                    if event["status"] not in ALLOWED_STATUS:
                        fail(f"invalid event status: {batch_path.name}")
                    if event["f32_commit_status"] != "NOT_TESTED":
                        fail("Stage 1 presented f32 commitment as tested")
                    for key in (
                        "cue_drive_max_abs_error", "normalized_cue_drive_error",
                        "axis_displacement_error", "normalized_axis_error",
                        "null_annihilation_max_abs", "normalized_null_annihilation_error",
                        "total_norm_error", "normalized_total_norm_error",
                        "reconstruction_error", "normalized_reconstruction_error",
                    ):
                        if not np.isfinite(event[key]) or event[key] > TOL:
                            fail(f"integrity field failed: {batch_path.name}:{key}")
                    if event["outside_support_changes"] != 0 or event["new_boundary_memberships"] != 0:
                        fail("support or boundary integrity failed")
                    if event["bounds_violation_count"] != 0:
                        fail("box feasibility failed")
    if all_events != new_states:
        fail(f"audited events {all_events}, expected {new_states}")
    if "Q10_STAGE1_VALID__BOUNDED_FREEDOM_PRESENT" not in statuses:
        fail("no bounded non-identity freedom was demonstrated")
    check_replay(out / "replay-R-tau4-trial1.json")
    pre = json.loads((out / "pre-execution.json").read_text())
    if pre["scientific_seed_bundles"] != 0 or pre["behavioral_inference"]:
        fail("pre-execution scope includes scientific work")
    if pre["seeds"] != seeds or pre["stage"] != stage:
        fail("pre-execution seed or stage mismatch")
    print(json.dumps({
        "status": "VERIFIED",
        "stage": stage,
        "new_audited_states": all_events,
        "cumulative_audited_states": cumulative,
        "event_statuses": sorted(statuses),
        "replay": "VERIFIED_BY_NUMPY",
        "behavioral_inference": False,
    }, indent=2))


if __name__ == "__main__":
    main()
