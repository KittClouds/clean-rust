from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("train_proposal_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v05_proposal_fit_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIT)


class ProposalTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = {"id": "task-0", "family_id": "family-0"}
        self.assignment = [index % 3 for index in range(FIT.N_ENTITIES)]
        self.actions = [
            (entity, role)
            for entity, old_role in enumerate(self.assignment)
            for role in range(FIT.N_ROLES)
            if role != old_role
        ]

    def _teacher(self, outcome: str = "positive_mass") -> dict:
        mass = 1.0 / len(self.actions) if outcome == "positive_mass" else 0.0
        return {
            "schema": "r1-proposal-teacher-sample-v01",
            "task_id": "task-0",
            "family_id": "family-0",
            "family_split": "train",
            "target": {
                "schema": FIT.TARGET_SCHEMA,
                "outcome": outcome,
                "edits": [{"entity": entity, "new_role": role, "q_probability": mass,
                           "g_fraction": 0.5} for entity, role in self.actions],
            },
        }

    def test_positive_teacher_distribution_maps_to_runtime_action_order(self) -> None:
        q, broadness = FIT.validate_target_row(self._teacher(), self.task, "train", self.actions)
        self.assertEqual(q.shape, (40,))
        self.assertAlmostEqual(float(q.sum()), 1.0)
        np.testing.assert_allclose(broadness, 0.5)

    def test_zero_mass_teacher_state_fails_closed_for_this_fit(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires positive-mass"):
            FIT.validate_target_row(self._teacher("zero_mass"), self.task, "train", self.actions)

    def test_action_order_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "action order/schema"):
            FIT.validate_target_row(self._teacher(), self.task, "train", list(reversed(self.actions)))


if __name__ == "__main__":
    unittest.main()
