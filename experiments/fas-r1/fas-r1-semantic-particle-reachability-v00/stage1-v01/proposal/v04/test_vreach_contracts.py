"""Focused offline contracts for the V04 V_reach request/refit boundary."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import refit_vreach as REFIT  # noqa: E402
import vreach_requests as REQUESTS  # noqa: E402


def roster_fixture() -> tuple[list[dict], dict]:
    public = []
    family_roster = []
    for index in range(96):
        task_id = f"task-{index:03}"
        split = "train" if index < 64 else "validation" if index < 80 else "qualification"
        public.append({"id": task_id, "family_id": f"family-{index:03}", "n": 20, "k": 3})
        family_roster.append({"task_id": task_id, "family_id": f"family-{index:03}", "split": split})
    support = {
        "schema": REQUESTS.SUPPORT_SCHEMA,
        "split_counts": dict(REQUESTS.SPLIT_COUNTS),
        "family_roster": family_roster,
    }
    return public, support


def start_fixture() -> list[dict]:
    public, support = roster_fixture()
    _, split_by_task = REQUESTS.validate_split_roster(public, support)
    rows = []
    for task_id, split in split_by_task.items():
        if split == "qualification":
            continue
        for state_index in range(32):
            source_kind = "uniform" if state_index < 16 else "solution_neighborhood"
            rows.append(
                {
                    "schema": "r1-vreach-stress-start-v04-v01",
                    "task_id": task_id,
                    "family_split": split,
                    "state_index": state_index,
                    "assignment": [state_index % 3 for _ in range(20)],
                    "source_kind": source_kind,
                }
            )
    return rows


def private_lineage_fixture(sidecar_sha: str = "c" * 64, sidecar_bytes: int = 123) -> dict:
    return {
        "file": REQUESTS.PRIVATE_TRAINVAL_FILENAME,
        "rows": 80,
        "split_counts": {"train": 64, "validation": 16},
        "sha256": sidecar_sha,
        "bytes": sidecar_bytes,
        "qualification_rows_omitted": 16,
        "source_private_sha256": REQUESTS.PRIVATE_WORLD_SHA256_V04,
    }


def proposal_receipt_fixture() -> dict:
    private = private_lineage_fixture()
    return {
        "schema": REQUESTS.PROPOSAL_RECEIPT_SCHEMA,
        "status": "R1_V04_PROPOSAL_FIT_COMPLETE",
        "proposal": {
            "weights_sha256": "a" * 64,
            "weights_file": REQUESTS.PROPOSAL_FILENAME,
            "architecture": REQUESTS.PROPOSAL_ARCHITECTURE,
            "frozen_identity_sha256": REQUESTS.IDENTITY_SHA256,
            "identity_receipt_sha256": "b" * 64,
        },
        "world_bundle": {"private_sha256": REQUESTS.PRIVATE_WORLD_SHA256_V04},
        "private_trainval": private,
        "output_files": {
            REQUESTS.PROPOSAL_FILENAME: {
                "path": str(HERE / REQUESTS.PROPOSAL_FILENAME),
                "sha256": "a" * 64,
                "bytes": 456,
            },
            REQUESTS.PRIVATE_TRAINVAL_FILENAME: {
                "path": str(HERE / REQUESTS.PRIVATE_TRAINVAL_FILENAME),
                "sha256": private["sha256"],
                "bytes": private["bytes"],
            }
        },
    }


class V04VReachContracts(unittest.TestCase):
    def test_v04_roster_is_exactly_64_16_16(self) -> None:
        public, support = roster_fixture()
        _, split_by_task = REQUESTS.validate_split_roster(public, support)
        self.assertEqual(len(split_by_task), 96)
        support["split_counts"]["qualification"] = 15
        with self.assertRaisesRegex(ValueError, "64/16/16"):
            REQUESTS.validate_split_roster(public, support)

    def test_private_sidecar_must_be_exact_trainval_ids_only(self) -> None:
        public, support = roster_fixture()
        _, split_by_task = REQUESTS.validate_split_roster(public, support)
        trainval = [
            {"id": task_id}
            for task_id, split in split_by_task.items()
            if split in ("train", "validation")
        ]
        self.assertEqual(len(REQUESTS.validate_private_trainval_rows(trainval, split_by_task)), 80)
        trainval[-1] = {"id": "task-080"}
        with self.assertRaisesRegex(ValueError, "exactly match"):
            REQUESTS.validate_private_trainval_rows(trainval, split_by_task)

    def test_start_states_require_all_80_tasks_and_no_qualification(self) -> None:
        public, support = roster_fixture()
        public_by_id, split_by_task = REQUESTS.validate_split_roster(public, support)
        rows = start_fixture()
        grouped = REQUESTS.validate_start_rows(rows, public_by_id, split_by_task)
        self.assertEqual(len(grouped), 80)
        qualification = dict(rows[0])
        qualification["task_id"] = "task-080"
        qualification["family_split"] = "qualification"
        with self.assertRaisesRegex(ValueError, "qualification start row"):
            REQUESTS.validate_start_rows(rows + [qualification], public_by_id, split_by_task)

    def test_start_state_contract_rejects_missing_row(self) -> None:
        public, support = roster_fixture()
        public_by_id, split_by_task = REQUESTS.validate_split_roster(public, support)
        rows = start_fixture()
        with self.assertRaisesRegex(ValueError, "exactly 80.*32"):
            REQUESTS.validate_start_rows(rows[:-1], public_by_id, split_by_task)

    def test_proposal_receipt_binds_checkpoint_identity_and_trainval_artifact(self) -> None:
        receipt = proposal_receipt_fixture()
        private_record = {"path": str(HERE / REQUESTS.PRIVATE_TRAINVAL_FILENAME), "sha256": "c" * 64, "bytes": 123}
        proposal_record = {"path": str(HERE / REQUESTS.PROPOSAL_FILENAME), "sha256": "a" * 64, "bytes": 456}
        receipt["output_files"][REQUESTS.PRIVATE_TRAINVAL_FILENAME]["path"] = private_record["path"]
        lineage = REQUESTS.verify_proposal_receipt(receipt, proposal_record, "a" * 64, private_record, 80)
        self.assertEqual(lineage["weights_sha256"], "a" * 64)
        receipt["world_bundle"]["private_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "full V04 private source"):
            REQUESTS.verify_proposal_receipt(receipt, proposal_record, "a" * 64, private_record, 80)

    def test_start_receipt_binds_trainval_and_proposal_receipts(self) -> None:
        receipt = {
            "schema": "FAS_R1_VREACH_STARTS_V04_V01",
            "status": "STRESS_VREACH_STARTS_COMPLETE",
            "analysis_mode": "ADAPTIVE_ENGINEERING",
            "qualification_previously_opened": True,
            "scientific_confirmation_eligible": False,
            "start_states_sha256": "a" * 64,
            "qualification_private_rows_opened": False,
            "qualification_states_consumed": False,
            "qualification_targets_consumed": False,
            "private_trainval_sha256": "b" * 64,
            "proposal_fit_receipt_sha256": "c" * 64,
        }
        REQUESTS.verify_start_receipt(receipt, "a" * 64, "b" * 64, "c" * 64)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            REQUESTS.verify_start_receipt(receipt, "a" * 64, "d" * 64, "c" * 64)

    def test_vreach_labels_reject_qualification_or_wrong_proposal(self) -> None:
        public, support = roster_fixture()
        _, split_by_task = REQUESTS.validate_split_roster(public, support)
        expected = {task_id for task_id, split in split_by_task.items() if split != "qualification"}
        dataset = {
            "schema": "r1-v-reach-label-dataset-v01",
            "task_id": "task-000",
            "proposal_sha256": "f" * 64,
            "states": [{
                "schema": "r1-v-reach-rollout-label-v01",
                "task_id": "task-000",
                "proposal_sha256": "f" * 64,
                "rollouts": [{"proposal_sha256": "f" * 64}],
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            labels = Path(temporary) / "labels.jsonl"
            labels.write_text(json.dumps(dataset) + "\n", encoding="utf-8")
            REFIT.validate_label_rows(labels, {"task-000"}, split_by_task, "f" * 64)
            dataset["task_id"] = "task-080"
            labels.write_text(json.dumps(dataset) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "qualification V_reach labels"):
                REFIT.validate_label_rows(labels, expected, split_by_task, "f" * 64)
            dataset["task_id"] = "task-000"
            dataset["proposal_sha256"] = "e" * 64
            labels.write_text(json.dumps(dataset) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected proposal hash"):
                REFIT.validate_label_rows(labels, {"task-000"}, split_by_task, "f" * 64)
            dataset["proposal_sha256"] = "f" * 64
            dataset["schema"] = "unexpected"
            labels.write_text(json.dumps(dataset) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected dataset schema"):
                REFIT.validate_label_rows(labels, {"task-000"}, split_by_task, "f" * 64)
            dataset["schema"] = "r1-v-reach-label-dataset-v01"
            dataset["states"][0]["schema"] = "unexpected"
            labels.write_text(json.dumps(dataset) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected label schema"):
                REFIT.validate_label_rows(labels, {"task-000"}, split_by_task, "f" * 64)
            dataset["states"][0]["schema"] = "r1-v-reach-rollout-label-v01"
            dataset["states"][0]["proposal_sha256"] = "e" * 64
            labels.write_text(json.dumps(dataset) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "state.*unexpected proposal hash"):
                REFIT.validate_label_rows(labels, {"task-000"}, split_by_task, "f" * 64)


if __name__ == "__main__":
    unittest.main()
