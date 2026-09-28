"""Frozen DH05 trajectory analysis."""
import itertools
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDITIONS = ["immediate", "quiet", "eligibility_retained", "eligibility_suppressed"]


def validate(rows, bundles, config):
    expected = set(itertools.product(
        config["sides"], config["taus"], config["seeds"], config["arms"], CONDITIONS
    ))
    keys = [(r["side"], r["tau"], r["seed"], r["arm"], r["condition"]) for r in rows]
    assert len(keys) == len(set(keys)), "duplicate outcome cell"
    assert set(keys) == expected, "missing or unexpected outcome cell"
    lookup = dict(zip(keys, rows))
    checkpoints = config["primary_checkpoints"]
    for side, tau, seed, arm in itertools.product(
        config["sides"], config["taus"], config["seeds"], config["arms"]
    ):
        group = [lookup[side, tau, seed, arm, c] for c in CONDITIONS]
        state = group[0]["result"]["acquisition_state_sha256"]
        assert all(r["result"]["acquisition_state_sha256"] == state for r in group)
        for row in group:
            result = row["result"]
            outcome = result["outcome"]
            assert [p["reversal_trials"] for p in result["trajectory"]] == checkpoints
            assert outcome["hot_allocations"] == 0
            assert outcome["unique_cue_codes"] == config["cues"]
            assert outcome["max_gain_mass_error"] < 1e-5
            assert arm != "Z" or outcome["changed_weights"] == 0
            assert abs(result["paired_final_old_probe"] +
                       result["paired_final_reversal_probe"] - 1) < 1e-15
            assert result["intervention"][0]["interval_trials"] == 0
            condition = row["condition"]
            expected_events = config["trials"] if condition == "immediate" else \
                config["trials"] // 2 * (config["delay_steps"] + 2)
            assert outcome["stimulus_events"] == expected_events
            if condition in CONDITIONS[2:]:
                audit = result["intervention"][1]
                assert audit["interval_trials"] == config["trials"] // 2
                assert audit["state_restoration_applied_trials"] == config["trials"] // 2
                assert audit["state_restoration_max_abs_error"] == 0
                suppressed = condition == "eligibility_suppressed"
                assert (result["diagnostics"][1]["interval_eligibility_l1_mean"] == 0) == suppressed
            else:
                assert result["intervention"][1]["interval_trials"] == 0
                assert result["diagnostics"][1]["interval_eligibility_l1_mean"] == 0
    for bundle in bundles:
        assert set(bundle["eligibility_contrast_geometry"]) == set(config["arms"])
    return lookup


def result_matrix(lookup, config, side, condition, field):
    return np.asarray([
        [lookup[side, tau, seed, config["primary_arm"], condition]["result"][field]
         for tau in config["taus"]]
        for seed in config["seeds"]
    ], dtype=float)


def trajectory_matrix(lookup, config, side, condition, field, checkpoint):
    return np.asarray([
        [lookup[side, tau, seed, config["primary_arm"], condition]["result"]["trajectory"]
         [checkpoint][field] for tau in config["taus"]]
        for seed in config["seeds"]
    ], dtype=float)


def summarize(matrix, indices, taus):
    bundles = np.asarray(matrix, dtype=float).mean(axis=1)
    samples = bundles[indices].mean(axis=1)
    return {
        "mean": float(bundles.mean()),
        "ci95": np.quantile(samples, [0.025, 0.975]).tolist(),
        "seed_values": bundles.tolist(),
        "tau_means": {str(t): float(np.asarray(matrix)[:, i].mean())
                      for i, t in enumerate(taus)},
        "n_seed_bundles": len(bundles),
    }


