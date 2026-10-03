from __future__ import annotations

import unittest

import numpy as np

from evaluate_qterminal_action_delta_v01 import fit_beta, softmax_cross_entropy


class QTerminalActionDeltaTests(unittest.TestCase):
    def test_uniform_scores_match_uniform_policy_cross_entropy(self):
        q = np.asarray([[0.5, 0.5, 0.0], [0.0, 0.25, 0.75]], dtype=np.float64)
        scores = np.zeros_like(q)
        self.assertAlmostEqual(softmax_cross_entropy(q, scores, 1.0), np.log(3.0), places=12)

    def test_fit_beta_uses_teacher_mass_and_returns_finite_value(self):
        q = np.asarray([[0.9, 0.1, 0.0], [0.0, 0.1, 0.9]], dtype=np.float64)
        scores = np.asarray([[1.0, 0.0, -1.0], [-1.0, 0.0, 1.0]], dtype=np.float64)
        beta, loss = fit_beta(q, scores)
        self.assertGreater(beta, 0.0)
        self.assertTrue(np.isfinite(loss))
        self.assertLess(loss, softmax_cross_entropy(q, scores, 0.0))


if __name__ == "__main__":
    unittest.main()
