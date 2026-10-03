"""Tests for the minimal deterministic Q10-PF5 dry run."""
from __future__ import annotations

import unittest

from qualify_q10_pf5 import bits, from_bits, prefix_value
from run_q10_pf5_dry import CHOICES, prefix_domain, sequential


class PrefixReplayTests(unittest.TestCase):
    def test_sequential_replay_starts_from_negative_zero(self) -> None:
        result = sequential([0, 1], [from_bits(0), from_bits(0)])
        self.assertEqual(bits(result), 0x00000000)

    def test_prefix_domain_contains_zero_and_legal_signed_prefixes(self) -> None:
        value = from_bits(0x3F000000)
        domain = prefix_domain(value)
        self.assertEqual(domain[0], 0)
        self.assertEqual(set(domain), set(CHOICES))
        for choice in domain:
            candidate = prefix_value(value, choice)
            self.assertTrue(0.0 < candidate < 2.0)


if __name__ == "__main__":
    unittest.main()
