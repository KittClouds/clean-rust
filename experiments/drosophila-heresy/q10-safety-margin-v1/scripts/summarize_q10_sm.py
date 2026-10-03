"""Reproducible standard-library summary for sealed Q10-SM engineering receipts."""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    values = sorted(values)
    result: dict[str, float] = {}
    for label, fraction in (("min", 0.0), ("q25", 0.25), ("median", 0.5), ("q75", 0.75), ("max", 1.0)):
        position = fraction * (len(values) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        weight = position - lower
        result[label] = values[lower] * (1.0 - weight) + values[upper] * weight
    return result


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: summarize_q10_sm.py Q10_SM_ROOT OUTPUT_JSON")
    root = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    events: list[dict] = []
    by_seed: Counter[str] = Counter()
    for directory in (root / "qualification" / "stage1-a-9401", root / "qualification" / "stage1-b-9402-9405"):
        for path in sorted(directory.glob("seed*.json")):
            batch = json.loads(path.read_text())
            for event in batch["events"]:
                event = dict(event)
                event["seed"] = batch["seed"]
                events.append(event)
                by_seed[str(batch["seed"])] += 1
    accepted = [event for event in events if event["status"].endswith("F32_SAFE_FREEDOM_PRESENT")]
    dominated = [event for event in events if event["status"].endswith("SAFETY_MARGIN_DOMINATED")]
    numeric_fields = {
        "residual_cosine": accepted,
        "rotation_angle": accepted,
        "minimum_safety_slack": accepted,
        "continuous_minimum_down_surplus_ulps": accepted,
        "continuous_minimum_up_surplus_ulps": accepted,
        "f32_cue_drive_drift": accepted,
        "f32_axis_drift": accepted,
        "f32_total_norm_drift": accepted,
        "f32_storage_displacement_drift": accepted,
        "f32_residual_cosine_drift": accepted,
        "true_minimum_safety_slack": events,
    }
    summary = {
        "protocol": "Q10-SM",
        "status": "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT",
        "total_events": len(events),
        "accepted_nonidentity_events": len(accepted),
        "safety_margin_dominated_events": len(dominated),
        "accepted_fraction": len(accepted) / len(events),
        "states_by_seed": dict(sorted(by_seed.items())),
        "quantiles": {
            field: quantiles([float(event[field]) for event in source])
            for field, source in numeric_fields.items()
        },
        "accepted_f32_down_steps_capped": quantiles([float(event["f32_minimum_down_steps_capped"]) for event in accepted]),
        "accepted_f32_up_steps_capped": quantiles([float(event["f32_minimum_up_steps_capped"]) for event in accepted]),
        "accepted_candidate_count": sorted({event["candidate_count"] for event in accepted}),
        "accepted_reserve_ulps": sorted({event["reserve_ulps"] for event in accepted}),
        "all_integrity_maxima": {
            field: max(float(event[field]) for event in events)
            for field in ("cue_drive_max_abs_error", "axis_displacement_error",
                          "null_annihilation_max_abs", "total_norm_error",
                          "reconstruction_error", "f32_safety_violation_count",
                          "f32_boundary_membership_symmetric_difference",
                          "f32_lower_boundary_membership_difference",
                          "f32_upper_boundary_membership_difference")
        },
        "scientific_seed_bundles": 0,
        "behavioral_inference": False,
        "sequential_f32_readout": "NOT_TESTED",
        "ulp_repair": "NOT_TESTED",
    }
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
