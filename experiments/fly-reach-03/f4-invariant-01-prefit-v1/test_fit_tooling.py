"""Synthetic contract, integrity, and analysis tests; no frozen outcomes read."""
from __future__ import annotations

import hashlib
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fit_contract import (
    ARMS, FIT_HEADER, expected_fit_ids, manifest_row_hashes,
    encode_prediction_stream, decode_prediction_stream,
    weighted_balanced_error, weighted_accuracy, signed_margin,
    polarity_metrics, delivery_alignment, prediction_signs, validate_fit_grid,
)
from fit_common import verify_manifest_entries
from fit_integrity import _read_prediction_independently
import fit_analysis


def _manifest_rows() -> list[dict[str, str]]:
    rows = []
    for fit_id in expected_fit_ids():
        arm, holdout, rep = fit_id.split("-")
        block = int(holdout[1:])
        rows.append({
            "fit_id": fit_id, "arm": arm, "fold_index": str(block - 306000),
            "heldout_block": str(block), "replicate_index": rep[1:],
        })
    return rows


def _test_csv() -> bytes:
    rows = _manifest_rows()
    lines = [",".join(FIT_HEADER)]
    for row in rows:
        lines.append(",".join(row.get(name, "x") for name in FIT_HEADER))
    return ("\n".join(lines) + "\n").encode("utf-8")


class FitContractTests(unittest.TestCase):
    def test_exact_grid_and_arm_counts(self) -> None:
        rows = _manifest_rows()
        self.assertEqual(72, len(rows))
        self.assertEqual(36, sum(row["arm"] == "D" for row in rows))
        self.assertEqual(36, sum(row["arm"] == "S" for row in rows))
        validate_fit_grid(rows)
        with self.assertRaises(ValueError):
            validate_fit_grid(rows[:-1])
        duplicate = rows.copy()
        duplicate[-1] = duplicate[-2]
        with self.assertRaises(ValueError):
            validate_fit_grid(duplicate)
        wrong_identity = [dict(row) for row in rows]
        wrong_identity[0]["heldout_block"] = "306001"
        with self.assertRaises(ValueError):
            validate_fit_grid(wrong_identity)

    def test_manifest_row_hashes_use_exact_lf_bytes(self) -> None:
        raw = _test_csv()
        whole, rows = manifest_row_hashes(raw)
        lines = raw.splitlines(keepends=True)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), whole)
        self.assertEqual(hashlib.sha256(lines[1]).hexdigest(), rows[expected_fit_ids()[0]])
        with self.assertRaises(ValueError):
            manifest_row_hashes(raw.replace(b"\n", b"\r\n"))

    def test_prediction_round_trip_and_identity_guards(self) -> None:
        keys = [bytes(range(18)), bytes(range(18, 36))]
        row_hash = hashlib.sha256(b"fit row\n").hexdigest()
        raw = encode_prediction_stream(
            block=306002, arm="S", replicate=1, manifest_row_sha256=row_hash,
            records=[(keys[0], 0.25), (keys[1], -0.5)],
        )
        decoded_keys, logits = decode_prediction_stream(
            raw, block=306002, arm="S", replicate=1, manifest_row_sha256=row_hash,
            expected_keys=keys,
        )
        self.assertEqual(keys, decoded_keys)
        self.assertEqual([0.25, -0.5], logits)
        self.assertEqual([-1, -1, 1], prediction_signs([0.0, -0.25, 0.0001]))
        with self.assertRaises(ValueError):
            decode_prediction_stream(
                raw, block=306002, arm="S", replicate=1, manifest_row_sha256=row_hash,
                expected_keys=keys[:1],
            )
        with self.assertRaises(ValueError):
            encode_prediction_stream(
                block=306002, arm="S", replicate=1, manifest_row_sha256=row_hash,
                records=[(keys[0], 0.25), (keys[0], 0.5)],
            )

    def test_integrity_rejects_duplicate_and_missing_prediction_rows(self) -> None:
        keys = [b"a" * 18, b"b" * 18]
        row_hash = hashlib.sha256(b"row\n").hexdigest()
        good = encode_prediction_stream(
            block=306000, arm="D", replicate=0, manifest_row_sha256=row_hash,
            records=[(keys[0], 1.0), (keys[1], -1.0)],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prediction.bin"
            path.write_bytes(good)
            digest = _read_prediction_independently(
                path, block=306000, arm="D", replicate=0, row_sha=row_hash, expected_keys=keys,
            )
            self.assertEqual(hashlib.sha256(good).hexdigest(), digest)
            with self.assertRaises(RuntimeError):
                _read_prediction_independently(
                    path, block=306000, arm="D", replicate=0, row_sha=row_hash, expected_keys=keys[:1],
                )
            duplicate = bytearray(good)
            duplicate[72 + 22:72 + 22 + 18] = duplicate[72:72 + 18]
            path.write_bytes(duplicate)
            with self.assertRaises(RuntimeError):
                _read_prediction_independently(
                    path, block=306000, arm="D", replicate=0, row_sha=row_hash, expected_keys=keys,
                )

    def test_source_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.bin"
            path.write_bytes(b"frozen")
            entry = {
                "path": "source.bin", "byte_length": 6,
                "sha256": hashlib.sha256(b"frozen").hexdigest(),
            }
            verify_manifest_entries({"entries": [entry]}, root)
            path.write_bytes(b"drift!")
            with self.assertRaises(RuntimeError):
                verify_manifest_entries({"entries": [entry]}, root)


class ScoringFixtureTests(unittest.TestCase):
    def test_balanced_error_accuracy_and_margin(self) -> None:
        signs = [1, 1, -1, 1]
        targets = [1, -1, -1, 1]
        q = [1.0, 2.0, 1.0, 1.0]
        self.assertAlmostEqual(1.0 / 3.0, weighted_balanced_error(signs, targets, q), places=14)
        self.assertAlmostEqual(3.0 / 5.0, weighted_accuracy(signs, targets, q), places=14)
        self.assertAlmostEqual(17.0 / 12.0, signed_margin([2.0, -1.0, -2.0, 1.0], targets, q), places=14)

    def test_absent_class_is_undefined(self) -> None:
        self.assertIsNone(weighted_balanced_error([1, 1], [1, 1], [1.0, 2.0]))
        self.assertIsNone(signed_margin([], [], []))

    def test_psi_concentration_and_delivery(self) -> None:
        keys = [bytes([index]) * 18 for index in range(5)]
        result = polarity_metrics(
            signs=[1, 1, -1, -1, 1], targets=[1, -1, 1, -1, 1], q=[1] * 5,
            native_delta=[1, 2, 0, 0, 0], reference=[1, -2, 0, 0, 0], row_keys=keys,
        )
        self.assertAlmostEqual(-0.6, result["psi_prop"], places=14)
        self.assertAlmostEqual(25.0 / 17.0, result["leverage_ess"], places=14)
        self.assertAlmostEqual(0.8, result["top_1pct_share"], places=14)
        self.assertAlmostEqual(0.8, result["top_5pct_share"], places=14)
        self.assertAlmostEqual(0.8, result["top_20pct_share"], places=14)
        self.assertAlmostEqual(1.0, delivery_alignment([1, -1], [1, 1], [1, 1], [1, -1]), places=14)

    def test_analysis_refuses_truth_before_integrity_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "INTEGRITY-RECEIPT.json").write_text(
                '{"status":"FAIL","heldout_truth_state":"SEALED"}\n', encoding="utf-8",
            )
            with patch.object(fit_analysis, "RUN", root):
                with self.assertRaises(RuntimeError):
                    fit_analysis.run()


if __name__ == "__main__":
    unittest.main()
