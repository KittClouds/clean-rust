"""Unit and live preflight tests for Q10-NA NA-0/NA-1/NA-2."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))

import qualify_q10_na as na  # noqa: E402


class PurePreflightTests(unittest.TestCase):
    def test_target_key_is_endpoint_row_identity(self) -> None:
        item = {"endpoint": "seed.json", "set_index": 2, "row": 17}
        self.assertEqual(na.target_key(item), ("seed.json", 2, 17))

    def test_raw_support_union_is_counted_without_helpful_overlay(self) -> None:
        targets = [
            {
                "endpoint": "seed.json",
                "set_index": 0,
                "row": 3,
                "all_raw_coordinates": 2,
            }
        ]
        raw = {("seed.json", 0, 3): {11, 19}}
        report = na.check_raw_support(targets, raw)
        self.assertTrue(report["complete"])
        self.assertEqual(report["total_raw_support_coordinates"], 2)

    def test_prefix_coverage_fails_closed_on_missing_key(self) -> None:
        targets = [
            {
                "endpoint": "seed.json",
                "set_index": 0,
                "row": 3,
            }
        ]
        raw = {("seed.json", 0, 3): {11}}
        keys = {("seed.json", 0, 11, step) for step in na.RMT_STEPS[:-1]}
        report = na.check_prefix_coverage(targets, raw, keys)
        self.assertEqual(report["required_prefix_keys"], len(na.RMT_STEPS))
        self.assertEqual(report["missing_prefix_keys"], 1)
        self.assertFalse(report["complete"])

    def test_empty_raw_support_is_complete_local_domain_only(self) -> None:
        targets = [{"endpoint": "seed.json", "set_index": 0, "row": 251}]
        report = na.classify_target_domains(targets, {}, set())
        record = report["records"][0]
        self.assertEqual(record["support_size"], 0)
        self.assertEqual(record["raw_support_coordinates"], [])
        self.assertTrue(record["complete_empty_domain"])
        self.assertEqual(
            record["local_preflight_classification"],
            "no-effect-within-complete-domain",
        )
        self.assertFalse(record["pair_replay_required"])
        self.assertFalse(record["triple_replay_required"])
        self.assertFalse(record["global_impossibility_claim"])
        self.assertEqual(report["empty_support_count"], 1)
        self.assertEqual(report["nonempty_support_count"], 0)

    def test_domain_cost_projection_uses_zero_plus_signed_prefixes(self) -> None:
        contract = {
            "budgets": {
                "max_pair_replays_per_row": 131072,
                "max_pair_replays_total": 25000000,
                "max_triple_replays_per_row": 1048576,
                "max_triple_replays_total": 50000000,
            },
            "replay": {
                "ordering": {
                    "endpoint": "stable endpoint identity",
                    "row": "ascending readout row",
                    "coordinates": "ascending coordinate tuple",
                    "prefix_tuple": "contract order",
                }
            },
        }
        targets = [
            {"endpoint": "a", "set_index": 0, "row": 1},
            {"endpoint": "b", "set_index": 0, "row": 2},
        ]
        raw = {
            ("a", 0, 1): {10, 20},
            ("b", 0, 2): set(),
        }
        report = na.project_domain_costs(targets, raw, contract)
        self.assertEqual(report["choice_count_per_coordinate"], 11)
        self.assertEqual(report["pair"]["exact_total_candidates"], 121)
        self.assertEqual(report["triple"]["exact_total_candidates"], 0)
        self.assertEqual(report["support_size_summary"]["minimum"], 0)
        self.assertEqual(report["support_size_summary"]["maximum"], 2)
        self.assertFalse(report["support_size_priority_used"])
        self.assertFalse(report["residual_mass_priority_used"])
        self.assertEqual(
            report["classification_guard"]["incomplete_global_triple_domain"],
            "higher-order-or-untested",
        )


class LivePreflightTests(unittest.TestCase):
    def test_current_receipt_has_exact_targets_and_explicit_coverage_state(self) -> None:
        receipt = na.build_receipt()
        self.assertEqual(receipt["targets"]["observed"], 326)
        self.assertEqual(receipt["targets"]["unique_identities"], 326)
        self.assertEqual(receipt["raw_support"]["union_mismatch_count"], 0)
        empty = receipt["targets"]["empty_support_summary"]
        self.assertEqual(empty["empty_support_count"], 2)
        self.assertEqual(empty["nonempty_support_count"], 324)
        self.assertEqual(empty["empty_support_rows"], [251, 251])
        self.assertFalse(empty["global_impossibility_claim"])
        costs = receipt["cost_projection"]
        self.assertEqual(costs["choice_count_per_coordinate"], 11)
        self.assertEqual(costs["support_size_summary"]["minimum"], 0)
        self.assertEqual(costs["support_size_summary"]["median"], 7)
        self.assertEqual(costs["support_size_summary"]["maximum"], 24)
        self.assertEqual(costs["pair"]["exact_total_candidates"], 1493624)
        self.assertTrue(costs["pair"]["within_total_budget"])
        self.assertEqual(costs["triple"]["exact_total_candidates"], 61058294)
        self.assertFalse(costs["triple"]["within_total_budget"])
        self.assertEqual(costs["triple"]["rows_within_per_row_budget"], 317)
        self.assertEqual(costs["triple"]["rows_over_per_row_budget"], 9)
        self.assertFalse(costs["support_size_priority_used"])
        self.assertFalse(costs["residual_mass_priority_used"])
        self.assertEqual(
            costs["classification_guard"]["incomplete_global_triple_domain"],
            "higher-order-or-untested",
        )
        empty_records = [
            item
            for item in receipt["targets"]["domain_records"]
            if item["support_size"] == 0
        ]
        self.assertEqual(len(empty_records), 2)
        self.assertTrue(
            all(
                item["local_preflight_classification"]
                == "no-effect-within-complete-domain"
                for item in empty_records
            )
        )
        self.assertTrue(
            all(
                item["global_impossibility_claim"] is False
                for item in empty_records
            )
        )
        self.assertIn(
            receipt["status"],
            {na.EXPECTED_NA_STATUS, na.BLOCKED_NA_STATUS, na.HASH_ERROR_STATUS},
        )
        self.assertFalse(receipt["replay_findings_emitted"])
        self.assertEqual(receipt["scientific_seed_bundles_used"], 0)
        self.assertFalse(receipt["behavioral_inference"])

    def test_preflight_receipt_has_no_replay_sections(self) -> None:
        receipt_path = na.protocol_root() / "qualification/preflight.json"
        if not receipt_path.exists():
            self.skipTest("run qualify_q10_na.py before the live receipt check")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertFalse(receipt["replay_findings_emitted"])
        self.assertNotIn("single_findings", receipt)
        self.assertNotIn("pair_findings", receipt)
        self.assertNotIn("triple_findings", receipt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
