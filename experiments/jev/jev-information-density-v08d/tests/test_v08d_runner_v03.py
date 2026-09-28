from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "execute_v08d_runner_v03.py"
SPEC = importlib.util.spec_from_file_location("jev_v08d_runner_v03", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ToleranceAliasTests(unittest.TestCase):
    def test_contract_limits_are_mapped_without_value_change(self) -> None:
        original = MODULE.core.read_json(MODULE.core.CONTRACT_PATH)
        normalized = MODULE.normalize_profile_tolerances(original)
        frozen = original["design"]["profile_constraints"]
        runtime = normalized["design"]["profile_constraints"]
        self.assertEqual(runtime["unique_relative_error_max"], frozen["unique_input_relative_error_max"])
        self.assertEqual(runtime["unique_relative_error_max"], frozen["unique_root_relative_error_max"])
        self.assertEqual(runtime["occurrence_histogram_tv_max"], frozen["input_occurrence_histogram_tv_max"])
        self.assertEqual(runtime["occurrence_histogram_tv_max"], frozen["root_occurrence_histogram_tv_max"])
        self.assertEqual(runtime["marginal_tv_max"], frozen["extra_family_axis_tv_max"])
        self.assertEqual(runtime["marginal_tv_max"], frozen["probability_source_tv_max"])
        self.assertEqual(original["design"]["profile_constraints"], frozen)

    def test_unequal_limits_are_rejected_not_relaxed(self) -> None:
        original = MODULE.core.read_json(MODULE.core.CONTRACT_PATH)
        original["design"]["profile_constraints"]["unique_root_relative_error_max"] = 0.03
        with self.assertRaisesRegex(ValueError, "equal per-axis"):
            MODULE.normalize_profile_tolerances(original)


if __name__ == "__main__":
    unittest.main()
