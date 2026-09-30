import random
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import exact_spans, identifier_type, local_surface_arrays, token_to_lexical_type
from derive_graph_data import create_world_examples
from fit_graph import (epoch_batches, feature_vectors, lexical_control_predictions,
                       random_link_metrics)
from graph_link import candidates_with_target
from graph_metrics import classification_metrics


class SpanContractTests(unittest.TestCase):
    def test_exact_spans_use_whole_alias_boundaries(self):
        text = "obj_0 in the hall; objectivity is unrelated."
        self.assertEqual(exact_spans(text, "obj_0"), [[0, 5]])
        self.assertEqual(exact_spans(text, "object"), [])

    def test_renderer_symbolic_ids_are_visible_as_a_separate_control(self):
        self.assertEqual(identifier_type("obj_0"), "OBJECT")
        self.assertEqual(identifier_type("loc_3"), "LOCATION")
        self.assertEqual(token_to_lexical_type("sapphire_object"), "OBJECT")
        self.assertEqual(token_to_lexical_type("vault_1"), "LOCATION")

    def test_local_surface_shapes_match_rung0_views(self):
        n = 3
        values = {name: np.zeros((n, 1024), dtype=np.float16)
                  for name in ("middle_mean", "final_mean", "final_last", "m4_mean")}
        indexes = np.asarray([0, 2])
        self.assertEqual(local_surface_arrays(values, indexes, "middle_plus_final").shape, (2, 2048))
        self.assertEqual(local_surface_arrays(values, indexes, "final_plus_mean").shape, (2, 2048))
        self.assertEqual(local_surface_arrays(values, indexes, "layer_m4_final").shape, (2, 1024))
        self.assertEqual(local_surface_arrays(values, indexes, "full_mean").shape, (2, 1024))


class GraphTargetTests(unittest.TestCase):
    def test_link_candidates_include_a_valid_self_loop_target(self):
        query = {"candidate_indices": [2, 3], "candidate_lex_types": ["L", "O"],
                 "candidate_id_types": ["LOCATION", "OBJECT"], "target_idx": 1,
                 "lex_target": "L", "id_type_target": "LOCATION"}
        candidates, lexical, identifiers = candidates_with_target(query)
        self.assertEqual(candidates, [2, 3, 1])
        self.assertEqual(lexical, ["L", "O", "L"])
        self.assertEqual(identifiers, ["LOCATION", "OBJECT", "LOCATION"])

    def test_first_token_control_does_not_require_local_scalers(self):
        rows = [{"row_idx": 1}]
        primitives = {"final_token": np.zeros((2, 4), dtype=np.float32),
                      "middle_final": np.zeros((2, 4), dtype=np.float32),
                      "full_mean": np.zeros((2, 4), dtype=np.float32),
                      "first_token": np.arange(8, dtype=np.float32).reshape(2, 4),
                      "layer_m4_final": np.zeros((2, 4), dtype=np.float32)}
        scalers = {"row": {"first_token": (np.zeros(4), np.ones(4))}}
        result = feature_vectors(rows, "node_type", "first_token", {}, primitives,
                                 scalers, representation="first_token")
        self.assertTrue(np.array_equal(result, primitives["first_token"][1:2]))

    def test_epoch_batches_are_deterministic_complete_and_block_local(self):
        keys = np.random.default_rng(5).permutation(10_003)
        order = np.argsort(keys, kind="stable")
        first = list(epoch_batches(10_003, np.random.default_rng(41), order))
        second = list(epoch_batches(10_003, np.random.default_rng(41), order))
        self.assertEqual([x.tolist() for x in first], [x.tolist() for x in second])
        self.assertEqual(sorted(np.concatenate(first).tolist()), list(range(10_003)))
        width = 2048 * 4
        ranks = np.empty(len(order), dtype=np.int64)
        ranks[order] = np.arange(len(order))
        self.assertTrue(all(len(set((ranks[batch] // width).tolist())) == 1
                            for batch in first))

    def test_chain_has_exact_one_and_two_hop_membership(self):
        ids = ["loc_0", "loc_1", "loc_2", "loc_3", "obj_0"]
        entities = {eid: (idx, "hall" if eid.startswith("loc") else "jade_object", True, "LEXICAL_CONTEXT")
                    for idx, eid in enumerate(ids)}
        world = {
            "entities": [{"id": eid, "type": "LOCATION" if eid.startswith("loc") else "OBJECT"}
                         for eid in ids],
            "initial_state": [
                {"pred": "CONNECTED", "args": ["loc_0", "loc_1"]},
                {"pred": "CONNECTED", "args": ["loc_1", "loc_2"]},
                {"pred": "CONNECTED", "args": ["loc_2", "loc_3"]},
                {"pred": "AT", "args": ["obj_0", "loc_0"]},
            ],
        }
        row_meta = {"row_idx": 0, "world_id": "toy", "surface_family": "S0"}
        examples = create_world_examples(world, row_meta, entities, [], random.Random(17), "TRAIN")
        one = examples["one_hop_membership"]
        two = examples["two_hop_membership"]
        self.assertEqual(sum(x["label"] == 1 for x in one), 6)
        self.assertEqual(sum(x["label"] == 0 for x in one), 6)
        self.assertEqual(sum(x["label"] == 1 for x in two), 4)
        self.assertEqual(sum(x["label"] == 0 for x in two), 2)
        link = examples["link_completion"]
        self.assertEqual(sum(x["label"] == 1 for x in link), 4)
        self.assertEqual(sum(x["label"] == 0 for x in link), 4)

    def test_random_link_control_uses_expected_reciprocal_rank(self):
        result = random_link_metrics([{"candidate_indices": [0, 1], "family": "S7"}])
        self.assertEqual(result["mrr"], 0.75)
        self.assertEqual(result["by_renderer"]["S7"]["hits_at_1"], 0.5)

    def test_lexical_and_symbolic_node_controls_stay_separate(self):
        rows = [{"lex_type": None, "id_type": "LOCATION"}]
        prior = np.ones(6, dtype=np.float64)
        lexical = lexical_control_predictions(rows, "node_type", {"mode": "lex", "table": {}}, prior)
        symbolic = lexical_control_predictions(rows, "node_type", {"mode": "id", "table": {}}, prior)
        self.assertTrue(np.array_equal(lexical[0], prior))
        self.assertEqual(int(np.argmax(symbolic[0])), 2)

    def test_macro_f1_ignores_classes_absent_from_truth_and_predictions(self):
        y = np.asarray([0, 0, 1, 1], dtype=np.int64)
        logits = np.asarray([[3, 0, 0, 0, 0, 0], [3, 0, 0, 0, 0, 0],
                             [0, 3, 0, 0, 0, 0], [0, 3, 0, 0, 0, 0]], dtype=np.float32)
        self.assertEqual(classification_metrics(y, logits, 6)["macro_f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
