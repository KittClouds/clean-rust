from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from prepare_tasks import (
    ASSIGNMENTS, BLOCK_IDS, SCHEDULE_DOMAIN, SIMULATOR_DOMAIN, TASK_DOMAIN,
    assignment_mapping, derive_seed, schedule_for_assignment,
)


class TaskDesignTests(unittest.TestCase):
    def test_exactly_two_blocks_are_mapped_to_every_balanced_assignment(self) -> None:
        mapping = assignment_mapping()
        self.assertEqual(len(mapping), 12)
        self.assertEqual([mapping.count(index) for index in range(6)], [2] * 6)
        self.assertEqual(len(ASSIGNMENTS), 6)
        self.assertEqual(len(BLOCK_IDS), 12)
        self.assertEqual(len(set(BLOCK_IDS)), 12)

    def test_fixed_label_assignment_preserves_ordinary_schedule_bytes(self) -> None:
        generator_path = Path(__file__).resolve().parents[1] / "scripts" / "prepare_qualification.py"
        spec = importlib.util.spec_from_file_location("f4_presentation03_schedule_test", generator_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seeds = (11, 309000, 987654321)
        for assignment in ASSIGNMENTS:
            expected_labels = [cue in assignment for cue in range(4)]
            for seed in seeds:
                fixed_labels, fixed_rows = schedule_for_assignment(seed, assignment)
                _random_labels, ordinary_rows = module.schedule(seed)
                self.assertEqual(fixed_labels, expected_labels)
                self.assertEqual(fixed_rows, ordinary_rows)

    def test_task_simulator_and_schedule_seed_domains_are_distinct(self) -> None:
        derived = [derive_seed(domain, 3, BLOCK_IDS[3]) for domain in (TASK_DOMAIN, SIMULATOR_DOMAIN, SCHEDULE_DOMAIN)]
        self.assertEqual(len({seed for seed, _digest, _payload in derived}), 3)
        self.assertEqual(len({digest for _seed, digest, _payload in derived}), 3)
        self.assertEqual(len({payload for _seed, _digest, payload in derived}), 3)


if __name__ == "__main__":
    unittest.main()
