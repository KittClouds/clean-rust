import unittest

import numpy as np

import train_pipeline as pipeline


class AdapterContractTests(unittest.TestCase):
    def test_v02_same_entity_implication_is_tautological(self):
        self.assertEqual(
            pipeline.satisfied(4, [0], [0, 1], [0, 0]),
            pipeline.satisfied(4, [0], [0, 1], [1, 0]),
        )

    def test_expected_adapter_delta_uses_frozen_kind_probabilities(self):
        from feature_math import FeatureTask

        task = FeatureTask(
            task_id="t",
            family_id="f",
            split="train",
            global_h=np.zeros(2048, dtype=np.float32),
            clause_h=np.zeros((1, 2048), dtype=np.float32),
            entity_mentions=[[0]],
            role_mentions=[[0]],
            input_row={},
        )
        probs = np.asarray([[0, 0, 1, 0, 0, 0]], dtype=np.float32)
        self.assertEqual(pipeline.action_adapter_score(task, probs, [1], 0, 0), 1.0)

    def test_fractional_auc_treats_rollout_rates_as_expected_labels(self):
        metrics = pipeline.binary_metrics(
            np.asarray([0.1, 0.9], dtype=np.float32),
            np.asarray([0.25, 0.75], dtype=np.float32),
        )
        self.assertAlmostEqual(metrics["roc_auc_fractional_targets"], 0.75)
        self.assertAlmostEqual(metrics["mean_forecast"], 0.5)


if __name__ == "__main__":
    unittest.main()
