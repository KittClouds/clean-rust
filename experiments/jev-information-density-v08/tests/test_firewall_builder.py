from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "build_firewall_registries.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("jev_v08_firewall_builder", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def episode(view: str = "choice") -> dict:
    return {
        "identity": {
            "episode_id": "episode-1",
            "world_instance_id": "root-1",
            "world_family_id": "world-family-1",
            "schema_family_id": "schema-family-1",
            "paraphrase_family_id": "definition-family-1",
            "perturbation_family_id": "intervention-family-1",
            "semantic_fingerprint": "semantic-hash",
            "surface_renderer_id": "prose",
        },
        "state": {"observable": {"content": "A visible observation."}},
        "runtime_schema": {
            "candidates": [
                {
                    "candidate_id": "a",
                    "candidate_semantic_id": "semantic-a",
                    "kind": "label",
                    "name": "Candidate A",
                    "description": "Definition A",
                    "aliases": [],
                    "opaque_id": None,
                    "parent_candidate_semantic_id": None,
                    "order_rank": None,
                },
                {
                    "candidate_id": "b",
                    "candidate_semantic_id": "semantic-b",
                    "kind": "label",
                    "name": "Candidate B",
                    "description": "Definition B",
                    "aliases": [],
                    "opaque_id": None,
                    "parent_candidate_semantic_id": None,
                    "order_rank": None,
                },
            ],
            "candidate_sets": [
                {
                    "candidate_set_id": "set-1",
                    "candidate_ids": ["a", "b"],
                    "set_role": "choice",
                    "declared_semantics": "choice_conditional",
                    "ordered": False,
                }
            ],
            "schema_family_id": "schema-family-1",
        },
        "queries": [
            {
                "query_id": "q1",
                "query_semantic_id": "internal-semantic-id",
                "view": view,
                "instruction": "Choose one candidate.",
                "candidate_set_id": "set-1",
            }
        ],
        "perturbation": None,
        # Deliberately no gold_targets: firewall generation must not need labels.
    }


class FirewallBuilderTests(unittest.TestCase):
    def test_choice_registry_uses_only_identity_and_model_visible_fields(self) -> None:
        rows = list(MODULE.episode_registry_rows(episode(), "fixture", {}, {}))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("group:episode-1|q1", row["overlap_keys"])
        self.assertTrue(any(key.startswith("model_input:") for key in row["overlap_keys"]))
        self.assertTrue(any(key.startswith("structural:") for key in row["overlap_keys"]))
        self.assertNotIn("A visible observation.", str(row))
        self.assertNotIn("semantic-a", str(row))

    def test_independent_registry_uses_one_group_per_runtime_candidate(self) -> None:
        rows = list(MODULE.episode_registry_rows(episode("independent_applicability"), "fixture", {}, {}))
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["group_id"] for row in rows},
            {"episode-1|q1|semantic-a", "episode-1|q1|semantic-b"},
        )


if __name__ == "__main__":
    unittest.main()
