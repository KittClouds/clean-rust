"""Receipt-level regression checks for the completed Q10-NA local replay."""
from __future__ import annotations

import collections
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReplayReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pair = json.loads((ROOT / "qualification/pair-full.json").read_text(encoding="utf-8"))
        cls.triple = json.loads((ROOT / "qualification/triple-full.json").read_text(encoding="utf-8"))
        cls.status = json.loads((ROOT / "STATUS.json").read_text(encoding="utf-8"))

    def test_pair_partition_and_budget(self) -> None:
        classes = collections.Counter(item["classification"] for item in self.pair["records"])
        self.assertEqual(classes, {"pair": 213, "no-effect-within-complete-domain": 111})
        self.assertEqual(sum(item["pair_replays"] for item in self.pair["records"]), 1_493_624)
        self.assertFalse(self.pair["triple_replay_executed"])

    def test_triple_partition_and_budget(self) -> None:
        classes = collections.Counter(item["classification"] for item in self.triple["records"])
        self.assertEqual(classes, {"triple": 16, "no-effect-within-complete-domain": 95})
        self.assertEqual(sum(item["triple_replays"] for item in self.triple["records"]), 15_868_182)
        self.assertTrue(all(item["triple_domain_complete"] for item in self.triple["records"]))

    def test_scope_firewall(self) -> None:
        for receipt in (self.pair, self.triple):
            self.assertEqual(receipt["scientific_seed_bundles_used"], 0)
            self.assertFalse(receipt["behavioral_inference"])
            self.assertFalse(receipt["canonical_repair_applied"])
            self.assertFalse(receipt["dh08b_authorized"])

    def test_status_matches_partition(self) -> None:
        self.assertEqual(self.status["status"], "Q10_NA_REPLAY_VALID__LOCAL_JOINT_AUTHORITY_MAPPED")
        self.assertEqual(self.status["target_rows"], 326)
        self.assertEqual(self.status["pair_authority_rows"], 213)
        self.assertEqual(self.status["triple_authority_rows"], 16)
        self.assertEqual(self.status["no_effect_after_pair_triple_rows"], 95)


if __name__ == "__main__":
    unittest.main(verbosity=2)
