"""Frozen DH06 factorial geometry analysis."""
import itertools
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDITIONS = ["immediate", "quiet", "neither", "parallel_only", "perpendicular_only", "both"]
CAUSAL = CONDITIONS[2:]


def summarize(matrix, indices, taus, interval="ci95"):
    bundles = np.asarray(matrix, dtype=float).mean(axis=1)
    samples = bundles[indices].mean(axis=1)
    quantiles = [0.0125, 0.9875] if interval == "ci97_5" else [0.025, 0.975]
    return {
        "mean": float(bundles.mean()),
        interval: np.quantile(samples, quantiles).tolist(),
        "seed_values": bundles.tolist(),
        "tau_means": {str(t): float(np.asarray(matrix)[:, i].mean()) for i, t in enumerate(taus)},
        "n_seed_bundles": len(bundles),
    }


def validate(rows, bundles, config):
    expected = set(itertools.product(config["sides"], config["taus"], config["seeds"], config["arms"], CONDITIONS))
    keys = [(r["side"], r["tau"], r["seed"], r["arm"], r["condition"]) for r in rows]
    assert len(keys) == len(set(keys)), "duplicate outcome cell"
    assert set(keys) == expected, "missing or unexpected outcome cell"
    lookup = dict(zip(keys, rows))
    checkpoints = config["primary_checkpoints"]
    for side, tau, seed, arm in itertools.product(config["sides"], config["taus"], config["seeds"], config["arms"]):
        group = [lookup[side, tau, seed, arm, condition] for condition in CONDITIONS]
        state = group[0]["result"]["acquisition_state_sha256"]
        assert all(row["result"]["acquisition_state_sha256"] == state for row in group)
        for row in group:
            result = row["result"]
            outcome = result["outcome"]
            assert [point["reversal_trials"] for point in result["trajectory"]] == checkpoints
            assert outcome["hot_allocations"] == 0
            assert outcome["unique_cue_codes"] == config["cues"]
            assert outcome["max_gain_mass_error"] < 1e-5
            assert arm != "Z" or outcome["changed_weights"] == 0
            assert abs(result["paired_final_old_probe"] + result["paired_final_reversal_probe"] - 1) < 1e-15
            condition = row["condition"]
            expected_events = config["trials"] if condition == "immediate" else config["trials"] // 2 * (config["delay_steps"] + 2)
            assert outcome["stimulus_events"] == expected_events
            if condition in CAUSAL:
                audit = result["intervention"][1]
                geometry = result["geometry"]
                assert audit["interval_trials"] == config["trials"] // 2
                assert audit["state_restoration_applied_trials"] == config["trials"] // 2
                assert audit["state_restoration_max_abs_error"] == 0
                assert geometry["interval_trials"] == config["trials"] // 2 if arm == "E" else geometry["interval_trials"] == 0
                if arm == "E":
                    assert geometry["q_negative"] + geometry["q_positive"] + geometry["q_zero"] == geometry["interval_trials"]
                    assert geometry["reconstruction_max_abs_error"] <= 1e-6
                suppressed = condition == "neither"
                assert (result["diagnostics"][1]["interval_eligibility_l1_mean"] == 0) == suppressed
            else:
                assert result["intervention"][1]["interval_trials"] == 0
                assert result["diagnostics"][1]["interval_eligibility_l1_mean"] == 0
                assert result["geometry"]["interval_trials"] == 0
    return lookup


def result_matrix(lookup, config, side, condition, field):
    return np.asarray([[lookup[side, tau, seed, config["primary_arm"], condition]["result"][field] for tau in config["taus"]] for seed in config["seeds"]], dtype=float)


def trajectory_matrix(lookup, config, side, condition, field, checkpoint):
    return np.asarray([[lookup[side, tau, seed, config["primary_arm"], condition]["result"]["trajectory"][checkpoint][field] for tau in config["taus"]] for seed in config["seeds"]], dtype=float)


