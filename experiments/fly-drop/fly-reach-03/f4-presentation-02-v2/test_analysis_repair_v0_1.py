from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_cphi_repair_v0_1 import _epoch_number  # noqa: E402


class AnalysisEpochRepairTests(unittest.TestCase):
    def test_decimal_csv_epoch_parses_as_integer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trace.csv"
            path.write_text("epoch,training_bce\n1.0,0.7\n200.0,0.1\n", encoding="utf-8")
            with path.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([_epoch_number(row["epoch"]) for row in rows], [1, 200])

    def test_integer_csv_epoch_remains_supported(self):
        self.assertEqual(_epoch_number("42"), 42)


if __name__ == "__main__":
    unittest.main()
