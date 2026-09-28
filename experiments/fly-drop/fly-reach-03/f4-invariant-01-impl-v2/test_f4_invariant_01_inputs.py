"""Synthetic shared-input normalization and hash gates; no task data."""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for path in (str(HERE), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from f4_invariant_01_inputs import normalize_fold_inputs, shared_stream_hashes  # noqa: E402
from f4_invariant_01_model import d_input, s_input  # noqa: E402
from f4_symmetry_01_common import normalize_f32  # noqa: E402
import numpy as np  # noqa: E402


def synthetic_rows() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[bytes]]:
    row_count = 5
    base = np.empty((row_count, 66), dtype=np.float32)
    tuples = np.empty((row_count, 4, 6), dtype=np.float32)
    for row in range(row_count):
        for field in range(66):
            base[row, field] = np.float32(((row * 13 + field * 7) % 37 - 18) / 16.0)
        for cue in range(4):
            incidence = (row + cue) % 2
            role = 1 if (row * 3 + cue) % 2 else -1
            tuples[row, cue] = np.asarray((incidence, role, incidence * role, (row - cue) / 8.0, (row + cue) / 16.0, (cue - row) / 32.0), dtype=np.float32)
    train = np.asarray([True, True, True, True, False])
    keys = [b"\x00\x00" + struct.pack("<QII", 700 + row, 3, row) for row in range(row_count)]
    return base, tuples, train, keys


class SharedInputTests(unittest.TestCase):
    def test_training_only_fold_normalization_matches_parent_float32_semantics(self):
        base, tuples, train, _keys = synthetic_rows()
        result = normalize_fold_inputs(base, tuples, train, 5)
        expected_base, expected_base_mean, expected_base_scale = normalize_f32(base, train)
        flat = tuples[:, :, 3:6].reshape(-1, 3)
        expected_tuple, expected_tuple_mean, expected_tuple_scale = normalize_f32(flat, np.repeat(train, 4))
        self.assertEqual(result.base.tobytes(), expected_base.tobytes())
        self.assertEqual(result.tuples[:, :, 3:6].tobytes(), expected_tuple.reshape(5, 4, 3).tobytes())
        self.assertEqual(result.base_mean.tobytes(), expected_base_mean.tobytes())
        self.assertEqual(result.base_scale.tobytes(), expected_base_scale.tobytes())
        self.assertEqual(result.tuple_mean.tobytes(), expected_tuple_mean.tobytes())
        self.assertEqual(result.tuple_scale.tobytes(), expected_tuple_scale.tobytes())
        self.assertEqual(len(result.payload), 576)
        self.assertEqual(len(result.sha256), 64)
        self.assertTrue(np.isfinite(result.base).all())
        self.assertTrue(np.isfinite(result.tuples).all())

    def test_holdout_values_do_not_change_fitted_normalizers(self):
        base, tuples, train, _keys = synthetic_rows()
        first = normalize_fold_inputs(base, tuples, train, 2)
        changed_base = base.copy()
        changed_tuples = tuples.copy()
        changed_base[~train] = np.float32(1e6)
        changed_tuples[~train, :, 3:6] = np.float32(-1e6)
        second = normalize_fold_inputs(changed_base, changed_tuples, train, 2)
        self.assertEqual(first.base_mean.tobytes(), second.base_mean.tobytes())
        self.assertEqual(first.base_scale.tobytes(), second.base_scale.tobytes())
        self.assertEqual(first.tuple_mean.tobytes(), second.tuple_mean.tobytes())
        self.assertEqual(first.tuple_scale.tobytes(), second.tuple_scale.tobytes())
        self.assertEqual(first.sha256, second.sha256)

    def test_pre_presentation_hashes_are_shared_and_domain_separated(self):
        base, tuples, train, keys = synthetic_rows()
        normalized = normalize_fold_inputs(base, tuples, train, 0)
        first = shared_stream_hashes(keys, normalized.base, normalized.tuples)
        second = shared_stream_hashes(keys, normalized.base.copy(), normalized.tuples.copy())
        self.assertEqual(first, second)
        self.assertEqual(len(set(first.values())), 3)
        d_view = d_input(normalized.base, normalized.tuples)
        s_base, s_tuples = s_input(normalized.base, normalized.tuples)
        self.assertEqual(d_view[:, :66].tobytes(), s_base.tobytes())
        self.assertEqual(s_tuples.tobytes(), normalized.tuples.tobytes())
        self.assertEqual(first, shared_stream_hashes(keys, s_base, s_tuples))

    def test_hash_input_contract_rejects_bad_keys_and_nonfinite_data(self):
        base, tuples, train, keys = synthetic_rows()
        normalized = normalize_fold_inputs(base, tuples, train, 0)
        with self.assertRaises(RuntimeError):
            shared_stream_hashes(keys[:-1], normalized.base, normalized.tuples)
        with self.assertRaises(RuntimeError):
            shared_stream_hashes(keys[:-1] + [keys[0]], normalized.base, normalized.tuples)
        bad = normalized.tuples.copy()
        bad[0, 0, 3] = np.float32(np.inf)
        with self.assertRaises(RuntimeError):
            shared_stream_hashes(keys, normalized.base, bad)


if __name__ == "__main__":
    unittest.main()
