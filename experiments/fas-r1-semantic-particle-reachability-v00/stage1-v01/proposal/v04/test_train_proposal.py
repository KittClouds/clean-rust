from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("train_proposal.py")
SPEC = importlib.util.spec_from_file_location("r1_v04_proposal_test_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
TRAINER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRAINER)


def support_manifest() -> dict:
    roster = []
    for split, count in TRAINER.SPLIT_COUNTS.items():
        split_code = {"train": "tr", "validation": "va", "qualification": "qu"}[split]
        for index in range(count):
            task_id = f"task-{split_code}-{index:02}"
            roster.append(
                {"task_id": task_id, "family_id": f"family-{task_id}", "split": split}
            )
    return {
        "schema": TRAINER.SUPPORT_SCHEMA,
        "status": "STRESS_TRAIN_VALIDATION_QUALIFICATION_READY",
        "split_counts": dict(TRAINER.SPLIT_COUNTS),
        "family_roster": roster,
    }


def teacher_row(task_id: str, split: str, family_id: str, state_index: int = 0) -> dict:
    assignment = [index % TRAINER.N_ROLES for index in range(TRAINER.N_ENTITIES)]
    edits = []
    first = True
    for entity, old_role in enumerate(assignment):
        for new_role in range(TRAINER.N_ROLES):
            if new_role == old_role:
                continue
            improved = int(first)
            edits.append(
                {
                    "entity": entity,
                    "new_role": new_role,
                    "n_improved_classes": improved,
                    "delta_d_min": -1 if first else 0,
                    "q_probability": float(improved),
                }
            )
            first = False
    return {
        "schema": "r1-proposal-teacher-sample-v01",
        "task_id": task_id,
        "family_id": family_id,
        "family_split": split,
        "state_index": state_index,
        "assignment": assignment,
        "raw_solution_count": TRAINER.RAW_SOLUTION_COUNT,
        "canonical_solution_class_count": TRAINER.CANONICAL_CLASS_COUNT,
        "target": {
            "schema": "r1-class-balanced-one-step-teacher-v01",
            "task_id": task_id,
            "outcome": "positive_mass",
            "class_count": TRAINER.CANONICAL_CLASS_COUNT,
            "minimum_distance_before": 5,
            "total_improved_class_mass": 1,
            "edits": edits,
        },
    }


