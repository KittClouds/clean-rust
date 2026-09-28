import copy
import csv
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import analyze


def config_fixture() -> dict:
    return {
        "observe": True,
        "seeds": list(range(8000, 8032)),
        "taus": [4.0, 16.0],
        "sides": ["R", "L"],
        "conditions": ["true_perpendicular"],
        "arms": ["E", "Z"],
        "cues": 16, "delay_steps": 12, "trials": 512,
        "eta": 0.05, "glut_sign": -1.0, "input_salt": 858980352,
        "threads": 4, "bootstrap_resamples": 20_000,
        "bootstrap_seed": 2026091608,
    }


def geometry_fixture(trial: int) -> dict:
    return {
        "trial": trial, "moves": 10, "sweeps": 1, "support": 100,
        "rotatable_support": 98, "true_nonzero": 100, "null_nonzero": 100,
        "true_lower": 2, "true_upper": 3, "null_lower": 2, "null_upper": 3,
        "boundary_symmetric_difference": 0, "true_norm": 0.2,
        "true_axial": -0.01, "null_axial": -0.01,
        "axial_absolute_error": 1e-10, "axial_error_over_total_norm": 2e-8,
        "axial_relative_error": 1e-8, "norm_relative_error": 3e-8,
        "residual_norm_relative_error": 4e-8, "residual_abs_cosine": 5e-6,
        "support_residual_abs_cosine": 4e-6, "max_bound_violation": 0.0,
        "outside_support_changes": 0, "minimum_found_not_global_optimum": True,
        "hot_allocations": 0,
    }


def event_fixture(seed: int, side: str, tau: float, trial: int, sign: float = 1.0) -> dict:
    seed_term = (seed - 8000) * 0.00001
    repeated_term = (0.00002 if side == "R" else -0.00002) + tau * 0.000001
    delta = sign * (0.001 + seed_term + repeated_term + trial * 0.0000001)
    base = 0.03 + trial * 1e-7
    null = base - 0.002
    true = null + delta
    return {
        "trial": trial, "base_margin": base, "true_margin": true,
        "null_margin": null, "true_minus_null": true - null,
        "true_endpoint_sha256": [(seed + trial) % 256] * 32,
        "geometry_valid": True, "shadow_hot_allocations": 0,
        "geometry": geometry_fixture(trial),
    }


def outcome_fixture(changed: int) -> dict:
    return {
        "accuracy": 0.5, "acquisition": 0.7, "reversal": 0.3,
        "late_acquisition": 0.75, "late_reversal": 0.35,
        "probe_acquisition": 0.6, "probe_reversal": 0.4,
        "curve": [0.5] * 8, "seconds": 0.01, "work": 100,
        "stimulus_events": 100, "state_bytes": 1000, "hot_allocations": 0,
        "unique_cue_codes": 16, "changed_weights": changed,
        "max_gain_mass_error": 0.0,
    }


def canonical_fixture(seed: int, side: str, tau: float, arm: str) -> dict:
    hash_byte = (seed + ord(side) + int(tau) + (0 if arm == "E" else 1)) % 256
    trajectory = [{
        "reversal_trials": trial, "old_map_margin": 0.03,
        "reversed_map_margin": -0.03, "acquisition_axis_coordinate": 0.8,
        "acquisition_axis_projection": 1.2,
        "reversal_parallel_projection": -0.2,
        "reversal_perpendicular_norm": 0.9,
    } for trial in (0, 16, 32, 64, 128, 256)]
    return {
        "outcome": outcome_fixture(123 if arm == "E" else 0),
        "diagnostics": None, "intervention": [{}, {}], "geometry": {},
        "weight_geometry": {}, "immediate_reference": None,
        "paired_final_old_probe": 0.55, "paired_final_reversal_probe": 0.45,
        "observer_array_bytes": 0, "intervention_array_bytes": 0,
        "acquisition_state_sha256": [hash_byte] * 32,
        "trajectory": trajectory, "null_events": [], "true_direction_events": [],
    }


def result_fixture(seed: int, side: str, tau: float, arm: str, sign: float = 1.0) -> dict:
    events = ([event_fixture(seed, side, tau, trial, sign)
               for trial in range(1, 257)] if arm == "E" else [])
    final_hash = (bytes(events[-1]["true_endpoint_sha256"]).hex()
                  if arm == "E" else "ab" * 32)
    return {
        "seed": seed, "side": side, "tau": tau, "arm": arm,
        "condition": "true_perpendicular", "final_weight_sha256": final_hash,
        "shadow": {"status": "PASSED" if arm == "E" else "FIXED_WEIGHT_CONTROL",
                   "events": events},
        "canonical": canonical_fixture(seed, side, tau, arm),
    }


