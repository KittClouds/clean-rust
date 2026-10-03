from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "execute_v08d_runner_v02.py"
SPEC = importlib.util.spec_from_file_location("jev_v08d_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RunnerAdapterTests(unittest.TestCase):
    def test_filters_only_the_run_directory_locator(self) -> None:
        contract = MODULE.core.read_json(MODULE.core.CONTRACT_PATH)
        outputs = MODULE.artifact_outputs(contract)
        self.assertNotIn("external_run_directory", outputs)
        self.assertEqual(outputs["integrity_receipt"], "integrity-receipt.json")
        self.assertEqual(outputs["freeze_receipt"], "freeze-receipt.json")

    def test_rejects_a_different_run_directory_locator(self) -> None:
        contract = {"outputs": {
            "external_run_directory": str(MODULE.V01_DIR / "unexpected"),
            "support_census": "support-census.json",
        }}
        with self.assertRaisesRegex(ValueError, "locator differs"):
            MODULE.artifact_outputs(contract)


if __name__ == "__main__":
    unittest.main()
