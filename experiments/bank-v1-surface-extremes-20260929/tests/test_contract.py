import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (ABSTAIN_REASONS, CATEGORICAL_HEADS, MULTILABEL_HEADS,
                    encode_targets, surface_batch)

class ContractTests(unittest.TestCase):
    def test_surface_derivations_are_fixed_and_ordered(self):
        p = {
            "final_token": np.full((2, 3), 4.0, dtype=np.float32),
            "full_mean": np.full((2, 3), 2.0, dtype=np.float32),
            "first_token": np.full((2, 3), 1.0, dtype=np.float32),
            "layer_m4_final": np.full((2, 3), 0.0, dtype=np.float32),
            "layer_m3_final": np.full((2, 3), 1.0, dtype=np.float32),
            "layer_m2_final": np.full((2, 3), 2.0, dtype=np.float32),
            "middle_final": np.full((2, 3), 3.0, dtype=np.float32),
        }
        projection = np.eye(3, dtype=np.float32)
        np.testing.assert_array_equal(surface_batch(p, 0, 1, "final_token", projection), [[4, 4, 4]])
        np.testing.assert_array_equal(surface_batch(p, 0, 1, "last4_final_mean", projection), [[1.75]*3])
        np.testing.assert_array_equal(surface_batch(p, 0, 1, "final_plus_mean", projection), [[4,4,4,2,2,2]])
        np.testing.assert_array_equal(surface_batch(p, 0, 1, "middle_plus_final", projection), [[3,3,3,4,4,4]])
        np.testing.assert_array_equal(surface_batch(p, 0, 1, "random_projection_256", projection), [[4,4,4]])

    def test_targets_come_only_from_bank_label_object(self):
        row = {
            "world_id": "TRAIN:test",
            "goal": {"pred": "AT", "args": ["obj_1", "loc_0"]},
            "bindings": [{"entity_id": "obj_1", "mention": "onyx_object"}],
            "labels": {
                "policy": {"decision": "ABSTAIN", "reason": "INSUFFICIENT_EVIDENCE"},
                "nli": "UNKNOWN",
                "entity": [{"id": "obj_1", "type": "OBJECT"}],
                "relation": [{"id": "f1", "pred": "CONNECTED"}],
                "transition": [{"id": "f1", "pred": "AT"}],
                "evidence": ["f1"],
            },
        }
        targets = encode_targets(row)
        self.assertEqual(CATEGORICAL_HEADS["decision"][targets["decision"]], "ABSTAIN")
        self.assertEqual(ABSTAIN_REASONS[targets["abstain_reason"]], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(set(MULTILABEL_HEADS["relation_predicates"][i]
                             for i in targets["relation_predicates"]), {"CONNECTED"})
        self.assertEqual(set(MULTILABEL_HEADS["evidence_predicates"][i]
                             for i in targets["evidence_predicates"]), {"CONNECTED"})
        self.assertFalse(any("goal_" in key for key in targets))

    def test_policy_only_rows_do_not_invent_structured_targets(self):
        row = {
            "world_id": "TEST:x@S4",
            "goal": {"pred": "AT", "args": ["obj_1", "loc_0"]},
            "bindings": [{"entity_id": "obj_1", "mention": "onyx_object"}],
            "labels": {"policy": {"decision": "ACT", "action": "MOVE"}},
        }
        targets = encode_targets(row)
        self.assertEqual(set(targets), {"decision", "action_type"})

if __name__ == "__main__":
    unittest.main()
