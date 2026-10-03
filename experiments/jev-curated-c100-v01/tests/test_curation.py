import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import curate_c100  # noqa: E402


class CurationHelpersTest(unittest.TestCase):
    def test_split_matches_frozen_policy(self):
        self.assertEqual(curate_c100.family_split("network_incident-000005"), "train")
        self.assertEqual(curate_c100.family_split("network_incident-000002"), "test")

    def test_group_count_is_deterministic(self):
        episode = {
            "queries": [{"query_id": "q", "view": "choice", "candidate_set_id": "cs"}],
            "runtime_schema": {
                "candidates": [{"candidate_id": "a"}],
                "candidate_sets": [{"candidate_set_id": "cs", "candidate_ids": ["a"]}],
            },
            "gold_targets": [{"query_id": "q", "target": {"target_kind": "choice", "other_probability": 0.0}}],
        }
        self.assertEqual(curate_c100.group_count(episode), curate_c100.group_count(episode))
        self.assertEqual(curate_c100.group_count(episode), 1)

    def test_selection_is_deterministic_and_budgeted(self):
        roots = []
        for index in range(8):
            roots.append(curate_c100.RootSummary(f"r-{index}", "world-a", groups=13 + index))
        left = curate_c100.select_roots(roots, 50, "seed")
        right = curate_c100.select_roots(roots, 50, "seed")
        self.assertEqual([item.root_id for item in left], [item.root_id for item in right])
        self.assertLessEqual(sum(item.groups for item in left), 50)


class CandidateArtifactSmokeTest(unittest.TestCase):
    def test_manifest_and_overlap_gate(self):
        output = Path(os.environ.get("JEV_C100_OUTPUT", str(ROOT)))
        manifest = json.loads((output / "selection-manifest.json").read_text(encoding="utf-8"))
        overlap = json.loads((output / "overlap-audit.json").read_text(encoding="utf-8"))
        selection_digest = curate_c100.sha256_text(
            json.dumps(manifest["selected_roots"], sort_keys=True, separators=(",", ":"))
        )
        self.assertEqual(selection_digest, manifest["root_selection_sha256"])
        self.assertLessEqual(manifest["selected_group_count"], manifest["target_groups"])
        self.assertEqual(manifest["status"], "gated_candidate_not_active_training")
        self.assertEqual(manifest["budget_status"], "underfilled_fail_closed")
        self.assertEqual(manifest["coverage_status"], "single_novel_world_family_after_current_firewall")
        self.assertFalse(manifest["selection_policy"]["protected_outcomes_used"])
        with (output / "train.jsonl").open(encoding="utf-8") as handle:
            self.assertEqual(sum(1 for _ in handle), manifest["selected_episode_count"])
        self.assertEqual(overlap["exact_episode_id"], 0)
        self.assertEqual(overlap["semantic_fingerprint"], 0)
        self.assertEqual(overlap["exact_text_sha256"], 0)
        self.assertEqual(overlap["normalized_text_sha256"], 0)
        self.assertEqual(overlap["same_root_family"], 0)


if __name__ == "__main__":
    unittest.main()
