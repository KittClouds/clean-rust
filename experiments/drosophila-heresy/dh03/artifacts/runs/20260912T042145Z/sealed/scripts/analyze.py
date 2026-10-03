"""Frozen DH03 factorial analysis; two co-primary channel effects."""
import itertools
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDITIONS = [
    "immediate",
    "quiet",
    "retain_both",
    "suppress_eligibility",
    "restore_state",
    "suppress_both",
]
FACTORIAL = CONDITIONS[2:]


def validate(rows, config):
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
        assert all(r["result"]["acquisition_state_sha256"] == state for r in group)
        assert all(r["result"]["outcome"]["probe_acquisition"] == probe for r in group)
        if arm == "Z":
            assert all(r["result"]["outcome"]["curve"] == group[0]["result"]["outcome"]["curve"] for r in group)
        for row in group:
            result = row["result"]
            outcome = result["outcome"]
            diagnostics = result["diagnostics"]
            intervention = result["intervention"]
            assert 0 <= outcome["probe_reversal"] <= 1
            assert 0 <= outcome["accuracy"] <= 1
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
            if condition not in FACTORIAL:
                assert intervention[1]["interval_trials"] == 0
                assert diagnostics[1]["interval_eligibility_l1_mean"] == 0
                continue
            audit = intervention[1]
            assert audit["interval_trials"] == config["trials"] // 2
            assert audit["raw_interval_eligibility_l1_mean"] > 0
            assert audit["pre_restore_state_mean_abs_mean"] > 0
            suppress = condition in {"suppress_eligibility", "suppress_both"}
            restore = condition in {"restore_state", "suppress_both"}
            assert (diagnostics[1]["interval_eligibility_l1_mean"] == 0) == suppress
            assert audit["eligibility_suppression_applied_trials"] == (
                config["trials"] // 2 if suppress else 0
            )
            assert audit["state_restoration_applied_trials"] == (
                config["trials"] // 2 if restore else 0
            )
            assert audit["eligibility_suppression_max_abs_error"] == 0
            assert audit["state_restoration_max_abs_error"] == 0
    return lookup


def effect_vectors(lookup, config, side, metric):
    by_seed_tau = {"eligibility": [], "state": [], "interaction": []}
    for seed in config["seeds"]:
        seed_values = {key: [] for key in by_seed_tau}
        for tau in config["taus"]:
            value = {
                condition: lookup[side, tau, seed, "E", condition]["result"]["outcome"][metric]
                for condition in FACTORIAL
            }
            seed_values["eligibility"].append(
                0.5 * (value["retain_both"] + value["restore_state"])
                - 0.5 * (value["suppress_eligibility"] + value["suppress_both"])
            )
            seed_values["state"].append(
                0.5 * (value["retain_both"] + value["suppress_eligibility"])
                - 0.5 * (value["restore_state"] + value["suppress_both"])
            )
            seed_values["interaction"].append(
                value["retain_both"]
                - value["suppress_eligibility"]
                - value["restore_state"]
                + value["suppress_both"]
            )
        for key in by_seed_tau:
            by_seed_tau[key].append(seed_values[key])
    return {key: np.asarray(value, dtype=float) for key, value in by_seed_tau.items()}


def summarize_effect(matrix, bootstrap_indices, taus, interval_levels=(0.95,)):
    bundles = matrix.mean(axis=1)
    samples = bundles[bootstrap_indices].mean(axis=1)
    intervals = {}
    for level in interval_levels:
        tail = (1.0 - level) / 2.0
        intervals[f"ci{100 * level:g}"] = np.quantile(samples, [tail, 1 - tail]).tolist()
    return {
        "mean": float(bundles.mean()),
        **intervals,
        "seed_effects": bundles.tolist(),
        "n_seed_bundles": len(bundles),
        "tau_means": {
            str(tau): float(matrix[:, index].mean())
            for index, tau in enumerate(taus)
        },
    }


def direction(interval):
    if interval[0] > 0:
        return "BENEFICIAL"
    if interval[1] < 0:
        return "HARMFUL"
    return "INCONCLUSIVE"


