from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("train_proposal_v02.py")
SPEC = importlib.util.spec_from_file_location("r1_v05_proposal_fit_v02_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIT)


class RoleAwareProposalFeatureTests(unittest.TestCase):
    def test_adds_explicit_old_and_new_role_without_changing_base_features(self) -> None:
        static = np.arange(20 * 3 * 8, dtype=np.float32).reshape(20, 3, 8) / 100.0
        assignment = [index % 3 for index in range(20)]
        base_actions, base_features = FIT.FM.candidate_features(static, assignment)

        actions, features = FIT.build_state_action_features(static, assignment)

        self.assertEqual(actions, base_actions)
        self.assertEqual(features.shape, (40, 16))
        np.testing.assert_array_equal(features[:, :10], base_features)
        self.assertEqual(actions[0], (0, 1))
        self.assertEqual(features[0, 10:13].tolist(), [1.0, 0.0, 0.0])
        self.assertEqual(features[0, 13:16].tolist(), [0.0, 1.0, 0.0])
        self.assertEqual(features[1, 13:16].tolist(), [0.0, 0.0, 1.0])

    def test_rejects_invalid_assignment_role(self) -> None:
        static = np.zeros((20, 3, 8), dtype=np.float32)
        assignment = [index % 3 for index in range(20)]
        assignment[0] = 3
        with self.assertRaisesRegex(ValueError, "valid N=20, K=3"):
            FIT.build_state_action_features(static, assignment)


if __name__ == "__main__":
    unittest.main()
