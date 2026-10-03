"""Independent Q08 smoke receipt validation; never inspect task performance."""

import collections
import hashlib
import json
import math
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LABELS = (
    "axial_match", "total_norm_match", "residual_norm_match", "residual_decorrelation",
    "boundary_membership", "permitted_support", "weight_bounds", "constructor_allocations",
    "nonzero_support_size", "cue_mbon_drive_match", "cue_score_match",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with pathlib.Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def finite_tree(value):
    if isinstance(value, float):
        require(math.isfinite(value), "nonfinite numeric receipt")
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def distribution(values):
    require(bool(values), "empty diagnostic distribution")
    return {"minimum": min(values), "median": statistics.median(values),
            "mean": statistics.fmean(values), "maximum": max(values)}


def gates(event):
    g = event["geometry"]
    r = event["readout"]
    cosine = g["residual_abs_cosine"]
    return (
        0 <= g["axial_error_over_total_norm"] <= 1e-7,
        0 <= g["norm_relative_error"] <= 1e-7,
        0 <= g["residual_norm_relative_error"] <= 1e-7,
        not event["zero_residual"] and cosine is not None and 0 <= cosine <= 1e-5,
        g["boundary_symmetric_difference"] == 0,
        g["outside_support_changes"] == 0,
        g["max_bound_violation"] == 0,
        g["hot_allocations"] == 0,
        abs(g["true_nonzero"] - g["null_nonzero"]) / max(g["true_nonzero"], 1) <= 0.01,
        0 <= r["max_normalized_drive_error"] <= 1e-7,
        0 <= r["max_cue_score_error"] <= 1e-7,
    )


def summarize(output):
    require(sys.flags.optimize == 0, "optimized Python forbidden")
    contract = json.loads((ROOT / "CONTRACT.json").read_text())
    require(digest(ROOT / "PLAN.md") == contract["plan_sha256"], "pre-smoke contract changed")
    execution = json.loads((output / "execution.json").read_text())
    require(execution["protocol"] == "Q08-ReadoutNull-v1", "wrong smoke protocol")
    require(execution["mode"] == "smoke" and execution["complete"] is True, "incomplete smoke")
    require(execution["configured_seeds"] == [9200] and execution["fresh_seed_bundles"] == 0,
            "smoke crossed seed firewall")
    require(execution["outcome_rows"] == 4, "smoke cell cardinality drift")
    require({path.name for path in output.glob("*.jsonl")} == {"R-tau4.jsonl", "L-tau4.jsonl"},
            "smoke file membership drift")
    events = []
    rows = []
    failures = collections.Counter()
    side_failures = {}
    for side in ("R", "L"):
        lines = (output / f"{side}-tau4.jsonl").read_text().splitlines()
        require(len(lines) == 1, "smoke bundle cardinality drift")
        bundle = json.loads(lines[0])
        finite_tree(bundle)
        require((bundle["seed"], bundle["side"], bundle["tau"]) == (9200, side, 4.0),
                "smoke bundle identity drift")
        require(len(bundle["results"]) == 2 and {row["arm"] for row in bundle["results"]} == {"E", "Z"},
                "smoke arm membership drift")
        for row in bundle["results"]:
            require((row["seed"], row["side"], row["tau"], row["condition"])
                    == (9200, side, 4.0, "true_perpendicular"), "smoke row identity drift")
            require(row["canonical"]["outcome"]["hot_allocations"] == 0, "canonical allocation detected")
            rows.append(row)
            if row["arm"] == "Z":
                require(row["shadow"] == {"status": "FIXED_WEIGHT_CONTROL", "events": []}, "Z shadow changed")
                require(row["canonical"]["outcome"]["changed_weights"] == 0, "Z weights changed")
                continue
            local = row["shadow"]["events"]
            require(len(local) == 256, "missing smoke event")
            failed_count = 0
            for trial, event in enumerate(local, 1):
                require(event["trial"] == trial and event["geometry"]["trial"] == trial, "event order drift")
                passed = gates(event)
                mask = sum(1 << index for index, ok in enumerate(passed) if not ok)
                require(mask == event["failure_mask"], "independent gate mask disagrees with Rust")
                require(event["geometry_valid"] == (mask == 0), "geometry-valid flag disagrees")
                readout = event["readout"]
                require(len(readout["true_cue_scores"]) == len(readout["null_cue_scores"])
                        == len(readout["cue_max_normalized_drive_errors"]) == 16, "cue vector cardinality drift")
                score_error = max(abs(t - n) for t, n in zip(readout["true_cue_scores"], readout["null_cue_scores"]))
                require(abs(score_error - readout["max_cue_score_error"]) <= 1e-15, "cue score error receipt drift")
                require(max(readout["cue_max_normalized_drive_errors"]) == readout["max_normalized_drive_error"],
                        "cue drive maximum receipt drift")
                failed = mask != 0 or event["shadow_hot_allocations"] != 0
                failed_count += failed
                for label, ok in zip(LABELS, passed):
                    failures[label] += not ok
                failures["shadow_allocations"] += event["shadow_hot_allocations"] != 0
                events.append({"side": side, **event})
            require(bytes(local[-1]["true_endpoint_sha256"]).hex() == row["final_weight_sha256"],
                    "true endpoint/final canonical weight hash mismatch")
            require(row["shadow"]["status"] == ("CONSTRUCTOR_FAILED" if failed_count else "PASSED"),
                    "constructor cell status disagrees with independent receipts")
            side_failures[side] = failed_count
    require(len(events) == 512 and len(rows) == 4, "smoke total cardinality drift")
    floors = [e["budget"]["optimistic_residual_abs_cosine_floor"] for e in events
              if e["budget"]["optimistic_residual_abs_cosine_floor"] is not None]
    all_group_floors = [e["budget"].get("all_group_optimistic_residual_abs_cosine_floor") for e in events
                        if e["budget"].get("all_group_optimistic_residual_abs_cosine_floor") is not None]
    for e in events:
        b = e["budget"]
        if "all_group_nullspace_energy" in b:
            require(abs(b["total_energy"] - b["all_group_nullspace_energy"] - b["all_group_fixed_energy"])
                    <= 1e-12 * max(b["total_energy"], 1.0), "all-group energy reconstruction drift")
            floor = b["all_group_optimistic_residual_abs_cosine_floor"]
            if floor is not None:
                expected = max(0.0, (b["all_group_fixed_energy"] - b["all_group_nullspace_energy"]
                                     - e["geometry"]["true_axial"] ** 2) / b["residual_energy"])
                require(abs(expected - floor) <= 1e-12, "all-group cosine floor arithmetic drift")
    all_failed = sum(side_failures.values())
    summary = {
        "protocol": "Q08-ReadoutNull-v1",
        "status": "SMOKE_CONSTRUCTOR_FAILED" if all_failed else "SMOKE_CONSTRUCTOR_PASSED",
        "integrity": "VALIDATED",
        "scientific_seed_bundles_used": 0,
        "behavioral_hypothesis_test": False,
        "seed": 9200, "events": 512, "events_failed": all_failed, "side_events_failed": side_failures,
        "failure_counts": dict(failures),
        "zero_residual_events": sum(e["zero_residual"] for e in events),
        "structurally_overconstrained_events": sum(e["budget"]["structurally_overconstrained"] for e in events),
        "optimistic_residual_cosine_floor": distribution(floors) if floors else None,
        "all_group_overconstrained_events": sum(floor > 1e-5 for floor in all_group_floors),
        "all_group_optimistic_residual_cosine_floor": distribution(all_group_floors) if all_group_floors else None,
        "actual_residual_cosine": distribution([e["geometry"]["residual_abs_cosine"] for e in events
                                                if e["geometry"]["residual_abs_cosine"] is not None]),
        "max_normalized_drive_error": distribution([e["readout"]["max_normalized_drive_error"] for e in events]),
        "max_cue_score_error": distribution([e["readout"]["max_cue_score_error"] for e in events]),
        "real_arithmetic_drive_error": distribution([e["readout"]["max_real_arithmetic_normalized_drive_error"] for e in events]),
        "rotatable_energy_fraction": distribution([e["budget"]["rotatable_nullspace_energy"]
                                                    / max(e["budget"]["total_energy"], 1e-30) for e in events]),
        "distractor_drive_difference": distribution([e["readout"]["max_distractor_normalized_drive_error"] for e in events]),
        "plan_sha256": contract["plan_sha256"],
        "input_hashes": {path.name: digest(path) for path in output.iterdir() if path.is_file()
                         and path.name not in {"independent-summary.json", "independent-report.md"}},
    }
    (output / "independent-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    report = f"""# Q08 independent smoke review

Status: `{summary['status']}`. Integrity: `VALIDATED`.

All 512 event receipts were retained. {all_failed} events failed the pre-smoke contract. R failed
{side_failures['R']} / 256; L failed {side_failures['L']} / 256.

{summary['structurally_overconstrained_events']} events have an optimistic grouping-constrained
decorrelation floor above the frozen gate under the quadruple implementation;
{summary['all_group_overconstrained_events']} retain a positive floor above the gate even allowing
all signature-group nullspaces. This is a constructor-contract limitation, not a theorem
about all possible nonlinear readout-preserving endpoints. Full qualification and DH-08B measured
execution remain gated if any event failed. No task performance was analyzed and no scientific seed
bundle was opened.
"""
    (output / "independent-report.md").write_text(report)
    return summary


if __name__ == "__main__":
    require(len(sys.argv) == 2, "usage: summarize_smoke.py SMOKE_OUTPUT")
    print(json.dumps(summarize(pathlib.Path(sys.argv[1]).resolve()), indent=2))
