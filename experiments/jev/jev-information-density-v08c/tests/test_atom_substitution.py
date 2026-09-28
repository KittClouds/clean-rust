from __future__ import annotations

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import build_phase2b_atom_candidates as builder
import optimize_matched_banks as optimizer


def make_group(group_id: str) -> optimizer.v08.Group:
    return optimizer.v08.Group(
        group_id=group_id,
        episode_id=f"episode-{group_id}",
        root_id="root-shared",
        families=(
            ("world_or_topology_family", "world"),
            ("ontology_family", "ontology"),
            ("schema_composition_family", "schema"),
            ("candidate_set_construction_family", "candidate-set"),
            ("definition_template_family", "definition"),
            ("intervention_family", "intervention"),
        ),
        strata=("world", "choice", "k2", "q1"),
        features=tuple((f"axis-{axis}:same",) for axis in range(5)),
        overlap_keys=("model_input:input-shared",),
        split_family_bundle_id="bundle-shared",
        posterior_entropy_nats=0.1,
    )


class AtomSubstitutionTests(unittest.TestCase):
    def test_build_one_picks_highest_priority_within_frozen_atom(self) -> None:
        witness = make_group("witness")
        replacement = make_group("replacement")
        selected, detail = builder.build_one(
            "CM100",
            "R100",
            "curated",
            "seed",
            [witness, replacement],
            {"R100": [witness]},
            {"witness": 1, "replacement": 2},
            group_limit=1,
        )
        self.assertEqual({group.group_id for group in selected}, {"replacement"})
        self.assertEqual(optimizer.group_atom(selected[0]), optimizer.group_atom(witness))
        self.assertEqual(detail["changed_group_count"], 2)
        self.assertTrue(detail["objective_positive_separation"])


if __name__ == "__main__":
    unittest.main()
