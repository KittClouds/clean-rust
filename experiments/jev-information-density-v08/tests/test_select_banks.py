from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "select_banks.py"
SPEC = importlib.util.spec_from_file_location("jev_v08_select_banks", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def group(index: int, family: int | None = None) -> MODULE.Group:
    family = index if family is None else family
    features = tuple(
        (f"axis-{axis}-bucket-{index % (axis + 2)}",)
        for axis in range(len(MODULE.COVERAGE_AXES))
    )
    return MODULE.Group(
        group_id=f"g-{index:04d}",
        episode_id=f"e-{index:04d}",
        root_id=f"root-{family:04d}",
        families=tuple(
            (axis, f"{axis}-{family:04d}")
            for axis in MODULE.FAMILY_AXES
        ),
        strata=(f"world-{family % 3}", "choice", "4", f"h-{index % 5}"),
        features=features,
        overlap_keys=(
            f"episode:e-{index:04d}",
            f"model_input:input-{index:04d}",
            f"gold_target:gold-{index:04d}",
        ),
        split_family_bundle_id=f"bundle-{family:04d}",
        posterior_entropy_nats=(index % 10) / 5.0,
    )


class SelectorTests(unittest.TestCase):
    def test_random_selection_is_exact_and_repeatable(self) -> None:
        rows = [group(index) for index in range(50)]
        first = MODULE.select_random(rows, 20)
        second = MODULE.select_random(rows, 20)
        self.assertEqual([row.group_id for row in first], [row.group_id for row in second])
        self.assertEqual(len(first), 20)
        self.assertEqual(len({row.group_id for row in first}), 20)

    def test_curated_selection_is_exact_and_repeatable(self) -> None:
        rows = [group(index) for index in range(40)]
        first = MODULE.select_curated(rows, 12)
        second = MODULE.select_curated(rows, 12)
        self.assertEqual([row.group_id for row in first], [row.group_id for row in second])
        self.assertEqual(len(first), 12)
        self.assertEqual(len({row.group_id for row in first}), 12)
        self.assertGreater(len({row.root_id for row in first}), 1)

    def test_curated_ranking_prefers_globally_rare_features(self) -> None:
        common_features = tuple((f"common-{axis}",) for axis in range(len(MODULE.COVERAGE_AXES)))
        rare_features = tuple((f"rare-{axis}",) for axis in range(len(MODULE.COVERAGE_AXES)))
        rows = [
            replace(group(index), features=common_features)
            for index in range(1, 10)
        ]
        rows.append(replace(group(0), features=rare_features))
        selected = MODULE.select_curated(rows, 1)
        self.assertEqual(selected[0].group_id, "g-0000")

    def test_family_assignment_keeps_all_linked_groups_together(self) -> None:
        rows = [group(index, family=index // 2) for index in range(200)]
        train, evaluation, report = MODULE.split_families(rows)
        train_bundles = {row.split_family_bundle_id for row in train}
        eval_bundles = {row.split_family_bundle_id for row, _axes in evaluation}
        self.assertTrue(train_bundles.isdisjoint(eval_bundles))
        self.assertTrue(report["split_family_bundle"]["held_out_bundle_count"] > 0)
        for axis in MODULE.FAMILY_AXES:
            train_families = {dict(row.families)[axis] for row in train}
            eval_families = {dict(row.families)[axis] for row, _axes in evaluation}
            self.assertTrue(train_families.isdisjoint(eval_families))
            self.assertTrue(report[axis]["available"])

    def test_component_family_cannot_cross_bundles(self) -> None:
        first = group(0, family=0)
        second = group(1, family=1)
        second = MODULE.Group(
            group_id=second.group_id,
            episode_id=second.episode_id,
            root_id=second.root_id,
            families=((MODULE.FAMILY_AXES[0], dict(first.families)[MODULE.FAMILY_AXES[0]]),)
            + second.families[1:],
            strata=second.strata,
            features=second.features,
            overlap_keys=second.overlap_keys,
            split_family_bundle_id=second.split_family_bundle_id,
            posterior_entropy_nats=second.posterior_entropy_nats,
        )
        with self.assertRaisesRegex(ValueError, "family value crosses split bundles"):
            MODULE.split_families([first, second])

    def test_group_parser_rejects_model_output_fields(self) -> None:
        row = {
            "group_id": "g-1",
            "episode_id": "e-1",
            "root_id": "r-1",
            "valid": True,
            "family_ids": {},
            "strata": {
                "world_family": "w",
                "query_view_type": "choice",
                "candidate_cardinality_bin": "4",
                "posterior_entropy_quintile": "q1",
            },
            "coverage_features": {
                axis: [f"{axis}-x"] for axis in MODULE.COVERAGE_AXES
            },
            "overlap_keys": [],
            "split_family_bundle_id": "bundle-1",
            "posterior_entropy_nats": 0.5,
            "model_score": 0.99,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "groups.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"extra=\['model_score'\]"):
                MODULE.read_group_records(path)

    def test_group_parser_adds_model_input_to_redundancy_features(self) -> None:
        source = group(1)
        row = {
            "group_id": source.group_id,
            "episode_id": source.episode_id,
            "root_id": source.root_id,
            "valid": True,
            "family_ids": dict(source.families),
            "strata": dict(zip(MODULE.STRATUM_FIELDS, source.strata)),
            "coverage_features": {
                axis: list(values)
                for axis, values in zip(MODULE.COVERAGE_AXES, source.features)
            },
            "overlap_keys": list(source.overlap_keys),
            "split_family_bundle_id": source.split_family_bundle_id,
            "posterior_entropy_nats": source.posterior_entropy_nats,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "groups.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            parsed = MODULE.read_group_records(path)[0]
        self.assertIn("input:input-0001", parsed.features[4])

    def test_identical_input_with_identical_gold_is_allowed(self) -> None:
        first = group(1)
        second = replace(
            group(2),
            overlap_keys=("episode:e-2", "model_input:same", "gold_target:same-gold"),
        )
        third = replace(
            group(3),
            overlap_keys=("episode:e-3", "model_input:same", "gold_target:same-gold"),
        )
        report = MODULE.audit_input_target_consistency([first, second, third])
        self.assertEqual(report["conflicting_model_input_count"], 0)
        self.assertEqual(report["duplicate_input_occurrence_count"], 1)

    def test_identical_input_with_different_gold_fails_consistency_gate(self) -> None:
        first = replace(
            group(1),
            overlap_keys=("episode:e-1", "model_input:same", "gold_target:gold-a"),
        )
        second = replace(
            group(2),
            overlap_keys=("episode:e-2", "model_input:same", "gold_target:gold-b"),
        )
        report = MODULE.audit_input_target_consistency([first, second])
        self.assertEqual(report["conflicting_model_input_count"], 1)
        self.assertEqual(report["max_gold_signatures_per_input"], 2)

    def test_collision_report_counts_groups_by_key_type_without_exposing_values(self) -> None:
        first = replace(
            group(1),
            overlap_keys=("episode:e-1", "text:private-digest", "model_input:private-input"),
        )
        second = replace(
            group(2),
            overlap_keys=("episode:e-2", "text:private-digest"),
        )
        report = MODULE.collision_report([first, second], {"text:private-digest", "model_input:private-input"})
        self.assertEqual(report["collision_group_count"], 2)
        self.assertEqual(report["collision_groups_by_key_type"], {"model_input": 1, "text": 2})
        self.assertNotIn("private-digest", json.dumps(report))
        self.assertNotIn("private-input", json.dumps(report))

    def test_topology_coverage_reads_only_structural_features(self) -> None:
        first = replace(group(1), features=((), (), (), ("topology:chain",), ()))
        second = replace(group(2), features=((), (), (), ("topology:collider",), ()))
        self.assertEqual(
            MODULE.topology_coverage([first, second]),
            {"chain": 1, "collider": 1},
        )

if __name__ == "__main__":
    unittest.main()
