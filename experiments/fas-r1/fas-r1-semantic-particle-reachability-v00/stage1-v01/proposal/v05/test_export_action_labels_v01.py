from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("export_action_labels_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v05_action_label_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
LABELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LABELS)


class ActionLabelTests(unittest.TestCase):
    def test_exact_constraint_delta_handles_supported_clause_variants(self) -> None:
        task = {
            "clauses": [
                {"Different": {"a": 0, "b": 1}},
                {"Same": {"a": 1, "b": 2}},
                {"FixedRole": {"entity": 0, "role": 0}},
                {"ForbiddenRole": {"entity": 2, "role": 1}},
                {"ExactlyOneRole": {"entities": [0, 1, 2], "role": 1}},
                {"ImpliesNotRole": {"if_entity": 0, "if_role": 0, "then_entity": 1, "then_role": 1}},
            ]
        }
        self.assertEqual(LABELS.satisfied_count(task, [0, 1, 2]), 4)
        self.assertEqual(LABELS.satisfied_count(task, [1, 1, 2]), 2)

    def test_qualification_teacher_row_is_rejected_before_action_labeling(self) -> None:
        tasks = [{"id": f"t{i}", "family_id": f"f{i}", "n": 20, "k": 3, "clauses": []} for i in range(80)]
        split = {task["id"]: "train" for task in tasks}
        teacher = [{"task_id": "t0", "family_id": "f0", "family_split": "qualification"}]
        with self.assertRaisesRegex(ValueError, "forbidden split"):
            LABELS.build_action_rows(tasks, teacher, split)


if __name__ == "__main__":
    unittest.main()
