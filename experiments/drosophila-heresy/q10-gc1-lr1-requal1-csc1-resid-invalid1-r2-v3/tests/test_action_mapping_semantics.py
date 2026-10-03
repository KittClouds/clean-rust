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

    def test_row_local_state_matches_canonical_full_state_for_orders_one_to_three(self) -> None:
        support_rows = self.runner.json.loads((self.runner.SUPPORT1 / "row-stats.json").read_text(encoding="utf-8"))["rows"]
        target_classes = {"SUPPORTED_SINGLETON_SILENT", "AUTHORITY_PRESENT_OUTSIDE_VALID_FRONTIER"}
        target_rows = {int(row["row"]) for row in support_rows if row["support_classification"] in target_classes or (row["support_classification"] == "VALID_FRONTIER_AUTHORITY_OBSERVED" and row["resid1_classification"] == "MOVABLE_NOT_TARGETABLE")}
        action_rows = {index: set(int(row) for row in action["dependency_rows"]) & target_rows for index, action in enumerate(self.context["actions"])}
        touched = sorted(index for index, rows in action_rows.items() if rows)
        self.assertTrue(touched)

        cases = [(touched[0],)]
        groups = tuple(self.context["groups"])
        by_group = self.context["by_group"]
        pair = next((tuple((a, b)) for left_pos, left in enumerate(groups) for right in groups[left_pos + 1:] for a in by_group[left] for b in by_group[right] if a in action_rows and (action_rows[a] or action_rows[b])), None)
        triple = next((tuple((a, b, c)) for i, left in enumerate(groups) for j in range(i + 1, len(groups)) for k in range(j + 1, len(groups)) for a in by_group[left] for b in by_group[groups[j]] for c in by_group[groups[k]] if action_rows[a] or action_rows[b] or action_rows[c]), None)
        self.assertIsNotNone(pair)
        self.assertIsNotNone(triple)
        cases.extend([pair, triple])

        for indices in cases:
            with self.subTest(actions=indices):
                affected = sorted(set().union(*(action_rows[index] for index in indices)))
                full = self.runner.full_candidate(self.exh, self.alg, self.context, indices)
                for row in affected:
                    self.assertEqual(self.runner.row_local_value(self.context, self.context["actions"], indices, row), int(full["readout"][row]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
