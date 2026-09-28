from __future__ import annotations

import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

import verify_integrity as repaired


def truth_bytes(keys: list[bytes]) -> bytes:
    header = repaired.TRUTH_MAGIC + struct.pack("<IIQ", 1, repaired.TRUTH_WIDTH, len(keys))
    return header + b"".join(key + bytes(repaired.TRUTH_WIDTH - len(key)) for key in keys)


class TruthKeyScanTests(unittest.TestCase):
    def test_repaired_scan_accepts_exact_key_stream(self) -> None:
        keys = [bytes(range(18)), bytes(range(18, 36))]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "truth.bin"
            raw = truth_bytes(keys)
            path.write_bytes(raw)
            self.assertEqual(repaired._truth_keys_only(path, keys), repaired.sha_bytes(raw))

    def test_repaired_scan_rejects_key_order_mismatch(self) -> None:
        keys = [bytes(range(18)), bytes(range(18, 36))]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "truth.bin"
            path.write_bytes(truth_bytes(keys))
            with self.assertRaisesRegex(RuntimeError, "truth/predictor key mismatch"):
                repaired._truth_keys_only(path, [keys[1], keys[0]])

    def test_repaired_scan_rejects_wrong_dimensions(self) -> None:
        keys = [bytes(range(18))]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "truth.bin"
            path.write_bytes(truth_bytes(keys)[:-1])
            with self.assertRaisesRegex(RuntimeError, "scoring truth dimensions mismatch"):
                repaired._truth_keys_only(path, keys)

    def test_original_verifier_reproduces_closed_stream_bug(self) -> None:
        original_path = Path(__file__).resolve().parents[1] / "validation-repair-v0.1.1" / "verify_integrity.py"
        spec = importlib.util.spec_from_file_location("original_integrity_verifier", original_path)
        if spec is None or spec.loader is None:
            self.fail("cannot load original verifier for regression control")
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        keys = [bytes(range(18))]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "truth.bin"
            path.write_bytes(truth_bytes(keys))
            with self.assertRaisesRegex(ValueError, "closed file"):
                original._truth_keys_only(path, keys)


if __name__ == "__main__":
    unittest.main()
