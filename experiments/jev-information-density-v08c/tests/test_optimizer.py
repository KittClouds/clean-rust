from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from ortools.sat.python import cp_model


SCRIPT = Path(__file__).resolve().parents[1] / "optimize_matched_banks.py"
SPEC = importlib.util.spec_from_file_location("jev_v08c_optimizer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def group(group_id: str, feature: str) -> MODULE.v08.Group:
    return MODULE.v08.Group(
        group_id=group_id,
        episode_id=f"ep-{group_id}",
        root_id="root",
        families=(
            ("world_or_topology_family", "world"),
            ("ontology_family", "ontology"),
            ("schema_composition_family", "schema"),
            ("candidate_set_construction_family", "set"),
            ("definition_template_family", "definition"),
            ("intervention_family", "intervention"),
        ),
        strata=("world", "choice", "k2", "q1"),
        features=tuple((f"{axis}:{feature}",) for axis in range(5)),
        overlap_keys=(f"model_input:{group_id}",),
        split_family_bundle_id="bundle",
        posterior_entropy_nats=0.1,
    )


class OptimizerTests(unittest.TestCase):
    def test_priority_ranks_are_unique_and_input_order_stable(self) -> None:
        rows = [group("a", "same"), group("b", "same"), group("c", "other")]
        expected = MODULE.priority_ranks(rows, "random", "seed")
        actual = MODULE.priority_ranks(list(reversed(rows)), "random", "seed")
        self.assertEqual(expected, actual)
        self.assertEqual(len(set(expected.values())), len(rows))

    def test_objective_selects_highest_priority_within_an_atom(self) -> None:
        rows = [group("low", "x"), group("high", "y")]
        atom = ("input", "root", ("cell",), (), "intervention")
        model = cp_model.CpModel()
        atom_count = model.new_int_var(0, 2, "atom_count")
        model.add(atom_count == 1)
        selected_vars, _ = MODULE.add_priority_objective(
            model,
            [atom_count],
            [atom],
            {atom: rows},
            {"low": 1, "high": 2},
        )
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        status = solver.solve(model)
        self.assertEqual(status, cp_model.OPTIMAL)
        chosen = {row.group_id for row, variable in selected_vars if solver.value(variable)}
        self.assertEqual(chosen, {"high"})


if __name__ == "__main__":
    unittest.main()