def analyze(run):
    config = json.loads((ROOT / "config.json").read_text())
    execution = json.loads((run / "execution.json").read_text())
    assert execution["complete"] and execution["protocol"] == "DH-03"
    assert config["primary_metric"] == "probe_reversal"
    rows = []
    nulls = []
    for side in config["sides"]:
        for tau in config["taus"]:
            path = run / f"{side}-tau{tau:g}.jsonl"
            records = [json.loads(line) for line in path.read_text().splitlines()]
            assert [record["seed"] for record in records] == config["seeds"]
            for bundle in records:
                null = bundle["null_routing"]
                assert null["degree_preserved"] and null["source_strength_preserved"]
                assert null["accepted"] > 0 and null["retained_fraction"] < 0.95
                assert all(
                    r["seed"] == bundle["seed"] and r["side"] == side and r["tau"] == tau
                    for r in bundle["results"]
                )
                nulls.append(null)
                rows.extend(bundle["results"])
    lookup = validate(rows, config)
    assert len(rows) == execution["outcome_rows"]

    vectors = effect_vectors(lookup, config, config["primary_side"], config["primary_metric"])
    rng = np.random.default_rng(config["bootstrap_seed"])
    indices = rng.integers(
        0,
        len(config["seeds"]),
        size=(config["bootstrap_resamples"], len(config["seeds"])),
    )
    eligibility = summarize_effect(
        vectors["eligibility"], indices, config["taus"], (0.95, 0.975)
    )
    state = summarize_effect(vectors["state"], indices, config["taus"], (0.95, 0.975))
    interaction = summarize_effect(vectors["interaction"], indices, config["taus"], (0.95,))
    eligibility["direction_97_5"] = direction(eligibility["ci97.5"])
    state["direction_97_5"] = direction(state["ci97.5"])
    status = (
        f"ELIGIBILITY_{eligibility['direction_97_5']}"
        f"__STATE_{state['direction_97_5']}"
    )

    fields = [
        "accuracy",
        "acquisition",
        "reversal",
        "late_acquisition",
        "late_reversal",
        "probe_acquisition",
        "probe_reversal",
        "seconds",
        "state_bytes",
        "work",
    ]
    means = {}
    for side in config["sides"]:
        means[side] = {}
        for arm in config["arms"]:
            means[side][arm] = {}
            for condition in CONDITIONS:
                selected = [
                    r["result"]
                    for r in rows
                    if r["side"] == side
                    and r["arm"] == arm
                    and r["condition"] == condition
                ]
                entry = {
                    field: float(np.mean([r["outcome"][field] for r in selected]))
                    for field in fields
                }
                entry["curve"] = np.mean(
                    [r["outcome"]["curve"] for r in selected], axis=0
                ).tolist()
                entry["phase_diagnostics"] = [
                    {
                        field: float(
                            np.mean([r["diagnostics"][phase][field] for r in selected])
                        )
                        for field in selected[0]["diagnostics"][phase]
                    }
                    for phase in [0, 1]
                ]
                entry["intervention"] = [
                    {
                        field: float(
                            np.mean([r["intervention"][phase][field] for r in selected])
                        )
                        for field in selected[0]["intervention"][phase]
                    }
                    for phase in [0, 1]
                ]
                for field in [
                    "observer_array_bytes",
                    "intervention_array_bytes",
                    "final_weight_floor_fraction",
                    "final_weight_ceiling_fraction",
                ]:
                    entry[field] = float(np.mean([r[field] for r in selected]))
                means[side][arm][condition] = entry

    result = {
        "status": status,
        "co_primary": {"eligibility_retained": eligibility, "state_retained": state},
        "interaction_descriptive": interaction,
        "means": means,
        "execution": execution,
        "arms": len(rows),
        "training_trials": len(rows) * config["trials"],
        "unique_acquisition_streams": len(config["sides"])
        * len(config["taus"])
        * len(config["seeds"])
        * len(config["arms"]),
        "unique_reversal_streams": len(rows),
        "all_acquisition_states_matched": True,
        "zero_hot_allocations": True,
        "numpy_version": np.__version__,
        "null_retained_range": [
            min(n["retained_fraction"] for n in nulls),
            max(n["retained_fraction"] for n in nulls),
        ],
        "total_online_edge_visits": sum(r["result"]["outcome"]["work"] for r in rows),
    }
    (run / "summary.json").write_text(json.dumps(result, indent=2) + "\n")

    def interval_text(effect, name):
        return (
            f"{name}: **{100 * effect['mean']:+.3f} pp**; paired 95% "
            f"[{100 * effect['ci95'][0]:+.3f}, {100 * effect['ci95'][1]:+.3f}]; "
            f"familywise 97.5% [{100 * effect['ci97.5'][0]:+.3f}, "
            f"{100 * effect['ci97.5'][1]:+.3f}]."
        )

    report = [
        "# DH-03 measured results",
        "",
        f"**{status}**",
        "",
        "All conditions began reversal from identical acquired states. The four "
        "factorial cells processed identical distractor schedules; only delivery "
        "of interval eligibility and post-interval neural state differed.",
        "",
        interval_text(eligibility, "Eligibility retained minus suppressed"),
        "",
        interval_text(state, "State retained minus restored"),
        "",
        f"Descriptive interaction: **{100 * interaction['mean']:+.3f} pp**, "
        f"paired 95% [{100 * interaction['ci95'][0]:+.3f}, "
        f"{100 * interaction['ci95'][1]:+.3f}].",
        "",
        f"{len(rows)} arm runs; {result['training_trials']:,} computed training "
        f"trials; {result['unique_acquisition_streams']} distinct acquisition "
        "streams reused across six conditions; 24 fresh computational seed "
        "bundles; two taus; one specimen.",
        "",
        "## Final reversal-probe accuracy",
        "",
        "| Slice | Arm | Immediate | Quiet | Retain both | Suppress eligibility | Restore state | Suppress both |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for side in config["sides"]:
        for arm in config["arms"]:
            values = " | ".join(
                f"{100 * means[side][arm][condition]['probe_reversal']:.2f}%"
                for condition in CONDITIONS
            )
            report.append(f"| {side} | {arm} | {values} |")

    report += [
        "",
        "E uses uniform local learning; Z has fixed weights. Only the two "
        "right-slice E factorial main effects are co-primary.",
        "",
        "## Right-slice intervention audit",
        "",
        "| Factorial cell | Raw interval eligibility L1 | Delivered interval L1 | Pre-restore state mean abs drift | Eligibility removals | State restorations |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for condition in FACTORIAL:
        entry = means["R"]["E"][condition]
        audit = entry["intervention"][1]
        delivered = entry["phase_diagnostics"][1]
        report.append(
            f"| {condition} | {audit['raw_interval_eligibility_l1_mean']:.3f} | "
            f"{delivered['interval_eligibility_l1_mean']:.3f} | "
            f"{audit['pre_restore_state_mean_abs_mean']:.6f} | "
            f"{audit['eligibility_suppression_applied_trials']:.0f} | "
            f"{audit['state_restoration_applied_trials']:.0f} |"
        )

    report += [
        "",
        "## Integrity and resources",
        "",
        "- Complete grid, unique cells, matched acquisition hashes, fixed-weight "
        "action parity, exact intervention receipts, event counts, and graph-null "
        "invariants passed.",
        f"- Simulator execution including setup and diagnostics: "
        f"{execution['wall_seconds']:.3f} seconds on {execution['threads']} workers.",
        "- No online-loop allocations. Observer and intervention snapshots are "
        "additional experimental instrumentation.",
        "",
        "## Interpretation limits",
        "",
        "- These are repeated causal interventions in a synthetic local learner, "
        "not a biological mediation analysis.",
        "- Restoring aggregate neural state can alter later eligibility formation; "
        "the factorial interaction is therefore reported explicitly.",
        "- Immediate and quiet are descriptive anchors and are not part of the "
        "co-primary factorial effects.",
        "- One specimen; left and right are related soma slices. No biological "
        "functional validation or universal-learning claim follows.",
        "- No post-outcome tuning, extra seeds, rule search, or endpoint change.",
        "",
        "Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. "
        "https://male-cns.janelia.org/download/",
    ]
    (run / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "co_primary": result["co_primary"],
                "interaction": interaction,
                "arms": len(rows),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    analyze(pathlib.Path(sys.argv[1]))
