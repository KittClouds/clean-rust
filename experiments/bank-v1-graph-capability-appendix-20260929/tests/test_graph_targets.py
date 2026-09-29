import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graph_targets import (PATH_CLASSES, derive_targets, path_class,
                           shortest_goal_path)


def world(goal_args, origin="loc_a", edges=(), goal_pred="AT", object_type="OBJECT"):
    facts = [{"pred": "AT", "args": ["obj_0", origin]}]
    facts.extend({"pred": "CONNECTED", "args": list(edge)} for edge in edges)
    return {
        "goal": {"pred": goal_pred, "args": goal_args},
        "entities": [{"id": "obj_0", "type": object_type},
                     {"id": "loc_a", "type": "LOCATION"},
                     {"id": "loc_b", "type": "LOCATION"},
                     {"id": "loc_c", "type": "LOCATION"}],
        "initial_state": facts,
    }


class GraphTargetTests(unittest.TestCase):
    def test_directed_representation_is_treated_as_undirected_connectivity(self):
        row = world(["obj_0", "loc_b"], edges=[("loc_b", "loc_a")])
        self.assertEqual(shortest_goal_path(row), 1)
        self.assertEqual(path_class(shortest_goal_path(row)), PATH_CLASSES.index("ONE_HOP"))

    def test_multi_hop_composition_and_disconnected_cases(self):
        two_hops = world(["obj_0", "loc_c"], edges=[("loc_a", "loc_b"), ("loc_b", "loc_c")])
        disconnected = world(["obj_0", "loc_c"], edges=[("loc_a", "loc_b")])
        self.assertEqual(shortest_goal_path(two_hops), 2)
        self.assertEqual(path_class(shortest_goal_path(two_hops)), PATH_CLASSES.index("MULTI_HOP"))
        self.assertEqual(shortest_goal_path(disconnected), -1)
        self.assertEqual(path_class(shortest_goal_path(disconnected)), PATH_CLASSES.index("DISCONNECTED"))

    def test_already_satisfied_goal_and_non_applicable_queries(self):
        already = world(["obj_0", "loc_a"])
        state_goal = world(["sw_0"], goal_pred="STATE")
        unknown_entity = world(["e_unknown", "loc_a"])
        self.assertEqual(shortest_goal_path(already), 0)
        self.assertIsNone(shortest_goal_path(state_goal))
        self.assertIsNone(shortest_goal_path(unknown_entity))

    def test_graph_level_targets_are_canonical_sets_and_not_node_rows(self):
        row = world(["obj_0", "loc_b"], edges=[("loc_a", "loc_b")])
        row["initial_state"].append({"pred": "STATE", "args": ["sw_0"], "value": "ACTIVE"})
        targets = derive_targets(row)
        self.assertEqual(targets["entity_types"], ["LOCATION", "OBJECT"])
        self.assertEqual(targets["relation_types"], ["AT", "CONNECTED", "STATE"])
        self.assertEqual(targets["state_values"], ["ACTIVE"])
        self.assertEqual(targets["goal_path_distance"], 1)

    def test_invalid_negative_distance_rejected(self):
        with self.assertRaises(ValueError):
            path_class(-2)


if __name__ == "__main__":
    unittest.main()
