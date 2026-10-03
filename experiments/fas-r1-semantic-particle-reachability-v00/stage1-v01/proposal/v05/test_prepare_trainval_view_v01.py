from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_trainval_view_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v05_trainval_view_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VIEW)


def _bytes(rows: list[dict]) -> bytes:
    return b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)


def _bundle(root: Path, *, cross_split_pair: bool = False) -> Path:
    bundle = root / "bundle"
    bundle.mkdir()
    roster = []
    worlds = []
    private_rows = []
    public_rows = []
    for pair in range(24):
        split = "train" if pair < 16 else "validation" if pair < 20 else "qualification"
        for variant, scenario in enumerate(sorted(VIEW.SCENARIOS)):
            task_id = f"task-{pair:02}-{variant}"
            family_id = f"family-{task_id}"
            task_split = split
            if cross_split_pair and pair == 0 and variant == 3:
                task_split = "validation"
            roster.append({
                "task_id": task_id,
                "family_id": family_id,
                "paired_world_id": f"pair-{pair:02}",
                "scenario_id": scenario,
                "split": task_split,
            })
            worlds.append({
                "task_id": task_id,
                "paired_world_id": f"pair-{pair:02}",
                "scenario_id": scenario,
                "split": task_split,
                "seed": pair + 100,
            })
            private_rows.append({"id": task_id, "family_id": family_id, "clauses": []})
            public_rows.append({"id": task_id, "family_id": family_id, "clauses": []})

    private = _bytes(private_rows)
    public = _bytes(public_rows)
    starts = b"{}\n"
    diagnostics = b"{}\n"
    config = b"{}\n"
    support = {
        "schema": VIEW.SUPPORT_SCHEMA,
        "status": "STRESS_TRAIN_VALIDATION_QUALIFICATION_READY",
        "source": {
            "path": "public-tasks.jsonl",
            "sha256": hashlib.sha256(public).hexdigest(),
            "bytes": len(public),
            "rows": 96,
        },
        "search_starts": {
            "sha256": hashlib.sha256(starts).hexdigest(),
            "bytes": len(starts),
        },
        "split_counts": VIEW.SPLITS,
        "paired_world_count": 24,
        "family_roster": roster,
    }
    paths = {
        "private-tasks.jsonl": private,
        "public-tasks.jsonl": public,
        "public-search-starts-v05.jsonl": starts,
        "private-diagnostics.jsonl": diagnostics,
        "stress-support-manifest-v05-1.json": (json.dumps(support) + "\n").encode(),
        "stress-config-v05.json": config,
    }
    for name, data in paths.items():
        (bundle / name).write_bytes(data)
    outputs = [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        for name, data in paths.items()
    ]
    generation = {
        "schema": VIEW.WORLD_SCHEMA,
        "status": "STRESS_GENERATION_COMPLETE",
        "source_identity": VIEW.SOURCE_IDENTITY,
        "accepted_worlds": 96,
        "lfm_or_model_contact_performed": False,
        "probe_or_training_performed": False,
        "output_hashes": outputs,
        "worlds": worlds,
    }
    (bundle / "private-generation-receipt-v05-1.json").write_text(json.dumps(generation))
    return bundle


class TrainValidationViewTests(unittest.TestCase):
    def test_emits_only_train_and_validation_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = _bundle(root)
            receipt = VIEW.prepare(bundle, root / "view")
            self.assertEqual(receipt["private_task_view_split_counts"], {"train": 64, "validation": 16})
            self.assertEqual(receipt["public_task_view_split_counts"], {"train": 64, "validation": 16})
            self.assertEqual(receipt["qualification_rows_emitted"], 0)
            self.assertFalse(receipt["qualification_targets_generated"])
            self.assertFalse(receipt["qualification_target_paths_or_hashes_recorded"])
            view = root / "view"
            for name in ("private-tasks-trainval-v05.jsonl", "public-tasks-trainval-v05.jsonl"):
                rows = VIEW.parse_jsonl((view / name).read_bytes(), name)
                self.assertEqual(len(rows), 80)
                self.assertFalse(any("qualification" in row for row in rows))
            support = json.loads((view / "stress-support-trainval-v05.json").read_text())
            self.assertEqual(support["split_counts"], {"train": 64, "validation": 16})
            self.assertEqual(len(support["family_roster"]), 80)

    def test_rejects_pair_split_crossing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "crosses"):
                VIEW.prepare(_bundle(root, cross_split_pair=True), root / "view")


if __name__ == "__main__":
    unittest.main()
