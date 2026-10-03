"""Frozen DH-07R analysis: realized residual-direction specificity."""
from __future__ import annotations

import csv
import itertools
import json
import math
import pathlib
import statistics
import sys
from collections.abc import Iterable

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDITIONS = (
    "immediate",
    "quiet",
    "neither",
    "parallel_only",
    "true_perpendicular",
    "null_perpendicular",
    "both_true",
    "parallel_null",
)
NULL_CONDITIONS = ("null_perpendicular", "parallel_null")
CHECKPOINTS = (0, 16, 32, 64, 128, 256)
AUDITS_PER_NULL_CELL = 256
T_CRIT_975_DF31 = 2.0395134463964077
GATES = {
    "axial_error_over_total_norm": 1e-7,
    "norm_relative_error": 1e-7,
    "residual_norm_relative_error": 1e-7,
    "residual_abs_cosine": 1e-5,
    "support_size_relative_difference": 0.01,
}
Z_OUTCOME_FIELDS = (
    "accuracy",
    "acquisition",
    "reversal",
    "late_acquisition",
    "late_reversal",
    "probe_acquisition",
    "probe_reversal",
    "curve",
    "changed_weights",
)


class AnalysisError(RuntimeError):
    """A fail-closed input or manipulation-integrity failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def finite_tree(value: object, path: str = "root") -> None:
    """Reject every non-finite numeric value anywhere in emitted JSON."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        require(math.isfinite(value), f"non-finite value at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            finite_tree(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            finite_tree(item, f"{path}.{key}")
        return
    raise AnalysisError(f"unsupported JSON value at {path}: {type(value).__name__}")


def tau_name(tau: float) -> str:
    return f"{tau:g}"


def load_config(path: pathlib.Path | None = None) -> dict:
    config = json.loads((path or ROOT / "config.json").read_text(encoding="utf-8"))
    require(len(config["seeds"]) == 32, "DH-07R requires exactly 32 seed bundles")
    require(len(set(config["seeds"])) == 32, "seed bundle identifiers must be unique")
    require(config["sides"] == ["R", "L"], "expected R and L slices")
    require(config["taus"] == [4.0, 16.0], "expected taus 4 and 16")
    require(config["arms"] == ["E", "Z"], "expected E and Z arms")
    require(config["conditions"] == list(CONDITIONS), "condition order or identity drift")
    require(config["trials"] == 512, "expected 512 total trials")
    require(config["bootstrap_resamples"] == 20_000, "expected 20,000 resamples")
    return config


def load_run(run: pathlib.Path, config: dict) -> tuple[list[dict], list[dict], dict]:
    execution = json.loads((run / "execution.json").read_text(encoding="utf-8"))
    finite_tree(execution, "execution")
    require(execution.get("complete") is True, "execution is incomplete")
    require(execution.get("protocol") == "DH-07R", "wrong execution protocol")
    require(execution.get("mode") == "run", "analysis accepts the sealed measured run only")
    require(execution.get("fresh_seed_bundles") == 32, "execution seed count mismatch")
    require(execution.get("configured_seeds") == config["seeds"], "execution seed identities mismatch")
    require(execution.get("specimens") == 1, "expected one synthetic specimen")

    bundles: list[dict] = []
    rows: list[dict] = []
    for side, tau in itertools.product(config["sides"], config["taus"]):
        path = run / f"{side}-tau{tau_name(tau)}.jsonl"
        require(path.is_file(), f"missing JSONL file: {path.name}")
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        require(len(records) == 32, f"{path.name}: expected 32 bundles")
        require([record.get("seed") for record in records] == config["seeds"],
                f"{path.name}: seed order or membership mismatch")
        for bundle in records:
            finite_tree(bundle, f"bundle[{side},{tau},{bundle.get('seed')}]")
            require(bundle.get("side") == side and bundle.get("tau") == tau,
                    f"bundle metadata mismatch for {side} tau={tau}")
            result_rows = bundle.get("results")
            require(isinstance(result_rows, list) and len(result_rows) == 16,
                    f"seed {bundle.get('seed')} {side} tau={tau}: expected 16 results")
            for row in result_rows:
                require(row.get("seed") == bundle["seed"] and row.get("side") == side
                        and row.get("tau") == tau, "result metadata differs from bundle")
            bundles.append(bundle)
            rows.extend(result_rows)
    require(len(bundles) == 128, "expected 128 side/tau seed bundles")
    require(len(rows) == 2_048, "expected 2,048 result cells")
    require(execution.get("outcome_rows") == len(rows), "execution outcome count mismatch")
    return rows, bundles, execution


def hash_receipt(value: object, label: str) -> str:
    require(isinstance(value, list) and len(value) == 32, f"{label}: malformed acquisition hash")
    require(all(isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 255
                for item in value), f"{label}: acquisition hash is not 32 bytes")
    return bytes(value).hex()


def final_point(row: dict) -> dict:
    trajectory = row["result"].get("trajectory")
    require(isinstance(trajectory, list), "trajectory missing")
    require(tuple(point.get("reversal_trials") for point in trajectory) == CHECKPOINTS,
            "trajectory checkpoints differ from 0,16,32,64,128,256")
    require(all(math.isclose(point["old_map_margin"], -point["reversed_map_margin"],
                             rel_tol=0.0, abs_tol=1e-12) for point in trajectory),
            "old-map and reversed-map trajectory margins are not complementary")
    point = trajectory[-1]
    require("old_map_margin" in point, "final old-map margin missing")
    geometry = row["result"].get("weight_geometry", {})
    require(math.isclose(point["old_map_margin"], geometry.get("final_old_map_margin", math.nan),
                         rel_tol=0.0, abs_tol=1e-12),
            "trajectory and final weight-geometry margins disagree")
    return point


def validate_audit(audit: dict, expected_trial: int, label: str) -> dict:
    require(audit.get("trial") == expected_trial, f"{label}: audit trial sequence mismatch")
    for field in ("axial_error_over_total_norm", "norm_relative_error",
                  "residual_norm_relative_error", "residual_abs_cosine"):
        value = audit.get(field)
        require(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value), f"{label}: {field} missing or non-finite")
        require(value <= GATES[field], f"{label}: {field} exceeds frozen gate")
    require(audit.get("boundary_symmetric_difference") == 0,
            f"{label}: boundary_symmetric_difference is not zero")
    require(audit.get("outside_support_changes") == 0,
            f"{label}: outside_support_changes is not zero")
    require(audit.get("hot_allocations") == 0, f"{label}: hot_allocations is not zero")
    require(audit.get("max_bound_violation") == 0.0,
            f"{label}: max_bound_violation is not zero")
    true_nonzero = audit.get("true_nonzero")
    null_nonzero = audit.get("null_nonzero")
    require(isinstance(true_nonzero, int) and true_nonzero >= 0
            and isinstance(null_nonzero, int) and null_nonzero >= 0,
            f"{label}: invalid realized support sizes")
    support_error = abs(true_nonzero - null_nonzero) / max(true_nonzero, 1)
    require(support_error <= GATES["support_size_relative_difference"],
            f"{label}: support-size relative difference exceeds frozen gate")
    return {
        "axial_error_over_total_norm": float(audit["axial_error_over_total_norm"]),
        "norm_relative_error": float(audit["norm_relative_error"]),
        "residual_norm_relative_error": float(audit["residual_norm_relative_error"]),
        "residual_abs_cosine": float(audit["residual_abs_cosine"]),
        "support_size_relative_difference": float(support_error),
    }


