from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("q_weight_diagnostics", HERE / "q_weight_diagnostics.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QWeightDiagnosticsTests(unittest.TestCase):
    def test_support_artifact_summaries_bind_all_blocks_and_assignments(self) -> None:
        root = HERE.parents[1] / "runs" / "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1"
        raw = json.loads((root / "RAW-WEIGHT-DIAGNOSTICS-v0.1.1.json").read_text(encoding="utf-8"))
        task_path = HERE.parents[1] / "runs" / "F4-PRESENTATION-03-ENG1" / "task-bank" / "TASK-BANK-MANIFEST.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        report = MODULE.build_map({"analysis_status": "fixture"}, raw, task)
        self.assertEqual(len(report["block_q_diagnostics"]), 12)
        self.assertEqual(len(report["assignment_q_diagnostics"]), 6)
        self.assertEqual(report["pooled_q_diagnostics"], raw["pooled_scope"])
        self.assertGreater(report["score_scope_count"], 300)
        self.assertEqual(report["weight_rule"], "q=1/p_inclusion; no trimming, capping, normalization, or winsorization")

    def test_empty_class_is_explicitly_unavailable_not_fabricated(self) -> None:
        empty = {"count": 0, "min_q": None, "max_q": None, "mean_q": None, "sum_q": 0.0, "ess": 0.0}
        MODULE._validate_summary(empty)

    def test_weight_diagnostics_require_all_frozen_fields(self) -> None:
        incomplete = {"count": 1, "min_q": 1.0, "max_q": 1.0, "mean_q": 1.0, "sum_q": 1.0}
        with self.assertRaises(RuntimeError):
            MODULE._validate_summary(incomplete)


if __name__ == "__main__":
    unittest.main()
