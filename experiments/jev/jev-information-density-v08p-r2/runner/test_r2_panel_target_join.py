"""Synthetic-only tests for the exact-world target join adapter."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("r2_panel_target_join.py")
SPEC = importlib.util.spec_from_file_location("jev_r2_panel_target_join_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
TARGET_JOIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TARGET_JOIN)
attach_exact_world_targets = TARGET_JOIN.attach_exact_world_targets


def fixture_rows() -> tuple[list[dict], list[dict], list[dict], dict[str, list[str]]]:
    semantic_ids = [f"family::candidate_{index}" for index in range(4)]
    vectors = {
        "anchor": [0.7, 0.1, 0.1, 0.1],
        "fact_flip": [0.1, 0.7, 0.1, 0.1],
        "sham": [0.7, 0.1, 0.1, 0.1],
        **{f"neutral_{index}": [0.7, 0.1, 0.1, 0.1] for index in range(1, 9)},
    }
    scope, exact, canonical = [], [], []
    for index, (role, posterior) in enumerate(vectors.items()):
        episode_id = f"episode-{index}"
        scope.append({"episode_id": episode_id, "neighborhood_id": "n-0", "family_slug": "family",
                      "role": role})
        exact.append({"episode_id": episode_id, "gold_targets": [{"value": {
            "semantic_type": "choice",
            "probabilities": [{"value": candidate, "probability": probability}
                              for candidate, probability in enumerate(posterior)],
        }}]})
        canonical.append({"episode_id": episode_id, "runtime_schema": {
            "schema_family_id": "schema:family",
            "candidates": [{"candidate_id": f"candidate-{candidate}",
                            "candidate_semantic_id": semantic_ids[candidate]}
                           for candidate in range(4)],
        }})
    return scope, exact, canonical, {"family": semantic_ids}


class ExactWorldTargetJoinTests(unittest.TestCase):
    def test_joins_targets_and_checks_invariance_and_fact_flip(self) -> None:
        scope, exact, canonical, orders = fixture_rows()
        receipt = attach_exact_world_targets(scope, exact, canonical, orders)
        self.assertEqual(receipt["status"], "EXACT_WORLD_TARGET_JOIN_PASS")
        self.assertEqual(receipt["join_key"], "episode_id")
        self.assertEqual(receipt["unique_episode_ids"], 11)
        self.assertEqual(receipt["fact_map_flip_count"], 1)
        self.assertTrue(all(len(row["target"]) == 4 for row in scope))

    def test_scope_indexes_preserve_both_episode_and_role_keys(self) -> None:
        scope, _exact, _canonical, _orders = fixture_rows()
        by_episode, by_role = TARGET_JOIN.index_scope_rows(scope)
        self.assertEqual(set(by_episode["n-0"]), {row["episode_id"] for row in scope})
        self.assertEqual(set(by_role["n-0"]), {row["role"] for row in scope})
        self.assertEqual(by_episode["n-0"]["episode-0"]["role"], "anchor")

    def test_rejects_episode_identity_set_mismatch(self) -> None:
        scope, exact, canonical, orders = fixture_rows()
        exact.pop()
        with self.assertRaisesRegex(ValueError, "exact bijection"):
            attach_exact_world_targets(scope, exact, canonical, orders)

    def test_rejects_candidate_order_mismatch(self) -> None:
        scope, exact, canonical, orders = fixture_rows()
        canonical[0]["runtime_schema"]["candidates"].reverse()
        with self.assertRaisesRegex(ValueError, "candidate identity/order mismatch"):
            attach_exact_world_targets(scope, exact, canonical, orders)

    def test_rejects_invariant_target_change(self) -> None:
        scope, exact, canonical, orders = fixture_rows()
        exact[2]["gold_targets"][0]["value"]["probabilities"][0]["probability"] = 0.6
        exact[2]["gold_targets"][0]["value"]["probabilities"][1]["probability"] = 0.2
        with self.assertRaisesRegex(ValueError, "invariant target changed"):
            attach_exact_world_targets(scope, exact, canonical, orders)


if __name__ == "__main__":
    unittest.main()