def z_signature(row: dict) -> dict:
    result = row["result"]
    outcome = result["outcome"]
    return {
        "final_weight_sha256": row["final_weight_sha256"],
        "acquisition_state_sha256": result["acquisition_state_sha256"],
        "outcome": {field: outcome[field] for field in Z_OUTCOME_FIELDS},
        "paired_final_old_probe": result["paired_final_old_probe"],
        "paired_final_reversal_probe": result["paired_final_reversal_probe"],
        "weight_geometry": result["weight_geometry"],
        "trajectory": result["trajectory"],
    }


def validate(rows: list[dict], config: dict) -> tuple[dict, list[dict]]:
    expected = set(itertools.product(
        config["sides"], config["taus"], config["seeds"], config["arms"], CONDITIONS
    ))
    keys = [(row.get("side"), row.get("tau"), row.get("seed"),
             row.get("arm"), row.get("condition")) for row in rows]
    require(len(keys) == len(set(keys)), "duplicate result cell")
    require(set(keys) == expected, "missing or unexpected result cell")
    lookup = dict(zip(keys, rows))
    manipulation_rows: list[dict] = []

    for side, tau, seed, arm in itertools.product(
            config["sides"], config["taus"], config["seeds"], config["arms"]):
        group = [lookup[side, tau, seed, arm, condition] for condition in CONDITIONS]
        acquisition = hash_receipt(group[0]["result"]["acquisition_state_sha256"], "acquisition")
        for row in group:
            label = f"{side}/tau={tau}/seed={seed}/{arm}/{row['condition']}"
            weight_hash = row.get("final_weight_sha256")
            require(isinstance(weight_hash, str) and len(weight_hash) == 64
                    and all(character in "0123456789abcdef" for character in weight_hash),
                    f"{label}: malformed final-weight SHA-256")
            require(hash_receipt(row["result"]["acquisition_state_sha256"], label) == acquisition,
                    f"{label}: acquisition hash parity failed")
            require(row["result"]["outcome"].get("hot_allocations") == 0,
                    f"{label}: simulator hot allocation detected")
            require(arm != "Z" or row["result"]["outcome"].get("changed_weights") == 0,
                    f"{label}: fixed-weight arm changed weights")
            require(math.isclose(row["result"]["paired_final_old_probe"]
                                 + row["result"]["paired_final_reversal_probe"],
                                 1.0, rel_tol=0.0, abs_tol=1e-12),
                    f"{label}: paired probe complementarity failed")
            final_point(row)
            manipulation = row.get("manipulation")
            require(isinstance(manipulation, dict), f"{label}: manipulation receipt missing")
            events = manipulation.get("events")
            require(isinstance(events, list), f"{label}: manipulation events missing")
            requires_audits = arm == "E" and row["condition"] in NULL_CONDITIONS
            if requires_audits:
                require(manipulation.get("status") == "PASSED", f"{label}: null policy not passed")
                require(len(events) == AUDITS_PER_NULL_CELL,
                        f"{label}: expected 256 null manipulation audits")
                metrics = [validate_audit(event, index, label)
                           for index, event in enumerate(events, 1)]
                manipulation_rows.append({
                    "seed": seed, "side": side, "tau": tau, "condition": row["condition"],
                    "events": len(events),
                    **{f"max_{field}": max(metric[field] for metric in metrics) for field in GATES},
                })
            else:
                require(manipulation.get("status") == "NOT_APPLICABLE" and not events,
                        f"{label}: unexpected manipulation audits")
        if arm == "Z":
            reference = z_signature(group[0])
            require(all(z_signature(row) == reference for row in group[1:]),
                    f"{side}/tau={tau}/seed={seed}: Z condition invariance failed")
    return lookup, manipulation_rows


