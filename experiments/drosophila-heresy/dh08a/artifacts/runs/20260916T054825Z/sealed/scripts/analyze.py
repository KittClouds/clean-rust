"""Frozen DH-08A analysis for event-local Q07-matched endpoint substitution."""
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
SIDES = ("R", "L")
TAUS = (4.0, 16.0)
ARMS = ("E", "Z")
CONDITION = "true_perpendicular"
EVENTS_PER_CELL = 256
WINDOWS = ((1, 16), (17, 32), (33, 64), (65, 128), (129, 256))
T_CRIT_975_DF31 = 2.0395134463964077
GATES = {
    "axial_error_over_total_norm": 1e-7,
    "norm_relative_error": 1e-7,
    "residual_norm_relative_error": 1e-7,
    "residual_abs_cosine": 1e-5,
    "support_size_relative_difference": 0.01,
}


class AnalysisError(RuntimeError):
    """Fail-closed input, geometry, or inferential-unit violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def finite_tree(value: object, path: str = "root") -> None:
    if value is None or isinstance(value, (str, bool)):
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


def tau_label(tau: float) -> str:
    return f"{tau:g}"


def load_config(path: pathlib.Path | None = None) -> dict:
    config = json.loads((path or ROOT / "config.json").read_text(encoding="utf-8"))
    finite_tree(config, "config")
    require(config.get("observe") is True, "measured config must enable observation")
    require(config.get("seeds") == list(range(8000, 8032)),
            "DH-08A requires exactly fresh seeds 8000..8031")
    require(config.get("sides") == list(SIDES), "expected R and L slices")
    require(config.get("taus") == list(TAUS), "expected taus 4 and 16")
    require(config.get("arms") == list(ARMS), "expected E and Z arms")
    require(config.get("conditions") == [CONDITION], "condition identity drift")
    require(config.get("trials") == 512, "expected 512 total trials")
    require(config.get("bootstrap_resamples") == 20_000,
            "expected 20,000 bootstrap resamples")
    require(config.get("bootstrap_seed") == 2026091608,
            "bootstrap seed differs from frozen protocol")
    return config


def hash_receipt(value: object, label: str) -> str:
    require(isinstance(value, list) and len(value) == 32,
            f"{label}: acquisition hash must contain 32 bytes")
    require(all(isinstance(byte, int) and not isinstance(byte, bool)
                and 0 <= byte <= 255 for byte in value),
            f"{label}: malformed acquisition hash byte")
    return bytes(value).hex()


def validate_audit(event: dict, ordinal: int, label: str) -> dict:
    require(isinstance(event, dict), f"{label}: event {ordinal} is not an object")
    finite_tree(event, f"{label}.event[{ordinal}]")
    require(event.get("trial") == ordinal,
            f"{label}: event order/trial mismatch at {ordinal}")
    require(event.get("geometry_valid") is True,
            f"{label}: geometry_valid false at event {ordinal}")
    require(event.get("shadow_hot_allocations") == 0,
            f"{label}: shadow hot allocations at event {ordinal}")
    for field in ("base_margin", "true_margin", "null_margin", "true_minus_null"):
        require(isinstance(event.get(field), (int, float))
                and math.isfinite(event[field]),
                f"{label}: invalid {field} at event {ordinal}")
    require(math.isclose(event["true_minus_null"],
                         event["true_margin"] - event["null_margin"],
                         rel_tol=0.0, abs_tol=1e-12),
            f"{label}: delta identity failed at event {ordinal}")
    geometry = event.get("geometry")
    require(isinstance(geometry, dict), f"{label}: geometry missing at event {ordinal}")
    finite_tree(geometry, f"{label}.event[{ordinal}].geometry")
    require(geometry.get("trial") == ordinal,
            f"{label}: geometry trial mismatch at event {ordinal}")
    for field in ("axial_error_over_total_norm", "norm_relative_error",
                  "residual_norm_relative_error"):
        require(isinstance(geometry.get(field), (int, float))
                and geometry[field] <= GATES[field],
                f"{label}: {field} gate failed at event {ordinal}")
    cosine = geometry.get("residual_abs_cosine")
    require(isinstance(cosine, (int, float))
            and cosine <= GATES["residual_abs_cosine"],
            f"{label}: residual_abs_cosine gate failed at event {ordinal}")
    require(geometry.get("boundary_symmetric_difference") == 0,
            f"{label}: boundary gate failed at event {ordinal}")
    require(geometry.get("outside_support_changes") == 0,
            f"{label}: outside-support gate failed at event {ordinal}")
    require(geometry.get("max_bound_violation") == 0,
            f"{label}: bound-violation gate failed at event {ordinal}")
    require(geometry.get("hot_allocations") == 0,
            f"{label}: geometry hot-allocation gate failed at event {ordinal}")
    true_nonzero = geometry.get("true_nonzero")
    null_nonzero = geometry.get("null_nonzero")
    require(isinstance(true_nonzero, int) and true_nonzero >= 0
            and isinstance(null_nonzero, int) and null_nonzero >= 0,
            f"{label}: support counts malformed at event {ordinal}")
    support_difference = abs(true_nonzero - null_nonzero) / max(true_nonzero, 1)
    require(support_difference <= GATES["support_size_relative_difference"],
            f"{label}: support-size gate failed at event {ordinal}")
    endpoint_hash = event.get("true_endpoint_sha256")
    require(isinstance(endpoint_hash, list) and len(endpoint_hash) == 32
            and all(isinstance(byte, int) and 0 <= byte <= 255 for byte in endpoint_hash),
            f"{label}: true endpoint hash malformed at event {ordinal}")
    return {
        "axial_error_over_total_norm": float(geometry["axial_error_over_total_norm"]),
        "norm_relative_error": float(geometry["norm_relative_error"]),
        "residual_norm_relative_error": float(geometry["residual_norm_relative_error"]),
        "residual_abs_cosine": float(cosine),
        "support_size_relative_difference": float(support_difference),
    }


def validate_canonical(row: dict, label: str) -> str:
    canonical = row.get("canonical")
    require(isinstance(canonical, dict), f"{label}: canonical DH07 result missing")
    outcome = canonical.get("outcome")
    require(isinstance(outcome, dict), f"{label}: canonical outcome missing")
    require(outcome.get("hot_allocations") == 0,
            f"{label}: canonical hot allocation detected")
    require(math.isclose(canonical.get("paired_final_old_probe", math.nan)
                         + canonical.get("paired_final_reversal_probe", math.nan),
                         1.0, rel_tol=0.0, abs_tol=1e-12),
            f"{label}: paired final probes are not complementary")
    trajectory = canonical.get("trajectory")
    require(isinstance(trajectory, list) and len(trajectory) == 6,
            f"{label}: canonical trajectory cardinality drift")
    require([point.get("reversal_trials") for point in trajectory]
            == [0, 16, 32, 64, 128, 256],
            f"{label}: canonical trajectory checkpoints drift")
    return hash_receipt(canonical.get("acquisition_state_sha256"), label)


def load_run(run: pathlib.Path, config: dict) -> tuple[list[dict], list[dict], dict]:
    execution = json.loads((run / "execution.json").read_text(encoding="utf-8"))
    finite_tree(execution, "execution")
    require(execution.get("protocol") == "DH-08A", "wrong execution protocol")
    require(execution.get("mode") == "run", "analysis accepts measured run mode only")
    require(execution.get("complete") is True, "execution is incomplete")
    require(execution.get("outcome_rows") == 256, "execution outcome-row count mismatch")
    require(execution.get("fresh_seed_bundles") == 32, "execution seed count mismatch")
    require(execution.get("configured_seeds") == config["seeds"],
            "execution/config seed mismatch")
    require(execution.get("specimens") == 1, "expected one synthetic specimen")

    expected_files = {f"{side}-tau{tau_label(tau)}.jsonl"
                      for side, tau in itertools.product(SIDES, TAUS)}
    actual_files = {path.name for path in run.glob("*.jsonl")}
    require(actual_files == expected_files, "JSONL membership differs from frozen design")
    bundles: list[dict] = []
    rows: list[dict] = []
    for filename in sorted(expected_files):
        path = run / filename
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                require(bool(line.strip()), f"{filename}:{line_number}: empty JSONL line")
                bundle = json.loads(line)
                finite_tree(bundle, f"{filename}:{line_number}")
                bundles.append(bundle)
                results = bundle.get("results")
                require(isinstance(results, list) and len(results) == 2,
                        f"{filename}:{line_number}: expected E and Z results")
                rows.extend(results)
    return rows, bundles, execution


def validate(rows: list[dict], bundles: list[dict], config: dict) -> tuple[dict, list[dict], list[dict]]:
    expected_bundles = set(itertools.product(config["seeds"], SIDES, TAUS))
    bundle_keys = [(bundle.get("seed"), bundle.get("side"), bundle.get("tau"))
                   for bundle in bundles]
    require(len(bundle_keys) == 128 and len(set(bundle_keys)) == 128,
            "bundle cardinality or uniqueness failed")
    require(set(bundle_keys) == expected_bundles, "missing or unexpected bundle")
    for bundle in bundles:
        for row in bundle["results"]:
            require((row.get("seed"), row.get("side"), row.get("tau"))
                    == (bundle.get("seed"), bundle.get("side"), bundle.get("tau")),
                    "result/bundle identity mismatch")

    expected_cells = set(itertools.product(config["seeds"], SIDES, TAUS, ARMS))
    keys = [(row.get("seed"), row.get("side"), row.get("tau"), row.get("arm"))
            for row in rows]
    require(len(keys) == 256 and len(set(keys)) == 256,
            "cell cardinality or uniqueness failed")
    require(set(keys) == expected_cells, "missing or unexpected result cell")
    lookup = dict(zip(keys, rows))
    event_rows: list[dict] = []
    cell_rows: list[dict] = []

    for key in sorted(expected_cells):
        seed, side, tau, arm = key
        row = lookup[key]
        label = f"seed={seed}/{side}/tau={tau_label(tau)}/{arm}"
        require(row.get("condition") == CONDITION, f"{label}: condition drift")
        weight_hash = row.get("final_weight_sha256")
        require(isinstance(weight_hash, str) and len(weight_hash) == 64
                and all(character in "0123456789abcdef" for character in weight_hash),
                f"{label}: malformed final weight hash")
        acquisition_hash = validate_canonical(row, label)
        outcome = row["canonical"]["outcome"]
        shadow = row.get("shadow")
        require(isinstance(shadow, dict), f"{label}: shadow receipt missing")
        events = shadow.get("events")
        require(isinstance(events, list), f"{label}: shadow events missing")
        if arm == "E":
            require(shadow.get("status") == "PASSED", f"{label}: shadow status not PASSED")
            require(len(events) == EVENTS_PER_CELL, f"{label}: expected exactly 256 events")
            gate_metrics = []
            for ordinal, event in enumerate(events, 1):
                gate_metrics.append(validate_audit(event, ordinal, label))
                window = next(f"{start}-{stop}" for start, stop in WINDOWS
                              if start <= ordinal <= stop)
                event_rows.append({
                    "seed": seed, "side": side, "tau": tau, "trial": ordinal,
                    "window": window,
                    "base_margin": event["base_margin"],
                    "true_margin": event["true_margin"],
                    "null_margin": event["null_margin"],
                    "true_minus_null": event["true_minus_null"],
                    "true_minus_base": event["true_margin"] - event["base_margin"],
                    "null_minus_base": event["null_margin"] - event["base_margin"],
                    **gate_metrics[-1],
                })
            final_endpoint_hash = bytes(events[-1]["true_endpoint_sha256"]).hex()
            require(final_endpoint_hash == weight_hash,
                    f"{label}: final true endpoint/final weight hash parity failed")
            cell_rows.append({
                "seed": seed, "side": side, "tau": tau, "arm": arm,
                "acquisition_state_sha256": acquisition_hash,
                "final_weight_sha256": weight_hash,
                "changed_weights": outcome["changed_weights"],
                "events": len(events),
                "mean_true_minus_null": statistics.fmean(e["true_minus_null"] for e in events),
                "mean_true_minus_base": statistics.fmean(
                    e["true_margin"] - e["base_margin"] for e in events),
                "mean_null_minus_base": statistics.fmean(
                    e["null_margin"] - e["base_margin"] for e in events),
                **{f"max_{field}": max(metric[field] for metric in gate_metrics)
                   for field in GATES},
            })
        else:
            require(shadow.get("status") == "FIXED_WEIGHT_CONTROL" and not events,
                    f"{label}: Z must have no shadow events")
            require(outcome.get("changed_weights") == 0,
                    f"{label}: Z fixed-weight control changed weights")
            cell_rows.append({
                "seed": seed, "side": side, "tau": tau, "arm": arm,
                "acquisition_state_sha256": acquisition_hash,
                "final_weight_sha256": weight_hash,
                "changed_weights": 0, "events": 0,
                "mean_true_minus_null": "", "mean_true_minus_base": "",
                "mean_null_minus_base": "",
                **{f"max_{field}": "" for field in GATES},
            })
    require(len(event_rows) == 32 * 2 * 2 * 256,
            "event cardinality is not 32 x 2 x 2 x 256")
    return lookup, event_rows, cell_rows


def infer_seed_values(values: Iterable[float]) -> dict:
    observed = [float(value) for value in values]
    require(len(observed) == 32,
            "pseudoreplication rejected: inference requires exactly 32 seed-bundle values")
    require(all(math.isfinite(value) for value in observed), "non-finite seed value")
    mean = statistics.fmean(observed)
    sample_sd = statistics.stdev(observed)
    standard_error = sample_sd / math.sqrt(32)
    radius = T_CRIT_975_DF31 * standard_error
    return {
        "mean": mean,
        "sample_sd": sample_sd,
        "standard_error": standard_error,
        "t_ci95": [mean - radius, mean + radius],
        "t_degrees_of_freedom": 31,
        "n_seed_bundles": 32,
        "inferential_unit": "computational seed bundle",
    }


def bootstrap_interval(values: Iterable[float], resamples: int, seed: int) -> dict:
    observed = np.asarray(list(values), dtype=np.float64)
    require(observed.shape == (32,),
            "pseudoreplication rejected: bootstrap requires 32 seed-bundle values")
    require(resamples == 20_000 and seed == 2026091608,
            "bootstrap settings differ from frozen protocol")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, 32, size=(resamples, 32))
    means = observed[indices].mean(axis=1)
    return {
        "ci95": np.quantile(means, [0.025, 0.975], method="linear").tolist(),
        "resamples": resamples,
        "bootstrap_seed": seed,
        "rng": "numpy.random.default_rng(PCG64)",
    }


def classify(t_interval: list[float], bootstrap: list[float]) -> str:
    if t_interval[0] > 0 and bootstrap[0] > 0:
        return "POSITIVE_ENDPOINT_EFFECT"
    if t_interval[1] < 0 and bootstrap[1] < 0:
        return "NEGATIVE_ENDPOINT_EFFECT"
    return "INCONCLUSIVE"


def seed_rows(event_rows: list[dict], config: dict) -> list[dict]:
    output = []
    for seed in config["seeds"]:
        seed_events = [row for row in event_rows if row["seed"] == seed]
        require(len(seed_events) == 2 * 2 * 256,
                f"seed {seed}: repeated-measure cardinality mismatch")
        row = {
            "seed": seed,
            "primary_true_minus_null": statistics.fmean(
                event["true_minus_null"] for event in seed_events),
            "true_minus_base": statistics.fmean(
                event["true_minus_base"] for event in seed_events),
            "null_minus_base": statistics.fmean(
                event["null_minus_base"] for event in seed_events),
        }
        for side in SIDES:
            subset = [event["true_minus_null"] for event in seed_events
                      if event["side"] == side]
            row[f"side_{side}"] = statistics.fmean(subset)
        for tau in TAUS:
            subset = [event["true_minus_null"] for event in seed_events
                      if event["tau"] == tau]
            row[f"tau_{tau_label(tau)}"] = statistics.fmean(subset)
        for start, stop in WINDOWS:
            subset = [event["true_minus_null"] for event in seed_events
                      if start <= event["trial"] <= stop]
            row[f"window_{start}_{stop}"] = statistics.fmean(subset)
        output.append(row)
    return output


def summarize_columns(rows: list[dict], columns: Iterable[str]) -> dict:
    return {column: infer_seed_values(row[column] for row in rows) for column in columns}


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    require(bool(rows), f"refusing to write empty CSV: {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def report_text(summary: dict) -> str:
    primary = summary["primary"]
    t_ci = primary["t_ci95"]
    boot = primary["bootstrap_ci95"]
    if summary["status"] == "POSITIVE_ENDPOINT_EFFECT":
        interpretation = ("The Q07-matched null endpoint immediately suppressed old-map "
                          "expression more strongly on endogenous true-path states.")
    elif summary["status"] == "NEGATIVE_ENDPOINT_EFFECT":
        interpretation = ("The immediate endpoint effect opposed the frozen DH-07R sign; "
                          "subsequent adaptive dynamics are required for the cumulative sign.")
    else:
        interpretation = ("Event-local endpoint sensitivity was unresolved; the cumulative "
                          "DH-07R result remains compatible with path-mediated dynamics.")
    return f"""# DH-08A Analysis Report

