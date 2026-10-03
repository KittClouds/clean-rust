from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
sys.path.insert(0, str(Path(__file__).parents[1] / "source"))
from linear_core import standardized_tensor

SOURCE = Path(__file__).parents[1] / "source" / "run_s10_transport.py"
SPEC = importlib.util.spec_from_file_location("s10_runner", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TransportContractTests(unittest.TestCase):
    def test_forward_and_backward_are_source_row_target_column(self) -> None:
        matrix = np.arange(16 * 16, dtype=np.float64).reshape(16, 16)
        forward = MODULE.summarize_direction(matrix, 1, True)
        backward = MODULE.summarize_direction(matrix, 1, False)
        self.assertEqual(forward["pairs"][0], {"source_layer": 1, "target_layer": 2, "balanced_accuracy": 1.0})
        self.assertEqual(backward["pairs"][0], {"source_layer": 2, "target_layer": 1, "balanced_accuracy": 16.0})
        self.assertEqual(forward["count"], 15)
        self.assertEqual(backward["count"], 15)

    def test_prediction_digest_is_order_sensitive(self) -> None:
        left = MODULE.file_digest_for_prediction(np.asarray([0, 1, 2], dtype=np.int64))
        right = MODULE.file_digest_for_prediction(np.asarray([2, 1, 0], dtype=np.int64))
        self.assertEqual(len(left), 64)
        self.assertNotEqual(left, right)

    def test_tree_root_is_path_sorted(self) -> None:
        a = [{"path": "b", "bytes": 1, "sha256": "1"}, {"path": "a", "bytes": 2, "sha256": "2"}]
        b = list(reversed(a))
        self.assertEqual(MODULE.tree_root(a), MODULE.tree_root(b))

    def test_preselected_slice_standardization_matches_original_and_preserves_source(self) -> None:
        matrix = np.arange(30, dtype=np.float32).reshape(10, 3)
        rows = np.asarray([0, 2, 5, 9], dtype=np.int64)
        raw = np.ascontiguousarray(matrix[rows], dtype=np.float32)
        original = raw.copy()
        mean = np.asarray([2.5, 8.0, 11.25], dtype=np.float64)
        scale = np.asarray([1.5, 3.0, 4.25], dtype=np.float64)
        preselected = MODULE.standardized_raw_tensor(raw, mean, scale, MODULE.torch.device("cpu"))
        indexed = standardized_tensor(matrix, rows, mean, scale, MODULE.torch.device("cpu"))
        np.testing.assert_array_equal(preselected.numpy(), indexed.numpy())
        np.testing.assert_array_equal(raw, original)


if __name__ == "__main__":
    unittest.main()
