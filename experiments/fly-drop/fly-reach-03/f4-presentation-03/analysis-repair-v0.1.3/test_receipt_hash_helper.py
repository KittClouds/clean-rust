from __future__ import annotations

import ast
import hashlib
import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "analyze_results.py"
SPEC = importlib.util.spec_from_file_location("f4pres03_analysis_v013", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load repaired analysis source")
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


class ReceiptHashHelperTests(unittest.TestCase):
    def test_receipt_hash_uses_existing_sha256_helper(self) -> None:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        unresolved_sha_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sha"
        ]
        self.assertEqual(unresolved_sha_calls, [])

    def test_sha_bytes_matches_standard_sha256(self) -> None:
        payload = b"F4-PRESENTATION-03 support receipt fixture"
        self.assertEqual(ANALYZER.sha_bytes(payload), hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
