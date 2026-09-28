import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
RUN = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01")


def read_json(name: str):
    return json.loads((RUN / name).read_text(encoding="utf-8"))


class PhaseAJConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = read_json("phase-a-objective-graph-receipt.json")
        cls.graph = read_json("objective-graph.json")
        cls.manifests = read_json("arm-manifests.json")
        cls.triplets = [
            json.loads(line)
            for line in (RUN / "inputs/triplets.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_model_contact_is_closed(self):
        self.assertEqual(self.receipt["status"], "PHASE_A_OBJECTIVE_GRAPH_READY_NO_MODEL_CONTACT")
        self.assertFalse(self.receipt["model_contact_authorized"])
        self.assertFalse(self.receipt["feature_extraction"])
        self.assertFalse(self.receipt["phoenix_access"])

    def test_lineage_and_counts(self):
        self.assertEqual(self.receipt["phase_a_identity"], "phase-a-v01-clean")
        self.assertEqual(self.receipt["parent_phase_a_identity"], "phase-a-v02-clean")
        self.assertFalse(self.receipt["quarantined_parentage"])
        self.assertEqual(self.receipt["primary_bank"]["count"], 100000)
        self.assertEqual(self.receipt["auxiliary_sham_views"]["count"], 5000)
        self.assertEqual(self.receipt["triplets"]["count"], 5000)
        self.assertEqual(self.receipt["existing_surface_invariance_pair_count"], 4982)

    def test_all_arms_share_rows_and_auxiliary_views(self):
        manifests = list(self.manifests.values())
        self.assertEqual({item["primary_bank_sha256"] for item in manifests}, {self.receipt["primary_bank"]["sha256"]})
        self.assertEqual({item["auxiliary_sham_views_sha256"] for item in manifests}, {self.receipt["auxiliary_sham_views"]["sha256"]})
        self.assertEqual({item["row_multiset_distance_from_other_arms"] for item in manifests}, {0})

    def test_objective_factorial_is_exact(self):
        expected = {
            "J00": (False, False),
            "J10": (True, False),
            "J01": (False, True),
            "J11": (True, True),
        }
        for arm, (sham_active, edge_active) in expected.items():
            events = {event["event_name"]: event for event in self.graph["arms"][arm]["events"]}
            self.assertTrue(events["base_pointwise"]["active"])
            self.assertTrue(events["existing_surface_invariance"]["active"])
            self.assertEqual(events["sham_pointwise"]["active"], sham_active)
            self.assertEqual(events["anchor_sham_invariance"]["active"], edge_active)
            self.assertEqual(events["sham_pointwise"]["count"], 5000)
            self.assertEqual(events["anchor_sham_invariance"]["count"], 5000)
            for event in events.values():
                self.assertTrue(event["objective_event_signature"])

    def test_triplet_semantics_are_reconciled(self):
        self.assertEqual(len(self.triplets), 5000)
        for triplet in self.triplets:
            self.assertEqual(len(triplet["anchor_gold"]), len(triplet["sham_gold"]))
            for anchor_value, sham_value in zip(triplet["anchor_gold"], triplet["sham_gold"]):
                self.assertLessEqual(abs(anchor_value - sham_value), 1e-12)
            self.assertNotEqual(triplet["expected_old_winner_index"], triplet["expected_new_winner_index"])
            self.assertTrue(triplet["anchor_group_id"])
            self.assertTrue(triplet["fact_flip_group_id"])
            self.assertTrue(triplet["sham_group_id"])


if __name__ == "__main__":
    unittest.main()
