from __future__ import annotations

import unittest

from resume_interrupted_fit_grid import expected_fit_ids, missing_fit_ids


class ResumeGridTests(unittest.TestCase):
    def test_frozen_grid_is_144_ids_in_block_replicate_arm_order(self) -> None:
        arms = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
        blocks = tuple(range(309000, 309012))
        fit_ids = expected_fit_ids(blocks, arms)
        self.assertEqual(len(fit_ids), 144)
        self.assertEqual(fit_ids[:4], ["D-H309000-I0", "Cphi-H309000-I0", "Cphi_unshared-H309000-I0", "Cphi_shuffled-H309000-I0"])
        self.assertEqual(fit_ids[-1], "Cphi_shuffled-H309011-I2")

    def test_missing_ids_preserve_manifest_order_without_rerunning_completed(self) -> None:
        expected = ["D-H1-I0", "Cphi-H1-I0", "D-H1-I1"]
        self.assertEqual(missing_fit_ids(expected, ["Cphi-H1-I0"]), ["D-H1-I0", "D-H1-I1"])

    def test_unknown_or_duplicate_ids_fail_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            missing_fit_ids(["D-H1-I0"], ["S-H1-I0"])
        with self.assertRaises(RuntimeError):
            missing_fit_ids(["D-H1-I0"], ["D-H1-I0", "D-H1-I0"])


if __name__ == "__main__":
    unittest.main()
