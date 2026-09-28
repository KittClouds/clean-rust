"""Synthetic unit and smoke tests; never reads qualification outcomes."""
from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from f4_symmetry_01_common import (
    INPUT_MAGIC, TRUTH_MAGIC, TRUTH_WIDTH, TUPLE_DTYPE, RawData,
    normalize_f32, read_training_labels,
)
from f4_symmetry_01_model import Encoder, tensor_hash
from f4_symmetry_01_prepare import _ordered_fit_rows, _projection_matrix, _project_f32
import numpy as np


class FrozenContractUnitTests(unittest.TestCase):
    def test_binary_magics_and_record_widths(self):
        self.assertEqual(len(INPUT_MAGIC), 16)
        self.assertEqual(len(TRUTH_MAGIC), 16)
        self.assertEqual(TUPLE_DTYPE.itemsize, 15)

    def test_projection_is_deterministic_and_signed_constant(self):
        first = _projection_matrix()
        second = _projection_matrix()
        self.assertEqual(first.shape, (24, 66))
        self.assertEqual(first.tobytes(), second.tobytes())
        bits = {int(value.view(np.uint32)) & 0x7FFFFFFF for value in first.flat}
        self.assertEqual(bits, {0x3DFC1764})

    def test_projection_dot_uses_repeatable_f32_outputs(self):
        x = np.arange(11 * 66, dtype=np.float32).reshape(11, 66) / np.float32(100.0)
        matrix = _projection_matrix()
        first = _project_f32(x, matrix)
        second = _project_f32(x, matrix)
        self.assertEqual(first.dtype, np.float32)
        self.assertEqual(first.shape, (11, 24))
        self.assertEqual(first.tobytes(), second.tobytes())

    def test_fold_normalization_is_f32_and_training_only(self):
        x = np.array([[1, 5], [3, 9], [100, 500]], dtype=np.float32)
        train = np.array([True, True, False])
        normalized, mean, scale = normalize_f32(x, train)
        np.testing.assert_array_equal(mean, np.array([2, 7], dtype=np.float32))
        np.testing.assert_array_equal(scale, np.array([1, 2], dtype=np.float32))
        self.assertEqual(normalized.dtype, np.float32)
        self.assertAlmostEqual(float(normalized[2, 0]), 98.0)

    def test_tensor_init_and_synthetic_fit_are_repeatable(self):
        first = Encoder(66, 0)
        second = Encoder(66, 0)
        self.assertEqual(tensor_hash(first.values), tensor_hash(second.values))
        rng = np.random.default_rng(99001)
        x = rng.standard_normal((32, 66)).astype(np.float32)
        y = (x[:, 0] > 0).astype(np.float32)
        first.fit(x, y)
        logits_a = first.logits(x)
        logits_b = first.logits(x)
        self.assertTrue(np.isfinite(logits_a).all())
        self.assertEqual(logits_a.tobytes(), logits_b.tobytes())
        self.assertEqual(hashlib.sha256(logits_a.tobytes()).digest(), hashlib.sha256(logits_b.tobytes()).digest())

    def test_fit_manifest_order_is_arm_major(self):
        rows = [
            {"fit_id": f"{arm}-H{block}", "arm": arm, "holdout_block": block}
            for block in (303003, 303002, 303001, 303000)
            for arm in ("D", "C", "B", "A")
        ]
        ordered = _ordered_fit_rows(rows)
        self.assertEqual(
            [str(row["fit_id"]) for row in ordered],
            [f"{arm}-H{block}" for arm in ("A", "B", "C", "D") for block in (303000, 303001, 303002, 303003)],
        )

    def test_training_reader_skips_heldout_payload_and_checks_before_close(self):
        keys = [
            b"\x00\x00" + struct.pack("<QII", 303000, 0, 5),
            b"\x00\x00" + struct.pack("<QII", 303001, 0, 6),
        ]
        header = TRUTH_MAGIC + struct.pack("<IIQ", 1, TRUTH_WIDTH, len(keys))
        rows = [
            keys[0] + struct.pack("<dbfff", 0.5, 1, 0.1, 0.4, 0.2),
            keys[1] + struct.pack("<dbfff", 0.5, 0, 0.1, 0.4, 0.2),
        ]
        with tempfile.TemporaryDirectory() as directory:
            truth_path = Path(directory) / "synthetic-truth.bin"
            truth_path.write_bytes(header + b"".join(rows))
            data = RawData(
                keys=keys,
                blocks=np.array([303000, 303001], dtype=np.uint64),
                a=np.zeros((2, 66), dtype=np.float32),
                tuples=np.zeros(2, dtype=TUPLE_DTYPE),
                truth_path=truth_path,
                count=2,
            )
            labels = read_training_labels(data, 303001)
            np.testing.assert_array_equal(labels, np.array([1.0, 0.0], dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
