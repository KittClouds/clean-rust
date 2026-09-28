from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_runtime_score_parity_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v04_runtime_score_parity_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class RuntimeScoreParityHelperTests(unittest.TestCase):
    def test_tolerance_uses_reference_scaled_absolute_bound(self) -> None:
        self.assertTrue(VERIFIER.within_tolerance(1.0, 1.0, 0.0, 0.0))
        self.assertTrue(VERIFIER.within_tolerance(1.000109, 1.0, 1e-4, 1e-5))
        self.assertFalse(VERIFIER.within_tolerance(1.000111, 1.0, 1e-4, 1e-5))

    def test_extended_path_matches_ordinary_windows_path(self) -> None:
        ordinary = r"D:\codex-runs\stage1\scores.jsonl"
        extended = "\\\\?\\" + ordinary
        self.assertEqual(
            VERIFIER.canonical_path(ordinary),
            VERIFIER.canonical_path(extended),
        )


if __name__ == "__main__":
    unittest.main()
