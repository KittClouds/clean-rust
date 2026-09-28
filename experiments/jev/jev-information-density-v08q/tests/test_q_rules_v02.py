from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load(name: str, filename: str):
    path = ROOT / "source" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RULES = load("q_rules", "q_analysis_rules_v02.py")
OBJECTIVE = load("q_objective", "q_weighted_objective_v02.py")
import torch

BASELINE_PATH = Path(__file__).parents[2] / "jev-frozen-scaling-v05" / "train_v05.py"
BASELINE_SPEC = importlib.util.spec_from_file_location("v05_baseline", BASELINE_PATH)
assert BASELINE_SPEC is not None and BASELINE_SPEC.loader is not None
BASELINE = importlib.util.module_from_spec(BASELINE_SPEC)
BASELINE_SPEC.loader.exec_module(BASELINE)


def passing_seed() -> dict:
    return {
        "delta_p_new_low_minus_sham": 0.021,
        "sham_low_correct_direction": 1.0,
        "sham_correct_direction": 1.0,
        "a_old_low_minus_sham": -0.01,
        "family_a_old_low_minus_sham": {"a": -0.02, "b": 0.0, "c": -0.04, "d": 0.0},
        "dup_sham_l1": 0.20,
        "dup_matched_neutral_l1": 0.20,
        "sham_low_sham_l1": 0.14,
        "sham_low_matched_neutral_l1": 0.14,
        "dup_sham_map_flip_rate": 0.20,
        "dup_matched_neutral_map_flip_rate": 0.20,
        "sham_low_sham_map_flip_rate": 0.24,
        "sham_low_matched_neutral_map_flip_rate": 0.22,
        "f_new_low_minus_sham": 0.11,
        "strict_low_minus_sham": 0.10,
    }


class PerSeedGateTests(unittest.TestCase):
    def test_operating_point_requires_joint_same_seed_conjunction(self) -> None:
        rows = {"a": passing_seed(), "b": passing_seed(), "c": passing_seed()}
        rows["a"]["preservation_overall_unused"] = 0
        self.assertTrue(RULES.cohort_labels(rows)["tunable_gain_locality_operating_point"])
        rows["a"]["a_old_low_minus_sham"] = -0.06
        rows["b"]["delta_p_new_low_minus_sham"] = 0.0
        rows["c"]["material_unused"] = 0
        self.assertFalse(RULES.seed_gate_record(rows["a"])["q_operating_point_seed_pass"])
        self.assertFalse(RULES.seed_gate_record(rows["b"])["q_operating_point_seed_pass"])

    def test_locality_is_material_advantage_over_concurrent_dup(self) -> None:
        row = passing_seed()
        row["sham_low_sham_l1"] = 0.16
        self.assertFalse(RULES.seed_gate_record(row)["material_locality_advantage_over_dup_pass"])
        row["sham_low_sham_l1"] = 0.14
        row["dup_matched_neutral_l1"] = 0.0
        result = RULES.seed_gate_record(row)
        self.assertFalse(result["material_locality_advantage_over_dup_pass"])
        self.assertTrue(result["dup_zero_l1_channel_unclassifiable"])

    def test_map_label_is_separate(self) -> None:
        row = passing_seed()
        row["f_new_low_minus_sham"] = 0.09
        result = RULES.seed_gate_record(row)
        self.assertTrue(result["q_operating_point_seed_pass"])
        self.assertFalse(result["q_map_response_seed_pass"])


class WeightedObjectiveTests(unittest.TestCase):
    def test_only_sham_low_auxiliary_rows_receive_half_weight(self) -> None:
        expected = {
            "B-DUP": [1.0] * 5,
            "B-MATCHED": [1.0] * 5,
            "B-SHAM": [1.0] * 5,
            "B-SHAM-LOW": [1.0, 1.0, 1.0, 0.5, 0.5],
        }
        for arm, weights in expected.items():
            actual = OBJECTIVE.event_weights(arm, 3, 2, device=torch.device("cpu"))
            self.assertEqual(actual.tolist(), weights)

    def test_unit_weights_reproduce_frozen_v05_objective(self) -> None:
        logits = torch.tensor([[0.2, -0.4, 0.7, 0.1], [-0.3, 0.5, 0.1, -0.2]], dtype=torch.float32)
        gold = torch.tensor([[0.1, 0.2, 0.6, 0.1], [1.0, 0.0, 0.0, 0.0]], dtype=torch.float32)
        mask = torch.ones_like(gold, dtype=torch.bool)
        kinds = ["choice", "independent"]
        sources = ["exact_generative_posterior", "empirical_annotator_distribution"]
        expected = BASELINE.v05_loss(logits, gold, mask, kinds, sources, 0.25)
        actual = OBJECTIVE.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, torch.ones(2))
        self.assertTrue(torch.equal(expected[0], actual[0]))
        self.assertTrue(torch.equal(expected[1], actual[1]))

    def test_half_auxiliary_dose_keeps_original_batch_denominator(self) -> None:
        one_logits = torch.tensor([[0.1, 0.4, -0.2, 0.3]], dtype=torch.float32)
        one_gold = torch.tensor([[0.7, 0.1, 0.1, 0.1]], dtype=torch.float32)
        one_mask = torch.ones_like(one_gold, dtype=torch.bool)
        doubled = one_logits.repeat(2, 1)
        doubled_gold = one_gold.repeat(2, 1)
        doubled_mask = one_mask.repeat(2, 1)
        full = OBJECTIVE.q_weighted_loss(
            doubled, doubled_gold, doubled_mask, ["choice", "choice"],
            ["exact_generative_posterior"] * 2, 0.25, torch.ones(2),
        )[0]
        low = OBJECTIVE.q_weighted_loss(
            doubled, doubled_gold, doubled_mask, ["choice", "choice"],
            ["exact_generative_posterior"] * 2, 0.25, torch.tensor([1.0, 0.5]),
        )[0]
        self.assertTrue(torch.equal(low, full * 0.75))


if __name__ == "__main__":
    unittest.main()