def write_fixture(root: pathlib.Path, sign: float = 1.0) -> pathlib.Path:
    config = config_fixture()
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (root / "execution.json").write_text(json.dumps({
        "protocol": "DH-08A", "mode": "run", "complete": True,
        "outcome_rows": 256, "fresh_seed_bundles": 32,
        "qualification_seed_bundles": 0, "configured_seeds": config["seeds"],
        "specimens": 1, "wall_seconds": 1.0,
        "canonical_policy": "parallel-off true-perpendicular",
        "shadow": "event-local Q07 feasible-null endpoint; never committed",
        "reward_rule": "action_contingent", "autodiff": False, "backprop": False,
    }), encoding="utf-8")
    for side in analyze.SIDES:
        for tau in analyze.TAUS:
            with (root / f"{side}-tau{tau:g}.jsonl").open("w", encoding="utf-8") as handle:
                for seed in config["seeds"]:
                    bundle = {
                        "seed": seed, "side": side, "tau": tau,
                        "plastic_edges": 100, "null_routing": {}, "setup_seconds": 0.01,
                        "results": [result_fixture(seed, side, tau, arm, sign)
                                    for arm in analyze.ARMS],
                    }
                    handle.write(json.dumps(bundle, separators=(",", ":")) + "\n")
    return config_path


