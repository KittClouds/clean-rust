from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "train_phase_b_corrected_v07.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_corrected_entrypoint_v07_tests", ENTRYPOINT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def must(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class CorrectionV07Tests(unittest.TestCase):
    def test_metadata_is_joined_by_exact_occurrence_without_changing_payload(self) -> None:
        common = [{
            "occurrence_index": 0, "group_id": "g0", "neighborhood_id": "n0",
            "role": "anchor", "episode_id": "e0", "feature_scope_index": 5,
            "target_hash": "t0", "candidate_order_hash": "c0",
            "candidate_semantic_ids": ["a", "b"],
        }]
        arm = [{
            "occurrence_index": 0, "group_id": "g0", "source_episode_id": "e0",
            "feature_scope_index": 5, "target_hash": "t0", "candidate_order_hash": "c0",
            "candidate_semantic_ids": ["a", "b"], "candidate_indices": [0, 1],
            "target": [1.0, 0.0], "candidate_mask": [True, True],
        }]
        merged = MODULE.bind_primary_rows(common, arm, must)
        self.assertEqual(merged[0]["role"], "anchor")
        self.assertEqual(merged[0]["neighborhood_id"], "n0")
        self.assertEqual(merged[0]["target"], arm[0]["target"])
        self.assertEqual(merged[0]["candidate_indices"], arm[0]["candidate_indices"])
        self.assertNotIn("role", arm[0])

    def test_metadata_join_fails_closed_on_order_drift(self) -> None:
        common = [{
            "occurrence_index": 0, "group_id": "g0", "neighborhood_id": "n0",
            "role": "anchor", "episode_id": "e0", "feature_scope_index": 5,
            "target_hash": "t0", "candidate_order_hash": "c0", "candidate_semantic_ids": ["a"],
        }]
        arm = [{
            "occurrence_index": 1, "group_id": "g0", "source_episode_id": "e0",
            "feature_scope_index": 5, "target_hash": "t0", "candidate_order_hash": "c0",
            "candidate_semantic_ids": ["a"],
        }]
        with self.assertRaises(RuntimeError):
            MODULE.bind_primary_rows(common, arm, must)


if __name__ == "__main__":
    unittest.main()
