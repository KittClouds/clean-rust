"""Synthetic contract tests for the sealed R2 bootstrap addendum."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
P_PHASE = ROOT / "experiments/jev-information-density-v08p/phase_b"
R2 = ROOT / "experiments/jev-information-density-v08p-r2"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class R2TrajectoryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_module("jev_p_trajectory_analysis_test", P_PHASE / "trajectory_analysis.py")
        cls.adapter = load_module("jev_p_r2_analysis_adapter_test", R2 / "runner/r2_analysis_adapter.py")
        cls.contract = json.loads((P_PHASE / "phase-b-p-analysis-contract-v01.json").read_text(encoding="utf-8"))
        cls.addendum = json.loads((R2 / "contracts/p-r2-analysis-addendum-v01.json").read_text(encoding="utf-8"))
        cls.runtime_contract = cls.adapter.prepare_runtime_contract(cls.contract, cls.addendum, cls.helper)

    def test_addendum_resolves_all_bootstrap_ambiguities_without_contract_edit(self):
        self.assertEqual(len(self.helper.contract_ambiguities(self.contract)), 3)
        spec = self.addendum["bootstrap_implementation"]
        self.assertEqual(spec["quantile"]["method"], "linear")
        self.assertEqual(tuple(spec["family_order"]), FAMILIES)
        self.assertIn("family-major", spec["draw_order"])
        self.assertIn("one 10000 x 2000 index plan", spec["resample_plan_scope"])
        self.assertEqual(self.contract["descriptive_event_time_rules"]["persistence"], self.adapter.EXPECTED_PERSISTENCE_TEXT)
        self.assertEqual(self.addendum["unchanged_contract_elements"]["bootstrap_replicates"], 10_000)

    def test_shared_plan_drives_synthetic_simultaneous_onsets(self):
        n = 2_000
        labels = np.repeat(np.asarray(FAMILIES, dtype=object), 500)
        plan_spec = self.addendum["bootstrap_implementation"]
        plan, _plan_hash = self.adapter.resample_plan(self.helper, self.runtime_contract, labels, self.addendum)
        self.assertEqual(plan.shape, (10_000, 2_000))
        self.helper.validate_stratified_resamples(
            plan, labels, family_order=plan_spec["family_order"], expected_replicates=10_000
        )

        steps = (80, *range(81, 121))
        family_order = plan_spec["family_order"]
        method = plan_spec["quantile"]["method"]
        probability = np.zeros((41, n), dtype=np.float64)
        probability[4:, :] = 0.1  # first positive change is step 84
        rise = self.adapter.continuous_analysis(
            self.helper, "new_probability_delta", probability, labels, plan,
            self.runtime_contract, self.addendum,
        )
        self.assertEqual(rise["onsets"]["positive_rise"]["onset_step"], 84)
        self.assertEqual(rise["onsets"]["positive_rise"]["confirmed_at_step"], 86)

        anchor = np.ones((41, n), dtype=np.float64)
        anchor[10:, :] = 0.8  # first anchor loss is step 90
        loss = self.adapter.continuous_analysis(
            self.helper, "anchor_old_map", anchor, labels, plan,
            self.runtime_contract, self.addendum,
        )
        self.assertEqual(loss["onsets"]["anchor_loss"]["onset_step"], 90)

        sham = np.full((41, n), 0.1, dtype=np.float64)
        sham[6:, :] = 0.05  # first sustained locality decrease is step 86
        locality = self.adapter.continuous_analysis(
            self.helper, "sham_l1", sham, labels, plan,
            self.runtime_contract, self.addendum,
        )
        self.assertEqual(locality["onsets"]["decrease"]["onset_step"], 86)

    def test_binary_appearance_and_four_cell_partition(self):
        n = 2_000
        labels = np.repeat(np.asarray(FAMILIES, dtype=object), 500)
        fact = np.zeros((41, n), dtype=np.bool_)
        fact[5:, :8] = True
        appearance = self.helper.binary_appearance_events("fact_new_map", fact, labels, self.runtime_contract)
        self.assertEqual(appearance["overall"]["first_nonzero"]["step"], 85)
        self.assertEqual(appearance["overall"]["first_three_consecutive_nonzero"]["onset_step"], 85)

        old = np.ones((41, n), dtype=np.bool_)
        old[10:, :20] = False
        partition = self.helper.four_cell_partition(old, fact, labels, self.runtime_contract,
                                                    steps=(80, *range(81, 121)))
        self.assertTrue(self.helper.validate_four_cell_partition(partition))
        self.assertTrue(all(step["n"] == 2_000 for step in partition["steps"]))
        self.assertEqual(partition["steps"][-1]["overall"]["A_AND_F"]["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