def seed_level_contrasts(lookup: dict, config: dict, field: str = "old_map_margin") -> list[dict]:
    records = []
    for seed in config["seeds"]:
        off_values, on_values = [], []
        side_values = {side: [] for side in config["sides"]}
        tau_values = {tau: [] for tau in config["taus"]}
        for side, tau in itertools.product(config["sides"], config["taus"]):
            def value(condition: str) -> float:
                return float(final_point(lookup[side, tau, seed, "E", condition])[field])
            off = value("true_perpendicular") - value("null_perpendicular")
            on = value("both_true") - value("parallel_null")
            off_values.append(off)
            on_values.append(on)
            paired = 0.5 * (off + on)
            side_values[side].append(paired)
            tau_values[tau].append(paired)
        def averaged(field_name: str, left: str, right: str) -> float:
            values = []
            for side, tau in itertools.product(config["sides"], config["taus"]):
                left_point = final_point(lookup[side, tau, seed, "E", left])
                right_point = final_point(lookup[side, tau, seed, "E", right])
                values.append(float(left_point[field_name]) - float(right_point[field_name]))
            return float(np.mean(values))
        off_mean = float(np.mean(off_values))
        on_mean = float(np.mean(on_values))
        records.append({
            "seed": seed,
            "parallel_off_true_minus_null": off_mean,
            "parallel_on_true_minus_null": on_mean,
            "primary_true_minus_null": 0.5 * (off_mean + on_mean),
            "interaction_on_minus_off": on_mean - off_mean,
            "axis_parallel_off_true_minus_null": averaged(
                "acquisition_axis_coordinate", "true_perpendicular", "null_perpendicular"),
            "axis_parallel_on_true_minus_null": averaged(
                "acquisition_axis_coordinate", "both_true", "parallel_null"),
            "parallel_off_true_minus_baseline": averaged(
                "old_map_margin", "true_perpendicular", "neither"),
            "parallel_off_null_minus_baseline": averaged(
                "old_map_margin", "null_perpendicular", "neither"),
            "parallel_on_true_minus_baseline": averaged(
                "old_map_margin", "both_true", "parallel_only"),
            "parallel_on_null_minus_baseline": averaged(
                "old_map_margin", "parallel_null", "parallel_only"),
            **{f"side_{side}": float(np.mean(values)) for side, values in side_values.items()},
            **{f"tau_{tau_name(tau)}": float(np.mean(values)) for tau, values in tau_values.items()},
        })
    return records


