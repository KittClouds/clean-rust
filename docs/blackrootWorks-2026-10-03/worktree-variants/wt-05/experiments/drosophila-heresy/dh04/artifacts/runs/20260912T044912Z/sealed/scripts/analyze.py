"""Frozen DH04 analysis: prespecified partial-erasure intersection rule."""
import itertools
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDITIONS = ["immediate", "quiet", "eligibility_retained", "eligibility_suppressed"]


def validate(rows, bundles, config):
    keys = [(r["side"], r["tau"], r["seed"], r["arm"], r["condition"]) for r in rows]
    expected = set(
        itertools.product(
            config["sides"], config["taus"], config["seeds"], config["arms"], CONDITIONS
        )
    )
    assert len(keys) == len(set(keys)), "duplicate outcome cell"
    assert set(keys) == expected, "missing or unexpected outcome cell"
    lookup = dict(zip(keys, rows))
    for side, tau, seed, arm in itertools.product(
        config["sides"], config["taus"], config["seeds"], config["arms"]
    ):
        group = [lookup[side, tau, seed, arm, condition] for condition in CONDITIONS]
        state = group[0]["result"]["acquisition_state_sha256"]
        probe = group[0]["result"]["outcome"]["probe_acquisition"]
        margin = group[0]["result"]["weight_geometry"]["acquired_old_map_margin"]
        assert all(r["result"]["acquisition_state_sha256"] == state for r in group)
        assert all(r["result"]["outcome"]["probe_acquisition"] == probe for r in group)
        assert all(
            r["result"]["weight_geometry"]["acquired_old_map_margin"] == margin for r in group
        )
        if arm == "Z":
            assert all(r["result"]["outcome"]["curve"] == group[0]["result"]["outcome"]["curve"] for r in group)
        for row in group:
            result = row["result"]
            outcome = result["outcome"]
            diagnostics = result["diagnostics"]
            intervention = result["intervention"]
            assert abs(
                result["paired_final_old_probe"] + result["paired_final_reversal_probe"] - 1
            ) < 1e-15
            assert outcome["hot_allocations"] == 0
            assert outcome["unique_cue_codes"] == config["cues"]
            assert outcome["max_gain_mass_error"] < 1e-5
            assert arm != "Z" or outcome["changed_weights"] == 0
            assert all(phase["trials"] == config["trials"] // 2 for phase in diagnostics)
            assert diagnostics[0]["interval_eligibility_l1_mean"] == 0
            assert intervention[0]["interval_trials"] == 0
            condition = row["condition"]
            expected_events = (
                config["trials"]
                if condition == "immediate"
                else config["trials"] // 2 * (config["delay_steps"] + 2)
            )
            assert outcome["stimulus_events"] == expected_events
            if condition not in CONDITIONS[2:]:
                assert intervention[1]["interval_trials"] == 0
                assert diagnostics[1]["interval_eligibility_l1_mean"] == 0
                continue
            audit = intervention[1]
            assert audit["interval_trials"] == config["trials"] // 2
            assert audit["raw_interval_eligibility_l1_mean"] > 0
            assert audit["pre_restore_state_mean_abs_mean"] > 0
            assert audit["state_restoration_applied_trials"] == config["trials"] // 2
            assert audit["state_restoration_max_abs_error"] == 0
            suppressed = condition == "eligibility_suppressed"
            assert (diagnostics[1]["interval_eligibility_l1_mean"] == 0) == suppressed
            assert audit["eligibility_suppression_applied_trials"] == (
                config["trials"] // 2 if suppressed else 0
            )
            assert audit["eligibility_suppression_max_abs_error"] == 0
    for bundle in bundles:
        geometry = bundle["eligibility_contrast_geometry"]
        assert set(geometry) == set(config["arms"])
        assert all(value is not None for value in geometry["E"].values())
        assert all(value is None for value in geometry["Z"].values())
    return lookup


def nested(row, path):
    value = row["result"]
    for key in path:
        value = value[key]
    return value


def seed_tau_matrix(lookup, config, side, path, first, second=None):
    matrix = []
    for seed in config["seeds"]:
        by_tau = []
        for tau in config["taus"]:
            value = nested(lookup[side, tau, seed, "E", first], path)
            if second is not None:
                value -= nested(lookup[side, tau, seed, "E", second], path)
            by_tau.append(value)
        matrix.append(by_tau)
    return np.asarray(matrix, dtype=float)


def summarize(matrix, indices, taus):
    bundles = matrix.mean(axis=1)
    samples = bundles[indices].mean(axis=1)
    return {
        "mean": float(bundles.mean()),
        "ci95": np.quantile(samples, [0.025, 0.975]).tolist(),
        "seed_values": bundles.tolist(),
        "n_seed_bundles": len(bundles),
        "tau_means": {
            str(tau): float(matrix[:, index].mean())
            for index, tau in enumerate(taus)
        },
    }


def classify(accuracy, coordinate_effect, retained_coordinate, retained_margin):
    if (
        accuracy["ci95"][0] > 0
        and coordinate_effect["ci95"][1] < 0
        and retained_coordinate["ci95"][0] > 0
        and retained_coordinate["ci95"][1] < 1
        and retained_margin["ci95"][0] > 0
    ):
        return "PARTIAL_ERASURE_SUPPORTED_IN_MODEL"
    if (
        accuracy["ci95"][0] > 0
        and retained_coordinate["ci95"][1] < 0
        and retained_margin["ci95"][1] < 0
    ):
        return "REVERSED_ACQUISITION_SUPPORTED_IN_MODEL"
    return "MECHANISM_UNRESOLVED"


def analyze(run):
    config = json.loads((ROOT / "config.json").read_text())
    execution = json.loads((run / "execution.json").read_text())
    assert execution["complete"] and execution["protocol"] == "DH-04"
    rows = []
    bundles = []
    nulls = []
    for side in config["sides"]:
        for tau in config["taus"]:
            records = [
                json.loads(line)
                for line in (run / f"{side}-tau{tau:g}.jsonl").read_text().splitlines()
            ]
            assert [record["seed"] for record in records] == config["seeds"]
            for bundle in records:
                null = bundle["null_routing"]
                assert null["degree_preserved"] and null["source_strength_preserved"]
                assert null["accepted"] > 0 and null["retained_fraction"] < 0.95
                assert all(
                    row["seed"] == bundle["seed"]
                    and row["side"] == side
                    and row["tau"] == tau
                    for row in bundle["results"]
                )
                bundles.append(bundle)
                nulls.append(null)
                rows.extend(bundle["results"])
    lookup = validate(rows, bundles, config)
    assert len(rows) == execution["outcome_rows"]

    rng = np.random.default_rng(config["bootstrap_seed"])
    indices = rng.integers(
        0,
        len(config["seeds"]),
        size=(config["bootstrap_resamples"], len(config["seeds"])),
    )
    side = config["primary_side"]
    accuracy = summarize(
        seed_tau_matrix(
            lookup,
            config,
            side,
            ["paired_final_reversal_probe"],
            "eligibility_retained",
            "eligibility_suppressed",
        ),
        indices,
        config["taus"],
    )
    coordinate_effect = summarize(
        seed_tau_matrix(
            lookup,
            config,
            side,
            ["weight_geometry", "acquisition_axis_coordinate"],
            "eligibility_retained",
            "eligibility_suppressed",
        ),
        indices,
        config["taus"],
    )
    retained_coordinate = summarize(
        seed_tau_matrix(
            lookup,
            config,
            side,
            ["weight_geometry", "acquisition_axis_coordinate"],
            "eligibility_retained",
        ),
        indices,
        config["taus"],
    )
    retained_margin = summarize(
        seed_tau_matrix(
            lookup,
            config,
            side,
            ["weight_geometry", "final_old_map_margin"],
            "eligibility_retained",
        ),
        indices,
        config["taus"],
    )
    status = classify(accuracy, coordinate_effect, retained_coordinate, retained_margin)

    fields = [
        "accuracy",
        "acquisition",
        "reversal",
        "late_reversal",
        "probe_acquisition",
        "probe_reversal",
        "paired_final_old_probe",
        "paired_final_reversal_probe",
    ]
    means = {}
    for current_side in config["sides"]:
        means[current_side] = {}
        for arm in config["arms"]:
            means[current_side][arm] = {}
            for condition in CONDITIONS:
                selected = [
                    row["result"]
                    for row in rows
                    if row["side"] == current_side
                    and row["arm"] == arm
                    and row["condition"] == condition
                ]
                entry = {}
                for field in fields:
                    if field in selected[0]:
                        entry[field] = float(np.mean([row[field] for row in selected]))
                    else:
                        entry[field] = float(np.mean([row["outcome"][field] for row in selected]))
                entry["curve"] = np.mean(
                    [row["outcome"]["curve"] for row in selected], axis=0
                ).tolist()
                entry["weight_geometry"] = {
                    field: float(np.mean([row["weight_geometry"][field] for row in selected]))
                    for field in selected[0]["weight_geometry"]
                    if selected[0]["weight_geometry"][field] is not None
                }
                entry["immediate_reference"] = {
                    field: float(np.mean([row["immediate_reference"][field] for row in selected]))
                    for field in selected[0]["immediate_reference"]
                    if selected[0]["immediate_reference"][field] is not None
                }
                entry["phase_diagnostics"] = [
                    {
                        field: float(
                            np.mean([row["diagnostics"][phase][field] for row in selected])
                        )
                        for field in selected[0]["diagnostics"][phase]
                    }
                    for phase in [0, 1]
                ]
                entry["intervention"] = [
                    {
                        field: float(
                            np.mean([row["intervention"][phase][field] for row in selected])
                        )
                        for field in selected[0]["intervention"][phase]
                    }
                    for phase in [0, 1]
                ]
                means[current_side][arm][condition] = entry

    contrast_fields = list(
        bundles[0]["eligibility_contrast_geometry"]["E"].keys()
    )
    contrast_geometry = {
        current_side: {
            field: float(
                np.mean(
                    [
                        bundle["eligibility_contrast_geometry"]["E"][field]
                        for bundle in bundles
                        if bundle["results"][0]["side"] == current_side
                    ]
                )
            )
            for field in contrast_fields
        }
        for current_side in config["sides"]
    }
    result = {
        "status": status,
        "primary_components": {
            "retained_minus_suppressed_reversal_probe": accuracy,
            "retained_minus_suppressed_acquisition_axis": coordinate_effect,
            "retained_acquisition_axis_coordinate": retained_coordinate,
            "retained_final_old_map_margin": retained_margin,
        },
        "means": means,
        "eligibility_contrast_geometry": contrast_geometry,
        "execution": execution,
        "arms": len(rows),
        "training_trials": len(rows) * config["trials"],
        "unique_acquisition_streams": len(config["sides"])
        * len(config["taus"])
        * len(config["seeds"])
        * len(config["arms"]),
        "all_acquisition_states_matched": True,
        "same_rng_probes_complementary": True,
        "zero_hot_allocations": True,
        "numpy_version": np.__version__,
        "null_retained_range": [
            min(null["retained_fraction"] for null in nulls),
            max(null["retained_fraction"] for null in nulls),
        ],
    }
    (run / "summary.json").write_text(json.dumps(result, indent=2) + "\n")

    def line(name, value, scale=1):
        return (
            f"{name}: **{scale * value['mean']:+.3f}**; paired 95% "
            f"[{scale * value['ci95'][0]:+.3f}, {scale * value['ci95'][1]:+.3f}]."
        )

    report = [
        "# DH-04 measured results",
        "",
        f"**{status}**",
        "",
        line("Retained minus suppressed reversed-probe effect, percentage points", accuracy, 100),
        "",
        line("Retained minus suppressed acquisition-axis coordinate", coordinate_effect),
        "",
        line("Retained final acquisition-axis coordinate", retained_coordinate),
        "",
        line("Retained final deterministic old-map margin", retained_margin),
        "",
        "The acquisition axis assigns initial weights coordinate 0 and acquired "
        "weights coordinate 1. Positive old-map margin means the acquired target "
        "mapping remains preferred.",
        "",
        f"{len(rows)} arm runs; {result['training_trials']:,} computed training "
        f"trials; {result['unique_acquisition_streams']} acquisition streams "
        "repeated across four conditions; 24 fresh seed bundles; two taus; one specimen.",
        "",
        "## Final same-RNG probes and weight geometry",
        "",
        "| Slice | Arm | Condition | Old-map probe | Reversed probe | Acquisition-axis q | Old-map margin |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for current_side in config["sides"]:
        for arm in config["arms"]:
            for condition in CONDITIONS:
                entry = means[current_side][arm][condition]
                geometry = entry["weight_geometry"]
                coordinate = geometry.get("acquisition_axis_coordinate")
                coordinate_text = "n/a" if coordinate is None else f"{coordinate:.4f}"
                report.append(
                    f"| {current_side} | {arm} | {condition} | "
                    f"{100 * entry['paired_final_old_probe']:.2f}% | "
                    f"{100 * entry['paired_final_reversal_probe']:.2f}% | "
                    f"{coordinate_text} | {geometry['final_old_map_margin']:.6f} |"
                )
    report += [
        "",
        "## Descriptive immediate-reference geometry",
        "",
        "| Condition | Cosine to immediate reversal delta | Distance to immediate final / immediate delta |",
        "|---|---:|---:|",
    ]
    for condition in CONDITIONS:
        reference = means["R"]["E"][condition]["immediate_reference"]
        report.append(
            f"| {condition} | {reference['reversal_delta_cosine_to_immediate']:.4f} | "
            f"{reference['distance_to_immediate_final_over_immediate_delta']:.4f} |"
        )
    contrast = contrast_geometry["R"]
    report += [
        "",
        "Retained-minus-suppressed eligibility contribution: negative-acquisition-axis "
        f"projection {contrast['retained_minus_suppressed_projection_on_negative_acquisition_axis']:.4f}; "
        "cosine to immediate reversal delta "
        f"{contrast['retained_minus_suppressed_cosine_to_immediate_reversal_delta']:.4f}; "
        "norm/acquisition norm "
        f"{contrast['retained_minus_suppressed_norm_over_acquisition_norm']:.4f}.",
        "",
        "## Integrity and limits",
        "",
        "- Complete grid, matching acquisition hashes and margins, fixed-weight "
        "action parity, exact intervention receipts, same-RNG probe complements, "
        "event counts, and graph-null invariants passed.",
        f"- Simulator execution including setup and diagnostics: "
        f"{execution['wall_seconds']:.3f} seconds on {execution['threads']} workers.",
        "- No online-loop allocations. Snapshot and geometry buffers are additional "
        "experimental instrumentation.",
        "- Weight geometry and action margins are model-coordinate evidence. They "
        "do not identify a biological mechanism.",
        "- One specimen; left/right are related soma slices. Synthetic dynamics, "
        "labels, bounds, clipping, and readout remain modelling choices.",
        "- No post-outcome tuning, extra seeds, endpoint changes, or rule search.",
        "",
        "Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. "
        "https://male-cns.janelia.org/download/",
    ]
    (run / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "primary_components": result["primary_components"],
                "arms": len(rows),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    analyze(pathlib.Path(sys.argv[1]))
