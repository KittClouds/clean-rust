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
        "seeds": list(range(7000, 7032)),
        "taus": [4.0, 16.0],
        "sides": ["R", "L"],
        "conditions": list(analyze.CONDITIONS),
        "arms": ["E", "Z"],
        "cues": 16,
        "delay_steps": 12,
        "trials": 512,
        "eta": 0.05,
        "glut_sign": -1.0,
        "input_salt": 858980352,
        "threads": 4,
        "bootstrap_resamples": 20_000,
        "bootstrap_seed": 2026091507,
    }


def audit_event(trial: int) -> dict:
    return {
        "trial": trial,
        "axial_error_over_total_norm": 2e-8,
        "norm_relative_error": 3e-8,
        "residual_norm_relative_error": 4e-8,
        "residual_abs_cosine": 5e-6,
        "boundary_symmetric_difference": 0,
        "outside_support_changes": 0,
        "hot_allocations": 0,
        "max_bound_violation": 0.0,
        "true_nonzero": 100,
        "null_nonzero": 100,
    }


def e_margin(condition: str, seed: int) -> float:
    index = seed - 7000
    values = {
        "immediate": -0.01,
        "quiet": 0.04,
        "neither": 0.035,
        "parallel_only": 0.025,
        "null_perpendicular": 0.03,
        "parallel_null": 0.02,
    }
    if condition == "true_perpendicular":
        return values["null_perpendicular"] - 0.1 + 0.001 * index
    if condition == "both_true":
        return values["parallel_null"] - 0.2 + 0.002 * index
    return values[condition]


def outcome_fixture() -> dict:
    return {
        "accuracy": 0.5,
        "acquisition": 0.75,
        "reversal": 0.25,
        "late_acquisition": 0.8,
        "late_reversal": 0.3,
        "probe_acquisition": 0.6,
        "probe_reversal": 0.4,
        "curve": [0.5] * 8,
        "seconds": 0.01,
        "work": 100,
        "stimulus_events": 100,
        "state_bytes": 1000,
        "hot_allocations": 0,
        "unique_cue_codes": 16,
        "changed_weights": 0,
        "max_gain_mass_error": 0.0,
    }


def result_fixture(seed: int, side: str, tau: float, arm: str, condition: str) -> dict:
    margin = 0.05 if arm == "Z" else e_margin(condition, seed)
    trajectory = [{
        "reversal_trials": checkpoint,
        "old_map_margin": margin,
        "reversed_map_margin": -margin,
        "acquisition_axis_coordinate": 1.0,
        "acquisition_axis_projection": 2.0,
        "reversal_parallel_projection": 0.0,
        "reversal_perpendicular_norm": 0.0,
    } for checkpoint in analyze.CHECKPOINTS]
    hash_byte = (seed + ord(side) + int(tau) + (0 if arm == "E" else 1)) % 256
    requires_audits = arm == "E" and condition in analyze.NULL_CONDITIONS
    manipulation = {
        "status": "PASSED" if requires_audits else "NOT_APPLICABLE",
        "events": [audit_event(i) for i in range(1, 257)] if requires_audits else [],
    }
    return {
        "seed": seed,
        "side": side,
        "tau": tau,
        "arm": arm,
        "condition": condition,
        "final_weight_sha256": (f"{hash_byte:02x}" * 32 if arm == "E" else "ab" * 32),
        "manipulation": manipulation,
        "result": {
            "outcome": outcome_fixture(),
            "paired_final_old_probe": 0.55,
            "paired_final_reversal_probe": 0.45,
            "acquisition_state_sha256": [hash_byte] * 32,
            "weight_geometry": {
                "initial_old_map_margin": 0.0,
                "acquired_old_map_margin": 0.1,
                "final_old_map_margin": margin,
                "final_reversal_map_margin": -margin,
                "acquisition_axis_coordinate": 1.0,
                "distance_from_initial_over_acquisition_norm": 1.0,
                "reversal_delta_over_acquisition_norm": 0.2,
            },
            "trajectory": trajectory,
        },
    }


def write_fixture(root: pathlib.Path) -> pathlib.Path:
    config = config_fixture()
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (root / "execution.json").write_text(json.dumps({
        "protocol": "DH-07R",
        "complete": True,
        "mode": "run",
        "outcome_rows": 2048,
        "fresh_seed_bundles": 32,
        "configured_seeds": config["seeds"],
        "specimens": 1,
        "wall_seconds": 1.0,
    }), encoding="utf-8")
    for side in config["sides"]:
        for tau in config["taus"]:
            path = root / f"{side}-tau{tau:g}.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for seed in config["seeds"]:
                    results = [result_fixture(seed, side, tau, arm, condition)
                               for arm in config["arms"] for condition in config["conditions"]]
                    bundle = {"seed": seed, "side": side, "tau": tau,
                              "plastic_edges": 10, "setup_seconds": 0.01, "results": results}
                    handle.write(json.dumps(bundle, separators=(",", ":")) + "\n")
    return config_path


