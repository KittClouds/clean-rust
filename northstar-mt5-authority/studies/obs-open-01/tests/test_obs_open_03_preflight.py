from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/obs_open_03_preflight.py"
SPEC = importlib.util.spec_from_file_location("obs_open_03_preflight", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PREFLIGHT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREFLIGHT
SPEC.loader.exec_module(PREFLIGHT)


class ObsOpen03PreflightTests(unittest.TestCase):
    def test_preflight_fails_closed_on_incomplete_semantics(self) -> None:
        receipt = PREFLIGHT.inspect()
        self.assertEqual("ABORTED_PREEXECUTION_PROTOCOL_INCOMPLETE", receipt["outcome"])
        codes = {row["code"] for row in receipt["issues"]}
        self.assertEqual({
            "DESCRIPTIVE_MEASUREMENT_FORMULAS_UNDEFINED",
            "FORMAL_ESTIMAND_REGISTRY_INCOMPLETE",
            "TEMPORAL_ROBUSTNESS_CONSTRUCTION_UNDEFINED",
            "CONFIRMATION_ESTIMAND_EMITTER_UNDEFINED",
            "REJECTION_LEDGER_TRANSITIONS_INCOMPLETE",
        }, codes)

    def test_no_scientific_outputs_or_confirmation_reads(self) -> None:
        receipt = PREFLIGHT.inspect()
        self.assertEqual(0, receipt["discovery_census_rows_produced"])
        self.assertEqual(0, receipt["formal_estimands_evaluated"])
        self.assertFalse(receipt["confirmation_observations_read"])
        self.assertEqual(0, receipt["source_schema_probe"]["rows_inside_admitted_opening_windows"])


if __name__ == "__main__":
    unittest.main()
