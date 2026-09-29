from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import feature_map, task_eligible  # noqa: E402
from fit import welford  # noqa: E402
from score import bootstrap_pair, verified_predictions  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_welford_matches_numpy_on_selected_training_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.f32le"
            rows = np.asarray([[1, 4], [5, 8], [3, 6], [50, 60]], dtype="<f4")
            path.write_bytes(rows.tobytes())
            mapped = feature_map(path, 4, 2)
            selected = np.asarray([0, 1, 2], dtype=np.int64)
            mean, scale = welford(mapped, selected, 2)
            np.testing.assert_allclose(mean, rows[selected].mean(axis=0))
            np.testing.assert_allclose(scale, rows[selected].std(axis=0), rtol=1e-6)
            del mapped

    def test_conditional_heads_require_both_training_side_terms(self):
        self.assertTrue(task_eligible({"context_term_id": 28, "entity_term_id": 29}, "context_identity"))
        self.assertFalse(task_eligible({"context_term_id": 28, "entity_term_id": 1}, "relation"))
        self.assertTrue(task_eligible({"context_term_id": 2, "entity_term_id": 1}, "exact_target"))

    def test_paired_bootstrap_zero_difference_for_identical_predictions(self):
        truth = np.asarray([0, 0, 1, 1, 0, 0, 1, 1])
        pred = np.asarray([0, 0, 1, 0, 0, 1, 1, 1])
        qids = ["q0"] * 2 + ["q1"] * 2 + ["q2"] * 2 + ["q3"] * 2
        strata = truth.tolist()
        result = bootstrap_pair(truth, pred, pred, qids, strata, 2, 7, 128)
        self.assertEqual(result["b_minus_a_mean"], 0.0)
        self.assertEqual(result["b_minus_a_5th_percentile"], 0.0)

    def test_tampered_prediction_cannot_be_scored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "predictions.jsonl").write_text('{"row_id":"a"}\n', encoding="utf-8")
            (path / "prediction-seal.json").write_text(json.dumps({
                "prediction_sha256": "0" * 64, "rows": 1,
                "partition": "TEST", "truth_join_performed": False,
            }), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                verified_predictions(path, 1)


if __name__ == "__main__":
    unittest.main()
