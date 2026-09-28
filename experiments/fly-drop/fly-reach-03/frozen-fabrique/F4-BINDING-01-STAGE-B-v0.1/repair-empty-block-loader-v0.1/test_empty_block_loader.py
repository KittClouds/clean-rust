"""Synthetic regression tests for expected-but-empty Stage B task blocks."""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

BRANCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRANCH))
import binding_stage_b_data as data  # noqa: E402
from binding_stage_b_empty_block_loader import load_predictors_allow_empty  # noqa: E402


def write_panel(path: Path, block: int) -> None:
    key = bytearray(18)
    key[0] = 0
    key[1] = 0
    struct.pack_into("<QII", key, 2, block, 0, 0)
    record = bytes(key) + np.zeros(66, dtype="<f4").tobytes() + bytes(4 * 15)
    header = data.INPUT_MAGIC + struct.pack("<IIQ", 1, data.INPUT_WIDTH, 1)
    path.write_bytes(header + record)


class EmptyBlockLoaderTests(unittest.TestCase):
    def test_absent_expected_blocks_are_valid_empty_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictors.bin"
            write_panel(path, 310001)
            panel = load_predictors_allow_empty(data, path)
            self.assertEqual(len(panel.keys), 1)
            self.assertEqual(set(map(int, panel.blocks)), {310001})
            self.assertEqual(panel.base.shape, (1, 66))
            self.assertEqual(panel.tuples.shape, (1, 4, 6))

    def test_out_of_domain_block_is_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictors.bin"
            write_panel(path, 319999)
            with self.assertRaisesRegex(RuntimeError, "outside the frozen domain"):
                load_predictors_allow_empty(data, path)


if __name__ == "__main__":
    unittest.main()