def factorial_matrix(lookup, config, side, field, checkpoint=None):
    def matrix(condition):
        if checkpoint is None:
            return result_matrix(lookup, config, side, condition, field)
        return trajectory_matrix(lookup, config, side, condition, field, checkpoint)

    neither = matrix("neither")
    parallel = matrix("parallel_only")
    perpendicular = matrix("perpendicular_only")
    both = matrix("both")
    return {
        "parallel_effect": (parallel - neither + both - perpendicular) / 2,
        "perpendicular_effect": (perpendicular - neither + both - parallel) / 2,
        "interaction": both - parallel - perpendicular + neither,
        "both_minus_neither": both - neither,
    }


def analyze(run):
    config = json.loads((ROOT / "config.json").read_text())
    execution = json.loads((run / "execution.json").read_text())
    assert execution["complete"] and execution["protocol"] == "DH-06"
    rows, bundles = [], []
    for side in config["sides"]:
        for tau in config["taus"]:
            records = [json.loads(line) for line in (run / f"{side}-tau{tau:g}.jsonl").read_text().splitlines()]
            assert [record["seed"] for record in records] == config["seeds"]
            for bundle in records:
                assert all(row["side"] == side and row["tau"] == tau and row["seed"] == bundle["seed"] for row in bundle["results"])
                bundles.append(bundle)
                rows.extend(bundle["results"])
    lookup = validate(rows, bundles, config)
    assert len(rows) == execution["outcome_rows"]
    rng = np.random.default_rng(config["bootstrap_seed"])
    indices = rng.integers(0, len(config["seeds"]), size=(config["bootstrap_resamples"], len(config["seeds"])))
    side = config["primary_side"]
    old = {condition: trajectory_matrix(lookup, config, side, condition, "old_map_margin", -1) for condition in CAUSAL}
    coordinate = {condition: trajectory_matrix(lookup, config, side, condition, "acquisition_axis_coordinate", -1) for condition in CAUSAL}
    old_factorial = factorial_matrix(lookup, config, side, "old_map_margin", -1)
    coordinate_factorial = factorial_matrix(lookup, config, side, "acquisition_axis_coordinate", -1)
    primary = {
        "perpendicular_effect_on_old_map_margin": summarize(old_factorial["perpendicular_effect"], indices, config["taus"], "ci97_5"),
        "parallel_effect_on_acquisition_axis_coordinate": summarize(coordinate_factorial["parallel_effect"], indices, config["taus"], "ci97_5"),
    }
    secondary = {
        "parallel_effect_on_old_map_margin": summarize(old_factorial["parallel_effect"], indices, config["taus"]),
        "perpendicular_effect_on_acquisition_axis_coordinate": summarize(coordinate_factorial["perpendicular_effect"], indices, config["taus"]),
        "old_map_interaction": summarize(old_factorial["interaction"], indices, config["taus"]),
        "acquisition_axis_interaction": summarize(coordinate_factorial["interaction"], indices, config["taus"]),
        "both_minus_neither_old_map_margin": summarize(old_factorial["both_minus_neither"], indices, config["taus"]),
        "both_minus_neither_acquisition_axis_coordinate": summarize(coordinate_factorial["both_minus_neither"], indices, config["taus"]),
    }
    fields = ["old_map_margin", "reversed_map_margin", "acquisition_axis_coordinate", "acquisition_axis_projection", "reversal_parallel_projection", "reversal_perpendicular_norm"]
    trajectory_means = {condition: {field: [float(trajectory_matrix(lookup, config, side, condition, field, i).mean()) for i in range(len(config["primary_checkpoints"]))] for field in fields} for condition in CONDITIONS}
    geometry_fields = ["realized_interval_l1_mean", "parallel_energy_fraction", "perpendicular_energy_fraction", "q_negative", "q_positive", "q_zero", "support_zero_events", "reconstruction_max_abs_error"]
    geometry_means = {condition: {field: float(np.asarray([[lookup[side, tau, seed, config["primary_arm"], condition]["result"]["geometry"][field] for tau in config["taus"]] for seed in config["seeds"]], dtype=float).mean()) for field in geometry_fields} for condition in CAUSAL}
    geometry_window_means = {condition: [{key: float(np.asarray([[lookup[side, tau, seed, config["primary_arm"], condition]["result"]["geometry"]["windows"][window][key] for tau in config["taus"]] for seed in config["seeds"]], dtype=float).mean()) for key in ["negative", "positive", "zero"]} for window in range(5)] for condition in CAUSAL}
    result = {
        "status": "GEOMETRY_ASSAY_COMPLETE",
        "primary": primary,
        "secondary": secondary,
        "checkpoints": config["primary_checkpoints"],
        "trajectory_means": trajectory_means,
        "geometry_means": geometry_means,
        "geometry_window_means": geometry_window_means,
        "execution": execution,
        "arms": len(rows),
        "training_trials": len(rows) * config["trials"],
        "unique_acquisition_streams": len(config["sides"]) * len(config["taus"]) * len(config["seeds"]) * len(config["arms"]),
        "same_rng_probes_complementary": True,
        "zero_hot_allocations": True,
        "numpy_version": np.__version__,
    }
    (run / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    report = ["# DH-06 measured results", "", "**GEOMETRY_ASSAY_COMPLETE**", "", "DH-06 decomposed realized interval eligibility plasticity into acquisition-aligned and support-masked orthogonal components.", "", f"Perpendicular factorial effect on final old-map margin: **{primary['perpendicular_effect_on_old_map_margin']['mean']:+.6f}**; 97.5% familywise [{primary['perpendicular_effect_on_old_map_margin']['ci97_5'][0]:+.6f}, {primary['perpendicular_effect_on_old_map_margin']['ci97_5'][1]:+.6f}].", "", f"Parallel factorial effect on final acquisition-axis coordinate: **{primary['parallel_effect_on_acquisition_axis_coordinate']['mean']:+.6f}**; 97.5% familywise [{primary['parallel_effect_on_acquisition_axis_coordinate']['ci97_5'][0]:+.6f}, {primary['parallel_effect_on_acquisition_axis_coordinate']['ci97_5'][1]:+.6f}].", "", f"{len(rows)} arm runs; {result['training_trials']:,} computed training trials; {len(config['seeds'])} fresh seed bundles; two taus; one specimen.", "", "## Right-slice E trajectory means", "", "| Field | Condition | " + " | ".join(f"t={t}" for t in config["primary_checkpoints"]) + " |", "|---|---|" + "---:|" * len(config["primary_checkpoints"])]
    for field in fields:
        for condition in CONDITIONS:
            values = trajectory_means[condition][field]
            report.append("| " + field + " | " + condition + " | " + " | ".join(f"{value:+.6f}" for value in values) + " |")
    report += ["", "## Geometry diagnostics", "", "| Condition | Interval L1 mean | Parallel energy | Perpendicular energy | q<0 | q>0 | q=0 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for condition in CAUSAL:
        values = geometry_means[condition]
        report.append(f"| {condition} | {values['realized_interval_l1_mean']:.6f} | {values['parallel_energy_fraction']:.6f} | {values['perpendicular_energy_fraction']:.6f} | {values['q_negative']:.1f} | {values['q_positive']:.1f} | {values['q_zero']:.1f} |")
    report += ["", "### q sign by reversal window", "", "| Condition | Window | q<0 | q>0 | q=0 |", "|---|---|---:|---:|---:|"]
    window_labels = ["1-16", "17-32", "33-64", "65-128", "129-256"]
    for condition in CAUSAL:
        for label, values in zip(window_labels, geometry_window_means[condition]):
            report.append(f"| {condition} | {label} | {values['negative']:.1f} | {values['positive']:.1f} | {values['zero']:.1f} |")
    report += ["", "## Integrity and limits", "", "- Acquisition hashes, checkpoint vectors, factorial compatibility, same-RNG probe complements, event counts, realized-update reconstruction, and zero online allocations were checked.", f"- Simulator execution including setup and diagnostics: {execution['wall_seconds']:.3f} seconds on {execution['threads']} workers.", "- Margins and weight projections are synthetic model diagnostics. The trajectory does not establish a biological mechanism or general learning rule.", "- No shuffled-orthogonal control, four-class task, rule search, extra seed top-up, or post-outcome tuning.", "", "Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/"]
    (run / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "primary": result["primary"]}, indent=2))


if __name__ == "__main__":
    analyze(pathlib.Path(sys.argv[1]))
