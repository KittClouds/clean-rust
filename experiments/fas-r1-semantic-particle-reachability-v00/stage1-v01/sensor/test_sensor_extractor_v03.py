#!/usr/bin/env python3
"""Regression tests for inventory-bound snapshot resolution."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sensor_v02 as v02  # noqa: E402
import run_sensor_v03 as v03  # noqa: E402

SNAPSHOT = Path(r"D:\r1-models\lfm2.5-1.2b-base-7453bca97ca1e67754c4035a4b4c584e1c9dd725")
INVENTORY = Path(
    r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor-qualification-v01\MODEL-SNAPSHOT-INVENTORY.json"
)


class SnapshotInventoryRepairTests(unittest.TestCase):
    def test_v02_reproduces_the_directory_name_stop(self) -> None:
        with self.assertRaisesRegex(ValueError, "snapshot directory name"):
            v02.resolve_snapshot(SNAPSHOT, None)

    def test_v03_accepts_prefixed_directory_path(self) -> None:
        self.assertEqual(v03.resolve_snapshot(SNAPSHOT, None), SNAPSHOT.resolve())

    def test_v03_accepts_only_exact_pinned_inventory(self) -> None:
        expected = json.loads(INVENTORY.read_text(encoding="utf-8"))
        actual_files, actual_tokenizer = v03.hash_snapshot(SNAPSHOT)
        self.assertTrue(v03.inventory_matches(actual_files, actual_tokenizer, expected))
        changed = json.loads(json.dumps(expected))
        changed["files"][0]["sha256"] = "0" * 64
        self.assertFalse(v03.inventory_matches(actual_files, actual_tokenizer, changed))
        wrong_revision = json.loads(json.dumps(expected))
        wrong_revision["revision"] = "0" * 40
        self.assertFalse(v03.inventory_matches(actual_files, actual_tokenizer, wrong_revision))

    def test_inventory_file_digest_is_the_manifest_value(self) -> None:
        digest = hashlib.sha256(INVENTORY.read_bytes()).hexdigest()
        self.assertEqual(digest, "84142f95653f8f0f1c60934d6c5c711747b89e48e8ff3181c67dc437becef103")


if __name__ == "__main__":
    unittest.main(verbosity=2)
