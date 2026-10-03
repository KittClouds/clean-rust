from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("train_action_relevance_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v05_action_fit_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIT)


class ActionFeatureTests(unittest.TestCase):
    def test_feature_encodes_state_edit_public_incidence_and_frozen_views(self) -> None:
        task = {
            "id": "task-0",
            "n": 20,
            "k": 3,
            "clauses": [{}, {}, {}],
            "entity_mentions": [[0, 1], [0, 2], [5]],
            "role_mentions": [[1], [0, 2], [2]],
        }
        global_h = np.zeros(FIT.HIDDEN, dtype=np.float32)
        global_h[0] = 0.25
        clause_h = np.zeros((3, FIT.HIDDEN), dtype=np.float32)
        clause_h[:, 5] = (1.0, 3.0, 5.0)
        cached = FIT._task_features(task, global_h, clause_h)
        assignment = [index % 3 for index in range(FIT.N_ENTITIES)]
        row = {
            "assignment": assignment,
            "edit": {"entity": 0, "from_role": 0, "to_role": 1},
            "sign_delta": 1,
            "teacher_q_probability": 1.0,
        }

        feature = FIT.action_feature(task, cached, row)
        row_with_different_teacher_q = {**row, "teacher_q_probability": 0.0}
        np.testing.assert_array_equal(feature, FIT.action_feature(task, cached, row_with_different_teacher_q))

        self.assertEqual(feature.shape, (6410,))
        self.assertEqual(feature[0], 1.0)  # entity 0 currently has role 0
        self.assertEqual(feature[60 + 1], 1.0)  # edit (entity 0, role 0 -> 1)
        self.assertAlmostEqual(float(feature[240]), 2.0 / 3.0)  # incidence count for entity 0
        self.assertAlmostEqual(float(feature[241]), 1.0 / 3.0)  # incidence count for entity 1
        self.assertAlmostEqual(float(feature[260]), 0.5)  # role incidence, normalized by affected clauses
        self.assertAlmostEqual(float(feature[266]), 0.25)  # global frozen view
        self.assertAlmostEqual(float(feature[266 + FIT.HIDDEN + 5]), 3.0)  # mean clause view
        self.assertAlmostEqual(float(feature[266 + FIT.HIDDEN * 2 + 5]), 2.0)  # entity-conditioned view

        actions, state_features = FIT.action_features_for_state(task, cached, assignment)
        self.assertEqual(actions[0], (0, 1))
        np.testing.assert_array_equal(state_features[0], feature)
        np.testing.assert_array_equal(
            state_features[1],
            FIT.action_feature(task, cached, {"assignment": assignment,
                                              "edit": {"entity": 0, "from_role": 0, "to_role": 2}}),
        )

    def test_action_must_match_assignment_and_be_a_real_edit(self) -> None:
        task = {"id": "task-0", "n": 20, "k": 3, "clauses": [],
                "entity_mentions": [], "role_mentions": []}
        cached = FIT._task_features(
            task, np.zeros(FIT.HIDDEN, dtype=np.float32), np.empty((0, FIT.HIDDEN), dtype=np.float32)
        )
        assignment = [index % 3 for index in range(FIT.N_ENTITIES)]
        row = {"assignment": assignment, "edit": {"entity": 0, "from_role": 1, "to_role": 2}}
        with self.assertRaisesRegex(ValueError, "legal state edit"):
            FIT.action_feature(task, cached, row)

    def test_negative_entity_id_is_rejected_without_python_negative_indexing(self) -> None:
        task = {"id": "task-0", "n": 20, "k": 3, "clauses": [],
                "entity_mentions": [], "role_mentions": []}
        cached = FIT._task_features(
            task, np.zeros(FIT.HIDDEN, dtype=np.float32), np.empty((0, FIT.HIDDEN), dtype=np.float32)
        )
        assignment = [index % 3 for index in range(FIT.N_ENTITIES)]
        row = {"assignment": assignment,
               "edit": {"entity": -1, "from_role": assignment[-1], "to_role": (assignment[-1] + 1) % 3}}
        with self.assertRaisesRegex(ValueError, "legal state edit"):
            FIT.action_feature(task, cached, row)

    def test_delta_fields_must_agree_with_exact_signed_change(self) -> None:
        row = {"satisfied_before": 7, "satisfied_after": 9,
               "delta_satisfied": 2, "sign_delta": 1}
        self.assertEqual(FIT.exact_delta_label(row), 1)
        row["sign_delta"] = -1
        with self.assertRaisesRegex(ValueError, "fields disagree"):
            FIT.exact_delta_label(row)


if __name__ == "__main__":
    unittest.main()
