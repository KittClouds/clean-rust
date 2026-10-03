from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_resid_invalid1_r2.py"


class BaselineRelativeActionSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("resid_invalid1_r2_under_test", RUNNER)
        if spec is None or spec.loader is None:
            raise RuntimeError("R2 runner import failed")
        cls.runner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.runner
        spec.loader.exec_module(cls.runner)
        cls.exh = cls.runner.load_module(cls.runner.EXH1_SCRIPT, "resid_invalid1_r2_exh_test")
        cls.alg = cls.exh.load_alg1()
        cls.context = cls.exh.prepare_context(cls.runner.CONTEXT, cls.alg)

    def test_known_false_positive_witnesses_use_frozen_baseline_mapping(self) -> None:
        result = self.runner.regression_preflight(self.exh, self.alg, self.context)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([item["row"] for item in result["cases"]], [36, 695])
        self.assertEqual([item["expected_bits"] for item in result["cases"]], [1092185578, 1103757538])
        self.assertEqual([item["legacy_bug_bits"] for item in result["cases"]], [1092185579, 1103757536])
        self.assertTrue(all(item["legacy_false_target_reproduced_and_rejected"] for item in result["cases"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
