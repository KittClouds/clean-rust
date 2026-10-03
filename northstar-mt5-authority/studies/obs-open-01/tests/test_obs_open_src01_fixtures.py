from __future__ import annotations

import runpy
import unittest
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
FIXTURES = STUDY / "source-recovery/tools/test_src01_boundary_fixtures.py"


class ObsOpenSrc01FixtureTests(unittest.TestCase):
    def test_controlled_endpoint_fixtures(self) -> None:
        namespace = runpy.run_path(str(FIXTURES))
        namespace["test_end_candle_new_high_is_included"]()
        namespace["test_end_candle_new_low_is_included"]()
        namespace["test_endpoint_is_shared_by_period_and_area"]()


if __name__ == "__main__":
    unittest.main()
