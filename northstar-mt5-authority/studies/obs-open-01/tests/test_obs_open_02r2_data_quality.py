from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools/obs_open_02r2_data_quality.py"
SPEC = importlib.util.spec_from_file_location("obs_open_02r2_data_quality", PATH)
assert SPEC is not None and SPEC.loader is not None
QUALITY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = QUALITY
SPEC.loader.exec_module(QUALITY)


class ObsOpen02R2DataQualityTests(unittest.TestCase):
    def test_bounded_reader_never_requests_first_forbidden_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.tsv"
            source.write_bytes(b"header\nd1\nd2\nd3\nd4\nconfirmation\n")
            rows = tuple(QUALITY.bounded_prefix_lines(source, safe_rows=3, total_rows=4))
        self.assertEqual((b"header\n", b"d1\n", b"d2\n", b"d3\n", b"d4\n"), rows)
        self.assertNotIn(b"confirmation\n", rows)

    def test_clock_mapping_matches_frozen_winter_and_summer_wall_time(self) -> None:
        winter = QUALITY.minute_epoch(QUALITY.date(2024, 1, 17), QUALITY.time(9, 30), 120)
        summer = QUALITY.minute_epoch(QUALITY.date(2024, 8, 14), QUALITY.time(9, 30), 180)
        winter_wall = QUALITY.datetime.fromtimestamp(winter, QUALITY.timezone.utc)
        summer_wall = QUALITY.datetime.fromtimestamp(summer, QUALITY.timezone.utc)
        self.assertEqual((16, 30), (winter_wall.hour, winter_wall.minute))
        self.assertEqual((16, 30), (summer_wall.hour, summer_wall.minute))


if __name__ == "__main__":
    unittest.main()
