"""Unit and post-run checks for Q10-GC0-AC3."""
from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import run_ac3 as AC3  # noqa: E402


class PrimitiveTests(unittest.TestCase):
    def test_finite_effect_rejects_missing_rows(self) -> None:
        effect = {
            "support_row_count": 2,
            "prefix_domain_complete": True,
            "physical_support_complete": True,
            "legal_prefixes": [{"choice": 0, "effect_bits": [0, 1], "geometry": {"x": 0.0}}],
            "illegal_prefixes": list(AC3.DECLARED_PREFIXES[1:]),
        }
        self.assertFalse(AC3.finite_effect(effect, 3))

    def test_finite_effect_requires_disjoint_prefix_partition(self) -> None:
        effect = {
            "support_row_count": 1,
            "prefix_domain_complete": True,
            "physical_support_complete": True,
            "legal_prefixes": [{"choice": 0, "effect_bits": [0], "geometry": {"x": 0.0}}],
            "illegal_prefixes": list(AC3.DECLARED_PREFIXES),
        }
        self.assertFalse(AC3.finite_effect(effect, 1))

    def test_json_hash_is_stable_for_key_order(self) -> None:
        self.assertEqual(AC3.json_hash({"b": 2, "a": 1}), AC3.json_hash({"a": 1, "b": 2}))


class SealTests(unittest.TestCase):
    def test_local_seal_is_preexecution_only(self) -> None:
        contract = AC3.load_local_seal()
        self.assertEqual(contract["identity"], "q10-gc0-ac3-v1")
        self.assertFalse(contract["firewall"]["gc1_authorized"])
        self.assertFalse(contract["firewall"]["candidate_generation"])


class PostRunTests(unittest.TestCase):
    def test_expansion_is_complete_when_execution_exists(self) -> None:
        if not AC3.EXECUTION.is_file():
            self.skipTest("AC3 execution has not run")
        execution = AC3.load_json(AC3.EXECUTION)
        self.assertEqual(execution["protocol"], "Q10-GC0-AC3")
        self.assertTrue(execution["firewall"]["engineering_only"])
        self.assertFalse(execution["firewall"]["scientific_promotion"])
        self.assertTrue(execution["gate"]["expanded_records_complete"])
        self.assertTrue(execution["gate"]["complete_authority_support_equals_raw_support"])

    def test_expansion_tables_are_unique_and_complete(self) -> None:
        if not AC3.EXPANDED_EFFECTS.is_file() or not AC3.EXPANDED_FEATURES.is_file():
            self.skipTest("AC3 expansion tables have not been written")
        effects = [json.loads(line) for line in AC3.EXPANDED_EFFECTS.read_text(encoding="utf-8").splitlines()]
        features = [json.loads(line) for line in AC3.EXPANDED_FEATURES.read_text(encoding="utf-8").splitlines()]
        effect_keys = {(item["endpoint"], int(item["set_index"]), int(item["coordinate"])) for item in effects}
        feature_keys = {(item["endpoint"], int(item["set_index"]), int(item["group_index"]), int(item["coordinate"])) for item in features}
        self.assertEqual(len(effects), len(effect_keys))
        self.assertEqual(len(features), len(feature_keys))
        self.assertTrue(all(item["complete"] for item in features))
        self.assertTrue(all(AC3.finite_effect(item, int(item["support_row_count"])) for item in effects))


if __name__ == "__main__":
    unittest.main()
