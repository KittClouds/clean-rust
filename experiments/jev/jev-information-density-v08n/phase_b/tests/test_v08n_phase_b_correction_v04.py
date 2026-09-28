from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "train_phase_b_corrected_v04.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_corrected_entrypoint_v04_tests", ENTRYPOINT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CorrectionV04Tests(unittest.TestCase):
    def test_primary_and_auxiliary_identity_resolution_is_lazy_and_exact(self) -> None:
        primary = {
            "group_id": "primary-group",
            "feature_scope_index": 7,
            "candidate_indices": [0, 1, 2, 3],
            "target": [1.0, 0.0, 0.0, 0.0],
        }
        auxiliary = {
            "source_episode_id": "aux-source",
            "feature_scope_index": 8,
            "candidate_indices": [3, 2, 1, 0],
            "target": [0.0, 0.0, 1.0, 0.0],
        }
        self.assertEqual(MODULE.prepare_event(primary)["group_id"], "primary-group")
        self.assertEqual(MODULE.prepare_event(auxiliary)["group_id"], "aux-source")
        self.assertEqual(MODULE.prepare_event(primary)["candidate_indices"], {"name_definition": [0, 1, 2, 3]})
        self.assertEqual(MODULE.prepare_event(auxiliary)["candidate_indices"], {"name_definition": [3, 2, 1, 0]})

    def test_failed_attempt_is_metadata_only_and_unchanged(self) -> None:
        details = MODULE.failed_attempt_forensic()
        self.assertEqual(details["optimizer_steps"], 0)
        self.assertFalse(details["evaluation_access"])
        self.assertEqual(set(details["files"]), {"run-config.json", "initial-head-template.sha256"})


if __name__ == "__main__":
    unittest.main()
