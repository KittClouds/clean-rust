"""Task-independent regression fixtures for the frozen R1 probe pipeline."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import numpy as np

from r1_sensor_probe_data_v01 import Rows
from r1_sensor_probe_fit_v01 import balanced_accuracy, binary_f1, fit_one, sample_weights, select_threshold
from r1_sensor_probe_score_v01 import _bootstrap_action_delta


class ProbePipelineTests(unittest.TestCase):
    def test_component_batch_gather_is_exact(self) -> None:
        left = np.asarray([[1, 2], [3, 4], [5, 6]], dtype=np.float32)
        right = np.asarray([[10], [20]], dtype=np.float32)
        rows = Rows(
            parts=[left, right], indexes=[None, np.asarray([1, 0, 1])],
            labels=np.asarray([0, 1, 0]), families=np.asarray(["a", "b", "a"]),
            keys=np.asarray(["x", "y", "z"]), conditions=np.asarray(["c"] * 3), extras=[{}, {}, {}],
        )
        observed = rows.batch(np.asarray([2, 0], dtype=np.int64))
        expected = np.asarray([[5, 6, 20], [1, 2, 20]], dtype=np.float32)
        np.testing.assert_array_equal(observed, expected)

    def test_balanced_accuracy_known_result(self) -> None:
        y = np.asarray([0, 0, 1, 1, 2, 2], dtype=np.int64)
        pred = np.asarray([0, 1, 1, 1, 2, 0], dtype=np.int64)
        self.assertAlmostEqual(balanced_accuracy(y, pred, 3), 2.0 / 3.0)

    def test_binary_f1_known_result(self) -> None:
        y = np.asarray([1, 1, 0, 0], dtype=np.int64)
        score = np.asarray([0.9, 0.4, 0.8, 0.1], dtype=np.float64)
        self.assertAlmostEqual(binary_f1(y, score, 0.5), 0.5)

    def test_threshold_ties_prefer_nearest_half_then_lower(self) -> None:
        y = np.asarray([1, 0], dtype=np.int64)
        score = np.asarray([0.5, 0.5], dtype=np.float64)
        threshold, f1 = select_threshold(y, score)
        self.assertEqual(threshold, 0.5)
        self.assertAlmostEqual(f1, 2.0 / 3.0)

    def test_training_weights_equalize_family_total(self) -> None:
        labels = np.asarray([0, 0, 1, 1, 1], dtype=np.int64)
        families = np.asarray(["a", "a", "a", "b", "b"])
        weights = sample_weights(labels, families, 2)
        self.assertAlmostEqual(float(weights[:3].sum()), 0.5)
        self.assertAlmostEqual(float(weights[3:].sum()), 0.5)

    def test_synthetic_fit_writes_locked_prediction_surface(self) -> None:
        def make_rows(offset: int, hidden: bool = False) -> Rows:
            x = np.random.default_rng(17 + offset).normal(size=(36, 8)).astype(np.float32)
            y = np.full(36, -1, dtype=np.int64) if hidden else np.arange(36, dtype=np.int64) % 3
            family = np.asarray([f"family-{i // 3}" for i in range(36)])
            keys = np.asarray([f"row-{offset}-{i}" for i in range(36)])
            condition = np.asarray(["id_seen"] * 36)
            return Rows([x], [None], y, family, keys, condition, [{} for _ in range(36)])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "synthetic-fit"
            receipt = fit_one("action", "real", 20260926, make_rows(0), make_rows(50), make_rows(100, True), output)
            self.assertGreaterEqual(receipt["best_epoch"], 1)
            self.assertTrue((output / "weights.pt").is_file())
            with np.load(output / "evaluation-predictions.npz", allow_pickle=False) as pred:
                self.assertEqual(pred["logits"].shape, (36, 3))

    def test_family_cluster_bootstrap_uses_locked_condition_panel(self) -> None:
        from r1_sensor_probe_data_v01 import ACTION_ORDER

        rows = []
        y_values = []
        for family in range(8):
            for condition in ("id_seen", "template_ood", "vocabulary_ood", "joint_ood"):
                for label, name in enumerate(ACTION_ORDER):
                    rows.append({"family_id": f"f{family}", "condition": condition, "target_sign": name})
                    y_values.append(label)
        y = np.asarray(y_values, dtype=np.int64)
        perfect = np.eye(3, dtype=np.float64)[y] * 5.0
        wrong = np.eye(3, dtype=np.float64)[(y + 1) % 3] * 5.0
        result = _bootstrap_action_delta(20260926, {"real": perfect, "shuffled": wrong, "surface": wrong}, rows,
                                         np.asarray([f"f{i}" for i in range(8)]))
        self.assertEqual(result["valid_replicates"], 2000)
        self.assertTrue(result["lower_excludes_zero"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
