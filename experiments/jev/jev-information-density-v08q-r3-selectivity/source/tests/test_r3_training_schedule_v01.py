import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import materialize_r3_training_schedule_v01 as schedule


class ScheduleContractTests(unittest.TestCase):
    def setUp(self):
        self.primary = []
        for pair in range(5_000):
            for role in ("anchor", "fact_flip"):
                index = len(self.primary)
                self.primary.append({
                    "occurrence_index": index,
                    "group_id": f"n-{pair:04d}::{role}",
                    "role": role,
                })
        self.auxiliary = [{"event_index": index} for index in range(5_000)]

    def test_bridge_indices_are_frozen(self):
        self.assertEqual(schedule.bridge_indices(), schedule.EXPECTED_BRIDGE_INDICES)

    def test_schedule_replays_and_covers_every_epoch(self):
        first = schedule.schedule_for_seed(self.primary, 123456)
        second = schedule.schedule_for_seed(self.primary, 123456)
        self.assertEqual(first, second)
        schedule.validate_schedule(self.primary, self.auxiliary, first, [123456])
        self.assertEqual(len(first), 120)
        for epoch in (1, 2, 3):
            block = [row for row in first if row["epoch"] == epoch]
            self.assertEqual(
                sorted(index for row in block for index in row["primary_occurrence_indices"]),
                list(range(10_000)),
            )
            self.assertEqual(
                sorted(index for row in block for index in row["auxiliary_anchor_batch_slots"]),
                list(range(5_000)),
            )

    def test_different_epochs_use_frozen_epoch_seed_offset(self):
        rows = schedule.schedule_for_seed(self.primary, 123456)
        first = [row["primary_occurrence_indices"] for row in rows[:40]]
        second = [row["primary_occurrence_indices"] for row in rows[40:80]]
        third = [row["primary_occurrence_indices"] for row in rows[80:]]
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)

    def test_bridge_is_only_a_polarity_assignment_change(self):
        balanced = []
        bridge = []
        for pair in range(5_000):
            direction = "high_to_low" if pair < 2_500 else "low_to_high"
            for source_role in ("anchor", "fact_flip"):
                bridge_item = {"neighborhood_id": f"n-{pair}", "role": source_role,
                    "episode_id": f"n-{pair}-{source_role}", "family_slug": "family",
                    "candidate_semantic_ids": ["a", "b", "c", "d"], "direction": "high_to_low",
                    "input_sha256": f"input-{pair}-{source_role}", "target_hash": f"target-{pair}-{source_role}",
                    "old_semantic_id": "a", "new_semantic_id": "b"}
                if direction == "high_to_low":
                    role, old_id, new_id = source_role, "a", "b"
                else:
                    role = "fact_flip" if source_role == "anchor" else "anchor"
                    old_id, new_id = "b", "a"
                balanced.append({**bridge_item, "role": role, "direction": direction,
                    "old_semantic_id": old_id, "new_semantic_id": new_id})
                bridge.append(bridge_item)
        counts = schedule.validate_bridge_pairing(balanced, bridge)
        self.assertEqual(counts, {"high_to_low": 5_000, "low_to_high": 5_000})
        bridge[-1] = {**bridge[-1], "episode_id": "different-episode"}
        with self.assertRaises(RuntimeError):
            schedule.validate_bridge_pairing(balanced, bridge)


if __name__ == "__main__":
    unittest.main()
