from __future__ import annotations

import unittest

import numpy as np

from s04_analyze import _diff, _margin_vector, _statistics
from s04_common import STATE_PAIRS


class MarginContractTests(unittest.TestCase):
    def test_pair_and_target_margins(self) -> None:
        result = _margin_vector(np.asarray([4.0, 1.0, 3.0]), target_state=2)
        self.assertEqual(result["state_0_minus_state_1"], 3.0)
        self.assertEqual(result["state_0_minus_state_2"], 1.0)
        self.assertEqual(result["state_1_minus_state_2"], -2.0)
        self.assertEqual(result["target_vs_best_rival"], -1.0)

    def test_delta_and_gamma_sign_convention(self) -> None:
        mean_a = _margin_vector(np.asarray([2.0, 1.0, 0.0]), target_state=0)
        mean_c = _margin_vector(np.asarray([3.0, 1.0, 0.0]), target_state=0)
        final_a = _margin_vector(np.asarray([1.0, 2.0, 0.0]), target_state=0)
        final_c = _margin_vector(np.asarray([4.0, 2.0, 0.0]), target_state=0)
        delta_mean = _diff(mean_a, mean_c)
        delta_final = _diff(final_a, final_c)
        gamma = {key: delta_final[key] - delta_mean[key] for key in delta_mean}
        self.assertEqual(delta_mean["state_0_minus_state_1"], 1.0)
        self.assertEqual(delta_final["state_0_minus_state_1"], 3.0)
        self.assertEqual(gamma["state_0_minus_state_1"], 2.0)
        self.assertEqual(len(STATE_PAIRS), 3)

    def test_nearest_rank_summary(self) -> None:
        result = _statistics([4.0, -1.0, 2.0, 3.0, 0.0])
        self.assertEqual(result["n"], 5)
        self.assertEqual(result["nearest_rank_p10"], -1.0)
        self.assertEqual(result["nearest_rank_p90"], 4.0)
        self.assertEqual((result["positive"], result["zero"], result["negative"]), (3, 1, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
