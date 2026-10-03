"""Focused tests for the deterministic locked-row metadata join."""
from __future__ import annotations

import unittest

from analysis_repair_common import enrich_lock_metadata


class LockMetadataRepairTests(unittest.TestCase):
    def test_join_adds_only_frozen_fit_metadata_and_preserves_lock_fields(self) -> None:
        registry = [
            {"fit_id": f"m{index}", "fold_index": index // 3, "heldout_block": 310000 + index // 3, "replicate_index": index % 3}
            for index in range(36)
        ]
        source_rows = [{"fit_id": row["fit_id"], "prediction_path": f"p/{row['fit_id']}.bin", "prediction_sha256": str(index)} for index, row in enumerate(registry)]
        lock = {"schema": "test", "predictions": source_rows}
        enriched = enrich_lock_metadata(lock, registry)
        self.assertEqual(lock["predictions"], source_rows)
        self.assertEqual(len(enriched["predictions"]), 36)
        for row, expected in zip(enriched["predictions"], registry, strict=True):
            self.assertEqual(row["fold_index"], expected["fold_index"])
            self.assertEqual(row["heldout_block"], expected["heldout_block"])
            self.assertEqual(row["replicate_index"], expected["replicate_index"])
            self.assertEqual(row["prediction_path"], f"p/{expected['fit_id']}.bin")

    def test_conflicting_or_duplicate_identity_fails_closed(self) -> None:
        registry = [
            {"fit_id": f"m{index}", "fold_index": index // 3, "heldout_block": 310000 + index // 3, "replicate_index": index % 3}
            for index in range(36)
        ]
        rows = [{"fit_id": row["fit_id"]} for row in registry]
        rows[0]["fold_index"] = 11
        with self.assertRaises(RuntimeError):
            enrich_lock_metadata({"predictions": rows}, registry)
        rows[0].pop("fold_index")
        rows[1]["fit_id"] = rows[0]["fit_id"]
        with self.assertRaises(RuntimeError):
            enrich_lock_metadata({"predictions": rows}, registry)


if __name__ == "__main__":
    unittest.main()
