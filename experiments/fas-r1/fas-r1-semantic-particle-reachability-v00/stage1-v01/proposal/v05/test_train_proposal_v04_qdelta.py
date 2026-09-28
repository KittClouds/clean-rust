from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SOURCE = Path(__file__).with_name("train_proposal_v04_qdelta.py")
sys.path.insert(0, str(SOURCE.parent))
sys.path.insert(0, str(SOURCE.parent.parent))
SPEC = importlib.util.spec_from_file_location("train_proposal_v04_qdelta", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AppendedDeltaFeaturesTests(unittest.TestCase):
    def test_appends_delta_for_unsorted_flat_action_indices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "base.f32"
            base = np.memmap(path, dtype="<f4", mode="w+", shape=(4, MODULE.BASE_INPUT_DIM))
            base[:] = np.arange(4, dtype=np.float32)[:, None]
            base.flush()
            delta = np.asarray([0.25, -0.5, 1.25, 2.0], dtype=np.float32)
            view = MODULE.AppendedDeltaFeatures(base, delta)

            rows = view[np.asarray([3, 1], dtype=np.int64)]

            self.assertEqual(rows.shape, (2, MODULE.INPUT_DIM))
            np.testing.assert_array_equal(rows[:, 0], np.asarray([3.0, 1.0], dtype=np.float32))
            np.testing.assert_array_equal(rows[:, -1], np.asarray([2.0, -0.5], dtype=np.float32))
            del view
            base._mmap.close()

    def test_rejects_misaligned_delta_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "base.f32"
            base = np.memmap(path, dtype="<f4", mode="w+", shape=(2, MODULE.BASE_INPUT_DIM))
            try:
                with self.assertRaisesRegex(ValueError, "shape/value mismatch"):
                    MODULE.AppendedDeltaFeatures(base, np.zeros(3, dtype=np.float32))
            finally:
                base._mmap.close()


if __name__ == "__main__":
    unittest.main()
