#!/usr/bin/env python3
"""Pre-model integrity and truth-table tests for R1 sensor preparation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare_sensor_qualification as prep  # noqa: E402
import run_sensor  # noqa: E402

DEFAULT_DATA = Path(
    r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor-qualification-v01\qualification-data-v02"
)
DEFAULT_PARENT = Path(
    r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage0-v01\construction-attempt-v02"
)


def independent_violation(clause: dict, assignment: list[int]) -> bool:
    kind, values = next(iter(clause.items()))
    if kind == "Same":
        return assignment[values["a"]] != assignment[values["b"]]
    if kind == "Different":
        return assignment[values["a"]] == assignment[values["b"]]
    if kind == "FixedRole":
        return assignment[values["entity"]] != values["role"]
    if kind == "ForbiddenRole":
        return assignment[values["entity"]] == values["role"]
    if kind == "ExactlyOneRole":
        return sum(assignment[e] == values["role"] for e in values["entities"]) != 1
    if kind == "ImpliesNotRole":
        return assignment[values["if_entity"]] == values["if_role"] and assignment[values["then_entity"]] == values["then_role"]
    raise AssertionError(f"unknown clause kind in independent test: {kind}")


class SensorPreparationTests(unittest.TestCase):
    def test_all_clause_truth_tables(self) -> None:
        self.assertFalse(independent_violation({"Same": {"a": 0, "b": 1}}, [0, 0]))
        self.assertTrue(independent_violation({"Same": {"a": 0, "b": 1}}, [0, 1]))
        self.assertFalse(independent_violation({"Different": {"a": 0, "b": 1}}, [0, 1]))
        self.assertTrue(independent_violation({"Different": {"a": 0, "b": 1}}, [0, 0]))
        self.assertFalse(independent_violation({"FixedRole": {"entity": 0, "role": 1}}, [1]))
        self.assertTrue(independent_violation({"ForbiddenRole": {"entity": 0, "role": 1}}, [1]))
        self.assertFalse(independent_violation({"ExactlyOneRole": {"entities": [0, 1], "role": 1}}, [1, 0]))
        self.assertTrue(independent_violation({"ExactlyOneRole": {"entities": [0, 1], "role": 1}}, [1, 1]))
        self.assertFalse(independent_violation({"ImpliesNotRole": {"if_entity": 0, "if_role": 1, "then_entity": 1, "then_role": 0}}, [1, 1]))
        self.assertTrue(independent_violation({"ImpliesNotRole": {"if_entity": 0, "if_role": 1, "then_entity": 1, "then_role": 0}}, [1, 0]))

    def test_singleton_exactly_one_renders_without_inventing_an_argument(self) -> None:
        clause = {"ExactlyOneRole": {"entities": [2], "role": 1}}
        for template in ("T0", "T1", "T2"):
            text, entities, roles, args = prep.render_clause(clause, prep.VOCABULARIES["V0"], template)
            self.assertTrue(text)
            self.assertEqual(entities, [2])
            self.assertEqual(roles, [1])
            self.assertEqual(args, {"entity_arg_0": 2, "role_arg_0": 1})

    def test_name_query_schema_rejects_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "names.jsonl"
            path.write_text(json.dumps({"name_id": "e0", "kind": "entities", "surface": "daxen"}) + "\n", encoding="utf-8")
            self.assertEqual(run_sensor.read_name_queries(path)[0]["surface"], "daxen")
            path.write_text(json.dumps({"name_id": "e0", "kind": "entities", "surface": "daxen", "label": 0}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_sensor.read_name_queries(path)

    def test_prepared_corpus_and_every_action_label_reconcile(self) -> None:
        if not DEFAULT_DATA.exists():
            self.skipTest(f"prepared corpus not present: {DEFAULT_DATA}")
        support = json.loads((DEFAULT_DATA / "SUPPORT-AUDIT.json").read_text(encoding="utf-8"))
        self.assertEqual(support["status"], "SUPPORT_PASS_PREMODEL")
        self.assertFalse(support["model_contact_performed"])
        public = prep.read_jsonl(DEFAULT_DATA / "public-probe-tasks.jsonl")
        targets = prep.read_jsonl(DEFAULT_DATA / "private-probe-targets.jsonl")
        actions = prep.read_jsonl(DEFAULT_DATA / "private-action-examples.jsonl")
        self.assertEqual(len(public), 320)
        self.assertEqual(len(targets), 320)
        self.assertEqual(len(actions), 55008)
        expected_public_fields = {
            "id", "family_id", "n", "k", "role_anonymous", "global_text", "clauses", "entity_mentions", "role_mentions"
        }
        for row in public:
            self.assertEqual(set(row), expected_public_fields)
        self.assertEqual(
            {row["eval_condition"] for row in targets if row["split"] == "evaluation"},
            {"id_seen", "template_ood", "vocabulary_ood", "joint_ood"},
        )
        private_tasks = {
            row["id"]: row
            for row in prep.read_jsonl(DEFAULT_PARENT / "private-tasks.jsonl")
        }
        counts: Counter[tuple[str, str]] = Counter()
        for row in actions:
            task = private_tasks[row["task_id"]]
            assignment = row["assignment"]
            before = sum(independent_violation(clause, assignment) for clause in task["clauses"])
            edited = assignment.copy()
            edited[row["edit_entity"]] = row["new_role"]
            after = sum(independent_violation(clause, edited) for clause in task["clauses"])
            delta = after - before
            label = "improve" if delta < 0 else "neutral" if delta == 0 else "worsen"
            self.assertEqual(row["violations_before"], before)
            self.assertEqual(row["delta_violations"], delta)
            self.assertEqual(row["target_sign"], label)
            counts[row["split"], label] += 1
        self.assertEqual(dict(counts), {
            ("train", "worsen"): 7661,
            ("train", "improve"): 7766,
            ("train", "neutral"): 11741,
            ("validation", "improve"): 2449,
            ("validation", "worsen"): 2611,
            ("validation", "neutral"): 3708,
            ("evaluation", "worsen"): 5411,
            ("evaluation", "neutral"): 8105,
            ("evaluation", "improve"): 5556,
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)
