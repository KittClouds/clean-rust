from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "train_phase_b_corrected_v06.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_corrected_entrypoint_v06_tests", ENTRYPOINT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CorrectionV06Tests(unittest.TestCase):
    def test_arm_primary_prefix_is_the_same_occurrence_stream(self) -> None:
        common = [{
            "occurrence_index": 0,
            "group_id": "g0",
            "neighborhood_id": "n0",
            "role": "anchor",
            "episode_id": "e0",
            "feature_scope_index": 5,
            "target_hash": "t0",
            "candidate_order_hash": "c0",
            "candidate_semantic_ids": ["a", "b"],
        }]
        enriched = [{
            "occurrence_index": 0,
            "group_id": "g0",
            "neighborhood_id": "n0",
            "role": "anchor",
            "source_episode_id": "e0",
            "feature_scope_index": 5,
            "target_hash": "t0",
            "candidate_order_hash": "c0",
            "candidate_semantic_ids": ["a", "b"],
            "target": [1.0, 0.0],
            "candidate_indices": [0, 1],
        }]
        require = lambda condition, message: self.fail(message) if not condition else None
        self.assertIs(MODULE.validate_primary_binding(common, enriched, require)[0], enriched[0])

    def test_primary_binding_rejects_identity_or_order_drift(self) -> None:
        common = [{"occurrence_index": 0, "group_id": "g0", "neighborhood_id": "n0", "role": "anchor", "episode_id": "e0", "source_partition": "train", "feature_scope_index": 5, "target_hash": "t0", "candidate_order_hash": "c0", "candidate_semantic_ids": ["a", "b"]}]
        drifted = [{"occurrence_index": 1, "group_id": "g0", "neighborhood_id": "n0", "role": "anchor", "source_episode_id": "e0", "feature_scope_index": 5, "target_hash": "t0", "candidate_order_hash": "c0", "candidate_semantic_ids": ["a", "b"]}]
        require = lambda condition, message: None if condition else (_ for _ in ()).throw(RuntimeError(message))
        with self.assertRaises(RuntimeError):
            MODULE.validate_primary_binding(common, drifted, require)


if __name__ == "__main__":
    unittest.main()