def bootstrap_summary(values: Iterable[float], resamples: int, seed: int) -> dict:
    observed = np.asarray(list(values), dtype=np.float64)
    require(observed.shape == (32,), "paired inference requires 32 seed-level values")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, observed.size, size=(resamples, observed.size))
    sampled_means = observed[indices].mean(axis=1)
    return {
        **t_summary(observed.tolist()),
        "ci95": np.quantile(sampled_means, [0.025, 0.975], method="linear").tolist(),
        "n_seed_bundles": int(observed.size),
        "resamples": resamples,
        "rng": "numpy.random.default_rng(PCG64)",
        "bootstrap_seed": seed,
        "seed_values": observed.tolist(),
    }


def t_summary(values: Iterable[float]) -> dict:
    observed = [float(value) for value in values]
    require(len(observed) == 32, "paired t interval requires 32 seed-level values")
    mean = statistics.fmean(observed)
    sample_sd = statistics.stdev(observed)
    standard_error = sample_sd / math.sqrt(len(observed))
    radius = T_CRIT_975_DF31 * standard_error
    return {
        "mean": mean,
        "sample_sd": sample_sd,
        "standard_error": standard_error,
        "t_ci95": [mean - radius, mean + radius],
        "t_degrees_of_freedom": 31,
    }


def write_csv(path: pathlib.Path, rows: list[dict], fields: list[str] | None = None) -> None:
    require(bool(rows), f"refusing to write empty CSV: {path.name}")
    columns = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def cell_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        point = final_point(row)
        output.append({
            "seed": row["seed"], "side": row["side"], "tau": row["tau"],
            "arm": row["arm"], "condition": row["condition"],
            "old_map_margin_t256": point["old_map_margin"],
            "reversed_map_margin_t256": point["reversed_map_margin"],
            "acquisition_axis_coordinate_t256": point["acquisition_axis_coordinate"],
            "final_weight_sha256": row["final_weight_sha256"],
            "acquisition_state_sha256": bytes(row["result"]["acquisition_state_sha256"]).hex(),
            "manipulation_audits": len(row["manipulation"]["events"]),
        })
    return output


