from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "discover_v08d_common_support.py"
SPEC = importlib.util.spec_from_file_location("jev_v08d_support", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class QuotaTests(unittest.TestCase):
    def test_exact_total_and_fourfold_replay_bound(self) -> None:
        capacities = {"a": 40, "b": 80, "c": 120}
        quotas = MODULE.allocate_quotas(capacities, target=30, multiplier=4)
        self.assertEqual(sum(quotas.values()), 30)
        self.assertEqual(set(quotas), set(capacities))
        for key, quota in quotas.items():
            self.assertGreaterEqual(quota, 1)
            self.assertLessEqual(quota * 4, capacities[key])

    def test_allocation_is_mapping_order_independent(self) -> None:
        first = {"a": 40, "b": 80, "c": 120, "d": 200}
        second = dict(reversed(list(first.items())))
        self.assertEqual(
            MODULE.allocate_quotas(first, target=45, multiplier=4),
            MODULE.allocate_quotas(second, target=45, multiplier=4),
        )

    def test_insufficient_capacity_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "fourfold replay capacity"):
            MODULE.allocate_quotas({"a": 40}, target=11, multiplier=4)

    def test_too_many_admitted_strata_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "one-per-stratum"):
            MODULE.allocate_quotas({str(i): 4 for i in range(5)}, target=4, multiplier=4)


class MetadataTests(unittest.TestCase):
    def make_row(self, *, topology: str = "direct_causes") -> tuple[object, ...]:
        joint = ["world-a", "bundle-a", "choice", "3-4", "q2", "medium"]
        coverage = {
            "structural_coverage": [f"topology:{topology}", "query:choice"],
            "semantic_novelty": ["definition:v0"],
        }
        families = {
            "world_or_topology_family": "world-a",
            "ontology_family": "ontology-a",
            "schema_composition_family": "schema-a",
            "candidate_set_construction_family": "candidate-set-a",
            "definition_template_family": "definition-a",
            "intervention_family": "surface-hide-do",
        }
        return (
            "g1", "e1", "r1", json.dumps(joint), "selector-input", "state-input",
            json.dumps(coverage), json.dumps(families), "choice", "choice", 0,
            "exact_generative_posterior", 4, "state-input", "candidate-ordered",
            "candidate-set", "target", "supervised", "ordered", "invariant", None,
        )

    def test_topology_is_extracted_from_nested_structural_features(self) -> None:
        item = MODULE.item_from_row(self.make_row())
        self.assertEqual(item.topology, ("direct_causes",))
        self.assertEqual(item.input_state, "state-input")
        self.assertEqual(item.input_selector, "selector-input")
        self.assertEqual(json.loads(item.stratum_id)[1], ["direct_causes"])

    def test_missing_topology_is_not_silently_erased(self) -> None:
        row = list(self.make_row())
        coverage = json.loads(row[6])
        coverage["structural_coverage"] = ["query:choice"]
        row[6] = json.dumps(coverage)
        with self.assertRaisesRegex(ValueError, "no topology feature"):
            MODULE.item_from_row(tuple(row))

    def test_missing_family_axis_is_not_silently_erased(self) -> None:
        row = list(self.make_row())
        families = json.loads(row[7])
        del families["ontology_family"]
        row[7] = json.dumps(families)
        with self.assertRaisesRegex(ValueError, "missing family axes"):
            MODULE.item_from_row(tuple(row))

    def test_tv_distance(self) -> None:
        self.assertAlmostEqual(
            MODULE.tv_distance(MODULE.Counter(a=8, b=2), MODULE.Counter(a=7, b=3)),
            0.1,
        )


if __name__ == "__main__":
    unittest.main()