class Dh07rAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.fixture_root = pathlib.Path(cls.temporary.name)
        cls.config_path = write_fixture(cls.fixture_root)
        cls.config = analyze.load_config(cls.config_path)
        cls.rows, cls.bundles, cls.execution = analyze.load_run(cls.fixture_root, cls.config)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_full_synthetic_jsonl_fixture_and_primary_estimand(self):
        summary = analyze.analyze(self.fixture_root, self.config_path)
        self.assertEqual(summary["status"], "DIRECTION_SPECIFICITY_SUPPORTED")
        self.assertAlmostEqual(summary["primary"]["mean"], -0.12675, places=12)
        self.assertEqual(summary["primary"]["n_seed_bundles"], 32)
        self.assertEqual(summary["primary"]["resamples"], 20_000)
        self.assertEqual(summary["manipulation_validity"]["null_cells"], 256)
        self.assertEqual(summary["manipulation_validity"]["events"], 65_536)
        expected = {"summary.json", "seed_contrasts.csv", "cells.csv",
                    "trajectory.csv", "manipulation_cells.csv", "REPORT.md"}
        self.assertEqual({path.name for path in (self.fixture_root / "analysis").iterdir()}, expected)
        with (self.fixture_root / "analysis" / "seed_contrasts.csv").open(newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 32)
        with (self.fixture_root / "analysis" / "cells.csv").open(newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 2048)

    def test_bootstrap_is_deterministic_and_resamples_only_seed_values(self):
        values = [-0.2 + index / 1000 for index in range(32)]
        first = analyze.bootstrap_summary(values, 20_000, 12345)
        second = analyze.bootstrap_summary(values, 20_000, 12345)
        self.assertEqual(first, second)
        self.assertEqual(first["seed_values"], values)
        self.assertEqual(first["n_seed_bundles"], 32)

    def test_every_null_gate_is_fail_closed(self):
        violations = {
            "axial_error_over_total_norm": ("axial_error_over_total_norm", 1.00001e-7),
            "norm_relative_error": ("norm_relative_error", 1.00001e-7),
            "residual_norm_relative_error": ("residual_norm_relative_error", 1.00001e-7),
            "residual_abs_cosine": ("residual_abs_cosine", 1.00001e-5),
            "boundary_symmetric_difference": ("boundary_symmetric_difference", 1),
            "outside_support_changes": ("outside_support_changes", 1),
            "hot_allocations": ("hot_allocations", 1),
            "max_bound_violation": ("max_bound_violation", 1e-12),
            "support-size": ("null_nonzero", 98),
        }
        for expected, (field, value) in violations.items():
            with self.subTest(gate=expected):
                event = audit_event(1)
                event[field] = value
                with self.assertRaisesRegex(analyze.AnalysisError, expected):
                    analyze.validate_audit(event, 1, "synthetic")

    def test_missing_result_cell_fails_cardinality(self):
        with self.assertRaisesRegex(analyze.AnalysisError, "missing or unexpected"):
            analyze.validate(self.rows[:-1], self.config)

    def test_acquisition_hash_parity_is_fail_closed(self):
        target = next(row for row in self.rows if row["arm"] == "E"
                      and row["condition"] == "quiet")
        original = target["result"]["acquisition_state_sha256"]
        target["result"]["acquisition_state_sha256"] = [255] * 32
        try:
            with self.assertRaisesRegex(analyze.AnalysisError, "acquisition hash parity"):
                analyze.validate(self.rows, self.config)
        finally:
            target["result"]["acquisition_state_sha256"] = original

    def test_fixed_weight_z_condition_invariance_is_fail_closed(self):
        target = next(row for row in self.rows if row["arm"] == "Z"
                      and row["condition"] == "quiet")
        target["result"]["outcome"]["reversal"] = 0.251
        try:
            with self.assertRaisesRegex(analyze.AnalysisError, "Z condition invariance"):
                analyze.validate(self.rows, self.config)
        finally:
            target["result"]["outcome"]["reversal"] = 0.25

    def test_nonfinite_json_value_is_rejected(self):
        with self.assertRaisesRegex(analyze.AnalysisError, "non-finite"):
            analyze.finite_tree({"bad": float("nan")})


if __name__ == "__main__":
    unittest.main()
