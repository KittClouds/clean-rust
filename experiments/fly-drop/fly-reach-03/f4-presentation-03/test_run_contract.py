from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

for _key in (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_MAXIMUM_THREADS",
):
    os.environ[_key] = "1"

import numpy as np

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
for _path in (BRANCH, STUDY / "f4-invariant-01-impl-v2", STUDY / "f4-invariant-01-prefit-v2", STUDY / "f4-presentation-02-v2", STUDY / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from analyze_results import (
    _decode_prediction, _delivery_alignment, _psi, _scatter_pooled_logits, _weighted_error, _weighted_margin,
)
from run_fits import PRED_EPOCHS, _prediction_bytes
from verify_integrity import _manifest_line_hash, _validate_fit_ids, _validate_prediction_keys, _verify_source_entry
from verify_integrity import ARMS as INTEGRITY_ARMS, BLOCKS as INTEGRITY_BLOCKS, REPLICATES as INTEGRITY_REPLICATES


class RunContractTests(unittest.TestCase):
    def test_reciprocal_inclusion_weighting_and_balanced_error(self) -> None:
        inclusion_probability = np.asarray([0.5, 0.25, 1.0], dtype=np.float64)
        q = 1.0 / inclusion_probability
        targets = np.asarray([1, 1, -1], dtype=np.int8)
        logits = np.asarray([1.0, -1.0, 1.0], dtype=np.float32)
        self.assertAlmostEqual(_weighted_error(logits, targets, q), 5.0 / 6.0, places=14)
        self.assertIsNone(_weighted_error(logits[:2], targets[:2], q[:2]))
        self.assertIsNone(_weighted_error(np.asarray([], dtype=np.float32), np.asarray([], dtype=np.int8), np.asarray([], dtype=np.float64)))
        self.assertAlmostEqual(_weighted_margin(np.asarray([2.0, -2.0]), np.asarray([1, 1]), np.asarray([1.0, 3.0])), -1.0)

    def test_pooled_prediction_scatter_restores_panel_row_order(self) -> None:
        predictions = {
            ("D", 0, 309000): np.asarray([[30.0, 31.0]], dtype=np.float32),
            ("D", 0, 309001): np.asarray([[10.0, 11.0]], dtype=np.float32),
        }
        block_rows = {
            309000: np.asarray([1, 3], dtype=np.int64),
            309001: np.asarray([0, 2], dtype=np.int64),
        }
        restored = _scatter_pooled_logits(predictions, "D", 0, block_rows, (309000, 309001), 4)
        np.testing.assert_array_equal(restored, np.asarray([10.0, 30.0, 11.0, 31.0], dtype=np.float32))

    def test_delivery_cosine_uses_declared_unweighted_cosine(self) -> None:
        truth = SimpleNamespace(
            native_delta=np.asarray([0.1, 0.2], dtype=np.float32),
            preweight=np.asarray([0.5, 1.0], dtype=np.float32),
            reference=np.asarray([1.0, 2.0], dtype=np.float32),
        )
        score = _delivery_alignment(
            np.asarray([1.0, -1.0], dtype=np.float32), np.asarray([0, 1], dtype=np.int64), truth
        )
        self.assertAlmostEqual(score, -0.6, places=6)

    def test_capability_weighted_polarity_and_concentration_fixture(self) -> None:
        truth = SimpleNamespace(
            y=np.asarray([1, -1], dtype=np.int8),
            native_delta=np.asarray([0.5, 1.0], dtype=np.float32),
            reference=np.asarray([0.4, -0.8], dtype=np.float32),
        )
        result = _psi(
            np.asarray([2.0, -2.0], dtype=np.float32),
            np.asarray([0, 1], dtype=np.int64),
            truth,
            np.asarray([2.0, 1.0]),
            [b"a", b"b"],
        )
        self.assertAlmostEqual(result["psi_prop"], 1.0)
        self.assertAlmostEqual(result["weighted_sign_agreement"], 1.0)
        self.assertAlmostEqual(result["leverage_sum"], 1.2)
        self.assertAlmostEqual(result["leverage_ess"], 1.8)
        self.assertAlmostEqual(result["top_1pct_share"], 2.0 / 3.0)

    def test_prediction_stream_round_trip_and_header_identity(self) -> None:
        keys = [b"a" * 18, b"b" * 18]
        logits = np.arange(len(PRED_EPOCHS) * len(keys), dtype=np.float32).reshape(len(PRED_EPOCHS), len(keys))
        row_hash = "ab" * 32
        raw = _prediction_bytes(309004, "Cphi", 2, row_hash, keys, logits)
        row = {"heldout_block": "309004", "arm": "Cphi", "replicate_index": "2"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prediction.bin"
            path.write_bytes(raw)
            actual = _decode_prediction(path, row, keys)
        np.testing.assert_array_equal(actual, logits)

    def test_integrity_rejects_missing_duplicate_fit_and_prediction_rows(self) -> None:
        fit_ids = [f"{arm}-H{block}-I{replicate}" for block in INTEGRITY_BLOCKS for replicate in INTEGRITY_REPLICATES for arm in INTEGRITY_ARMS]
        _validate_fit_ids(fit_ids)
        with self.assertRaisesRegex(RuntimeError, "missing or duplicate"):
            _validate_fit_ids(fit_ids[:-1])
        duplicate_fit = fit_ids.copy()
        duplicate_fit[-1] = duplicate_fit[-2]
        with self.assertRaisesRegex(RuntimeError, "missing or duplicate"):
            _validate_fit_ids(duplicate_fit)
        _validate_prediction_keys([b"row-a", b"row-b"], [b"row-a", b"row-b"])
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            _validate_prediction_keys([b"row-a", b"row-a"], [b"row-a", b"row-b"])
        with self.assertRaisesRegex(RuntimeError, "coverage/order"):
            _validate_prediction_keys([b"row-a"], [b"row-a", b"row-b"])

    def test_integrity_rejects_source_drift(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "frozen.py"
            path.write_bytes(b"frozen-source")
            entry = {"path": "frozen.py", "byte_length": 13, "sha256": hashlib.sha256(b"frozen-source").hexdigest()}
            _verify_source_entry(entry, root)
            path.write_bytes(b"changed-source")
            with self.assertRaisesRegex(RuntimeError, "source drift"):
                _verify_source_entry(entry, root)

    def test_manifest_row_hash_covers_the_exact_lf_terminated_bytes(self) -> None:
        import hashlib

        row = b"fit_id,arm\nD-H309000-I0,D\n"
        self.assertEqual(_manifest_line_hash(row), hashlib.sha256(row).hexdigest())
        with self.assertRaisesRegex(RuntimeError, "line ending"):
            _manifest_line_hash(b"fit_id,arm\r\n")


if __name__ == "__main__":
    unittest.main()
