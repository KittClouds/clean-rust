from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "obs_open_02r1_familywise_rules.py"
SPEC = importlib.util.spec_from_file_location("obs_open_02r1_rules", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RULES = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RULES
SPEC.loader.exec_module(RULES)


class ObsOpen02R1RuleTests(unittest.TestCase):
    def test_complete_null_fixture_is_not_promoted(self) -> None:
        values = {f"S{i:03d}": 0.0 for i in range(129)}
        summary = RULES.bootstrap_summary(values)
        self.assertEqual(0.0, summary["point_estimate"])
        self.assertEqual(1.0, summary["raw_p"])

    def test_injected_effect_can_pass_holm_only_when_familywise_qualified(self) -> None:
        p_values = {key: 0.5 for key in RULES.expand_estimand_ids()}
        p_values["SIGNED_PATH_DISPLACEMENT_K09"] = 0.0001
        decisions = RULES.holm_bonferroni(p_values)
        self.assertTrue(decisions["SIGNED_PATH_DISPLACEMENT_K09"])

    def test_formal_family_is_complete_and_fixed(self) -> None:
        ids = RULES.expand_estimand_ids()
        self.assertEqual(119, len(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("WIDTH_DELTA_ADJACENT_K01_TO_K02", ids)
        self.assertIn("SIGNED_PATH_DISPLACEMENT_K30", ids)

    def test_bootstrap_is_deterministic_and_session_based(self) -> None:
        values = {f"S{i:03d}": float(i - 3) for i in range(20)}
        first = RULES.bootstrap_summary(values)
        second = RULES.bootstrap_summary(dict(reversed(tuple(values.items()))))
        self.assertEqual(first, second)
        self.assertEqual(2000, first["resamples"])
        self.assertEqual(20260814, first["seed"])

    def test_holm_blocks_isolated_attractive_value(self) -> None:
        p_values = {key: 0.5 for key in RULES.expand_estimand_ids()}
        p_values["WIDTH_DELTA_ADJACENT_K17_TO_K18"] = 0.001
        decisions = RULES.holm_bonferroni(p_values)
        self.assertFalse(decisions["WIDTH_DELTA_ADJACENT_K17_TO_K18"])

    def test_support_floors_are_predata(self) -> None:
        good = RULES.SupportSnapshot(129, 4, 10, 2, 20)
        weak = RULES.SupportSnapshot(128, 4, 10, 2, 20)
        self.assertTrue(RULES.support_pass(good))
        self.assertFalse(RULES.support_pass(weak))
        self.assertFalse(RULES.support_pass(good, conditional=True))

    def test_sparse_and_conditional_cells_fail_closed(self) -> None:
        sparse = RULES.SupportSnapshot(129, 4, 10, 2, 20, conditional_cell_sessions=29)
        admitted = RULES.SupportSnapshot(129, 4, 10, 2, 20, conditional_cell_sessions=30)
        self.assertFalse(RULES.support_pass(sparse, conditional=True))
        self.assertTrue(RULES.support_pass(admitted, conditional=True))

    def test_temporal_sign_reversal_is_not_stability(self) -> None:
        stable = RULES.temporal_status(1, [(1, True)] * 4, [(1, True)] * 2)
        unstable = RULES.temporal_status(1, [(1, True), (-1, True), (-1, True), (1, True)], [(1, True)] * 2)
        insufficient = RULES.temporal_status(1, [(1, True), (0, True), (1, True), (1, True)], [(1, True)] * 2)
        self.assertEqual("TEMPORALLY_SUPPORTED", stable)
        self.assertEqual("TEMPORALLY_UNSTABLE", unstable)
        self.assertEqual("TEMPORAL_SUPPORT_INSUFFICIENT", insufficient)
        sensitivity_failure = RULES.temporal_status(1, [(1, True)] * 4, [(1, True)] * 2, [(0, True)])
        self.assertEqual("TEMPORAL_SUPPORT_INSUFFICIENT", sensitivity_failure)

    def test_candidate_precedence_and_disabled_semantics(self) -> None:
        support = RULES.SupportSnapshot(129, 4, 10, 2, 20)
        category, reason = RULES.classify_formal_candidate(
            "WIDTH_DELTA_ADJACENT", 1.0, 0.001, True, support, "TEMPORALLY_SUPPORTED"
        )
        self.assertEqual("SCALE_DEPENDENT_STRUCTURE", category)
        self.assertIsNone(reason)
        category, reason = RULES.classify_formal_candidate(
            "WIDTH_DELTA_ADJACENT", 1.0, 0.001, True, support, "TEMPORALLY_UNSTABLE"
        )
        self.assertEqual("TEMPORALLY_UNSTABLE_STRUCTURE", category)
        self.assertEqual("TEMPORALLY_UNSTABLE", reason)

    def test_disabled_representation_and_null_classes_are_descriptive(self) -> None:
        contract = json.loads((ROOT / "contracts/obs_open_02r1_familywise_rule_v1.json").read_text(encoding="utf-8"))
        classes = contract["candidate_classes"]
        self.assertIn("DESCRIPTIVE_ONLY", classes["REPRESENTATION_SENSITIVE_STRUCTURE"])
        self.assertIn("DISABLED", classes["SUPPORTED_NULL_OR_NEAR_NULL"])
        self.assertEqual("NEAR_NULL_NOT_EVALUABLE", contract["near_null"]["classification"])

    def test_isolated_scale_extremum_has_no_special_rule(self) -> None:
        contract = json.loads((ROOT / "contracts/obs_open_02r1_familywise_rule_v1.json").read_text(encoding="utf-8"))
        self.assertIn("DISABLED", contract["candidate_classes"]["SCALE_STABLE_STRUCTURE"])
        self.assertIn("NO_PREDECLARED_REGION_RULE", contract["rejection_codes"])

    def test_unknown_or_nonformal_view_fails_closed(self) -> None:
        support = RULES.SupportSnapshot(129, 4, 10, 2, 20)
        category, reason = RULES.classify_formal_candidate(
            "REPRESENTATION_SENSITIVE_STRUCTURE", 1.0, 0.001, True, support, "TEMPORALLY_SUPPORTED"
        )
        self.assertEqual(("NOT_EVALUABLE", "NOT_EVALUABLE"), (category, reason))

    def test_no_real_data_path_is_used(self) -> None:
        self.assertFalse((ROOT / "qualification/universe/universe/discovery_census.tsv").exists())
        self.assertFalse((ROOT / "qualification/universe/universe/candidate_registry.tsv").exists())


if __name__ == "__main__":
    unittest.main()
