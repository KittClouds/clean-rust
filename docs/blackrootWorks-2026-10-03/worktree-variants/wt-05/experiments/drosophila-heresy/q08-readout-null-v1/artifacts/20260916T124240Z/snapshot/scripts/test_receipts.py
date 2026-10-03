"""Meaningful integrity tests for the independent constructor gate reviewer."""

import copy
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import summarize_smoke as reviewer


def event(trial):
    return {
        "trial": trial, "zero_residual": False, "geometry_valid": True,
        "failure_mask": 0, "shadow_hot_allocations": 0, "true_endpoint_sha256": [1] * 32,
        "geometry": {
            "trial": trial, "axial_error_over_total_norm": 0.0, "norm_relative_error": 0.0,
            "residual_norm_relative_error": 0.0, "residual_abs_cosine": 0.0,
            "boundary_symmetric_difference": 0, "outside_support_changes": 0,
            "max_bound_violation": 0.0, "hot_allocations": 0, "true_nonzero": 100,
            "null_nonzero": 100,
        },
        "readout": {
            "true_cue_scores": [0.1] * 16, "null_cue_scores": [0.1] * 16,
            "cue_max_normalized_drive_errors": [0.0] * 16,
            "max_normalized_drive_error": 0.0, "max_cue_score_error": 0.0,
            "max_real_arithmetic_normalized_drive_error": 0.0,
            "max_distractor_normalized_drive_error": 0.1,
        },
        "budget": {
            "optimistic_residual_abs_cosine_floor": 0.0, "structurally_overconstrained": False,
            "rotatable_nullspace_energy": 1.0, "total_energy": 1.0,
        },
    }


def write_fixture(out, mutate=None):
    execution = {"protocol": "Q08-ReadoutNull-v1", "mode": "smoke", "complete": True,
                 "configured_seeds": [9200], "fresh_seed_bundles": 0, "outcome_rows": 4}
    (out / "execution.json").write_text(json.dumps(execution))
    for side in ("R", "L"):
        rows = []
        for arm in ("E", "Z"):
            local = [event(trial) for trial in range(1, 257)] if arm == "E" else []
            row = {
                "seed": 9200, "side": side, "tau": 4.0, "arm": arm,
                "condition": "true_perpendicular", "final_weight_sha256": "01" * 32,
                "canonical": {"outcome": {"hot_allocations": 0, "changed_weights": 0}},
                "shadow": {"status": "PASSED" if arm == "E" else "FIXED_WEIGHT_CONTROL", "events": local},
            }
            if mutate and side == "R" and arm == "E":
                mutate(row)
            rows.append(row)
        bundle = {"seed": 9200, "side": side, "tau": 4.0, "results": rows}
        (out / f"{side}-tau4.jsonl").write_text(json.dumps(bundle) + "\n")


class ReceiptTests(unittest.TestCase):
    def test_complete_passing_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory)
            write_fixture(out)
            result = reviewer.summarize(out)
            self.assertEqual(result["status"], "SMOKE_CONSTRUCTOR_PASSED")
            self.assertEqual(result["events"], 512)

    def test_constructor_failure_is_reported_without_discarding_event(self):
        def mutate(row):
            e = row["shadow"]["events"][0]
            e["geometry"]["residual_abs_cosine"] = 0.5
            e["failure_mask"] = 1 << 3
            e["geometry_valid"] = False
            row["shadow"]["status"] = "CONSTRUCTOR_FAILED"
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory)
            write_fixture(out, mutate)
            result = reviewer.summarize(out)
            self.assertEqual(result["events"], 512)
            self.assertEqual(result["events_failed"], 1)
            self.assertEqual(result["failure_counts"]["residual_decorrelation"], 1)

    def test_malformed_gate_mask_event_order_hash_and_nonfinite_fail_closed(self):
        mutations = (
            lambda row: row["shadow"]["events"][0].update(failure_mask=1),
            lambda row: row["shadow"]["events"][0].update(trial=2),
            lambda row: row.update(final_weight_sha256="ff" * 32),
            lambda row: row["shadow"]["events"][0]["readout"].update(max_normalized_drive_error=float("nan")),
            lambda row: row["shadow"]["events"].pop(),
            lambda row: row["shadow"]["events"][0]["readout"].update(max_cue_score_error=1e-8),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                out = pathlib.Path(directory)
                write_fixture(out, mutation)
                with self.assertRaises(RuntimeError):
                    reviewer.summarize(out)

    def test_each_numerical_and_constraint_gate_has_an_independent_failure(self):
        base = event(1)
        mutations = (
            ("geometry", "axial_error_over_total_norm", 2e-7),
            ("geometry", "norm_relative_error", 2e-7),
            ("geometry", "residual_norm_relative_error", 2e-7),
            ("geometry", "residual_abs_cosine", 2e-5),
            ("geometry", "boundary_symmetric_difference", 1),
            ("geometry", "outside_support_changes", 1),
            ("geometry", "max_bound_violation", 1e-8),
            ("geometry", "hot_allocations", 1),
            ("geometry", "null_nonzero", 102),
            ("readout", "max_normalized_drive_error", 2e-7),
            ("readout", "max_cue_score_error", 2e-7),
        )
        for index, (parent, field, value) in enumerate(mutations):
            altered = copy.deepcopy(base)
            altered[parent][field] = value
            passed = reviewer.gates(altered)
            self.assertEqual([i for i, ok in enumerate(passed) if not ok], [index])


if __name__ == "__main__":
    unittest.main()
