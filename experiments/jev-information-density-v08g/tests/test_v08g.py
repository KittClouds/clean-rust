from __future__ import annotations

import importlib.util
import pathlib
import unittest

import torch

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "train_v08g.py"
SPEC = importlib.util.spec_from_file_location("jev_v08g_test_module", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FixedHead(torch.nn.Module):
    def forward(self, state: torch.Tensor, candidate: torch.Tensor) -> torch.Tensor:
        return torch.zeros((state.shape[0], candidate.shape[1]), dtype=torch.float32)


def group(group_id: str, view: str, gold: list[float], semantic_ids: list[str],
          kind: str = "choice") -> dict:
    return {
        "group_id": group_id,
        "episode_id": group_id.split("|")[0],
        "query_id": "q",
        "kind": kind,
        "view": view,
        "candidate_indices": {"name_definition": list(range(len(semantic_ids)))},
        "candidate_semantic_ids": semantic_ids,
        "candidate_cardinality": len(semantic_ids),
        "state_idx": 0,
        "gold": gold,
        "probability_source": "exact_generative_posterior",
        "authority": "exact_synthetic_control",
        "split": "new_tight_eval",
        "semantic_fingerprint": "fp",
        "invariant_key": group_id,
        "perturbation_class": None,
        "root_id": "root-1",
        "family_ids": {},
        "coverage_features": {},
        "open_world": False,
    }


class V08GTests(unittest.TestCase):
    def test_occurrences_survive_shared_feature_identity(self) -> None:
        rows = [
            group("ep1|q1", "choice", [1.0, 0.0], ["a", "b"]),
            group("ep2|q2", "choice", [0.0, 1.0], ["a", "b"]),
        ]
        features = torch.tensor([[1.0, 2.0, 3.0]])
        candidates = torch.tensor([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        scored = MODULE.score_groups(FixedHead(), rows, features, candidates,
                                     "name_definition", "cpu", batch_size=8)
        self.assertEqual(len(scored), 2)
        self.assertEqual([row["group_id"] for row in scored], ["ep1|q1", "ep2|q2"])
        self.assertEqual(scored[0]["prediction"], [0.5, 0.5])
        self.assertEqual(scored[1]["gold"], [0.0, 1.0])

    def test_semantic_alignment_ignores_candidate_reorder(self) -> None:
        left = {"candidate_semantic_ids": ["a", "b"], "prediction": [0.8, 0.2]}
        right = {"candidate_semantic_ids": ["b", "a"], "prediction": [0.2, 0.8]}
        p, q = MODULE.align_values(left, right)
        self.assertEqual(p, [0.8, 0.2])
        self.assertEqual(q, [0.8, 0.2])
        self.assertEqual(MODULE.distribution_drift([(left, right)][0:1])["mean_l1"], 0.0)

    def test_ordinal_metrics_include_order_aware_scores(self) -> None:
        rows = [
            {"view": "ordinal_score", "kind": "choice", "probability_source": "exact_generative_posterior",
             "gold": [0.0, 1.0, 0.0], "prediction": [0.0, 0.8, 0.2]},
            {"view": "ordinal_score", "kind": "choice", "probability_source": "exact_generative_posterior",
             "gold": [0.0, 0.0, 1.0], "prediction": [0.0, 0.1, 0.9]},
        ]
        result = MODULE.typed_metrics(rows)["by_view"]["ordinal_score"]["ordinal"]
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["exact_accuracy"], 1.0)
        self.assertEqual(result["adjacent_accuracy"], 1.0)
        self.assertAlmostEqual(result["ranked_probability_score_normalized"], 0.0125, places=12)

    def test_frozen_l3_batch_math_backpropagates_only_head(self) -> None:
        rows = [group("ep1|q1", "choice", [0.75, 0.25], ["a", "b"]),
                group("ep2|q2", "independent_applicability", [0.7], ["a"], "independent")]
        state_features = torch.randn(2, 4)
        candidate_features = torch.randn(2, 4)
        head = MODULE.probe.CompatibilityHead(4, "mlp", 128)
        optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01)
        state, candidate, gold, mask, kinds, sources = MODULE.trainer.fast_tensor_batch(
            rows, state_features, candidate_features, "name_definition", "cpu", reorder=True)
        logits = head(state, candidate)
        loss, brier = MODULE.trainer.v05_loss(logits, gold, mask, kinds, sources, 0.25)
        (loss + 0.10 * torch.zeros(())).backward()
        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(torch.isfinite(brier))
        self.assertTrue(any(parameter.grad is not None for parameter in head.parameters()))
        optimizer.step()


if __name__ == "__main__":
    unittest.main()
