from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import train_qterminal_v05_v02 as fit  # noqa: E402
from model_clausewise_v02 import ClausewiseQTerminal, conjunction_log_odds  # noqa: E402


class V05TerminalTests(unittest.TestCase):
    def _row(self, candidate_id: str, task_id: str, split: str, valid: bool, assignment: list[int]):
        return {
            "schema": "R1_QTERMINAL_V05_CANDIDATE_V02",
            "candidate_id": candidate_id,
            "task_id": task_id,
            "family_id": f"family-{task_id}",
            "split": split,
            "source_kind": "test-fixture",
            "assignment": assignment,
            "posthoc_valid": valid,
            "clause_satisfied": [valid],
            "label_source": "independent_typed_validator_v1",
        }

    def test_candidate_loader_preserves_roster_and_balances_each_task(self):
        roster = {
            "train-task": {"family_id": "family-train-task", "split": "train"},
            "validation-task": {"family_id": "family-validation-task", "split": "validation"},
        }
        feature_index = {"train-task": 0, "validation-task": 1}
        rows = []
        for task_id, split in (("train-task", "train"), ("validation-task", "validation")):
            rows.append(self._row(f"{task_id}-valid", task_id, split, True, [0] * 20))
            rows.append(self._row(f"{task_id}-invalid", task_id, split, False, [1] * 20))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            features = {"constraint_mask": np.ones((2, 1), dtype=np.bool_)}
            assignments, labels, clause_labels, splits, indices, loaded = fit.load_candidates(path, feature_index, roster, features, 1)
        self.assertEqual(assignments.shape, (4, 20))
        self.assertEqual(labels.tolist(), [1, 0, 1, 0])
        self.assertEqual(splits.tolist(), ["train", "train", "validation", "validation"])
        self.assertEqual(indices.tolist(), [0, 0, 1, 1])
        self.assertEqual(clause_labels[:, 0].tolist(), [True, False, True, False])
        self.assertEqual(len(loaded), 4)

    def test_candidate_loader_rejects_test_or_qualification_rows(self):
        roster = {"task": {"family_id": "family-task", "split": "train"}}
        row = self._row("candidate", "task", "qualification", True, [0] * 20)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(fit.ContractError):
                fit.load_candidates(path, {"task": 0}, roster, {"constraint_mask": np.ones((1, 1), dtype=np.bool_)}, 1)

    def test_batch_adapter_pads_roles_and_runs_qterminal(self):
        features = {
            "n": np.asarray([3, 3], dtype=np.int64),
            "k": np.asarray([3, 3], dtype=np.int64),
            "h_constraints": np.zeros((2, 2, 8), dtype=np.float32),
            "constraint_mask": np.asarray([[True, False], [True, True]], dtype=np.bool_),
            "entity_incidence": np.zeros((2, 2, 20), dtype=np.bool_),
            "role_incidence": np.zeros((2, 2, 6), dtype=np.bool_),
            "h_global": np.zeros((2, 8), dtype=np.float32),
        }
        assignments = np.full((2, 20), 255, dtype=np.uint8)
        assignments[0, :3] = [0, 1, 2]
        assignments[1, :3] = [2, 2, 0]
        H, h_global, one_hot = fit.make_batch(features, assignments, np.asarray([0, 1]), np.asarray([0, 1]), torch.device("cpu"))
        self.assertEqual(tuple(one_hot.shape), (2, 20, 6))
        self.assertEqual(float(one_hot[0, :3, :3].sum()), 3.0)
        self.assertEqual(float(one_hot[0, 3:, :].sum()), 0.0)
        model = ClausewiseQTerminal(hidden_dim=8, hidden_size=16, max_roles=6)
        logits, clause_logits = model.forward_with_clause_logits(H, h_global, one_hot)
        self.assertEqual(tuple(logits.shape), (2,))
        self.assertEqual(tuple(clause_logits.shape), (2, 2))
        self.assertTrue(torch.isfinite(logits).all())
        self.assertTrue(torch.isfinite(clause_logits).all())

    def test_candidate_loader_rejects_clause_label_disagreement(self):
        roster = {"task": {"family_id": "family-task", "split": "train"}}
        row = self._row("candidate", "task", "train", True, [0] * 20)
        row["clause_satisfied"] = [False]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(fit.ContractError):
                fit.load_candidates(path, {"task": 0}, roster, {"constraint_mask": np.ones((1, 1), dtype=np.bool_)}, 1)

    def test_temperature_and_metrics_remain_finite(self):
        labels = np.asarray([0, 0, 1, 1], dtype=np.uint8)
        logits = np.asarray([-2.0, -0.5, 0.5, 2.0], dtype=np.float32)
        temperature = fit.choose_temperature(logits, labels)
        self.assertGreaterEqual(temperature, 0.0499)
        self.assertLessEqual(temperature, 20.0)
        result = fit.metrics(labels, logits, temperature)
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["roc_auc"], 1.0)
        self.assertTrue(np.isfinite(result["bce"]))

    def test_conjunction_score_penalizes_one_violated_clause(self):
        mask = torch.ones((2, 4), dtype=torch.bool)
        logits = torch.tensor([[5.0, 5.0, 5.0, 5.0], [5.0, 5.0, -5.0, 5.0]])
        score = conjunction_log_odds(logits, mask)
        self.assertGreater(float(score[0]), 0.0)
        self.assertLess(float(score[1]), 0.0)


if __name__ == "__main__":
    unittest.main()