def analyze(run):
    config = json.loads((ROOT / "config.json").read_text())
    execution = json.loads((run / "execution.json").read_text())
    assert execution["complete"] and execution["protocol"] == "DH-05"
    rows, bundles = [], []
    for side in config["sides"]:
        for tau in config["taus"]:
            records = [json.loads(line) for line in
                       (run / f"{side}-tau{tau:g}.jsonl").read_text().splitlines()]
            assert [r["seed"] for r in records] == config["seeds"]
            for bundle in records:
                assert all(r["side"] == side and r["tau"] == tau and
                           r["seed"] == bundle["seed"] for r in bundle["results"])
                bundles.append(bundle)
                rows.extend(bundle["results"])
    lookup = validate(rows, bundles, config)
    assert len(rows) == execution["outcome_rows"]
    rng = np.random.default_rng(config["bootstrap_seed"])
    indices = rng.integers(0, len(config["seeds"]),
                           size=(config["bootstrap_resamples"], len(config["seeds"])))
    side = config["primary_side"]
    retained, suppressed = "eligibility_retained", "eligibility_suppressed"
    margin_effect = summarize(
        result_matrix(lookup, config, side, retained, "paired_final_old_probe") -
        result_matrix(lookup, config, side, suppressed, "paired_final_old_probe"),
        indices, config["taus"])
    projection_effect = summarize(
        trajectory_matrix(lookup, config, side, retained,
                           "acquisition_axis_projection", -1) -
        trajectory_matrix(lookup, config, side, suppressed,
                           "acquisition_axis_projection", -1),
        indices, config["taus"])
    fields = ["old_map_margin", "reversed_map_margin",
              "acquisition_axis_coordinate", "acquisition_axis_projection",
              "reversal_parallel_projection", "reversal_perpendicular_norm"]
    trajectory_means = {}
    for condition in CONDITIONS:
        trajectory_means[condition] = {}
        for field in fields:
            trajectory_means[condition][field] = [
                float(trajectory_matrix(lookup, config, side, condition, field, i).mean())
                for i in range(len(config["primary_checkpoints"]))
            ]
    result = {
        "status": "TRAJECTORY_ASSAY_COMPLETE",
        "primary": {
            "retained_minus_suppressed_final_old_probe": margin_effect,
            "retained_minus_suppressed_final_acquisition_axis_projection": projection_effect,
        },
        "checkpoints": config["primary_checkpoints"],
        "trajectory_means": trajectory_means,
        "execution": execution,
        "arms": len(rows),
        "training_trials": len(rows) * config["trials"],
        "unique_acquisition_streams": len(config["sides"]) * len(config["taus"]) *
        len(config["seeds"]) * len(config["arms"]),
        "same_rng_probes_complementary": True,
        "zero_hot_allocations": True,
        "numpy_version": np.__version__,
    }
    (run / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    report = [
        "# DH-05 measured results", "", "**TRAJECTORY_ASSAY_COMPLETE**", "",
        "DH-05 measured the DH-04 causal cells at declared reversal checkpoints.",
        "",
        f"Final old-map probe, retained minus suppressed: **{100 * margin_effect['mean']:+.3f} pp**; "
        f"95% [{100 * margin_effect['ci95'][0]:+.3f}, {100 * margin_effect['ci95'][1]:+.3f}].",
        "",
        f"Final acquisition-axis projection, retained minus suppressed: **{projection_effect['mean']:+.6f}**; "
        f"95% [{projection_effect['ci95'][0]:+.6f}, {projection_effect['ci95'][1]:+.6f}].",
        "",
        f"{len(rows)} arm runs; {result['training_trials']:,} computed training trials; "
        "24 fresh seed bundles; two taus; one specimen.",
        "",
        "## Right-slice E trajectory means", "",
        "| Field | Condition | " + " | ".join(f"t={t}" for t in config["primary_checkpoints"]) + " |",
        "|---|---|" + "---:|" * len(config["primary_checkpoints"]),
    ]
    for field in fields:
        for condition in CONDITIONS:
            values = trajectory_means[condition][field]
            report.append("| " + field + " | " + condition + " | " +
                          " | ".join(f"{v:+.6f}" for v in values) + " |")
    report += [
        "", "## Integrity and limits", "",
        "- Acquisition hashes, checkpoint vectors, DH-04 causal compatibility, "
        "same-RNG probe complements, event counts, and zero online allocations passed.",
        f"- Simulator execution including setup and diagnostics: {execution['wall_seconds']:.3f} seconds "
        f"on {execution['threads']} workers.",
        "- Margins and weight projections are model diagnostics. The trajectory "
        "does not establish a biological mechanism.",
        "- No new intervention, rule search, extra seed, or post-outcome tuning.",
        "",
        "Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. "
        "https://male-cns.janelia.org/download/",
    ]
    (run / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "primary": result["primary"]}, indent=2))


if __name__ == "__main__":
    analyze(pathlib.Path(sys.argv[1]))