class Dh08aAnalysisTests(unittest.TestCase):
    def test_full_fixture_outputs_and_positive_primary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_path = write_fixture(root)
            summary = analyze.analyze(root, config_path)
            self.assertEqual(summary["status"], "POSITIVE_ENDPOINT_EFFECT")
            self.assertEqual(summary["primary"]["n_seed_bundles"], 32)
            self.assertGreater(summary["primary"]["t_ci95"][0], 0)
            self.assertGreater(summary["primary"]["bootstrap_ci95"][0], 0)
            self.assertEqual(summary["integrity"]["events"], 32_768)
            expected = {"summary.json", "events.csv", "cells.csv", "seeds.csv", "REPORT.md"}
            self.assertEqual({path.name for path in (root / "analysis").iterdir()}, expected)
            for name, count in (("events.csv", 32_768), ("cells.csv", 256), ("seeds.csv", 32)):
                with (root / "analysis" / name).open(newline="", encoding="utf-8") as handle:
                    self.assertEqual(len(list(csv.DictReader(handle))), count)

    def test_negative_and_inconclusive_status_rules(self):
        negative = [-0.1 - index * 0.001 for index in range(32)]
        neg_t = analyze.infer_seed_values(negative)["t_ci95"]
        neg_b = analyze.bootstrap_interval(negative, 20_000, 2026091608)["ci95"]
        self.assertEqual(analyze.classify(neg_t, neg_b), "NEGATIVE_ENDPOINT_EFFECT")
        crossing = [-1.0, 1.0] * 16
        cross_t = analyze.infer_seed_values(crossing)["t_ci95"]
        cross_b = analyze.bootstrap_interval(crossing, 20_000, 2026091608)["ci95"]
        self.assertEqual(analyze.classify(cross_t, cross_b), "INCONCLUSIVE")
        self.assertEqual(analyze.classify([0.1, 0.2], [-0.01, 0.2]), "INCONCLUSIVE")

    def test_bootstrap_is_deterministic(self):
        values = [0.01 + index * 0.001 for index in range(32)]
        first = analyze.bootstrap_interval(values, 20_000, 2026091608)
        second = analyze.bootstrap_interval(values, 20_000, 2026091608)
        self.assertEqual(first, second)

    def test_pseudoreplication_is_rejected(self):
        with self.assertRaisesRegex(analyze.AnalysisError, "pseudoreplication"):
            analyze.infer_seed_values([0.1] * 32_768)
        with self.assertRaisesRegex(analyze.AnalysisError, "pseudoreplication"):
            analyze.bootstrap_interval([0.1] * 1_024, 20_000, 2026091608)

    def test_every_q07_gate_and_shadow_gate_fail_closed(self):
        changes = {
            "geometry_valid": ("event", "geometry_valid", False, "geometry_valid"),
            "shadow allocation": ("event", "shadow_hot_allocations", 1, "shadow hot"),
            "axial": ("geometry", "axial_error_over_total_norm", 1.0001e-7, "axial_error"),
            "norm": ("geometry", "norm_relative_error", 1.0001e-7, "norm_relative"),
            "residual norm": ("geometry", "residual_norm_relative_error", 1.0001e-7,
                              "residual_norm"),
            "cosine": ("geometry", "residual_abs_cosine", 1.0001e-5, "residual_abs"),
            "boundary": ("geometry", "boundary_symmetric_difference", 1, "boundary"),
            "outside": ("geometry", "outside_support_changes", 1, "outside-support"),
            "bound": ("geometry", "max_bound_violation", 1e-12, "bound-violation"),
            "geometry allocation": ("geometry", "hot_allocations", 1, "hot-allocation"),
            "support": ("geometry", "null_nonzero", 98, "support-size"),
        }
        for name, (where, field, value, message) in changes.items():
            with self.subTest(gate=name):
                event = event_fixture(8000, "R", 4.0, 1)
                target = event if where == "event" else event["geometry"]
                target[field] = value
                with self.assertRaisesRegex(analyze.AnalysisError, message):
                    analyze.validate_audit(event, 1, "synthetic")
        event = event_fixture(8000, "R", 4.0, 1)
        event["geometry"]["residual_abs_cosine"] = None
        with self.assertRaisesRegex(analyze.AnalysisError, "residual_abs_cosine"):
            analyze.validate_audit(event, 1, "synthetic")

    def test_event_order_delta_identity_and_nonfinite_fail_closed(self):
        event = event_fixture(8000, "R", 4.0, 1)
        event["trial"] = 2
        with self.assertRaisesRegex(analyze.AnalysisError, "order/trial"):
            analyze.validate_audit(event, 1, "synthetic")
        event = event_fixture(8000, "R", 4.0, 1)
        event["true_minus_null"] += 1e-6
        with self.assertRaisesRegex(analyze.AnalysisError, "delta identity"):
            analyze.validate_audit(event, 1, "synthetic")
        with self.assertRaisesRegex(analyze.AnalysisError, "non-finite"):
            analyze.finite_tree({"bad": float("nan")})

    def test_exact_cardinality_z_fixed_and_hash_shape(self):
        config = config_fixture()
        bundles = []
        rows = []
        for seed, side, tau in __import__("itertools").product(config["seeds"], analyze.SIDES,
                                                               analyze.TAUS):
            results = [result_fixture(seed, side, tau, arm) for arm in analyze.ARMS]
            bundles.append({"seed": seed, "side": side, "tau": tau, "results": results})
            rows.extend(results)
        analyze.validate(rows, bundles, config)
        with self.assertRaisesRegex(analyze.AnalysisError, "cell cardinality"):
            analyze.validate(rows[:-1], bundles, config)
        bad_rows = copy.deepcopy(rows)
        z = next(row for row in bad_rows if row["arm"] == "Z")
        z["canonical"]["outcome"]["changed_weights"] = 1
        with self.assertRaisesRegex(analyze.AnalysisError, "fixed-weight"):
            analyze.validate(bad_rows, copy.deepcopy(bundles), config)
        bad_rows = copy.deepcopy(rows)
        bad_rows[0]["canonical"]["acquisition_state_sha256"] = [1] * 31
        with self.assertRaisesRegex(analyze.AnalysisError, "acquisition hash"):
            analyze.validate(bad_rows, bundles, config)

    def test_missing_e_event_forbidden_z_event_and_final_hash_fail_closed(self):
        config = config_fixture()
        bundles = []
        rows = []
        for seed, side, tau in __import__("itertools").product(config["seeds"], analyze.SIDES,
                                                               analyze.TAUS):
            results = [result_fixture(seed, side, tau, arm) for arm in analyze.ARMS]
            bundles.append({"seed": seed, "side": side, "tau": tau, "results": results})
            rows.extend(results)
        bad_rows = copy.deepcopy(rows)
        next(row for row in bad_rows if row["arm"] == "E")["shadow"]["events"].pop()
        with self.assertRaisesRegex(analyze.AnalysisError, "exactly 256 events"):
            analyze.validate(bad_rows, bundles, config)
        bad_rows = copy.deepcopy(rows)
        z = next(row for row in bad_rows if row["arm"] == "Z")
        z["shadow"]["events"].append(event_fixture(8000, "R", 4.0, 1))
        with self.assertRaisesRegex(analyze.AnalysisError, "Z must have no shadow events"):
            analyze.validate(bad_rows, bundles, config)
        bad_rows = copy.deepcopy(rows)
        next(row for row in bad_rows if row["arm"] == "E")["final_weight_sha256"] = "00" * 32
        with self.assertRaisesRegex(analyze.AnalysisError, "endpoint/final weight hash parity"):
            analyze.validate(bad_rows, bundles, config)

    def test_config_bootstrap_seed_and_seed_set_are_frozen(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "config.json"
            config = config_fixture()
            config["bootstrap_seed"] += 1
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(analyze.AnalysisError, "bootstrap seed"):
                analyze.load_config(path)
            config = config_fixture()
            config["seeds"][-1] = 9999
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(analyze.AnalysisError, "fresh seeds"):
                analyze.load_config(path)


if __name__ == "__main__":
    unittest.main()