def trajectory_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        for point in row["result"]["trajectory"]:
            output.append({
                "seed": row["seed"], "side": row["side"], "tau": row["tau"],
                "arm": row["arm"], "condition": row["condition"], **point,
            })
    return output


def manipulation_summary(rows: list[dict]) -> dict:
    return {
        "null_cells": len(rows),
        "events": sum(row["events"] for row in rows),
        "expected_events_per_null_cell": AUDITS_PER_NULL_CELL,
        "all_frozen_gates_passed": True,
        "observed_maxima": {
            field: max(row[f"max_{field}"] for row in rows) for field in GATES
        },
        "frozen_upper_gates": dict(GATES),
        "exact_zero_gates": {
            "boundary_symmetric_difference": 0,
            "outside_support_changes": 0,
            "max_bound_violation": 0,
            "hot_allocations": 0,
        },
    }


def analyze(run: pathlib.Path, config_path: pathlib.Path | None = None) -> dict:
    config = load_config(config_path)
    rows, _bundles, execution = load_run(run, config)
    lookup, manipulations = validate(rows, config)
    contrasts = seed_level_contrasts(lookup, config)
    primary = bootstrap_summary(
        [row["primary_true_minus_null"] for row in contrasts],
        config["bootstrap_resamples"], config["bootstrap_seed"],
    )
    ci_low, ci_high = primary["ci95"]
    t_low, t_high = primary["t_ci95"]
    status = ("DIRECTION_SPECIFICITY_SUPPORTED" if ci_high < 0 and t_high < 0 else
              "OPPOSITE_DIRECTION_EFFECT" if ci_low > 0 and t_low > 0 else "INCONCLUSIVE")
    cells = cell_rows(rows)
    cell_means = {}
    for arm, condition in itertools.product(config["arms"], CONDITIONS):
        values = [row["old_map_margin_t256"] for row in cells
                  if row["arm"] == arm and row["condition"] == condition]
        cell_means[f"{arm}:{condition}"] = float(np.mean(values))
    secondary_fields = (
        "parallel_off_true_minus_null", "parallel_on_true_minus_null",
        "interaction_on_minus_off", "axis_parallel_off_true_minus_null",
        "axis_parallel_on_true_minus_null", "parallel_off_true_minus_baseline",
        "parallel_off_null_minus_baseline", "parallel_on_true_minus_baseline",
        "parallel_on_null_minus_baseline",
    )
    secondary = {
        field: t_summary(record[field] for record in contrasts) for field in secondary_fields
    }
    summary = {
        "schema": "dh07r-analysis-v1",
        "status": status,
        "primary": {
            "name": "structured_minus_matched_null_old_map_margin_t256",
            "estimand": "per seed: mean over side and tau of 0.5*((true_perpendicular-null_perpendicular)+(both_true-parallel_null))",
            **primary,
            "prediction": "negative",
        },
        "descriptive": {
            "paired_seed_intervals": secondary,
            "cell_mean_old_map_margin_t256": cell_means,
        },
        "manipulation_validity": manipulation_summary(manipulations),
        "integrity": {
            "seed_bundles": 32,
            "sides": 2,
            "taus": 2,
            "arms": 2,
            "conditions": 8,
            "result_cells": len(rows),
            "acquisition_hash_parity": True,
            "fixed_weight_z_condition_invariance": True,
            "finite_json_values": True,
        },
        "execution": execution,
        "numpy_version": np.__version__,
    }

    analysis_dir = run / "analysis"
    require(not analysis_dir.exists(), "analysis directory already exists; refusing overwrite")
    analysis_dir.mkdir()
    (analysis_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    write_csv(analysis_dir / "seed_contrasts.csv", contrasts)
    write_csv(analysis_dir / "cells.csv", cells)
    write_csv(analysis_dir / "trajectory.csv", trajectory_rows(rows))
    write_csv(analysis_dir / "manipulation_cells.csv", manipulations)

    report = [
        "# DH-07R measured analysis",
        "",
        f"**{status}**",
        "",
        "The primary paired estimate compares the endogenous residual direction with the locally matched feasible null direction in both parallel contexts.",
        "",
        f"Structured minus matched-null final old-map margin: **{primary['mean']:+.6f}**; paired seed-level 95% t interval **[{primary['t_ci95'][0]:+.6f}, {primary['t_ci95'][1]:+.6f}]** and 95% percentile bootstrap interval **[{ci_low:+.6f}, {ci_high:+.6f}]**.",
        "",
        f"The estimate uses {primary['n_seed_bundles']} fresh seed bundles and {primary['resamples']:,} deterministic bootstrap resamples. Each seed contributes one value after equal averaging across both slices and both taus.",
        "",
        "## Parallel contexts",
        "",
        "| Context | Mean true minus null old-map margin | Paired 95% t interval |",
        "|---|---:|---:|",
        f"| Parallel off | {secondary['parallel_off_true_minus_null']['mean']:+.6f} | [{secondary['parallel_off_true_minus_null']['t_ci95'][0]:+.6f}, {secondary['parallel_off_true_minus_null']['t_ci95'][1]:+.6f}] |",
        f"| Parallel on | {secondary['parallel_on_true_minus_null']['mean']:+.6f} | [{secondary['parallel_on_true_minus_null']['t_ci95'][0]:+.6f}, {secondary['parallel_on_true_minus_null']['t_ci95'][1]:+.6f}] |",
        f"| On minus off | {secondary['interaction_on_minus_off']['mean']:+.6f} | [{secondary['interaction_on_minus_off']['t_ci95'][0]:+.6f}, {secondary['interaction_on_minus_off']['t_ci95'][1]:+.6f}] |",
        "",
        "## Manipulation validity",
        "",
        f"All {summary['manipulation_validity']['events']:,} committed null events across {summary['manipulation_validity']['null_cells']} E-arm null cells passed the frozen gates.",
        "",
        "| Diagnostic | Observed maximum | Frozen upper gate |",
        "|---|---:|---:|",
    ]
    for field, gate in GATES.items():
        report.append(f"| {field} | {summary['manipulation_validity']['observed_maxima'][field]:.9g} | {gate:.9g} |")
    report += [
        "",
        "Boundary symmetric difference, outside-support changes, bound violation, and hot-loop allocations were exactly zero for every null event.",
        "",
        "## Integrity and limits",
        "",
        "- The input contained exactly 32 seeds, two slices, two taus, two arms, and eight conditions: 2,048 result cells.",
        "- Acquisition hashes matched across conditions within each seed, slice, tau, and arm. Fixed-weight Z scientific outputs were condition invariant.",
        "- This estimates an adaptive direction-replacement policy: after arms diverge, each null is matched in its own current state.",
        "- Seeds are paired computational replicates from one synthetic specimen. They are not independent animals or evidence of a biological mechanism.",
        "- A nonzero effect identifies residual-direction specificity under the frozen matching contract; it does not by itself establish latent-memory recovery or transfer to other tasks.",
        "",
        "## Machine-readable outputs",
        "",
        "- `summary.json`: primary inference, manipulation gates, and integrity receipts",
        "- `seed_contrasts.csv`: one paired primary value per seed bundle",
        "- `cells.csv`: one row per result cell",
        "- `trajectory.csv`: one row per checkpoint and result cell",
        "- `manipulation_cells.csv`: one row per E-arm null-policy cell",
    ]
    (analysis_dir / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "primary": summary["primary"]}, indent=2))
    return summary


if __name__ == "__main__":
    require(len(sys.argv) == 2, "usage: analyze.py RUN_DIRECTORY")
    analyze(pathlib.Path(sys.argv[1]))