class V04ProposalContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = support_manifest()
        self.task_split = TRAINER.validate_support_manifest(self.manifest)
        self.task_family = {
            row["task_id"]: row["family_id"] for row in self.manifest["family_roster"]
        }

    def train_validation_rows(self) -> list[dict]:
        return [
            teacher_row(task_id, split, self.task_family[task_id])
            for task_id, split in self.task_split.items()
            if split in ("train", "validation")
        ]

    def test_exact_v04_roster_and_expected_teacher_row_counts(self) -> None:
        counts = TRAINER.validate_teacher_rows(
            self.train_validation_rows(), self.task_split, 1, self.task_family
        )
        self.assertEqual(counts, {"train": 64, "validation": 16, "qualification": 0})

    def test_manifest_rejects_split_count_drift(self) -> None:
        changed = copy.deepcopy(self.manifest)
        changed["split_counts"]["train"] -= 1
        with self.assertRaisesRegex(ValueError, "split counts changed"):
            TRAINER.validate_support_manifest(changed)

    def test_qualification_target_is_rejected(self) -> None:
        rows = self.train_validation_rows()
        qualification_id = next(
            task_id for task_id, split in self.task_split.items() if split == "qualification"
        )
        qualification_row = teacher_row(
            qualification_id,
            "qualification",
            self.task_family[qualification_id],
        )
        rows[0] = qualification_row
        with self.assertRaisesRegex(ValueError, "qualification teacher target is forbidden"):
            TRAINER.validate_teacher_rows(rows, self.task_split, 1, self.task_family)

    def test_teacher_requires_nine_classes_and_class_balanced_q(self) -> None:
        rows = self.train_validation_rows()
        rows[0]["canonical_solution_class_count"] = 8
        with self.assertRaisesRegex(ValueError, "canonical solution class count"):
            TRAINER.validate_teacher_rows(rows, self.task_split, 1, self.task_family)

        rows = self.train_validation_rows()
        rows[0]["target"]["edits"][0]["q_probability"] = 0.5
        with self.assertRaisesRegex(ValueError, "not proportional"):
            TRAINER.validate_teacher_rows(rows, self.task_split, 1, self.task_family)

    def test_zero_mass_state_is_retained_as_explicit_zero_distribution(self) -> None:
        rows = self.train_validation_rows()
        target = rows[0]["target"]
        target["outcome"] = "zero_mass"
        target["total_improved_class_mass"] = 0
        for edit in target["edits"]:
            edit["n_improved_classes"] = 0
            edit["delta_d_min"] = 0
            edit["q_probability"] = 0.0
        counts = TRAINER.validate_teacher_rows(
            rows, self.task_split, 1, self.task_family
        )
        self.assertEqual(counts["qualification"], 0)

    def test_teacher_source_and_shared_routine_pins(self) -> None:
        records = TRAINER.verify_source_pins()
        self.assertEqual(set(records), set(TRAINER.SOURCE_PINS))

    def test_renderer_seed_diagnostics_bind_to_public_roster(self) -> None:
        public_by_id = {}
        world_rows = []
        for index, roster_row in enumerate(self.manifest["family_roster"]):
            task_id = roster_row["task_id"]
            public_by_id[task_id] = {
                "id": task_id,
                "family_id": roster_row["family_id"],
                "n": TRAINER.N_ENTITIES,
                "k": TRAINER.N_ROLES,
                "clauses": [{} for _ in range(36)],
            }
            world_rows.append(
                {
                    "task_id": task_id,
                    "family_id": roster_row["family_id"],
                    "seed": 1000 + index,
                    "n": TRAINER.N_ENTITIES,
                    "k": TRAINER.N_ROLES,
                    "edge_count": 36,
                    "raw_solution_count": TRAINER.RAW_SOLUTION_COUNT,
                    "canonical_solution_class_count": TRAINER.CANONICAL_CLASS_COUNT,
                    "role_automorphism_count": 6,
                    "role_anonymous": True,
                }
            )
        digest = TRAINER.validate_generation_world_roster(world_rows, public_by_id)
        self.assertEqual(len(digest), 64)

        world_rows[0]["seed"] = "1000"
        with self.assertRaisesRegex(ValueError, "seed/solution diagnostics"):
            TRAINER.validate_generation_world_roster(world_rows, public_by_id)

    def test_private_view_contains_exact_train_validation_ids_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r1-v04-private-view-") as temp_dir:
            root = Path(temp_dir)
            source_path = root / "private-source.jsonl"
            output_path = root / "artifact" / "private-tasks-trainval-v04.jsonl"
            source_rows = []
            for index, roster_row in enumerate(self.manifest["family_roster"]):
                row = {
                    "id": roster_row["task_id"],
                    "family_id": roster_row["family_id"],
                    "seed": index,
                }
                if roster_row["split"] == "qualification":
                    row["qualification_only_fixture_marker"] = f"held-out-{index}"
                source_rows.append(row)
            source_path.write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in source_rows),
                encoding="utf-8",
            )

            record = TRAINER.write_trainval_private_view(
                source_path, self.task_split, output_path, self.task_family
            )
            output_rows = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            ]
            expected_ids = {
                task_id
                for task_id, split in self.task_split.items()
                if split in ("train", "validation")
            }
            self.assertEqual(len(output_rows), 80)
            self.assertEqual({row["id"] for row in output_rows}, expected_ids)
            self.assertTrue(
                all("qualification_only_fixture_marker" not in row for row in output_rows)
            )
            self.assertEqual(record["rows"], 80)
            self.assertEqual(record["split_counts"], {"train": 64, "validation": 16})
            self.assertEqual(record["qualification_rows_omitted"], 16)
            self.assertEqual(record["source_private_sha256"], TRAINER.file_record(source_path)["sha256"])
            self.assertEqual(record["sha256"], TRAINER.file_record(output_path)["sha256"])


if __name__ == "__main__":
    unittest.main()
