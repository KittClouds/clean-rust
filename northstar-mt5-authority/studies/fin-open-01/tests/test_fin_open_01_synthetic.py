import sys
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from fin_open_01_synthetic import (  # noqa: E402
    analyze,
    block_permute_profiles,
    make_surface,
    run_synthetic_qualification,
)


class FinOpen01SyntheticTests(unittest.TestCase):
    def test_complete_synthetic_receipt_passes(self) -> None:
        receipt = run_synthetic_qualification()
        self.assertEqual(receipt["status"], "PASS")
        self.assertFalse(receipt["real_outcomes_read"])
        self.assertFalse(receipt["science_confirmation_read"])

    def test_block_randomization_preserves_whole_profiles_by_stratum(self) -> None:
        surface = make_surface(relation="same")
        moved = block_permute_profiles(surface, seed=19)
        for stratum in (120, 180):
            original = sorted(profile for profile, value in zip(surface.profiles, surface.strata) if value == stratum)
            shuffled = sorted(profile for profile, value in zip(moved, surface.strata) if value == stratum)
            self.assertEqual(original, shuffled)

    def test_session_count_is_the_independent_unit(self) -> None:
        surface = make_surface(scales=8, horizons=12, relation="same")
        result = analyze(surface, permutations=64)
        self.assertEqual(result["independent_units"], surface.sessions)


if __name__ == "__main__":
    unittest.main()
