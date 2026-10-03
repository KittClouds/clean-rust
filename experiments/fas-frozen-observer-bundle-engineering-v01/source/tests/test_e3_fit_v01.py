from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
SCRIPT = PROJECT / "source" / "scripts" / "fit_observers_e3_v01.py"
SPEC = importlib.util.spec_from_file_location("fit_observers_e3_v01_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FIT
SPEC.loader.exec_module(FIT)


class E3FitContractTests(unittest.TestCase):
    def test_welford_matches_population_scale_and_repairs_constant_column(self) -> None:
        values = np.zeros((5, FIT.DIM), dtype=np.float32)
        values[:, 0] = np.asarray([1, 2, 4, 8, 10], dtype=np.float32)
        values[:, 1] = 7.0
        mean, scale, count = FIT.fit_welford(values, np.arange(5), chunk_rows=2)
        self.assertEqual(count, 5)
        self.assertAlmostEqual(float(mean[0]), float(values[:, 0].mean()), places=5)
        self.assertAlmostEqual(float(scale[0]), float(values[:, 0].std()), places=5)
        self.assertEqual(float(mean[1]), 7.0)
        self.assertEqual(float(scale[1]), 1.0)
        self.assertEqual(mean.dtype, np.dtype("<f4"))
        self.assertEqual(scale.dtype, np.dtype("<f4"))

    def test_actual_fit_partition_eligibility_and_class_support(self) -> None:
        prepared, summary = FIT.prepare_fit_rows({})
        self.assertEqual(summary["fit_label_rows"], 85_204)
        self.assertEqual(summary["eligibility_mismatches"], 0)
        self.assertEqual(summary["context_identity"]["fit_rows"], 85_204)
        self.assertEqual(summary["entity_identity"]["fit_rows"], 85_204)
        self.assertEqual(summary["relation"]["fit_rows"], 21_188)
        self.assertEqual(summary["observed_state"]["fit_rows"], 21_188)
        self.assertEqual(summary["exact_target"]["fit_rows"], 21_188)
        self.assertEqual(len(prepared), 5)

    def test_no_heldout_label_path_or_scoring_code_is_bound(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("eval-labels-v01.jsonl", source)
        self.assertNotIn("balanced_accuracy", source)
        self.assertNotIn("evaluation_labels_path", source)
        self.assertIn('"evaluation_labels_opened": False', source)
        self.assertIn('"test_performance_scored": False', source)

    def test_contract_declares_only_fit_partition_access(self) -> None:
        contract_path = PROJECT / "contracts" / "e3-fit-v01.json"
        if not contract_path.is_file():
            self.skipTest("E3 contract is built after the fit-source regression tests")
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["evaluation_data_access"], "PROHIBITED; evaluation labels and all TEST-label content remain unopened")
        self.assertIn("fit_labels", contract["inputs"])
        self.assertNotIn("evaluation_labels", contract["inputs"])
        self.assertEqual(contract["authority"]["evaluation_scoring_authorized"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