Status: `{summary['status']}`

## Primary result

The sole inferential unit was the computational seed bundle (n=32). Each seed value is the mean
`true_margin - null_margin` over R/L, tau 4/16, and 256 events. Events, sides, and taus were not
treated as independent samples.

| Quantity | Value |
| --- | ---: |
| Mean | {primary['mean']:.12g} |
| Sample SD | {primary['sample_sd']:.12g} |
| Standard error | {primary['standard_error']:.12g} |
| Paired t 95% interval | [{t_ci[0]:.12g}, {t_ci[1]:.12g}] |
| Seed bootstrap 95% interval | [{boot[0]:.12g}, {boot[1]:.12g}] |

{interpretation}

## Integrity

- Validated 128 bundles, 256 cells, and 32,768 ordered E-arm shadow events.
- Every Q07 committed-geometry gate passed; E shadow status was `PASSED` in every cell.
- Every Z cell had zero events and zero changed weights.
- All canonical acquisition hashes were structurally validated. No repeated-condition acquisition
  hash parity comparison exists in this one-condition design, so no unavailable parity was inferred.
- Secondary windows, side, tau, and endpoint-versus-base summaries use seed-level aggregation.

## Scope

This is an event-local effect conditional on states visited by the endogenous true policy in one
synthetic specimen. Q07 matches permitted support and support size within 1%; it does not force
identical realized nonzero coordinates. This therefore tests the Q07-matched endpoint substitution,
not a mathematically pure residual rotation and not a decomposition of the cumulative DH-07R effect.
"""


def analyze(run: pathlib.Path, config_path: pathlib.Path | None = None) -> dict:
    config = load_config(config_path)
    rows, bundles, execution = load_run(run, config)
    _, events, cells = validate(rows, bundles, config)
    seeds = seed_rows(events, config)
    primary_values = [row["primary_true_minus_null"] for row in seeds]
    primary = infer_seed_values(primary_values)
    bootstrap = bootstrap_interval(primary_values, config["bootstrap_resamples"],
                                   config["bootstrap_seed"])
    primary["bootstrap_ci95"] = bootstrap["ci95"]
    primary["bootstrap_resamples"] = bootstrap["resamples"]
    primary["bootstrap_seed"] = bootstrap["bootstrap_seed"]
    primary["bootstrap_rng"] = bootstrap["rng"]
    status = classify(primary["t_ci95"], primary["bootstrap_ci95"])
    secondary_columns = ["true_minus_base", "null_minus_base", "side_R", "side_L",
                         "tau_4", "tau_16",
                         *(f"window_{start}_{stop}" for start, stop in WINDOWS)]
    max_gates = {field: max(float(row[f"max_{field}"]) for row in cells if row["arm"] == "E")
                 for field in GATES}
    summary = {
        "protocol": "DH-08A",
        "status": status,
        "primary": primary,
        "secondary_seed_level": summarize_columns(seeds, secondary_columns),
        "integrity": {
            "status": "PASSED",
            "specimens": 1,
            "seed_bundles": 32,
            "bundles": len(bundles),
            "cells": len(rows),
            "e_cells": sum(row["arm"] == "E" for row in cells),
            "z_cells": sum(row["arm"] == "Z" for row in cells),
            "events": len(events),
            "events_per_seed": 2 * 2 * 256,
            "inferential_observations": 32,
            "acquisition_hashes_validated": len(rows),
            "acquisition_hash_parity_comparisons_available": 0,
            "final_true_endpoint_weight_hash_parity_checks": 128,
            "max_q07_gate_values": max_gates,
            "execution": execution,
        },
        "limitations": [
            "One synthetic specimen; computational seed bundles are the inferential units.",
            "The estimand is event-local and conditional on endogenous true-policy states.",
            "Q07 permits small within-support differences in realized zero placement.",
            "The analysis does not decompose the cumulative DH-07R policy contrast.",
        ],
    }
    analysis_dir = run / "analysis"
    analysis_dir.mkdir(exist_ok=True)
    write_csv(analysis_dir / "events.csv", events)
    write_csv(analysis_dir / "cells.csv", cells)
    write_csv(analysis_dir / "seeds.csv", seeds)
    (analysis_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    (analysis_dir / "REPORT.md").write_text(report_text(summary), encoding="utf-8")
    return summary


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("usage: analyze.py RUN_DIR [CONFIG]", file=sys.stderr)
        return 2
    try:
        run = pathlib.Path(sys.argv[1]).resolve()
        config = pathlib.Path(sys.argv[2]).resolve() if len(sys.argv) == 3 else None
        summary = analyze(run, config)
    except (AnalysisError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"DH-08A analysis failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
