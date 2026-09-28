"""Independent Q09 Stage A reviewer; rejects partial or behavioral output."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ALLOWED_STATUS = {
    "LINEAR_AUDIT_VALID__FREEDOM_PRESENT",
    "LINEAR_AUDIT_VALID__CONSTRAINT_DOMINATED",
    "LINEAR_AUDIT_VALID__NUMERICALLY_AMBIGUOUS",
}
FORBIDDEN_WORDS = ("accuracy", "correct", "margin", "probe", "trajectory")


def fail(message: str) -> None:
    raise RuntimeError(message)


def reject_behavior(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if any(word in lowered for word in FORBIDDEN_WORDS):
                fail(f"behavioral field exposed at {path}.{key}")
            reject_behavior(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_behavior(child, f"{path}[{index}]")


def check_replay(path: Path) -> None:
    replay = json.loads(path.read_text())
    snapshot = replay["snapshot"]
    # Snapshot base/target are serialized from Rust f32 values. Re-quantize
    # before widening so this reconstruction matches f64::from(f32) in the
    # audit, rather than treating JSON's shortest decimal as f64 storage.
    base = np.asarray(snapshot["base"], dtype=np.float32).astype(np.float64)
    target = np.asarray(snapshot["target"], dtype=np.float32).astype(np.float64)
    axis = np.asarray(snapshot["axis"], dtype=np.float64)
    permitted = np.asarray(snapshot["permitted"], dtype=bool)
    d = target - base
    interior = np.flatnonzero(permitted & (target != 0.0) & (target != 2.0))
    fixed = np.flatnonzero(permitted & ~((target != 0.0) & (target != 2.0)))
    outside = np.flatnonzero(~permitted)
    if np.any(np.abs(d[outside]) != 0.0):
        fail("replay has displacement outside permitted support")
    rows = np.asarray(replay["scaled_operator"], dtype=np.float64)
    scales = np.asarray(replay["row_scales"], dtype=np.float64)
    if rows.shape[0] != len(scales):
        fail("row-scale dimension mismatch")
    x = d[interior]
    b = np.asarray(replay["targets"], dtype=np.float64)
    if rows.shape[1] != len(interior) or rows.shape[0] != len(b):
        fail("replay operator/target dimension mismatch")
    expected_b = np.zeros(rows.shape[0], dtype=np.float64)
    full = np.asarray(replay["operator"]["rows"], dtype=object)
    fixed_vector = np.zeros_like(d)
    fixed_vector[fixed] = d[fixed]
    expected_b[:-1] = np.asarray(
        [sum(d[index] for index in row) - sum(fixed_vector[index] for index in row)
         for row in full], dtype=np.float64
    )
    expected_b[-1] = np.dot(d - fixed_vector, axis)
    scaled_b = b * scales
    if not np.allclose(b, expected_b, rtol=2e-12, atol=2e-12):
        fail("saved unscaled target differs from independent reconstruction")
    if not np.allclose(rows @ x, scaled_b, rtol=2e-10, atol=2e-10):
        fail("true interior does not satisfy scaled linear constraints")

    u, singular, vt = np.linalg.svd(rows, full_matrices=False)
    sigma_max = float(singular[0]) if singular.size else 0.0
    threshold = sigma_max * max(rows.shape) * np.finfo(np.float64).eps * 1000.0
    rank = int(np.count_nonzero(singular > threshold))
    audit = replay["audit"]
    combined = audit["combined_rank"]
    if combined["rows"] != rows.shape[0] or combined["columns"] != rows.shape[1]:
        fail("saved rank dimensions mismatch")
    if combined["rank"] != rank or combined["nullity"] != rows.shape[1] - rank:
        fail("saved rank differs from independent NumPy reconstruction")
    saved_sigma = np.asarray(combined["singular_values"], dtype=np.float64)
    if len(saved_sigma) != rows.shape[0] or not np.allclose(
        saved_sigma[: len(singular)], singular, rtol=2e-8, atol=2e-10
    ):
        fail("saved singular spectrum differs from independent reconstruction")
    projector = vt[:rank].T @ vt[:rank]
    projected = projector @ x
    saved_star = np.asarray(replay["d_star"], dtype=np.float64)[interior]
    if not np.allclose(projected, saved_star, rtol=3e-8, atol=3e-10):
        fail("saved row-space projection differs from independent reconstruction")
    saved_null = np.asarray(replay["n_true"], dtype=np.float64)[interior]
    if np.linalg.norm(rows @ saved_null) > 2e-8 * max(1.0, np.linalg.norm(rows @ x)):
        fail("saved null component is not annihilated")
    if audit["box_feasibility"] != "NOT_TESTED" or audit["alternative_seq32_equality"] != "NOT_TESTED":
        fail("Q09 deferred gates were presented as tested")


def main() -> None:
    if len(sys.argv) != 2:
        raise RuntimeError("usage: review_q09.py STAGE_A_DIRECTORY")
    out = Path(sys.argv[1]).resolve()
    execution = json.loads((out / "execution.json").read_text())
    raw_stage = execution.get("stage")
    stage = {"A": "A", "B": "B", "stage-a": "A", "stage-b": "B"}.get(raw_stage)
    expected_seeds = [9201] if stage == "A" else [9202, 9203, 9204, 9205] if stage == "B" else None
    normalized_execution = dict(execution)
    normalized_execution["stage"] = stage
    stage_a_execution = {
        "protocol": "Q09-LFA", "schema_version": 1, "stage": "A", "complete": True,
        "audited_states": 1024, "scientific_seed_bundles": 0, "behavioral_inference": False,
        "linear_integrity_valid": True, "box_feasibility": "NOT_TESTED",
        "alternative_seq32_equality": "NOT_TESTED",
    }
    stage_b_execution = {
        "protocol": "Q09-LFA", "schema_version": 1, "stage": "B", "complete": True,
        "audited_states": 5120, "new_audited_states": 4096, "prior_stage_a_states": 1024,
        "scientific_seed_bundles": 0, "behavioral_inference": False,
        "linear_integrity_valid": True, "box_feasibility": "NOT_TESTED",
        "alternative_seq32_equality": "NOT_TESTED",
    }
    if normalized_execution != stage_a_execution and normalized_execution != stage_b_execution:
        fail("execution receipt is incomplete or outside Q09 scope")
    if expected_seeds is None or execution["audited_states"] != (1024 if stage == "A" else 5120):
        fail("unsupported Q09 stage")
    batches = [
        out / (f"{side}-tau{tau}.json" if stage == "A" else f"seed{seed}-{side}-tau{tau}.json")
        for seed in expected_seeds
        for side in ("R", "L")
        for tau in (4, 16)
    ]
    all_events = 0
    for batch_path in batches:
        batch = json.loads(batch_path.read_text())
        post_len = batch["post_len"]
        if batch["seed"] not in expected_seeds or batch["drive_rows"] != 16 * post_len:
            fail(f"bad batch dimensions or seed: {batch_path.name}")
        if batch["combined_rows"] != batch["drive_rows"] + 1:
            fail(f"bad combined row count: {batch_path.name}")
        for result in batch["results"]:
            reject_behavior(result)
            if result["arm"] == "E":
                events = result["events"]
                if len(events) != 256:
                    fail(f"event count mismatch: {batch_path.name}")
                for event in events:
                    all_events += 1
                    if event["status"] not in ALLOWED_STATUS or not event["integrity"]["valid"]:
                        fail(f"invalid event status: {batch_path.name}")
                    if len(event["combined_rank"]["singular_values"]) != batch["combined_rows"]:
                        fail(f"singular spectrum length mismatch: {batch_path.name}")
            elif result["events"]:
                fail("non-audited Z arm contains linear events")
    expected_new_states = 1024 if stage == "A" else 4096
    if all_events != expected_new_states:
        fail(f"audited event count {all_events}, expected {expected_new_states}")
    check_replay(out / "replay-R-tau4-trial1.json")
    pre = json.loads((out / "pre-execution.json").read_text())
    if (pre["scientific_seed_bundles"] != 0 or pre["behavioral_inference"]
            or {"A": "A", "B": "B", "stage-a": "A", "stage-b": "B"}.get(pre.get("stage", "A")) != stage
            or pre.get("seeds", [9201]) != expected_seeds):
        fail("pre-execution scope mismatch")
    print(json.dumps({"status": "VERIFIED", "audited_states": execution["audited_states"],
                      "new_audited_states": all_events, "replay": "VERIFIED_BY_NUMPY",
                      "behavioral_inference": False}, indent=2))


if __name__ == "__main__":
    main()
