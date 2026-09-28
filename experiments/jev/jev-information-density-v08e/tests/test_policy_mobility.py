from __future__ import annotations

import collections
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
import audit_policy_mobility as mobility  # noqa: E402
import analyze_policy_mobility_v05 as mobility_v05  # noqa: E402


class PolicyMobilityTests(unittest.TestCase):
    def test_variance_decomposition_separates_within_and_between(self) -> None:
        result = mobility.score_variance_by_class(
            [("a", 0.0), ("a", 2.0), ("b", 10.0), ("b", 10.0)]
        )
        scores = result["curation_score"]
        self.assertAlmostEqual(scores["population_variance_total"], 20.75)
        self.assertAlmostEqual(scores["population_variance_within_signature"], 0.5)
        self.assertAlmostEqual(scores["population_variance_between_signature"], 20.25)
        pairs = result["pairwise_rank_discrimination"]
        self.assertEqual(pairs["same_signature_pairs_with_strict_score_order"], 1)
        self.assertAlmostEqual(pairs["fraction_of_same_signature_pairs_with_strict_score_order"], 0.5)
        self.assertAlmostEqual(pairs["fraction_of_strict_score_pairs_within_signature"], 0.2)

    def test_signature_queue_merge_preserves_frozen_order(self) -> None:
        rows = [
            SimpleNamespace(group_id="g1", supervised_signature_sha256="s1"),
            SimpleNamespace(group_id="g2", supervised_signature_sha256="s1"),
            SimpleNamespace(group_id="g3", supervised_signature_sha256="s2"),
            SimpleNamespace(group_id="g4", supervised_signature_sha256="s3"),
        ]
        quotas = {"cell": 3}
        score = {"g1": 0.2, "g2": 0.9, "g3": 0.5, "g4": 0.8}
        for policy_name in ("random", "curated"):
            expected = sorted(rows, key=lambda row: mobility.frozen_key(row, score, policy_name))[:3]
            actual = mobility.select_by_signature_queues({"cell": rows}, quotas, score, policy_name)
            self.assertEqual([row.group_id for row in actual], [row.group_id for row in expected])

    def test_choose2_handles_empty_and_singleton_classes(self) -> None:
        self.assertEqual(mobility.choose2(0), 0)
        self.assertEqual(mobility.choose2(1), 0)
        self.assertEqual(mobility.choose2(5), 10)

    def test_axis_score_mean_matches_frozen_curation_score(self) -> None:
        features = (("a",), ("b", "c"), ("d",), ("e",), ("f", "g"))
        counts = [
            collections.Counter({feature: count for feature, count in zip(axis, (2, 8))})
            for axis in features
        ]
        axes = mobility.curation_axis_scores(features, counts)
        self.assertAlmostEqual(
            sum(axes) / len(axes),
            mobility.policy.curation_score(features, counts),
        )

    def test_hierarchical_variance_closes_across_all_levels(self) -> None:
        rows = [
            ("s1", "state1", "sig1", 0.0),
            ("s1", "state1", "sig1", 2.0),
            ("s1", "state1", "sig2", 4.0),
            ("s1", "state2", "sig3", 8.0),
            ("s2", "state3", "sig4", 10.0),
        ]
        result = mobility_v05.hierarchical_score_variance(iter(rows))
        population = result["population"]
        self.assertAlmostEqual(population["population_variance"], 13.76)
        self.assertAlmostEqual(sum(population["component_shares"].values()), 1.0)
        self.assertGreater(
            population["hierarchical_components"]["within_state_between_supervised_signatures"],
            0.0,
        )
        self.assertLess(population["closure_absolute_error"], 1e-12)
        for stratum in result["per_stratum"]:
            expected_share_sum = 1.0 if stratum["population_variance"] else 0.0
            self.assertAlmostEqual(sum(stratum["shares"].values()), expected_share_sum)

    def test_profile_preserving_cell_contains_only_declared_profile_axes(self) -> None:
        row = SimpleNamespace(
            stratum_id="stratum",
            input_state="state",
            root_id="root",
            family_items=(("world", "w1"),),
            topology=("chain",),
            intervention="reveal",
            kind="choice",
            view="closed",
            candidate_count=4,
            open_world=False,
            probability_source="exact",
            input_selector="selector-a",
            supervised_signature_sha256="sig-a",
        )
        same_profile_different_decision = SimpleNamespace(**{
            **row.__dict__,
            "input_selector": "selector-b",
            "supervised_signature_sha256": "sig-b",
        })
        self.assertEqual(
            mobility_v05.profile_preserving_cell(row),
            mobility_v05.profile_preserving_cell(same_profile_different_decision),
        )


if __name__ == "__main__":
    unittest.main()
