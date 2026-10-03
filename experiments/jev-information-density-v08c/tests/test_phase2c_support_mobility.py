from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_phase2c_support_mobility as mobility


class SupportMobilityTests(unittest.TestCase):
    def test_canonical_digest_is_order_stable_for_mapping(self) -> None:
        self.assertEqual(mobility.digest({"a": 1, "b": 2}), mobility.digest({"b": 2, "a": 1}))

    def test_tv_identical_and_disjoint(self) -> None:
        self.assertEqual(mobility.tv(Counter({"a": 4}), Counter({"a": 4})), 0.0)
        self.assertEqual(mobility.tv(Counter({"a": 4}), Counter({"b": 4})), 1.0)

    def test_same_marginal_swap_has_zero_tv(self) -> None:
        base_t = Counter({"topology:x": 10})
        base_i = Counter({"intervention:x": 10})
        top_tv, intervention_tv = mobility.profile_tv_after_swap(
            base_t, base_i, base_t, base_i,
            ("topology:x",), ("topology:x",), "intervention:x", "intervention:x",
        )
        self.assertEqual((top_tv, intervention_tv), (0.0, 0.0))

    def test_swap_recomputes_both_marginals(self) -> None:
        base_t = Counter({"a": 100, "b": 100})
        base_i = Counter({"i": 100, "j": 100})
        top_tv, intervention_tv = mobility.profile_tv_after_swap(
            base_t, base_i, base_t, base_i,
            ("a",), ("b",), "i", "j",
        )
        self.assertGreater(top_tv, 0.0)
        self.assertGreater(intervention_tv, 0.0)

    def test_marginal_delta_removes_zero_counts(self) -> None:
        base = Counter({"a": 1})
        result = mobility.apply_delta(base, Counter({"a": -1, "b": 1}))
        self.assertEqual(result, Counter({"b": 1}))


if __name__ == "__main__":
    unittest.main()
