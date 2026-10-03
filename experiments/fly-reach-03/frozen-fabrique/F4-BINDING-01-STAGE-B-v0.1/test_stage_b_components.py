"""Task-independent regression tests for F4-BINDING-01 Stage B tooling."""
from __future__ import annotations

import unittest

import numpy as np

import binding_stage_b_model as model
import binding_stage_b_scoring as scoring
import prepare_stage_b_tasks as tasks


class AssignmentNamespaceTests(unittest.TestCase):
    def test_assignment_mapping_is_balanced_and_reproducible(self) -> None:
        first = tasks.assignment_mapping()
        second = tasks.assignment_mapping()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 24)
        self.assertEqual([first.count(index) for index in range(6)], [4] * 6)

    def test_seed_domains_produce_72_unique_values(self) -> None:
        domains = (tasks.TASK_DOMAIN, tasks.SIMULATOR_DOMAIN, tasks.SCHEDULE_DOMAIN)
        seeds = [
            tasks.derive_seed(domain, ordinal, block)[0]
            for domain in domains
            for ordinal, block in enumerate(tasks.BLOCK_IDS)
        ]
        self.assertEqual(len(seeds), 72)
        self.assertEqual(len(set(seeds)), 72)


class InferenceInterventionTests(unittest.TestCase):
    @staticmethod
    def random_tensors() -> list[np.ndarray]:
        rng = np.random.Generator(np.random.PCG64(14837))
        arrays = []
        for shape in model.CPHI.TENSOR_SHAPES:
            if len(shape) == 1:
                arrays.append(np.zeros(shape, dtype=np.float32))
            else:
                arrays.append((rng.standard_normal(shape) * 0.03).astype(np.float32))
        return arrays

    def test_frozen_interventions_preserve_h_and_change_only_slot_map(self) -> None:
        rng = np.random.Generator(np.random.PCG64(2811))
        base = rng.standard_normal((12, 66)).astype(np.float32)
        tuples = rng.standard_normal((12, 4, 6)).astype(np.float32)
        tensors = self.random_tensors()
        h = model.h_from_normalized(base, tuples, tensors)
        before = h.tobytes()
        outputs = {
            name: model.rho_forward(base, h, tensors, permutation)
            for name, permutation in model.PERMUTATIONS.items()
        }
        self.assertEqual(h.tobytes(), before)
        self.assertEqual(set(model.PERMUTATIONS), {"intact", "pair_swap", "cycle_4"})
        self.assertEqual(model.PERMUTATIONS["intact"], (0, 1, 2, 3))
        self.assertEqual(model.PERMUTATIONS["pair_swap"], (1, 0, 2, 3))
        self.assertEqual(model.PERMUTATIONS["cycle_4"], (1, 2, 3, 0))
        self.assertTrue(np.isfinite(np.stack(list(outputs.values()))).all())
        self.assertGreater(float(np.max(np.abs(outputs["pair_swap"] - outputs["intact"]))), 0.0)
        self.assertGreater(float(np.max(np.abs(outputs["cycle_4"] - outputs["intact"]))), 0.0)

    def test_nonpermutation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            model.rho_forward(
                np.zeros((1, 66), dtype=np.float32),
                np.zeros((1, 4, 16), dtype=np.float32),
                self.random_tensors(),
                (0, 0, 1, 2),
            )


class ScoringTests(unittest.TestCase):
    def test_weighted_balanced_error_and_q_diagnostics(self) -> None:
        y = np.asarray([-1, 1, -1, 1], dtype=np.int8)
        logits = np.asarray([-2.0, 2.0, 3.0, 4.0], dtype=np.float32)
        q = np.asarray([1.0, 3.0, 2.0, 4.0], dtype=np.float64)
        self.assertAlmostEqual(scoring.weighted_balanced_error(logits, y, q), 1.0 / 3.0)
        diag = scoring.q_diagnostics(q)
        self.assertEqual(diag["count"], 4)
        self.assertEqual(diag["min"], 1.0)
        self.assertEqual(diag["max"], 4.0)
        self.assertEqual(diag["sum"], 10.0)
        self.assertAlmostEqual(diag["ess"], 100.0 / 30.0)

    def test_one_class_balanced_error_is_undefined(self) -> None:
        y = np.asarray([1, 1], dtype=np.int8)
        logits = np.asarray([1.0, -1.0], dtype=np.float32)
        q = np.asarray([1.0, 2.0], dtype=np.float64)
        self.assertIsNone(scoring.weighted_balanced_error(logits, y, q))

    def test_pair_bootstrap_is_deterministic_and_block_clustered(self) -> None:
        block_ids = tuple(range(310000, 310024))
        block_to_assignment = {block: index // 4 for index, block in enumerate(block_ids)}
        blocks = np.repeat(np.asarray(block_ids, dtype=np.uint64), 2)
        y = np.tile(np.asarray([-1, 1], dtype=np.int8), 24)
        q = np.ones(48, dtype=np.float64)
        logits = np.zeros((36, 48, 3), dtype=np.float32)
        logits[:, 0::2, 0] = -1.0
        logits[:, 1::2, 0] = 1.0
        logits[:, 0::2, 1] = 1.0
        logits[:, 1::2, 1] = 1.0
        logits[:, 0::2, 2] = -1.0
        logits[:, 1::2, 2] = 1.0
        first = scoring.paired_block_bootstrap(logits, blocks, block_to_assignment, y, q, 918273, draws=32)
        second = scoring.paired_block_bootstrap(logits, blocks, block_to_assignment, y, q, 918273, draws=32)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["draws_evaluable"], 32)
        self.assertEqual(first["intervals"]["pair_swap"], [0.5, 0.5])
        self.assertEqual(first["intervals"]["cycle_4"], [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
