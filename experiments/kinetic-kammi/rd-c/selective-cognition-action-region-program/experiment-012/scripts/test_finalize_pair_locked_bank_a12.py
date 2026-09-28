from __future__ import annotations

import unittest

from finalize_pair_locked_bank_e012_a12 import (
    candidate_block_configs,
    make_config,
    maps_for,
)


def task(task_id: str, pair_id: str, target: str = "E_t") -> dict:
    role_ids = {"a": 1, "b": 2, "c": 3, "d": 4}
    options = [
        {
            "hidden_candidate_role": role,
            "action": {"id": action_id},
            "patch_sha256": f"patch-{role}",
            "summary": f"summary-{role}",
            "diff_excerpt": f"diff-{role}",
        }
        for role, action_id in role_ids.items()
    ]
    return {
        "task_id": task_id,
        "pair_id": pair_id,
        "within_family_index": 1 if task_id.endswith("1") else 2,
        "counterfactual_change_channel_hidden": target,
        "candidate_role_to_action_id_hidden": role_ids,
        "candidate_options_hidden": options,
        "check_cases": ["case-01"],
    }


class PairedAssignmentTests(unittest.TestCase):
    def test_single_channel_pair_keeps_mapping_and_order(self) -> None:
        left, right = task("task-1", "pair-1"), task("task-2", "pair-1")
        passes = {"task-1": {"a"}, "task-2": {"b"}}
        gold = {"task-1": "a", "task-2": "b"}
        patch_hashes = {task_id: {role: f"patch-{role}" for role in "abcd"} for task_id in passes}
        configs = candidate_block_configs([left, right], "E_t", passes, gold, patch_hashes)
        self.assertEqual(len(configs), 24 * 24)
        chosen = configs[0]
        self.assertEqual(chosen["mapping_by_task"]["task-1"], chosen["mapping_by_task"]["task-2"])
        self.assertNotEqual(chosen["valid_ids_by_task"]["task-1"], chosen["valid_ids_by_task"]["task-2"])

    def test_candidate_content_pair_changes_id_binding_and_keeps_order(self) -> None:
        left, right = task("task-1", "pair-1", "E_c.content"), task("task-2", "pair-1", "E_c.content")
        passes = {"task-1": {"a"}, "task-2": {"a"}}
        gold = {"task-1": "a", "task-2": "a"}
        patch_hashes = {task_id: {role: f"patch-{role}" for role in "abcd"} for task_id in passes}
        configs = candidate_block_configs([left, right], "E_c.content", passes, gold, patch_hashes)
        self.assertTrue(configs)
        self.assertTrue(all(set(config["order"]) == {1, 2, 3, 4} for config in configs))
        self.assertTrue(all(config["valid_ids_by_task"]["task-1"] != config["valid_ids_by_task"]["task-2"] for config in configs))
        self.assertTrue(all(config["mapping_by_task"]["task-1"] != config["mapping_by_task"]["task-2"] for config in configs))

    def test_assignment_counts_by_id_position_and_gold(self) -> None:
        role_ids = maps_for(list("abcd"), [1, 2, 3, 4])[0]
        row = task("task-1", "pair-1")
        config = make_config([row], [role_ids], (1, 2, 3, 4), {"task-1": {"a", "b"}}, {"task-1": "a"})
        self.assertEqual(config["id_counts"], (1, 1, 0, 0))
        self.assertEqual(config["position_counts"], (1, 1, 0, 0))
        self.assertEqual(config["gold_positions"], {"task-1": 0})


if __name__ == "__main__":
    unittest.main()
