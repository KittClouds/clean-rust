from __future__ import annotations

import ast
import hashlib
import typing
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase2c_training_signatures as signatures


def _episode() -> dict:
    return {
        "identity": {"episode_id": "ep-base"},
        "state": {"observable": {"content": "evidence text"}},
        "runtime_schema": {
            "candidates": [
                {
                    "candidate_id": "a",
                    "candidate_semantic_id": "alpha",
                    "name": "Alpha",
                    "description": "First meaning",
                },
                {
                    "candidate_id": "b",
                    "candidate_semantic_id": "beta",
                    "name": "Beta",
                    "description": "Second meaning",
                },
            ],
            "candidate_sets": [
                {
                    "candidate_set_id": "choice-set",
                    "candidate_ids": ["a", "b"],
                }
            ],
        },
        "queries": [
            {
                "query_id": "q1",
                "view": "choice",
                "query_semantic_id": "runtime-q",
                "candidate_set_id": "choice-set",
            }
        ],
        "gold_targets": [
            {
                "query_id": "q1",
                "target": {
                    "target_kind": "choice",
                    "distribution": [
                        {"candidate_semantic_id": "alpha", "probability": 0.25},
                        {"candidate_semantic_id": "beta", "probability": 0.75},
                    ],
                    "other_probability": 0.0,
                },
                "probability_source": {
                    "probability_source": "exact_generative_posterior"
                },
            }
        ],
        "perturbation": {},
    }


def _probe_projection_functions() -> dict:
    probe_path = Path(__file__).resolve().parents[2] / "jev-frozen-readout-v01" / "probe.py"
    tree = ast.parse(probe_path.read_text(encoding="utf-8"))
    selected_names = {
        "stable_hash",
        "stable_opaque_id",
        "candidate_surface",
        "candidate_index",
        "query_candidates",
        "query_target",
        "state_query_text",
        "split_name",
        "group_records",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in selected_names
    ]
    namespace = {"Any": typing.Any, "hashlib": hashlib}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(probe_path), "exec"), namespace)
    return namespace


class TrainingSignatureTests(unittest.TestCase):
    def test_adapter_projection_uses_exact_v05_state_and_candidate_surface(self) -> None:
        groups = signatures.group_records(_episode())
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["group_id"], "ep-base|q1")
        self.assertEqual(group["kind"], "choice")
        self.assertEqual(group["candidate_surfaces"], [
            "Alpha — First meaning",
            "Beta — Second meaning",
        ])
        self.assertEqual(group["gold"], [0.25, 0.75])
        self.assertIn("Runtime query: runtime-q", group["state_text"])

    def test_projection_matches_frozen_probe_functions_without_importing_torch(self) -> None:
        reference_functions = _probe_projection_functions()
        reference = reference_functions["group_records"]([_episode()])
        actual = signatures.group_records(_episode())
        self.assertEqual(len(reference), len(actual))
        expected = reference[0]
        observed = actual[0]
        self.assertEqual(expected["group_id"], observed["group_id"])
        self.assertEqual(expected["kind"], observed["kind"])
        self.assertEqual(expected["view"], observed["view"])
        self.assertEqual(expected["state_text"], observed["state_text"])
        self.assertEqual(expected["gold"], observed["gold"])
        self.assertEqual(expected["open_world"], observed["open_world"])
        self.assertEqual(expected["probability_source"], observed["probability_source"])
        self.assertEqual(
            [
                reference_functions["candidate_surface"](
                    expected["candidate_descriptions"][semantic_id], position, "name_definition"
                )
                for position, semantic_id in enumerate(expected["candidate_semantic_ids"])
            ],
            observed["candidate_surfaces"],
        )

    def test_candidate_reordering_is_supervised_equivalent_but_order_diagnostic_differs(self) -> None:
        first = {
            "state_text": "same state",
            "candidate_surfaces": ["A — alpha", "B — beta"],
            "gold": [0.25, 0.75],
            "kind": "choice",
            "view": "choice",
            "open_world": False,
            "probability_source": "exact_generative_posterior",
        }
        reversed_group = dict(first)
        reversed_group["candidate_surfaces"] = list(reversed(first["candidate_surfaces"]))
        reversed_group["gold"] = list(reversed(first["gold"]))
        left = signatures.base_signatures(first)
        right = signatures.base_signatures(reversed_group)
        self.assertEqual(left["supervised_signature_sha256"], right["supervised_signature_sha256"])
        self.assertNotEqual(left["ordered_signature_sha256"], right["ordered_signature_sha256"])

    def test_float32_bits_match_tensor_target_rounding(self) -> None:
        self.assertEqual(signatures.f32_bits(0.1), "cdcccc3d")
        self.assertEqual(signatures.f32_bits(0.1000000001), "cdcccc3d")
        with self.assertRaises(ValueError):
            signatures.f32_bits(float("nan"))

    def test_first_sixteen_invariance_pairs_are_directed_and_group_sorted(self) -> None:
        rows = []
        for index in range(18):
            common = {
                "kind": "choice",
                "view": "choice",
                "state_text": f"state-{index}",
                "candidate_surfaces": ["A — alpha", "B — beta"],
                "gold": [0.5, 0.5],
                "open_world": False,
                "probability_source": "exact_generative_posterior",
                "invariant_key": f"family-{index}",
            }
            rows.append({
                **common,
                "group_id": f"{index:02d}-base",
                "perturbation_class": None,
            })
            rows.append({
                **common,
                "group_id": f"{index:02d}-surface",
                "state_text": f"surface-state-{index}",
                "perturbation_class": "surfaceinvariance",
            })
        pairs = signatures.selected_invariance_pairs(reversed(rows), max_pairs=16)
        self.assertEqual(len(pairs), 16)
        self.assertTrue(all(left["group_id"].endswith("-base") for left, _ in pairs))
        self.assertTrue(all(right["group_id"].endswith("-surface") for _, right in pairs))
        final, edge_hashes = signatures.attach_invariance_context(rows)
        self.assertEqual(len(edge_hashes), 16)
        self.assertEqual(len(final), len(rows))

    def test_open_world_rows_do_not_enter_invariance_pairs(self) -> None:
        rows = []
        for suffix, perturbation, open_world in (
            ("base", None, True),
            ("surface", "surfaceinvariance", True),
        ):
            rows.append({
                "group_id": suffix,
                "kind": "choice",
                "view": "choice",
                "state_text": "state",
                "candidate_surfaces": ["A — alpha"],
                "gold": [0.4],
                "open_world": open_world,
                "probability_source": "exact_generative_posterior",
                "invariant_key": "one-family",
                "perturbation_class": perturbation,
            })
        self.assertEqual(signatures.selected_invariance_pairs(rows), [])

    def test_multiset_distance_counts_multiplicity(self) -> None:
        self.assertEqual(signatures.multiset_distance(["a", "a", "b"], ["a", "b", "b"]), 1 / 3)
        self.assertEqual(signatures.multiset_distance(["a"], ["a"]), 0.0)


if __name__ == "__main__":
    unittest.main()
