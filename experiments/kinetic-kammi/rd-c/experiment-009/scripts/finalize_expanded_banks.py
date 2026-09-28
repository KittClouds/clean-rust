from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
DEV = ROOT / "tasks" / "expanded" / "dev-bank-v4"
HELDOUT = ROOT / "tasks" / "expanded" / "heldout-bank-v5"
PILOT = ROOT / "tasks" / "frames" / "frame-lock.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    dev_lock = read_json(DEV / "frame-lock.json")
    heldout_lock = read_json(HELDOUT / "frame-lock.json")
    dev_ids = [item["frame"]["task_id"] for item in dev_lock["frames"]]
    heldout_ids = [item["frame"]["task_id"] for item in heldout_lock["frames"]]
    dev_families = sorted({item["frame"]["task_family"] for item in dev_lock["frames"]})
    heldout_families = sorted({item["frame"]["task_family"] for item in heldout_lock["frames"]})
    pilot_families = {
        item["frame"]["task_family"] for item in read_json(PILOT)["frames"]
    }
    if set(dev_families) & set(heldout_families):
        raise SystemExit("development and held-out task families overlap")
    if set(pilot_families) & set(heldout_families):
        raise SystemExit("held-out families overlap previously scored pilot families")
    if set(pilot_families) & set(dev_families):
        raise SystemExit("development families overlap previously scored pilot families")

    for root, role, other, family_list in (
        (DEV, "development", "heldout", heldout_families),
        (HELDOUT, "heldout", "development", dev_families),
    ):
        receipt_path = root / "bank-build-receipt.json"
        receipt = read_json(receipt_path)
        receipt["bank_role"] = role
        receipt["selection_method"] = (
            "task families and existing exact unit tests selected from a frozen product commit before observer output; "
            "candidate mutations were specified against those contracts and test pass/fail outcomes"
        )
        receipt["task_family_split"] = {
            role: sorted({item["frame"]["task_family"] for item in read_json(root / "frame-lock.json")["frames"]}),
            other: family_list,
            "unit": "task family; all development and held-out tasks are from one frozen product repository",
        }
        write_json(receipt_path, receipt)

    labels = read_json(DEV / "sealed-labels.json")["tasks"]
    heldout_labels = read_json(HELDOUT / "sealed-labels.json")["tasks"]
    if set(labels) != set(dev_ids) or set(heldout_labels) != set(heldout_ids):
        raise SystemExit("sealed label IDs do not match the frozen task lists")
    if len(dev_ids) != 8 or len(heldout_ids) != 8 or len(dev_families) != 4 or len(heldout_families) != 4:
        raise SystemExit("expected eight tasks in each bank across four task families")

    split = {
        "schema_version": 1,
        "source_repository_revision": "9a88547372cd35f8dc31f026f0cd8dd8fca8e641",
        "source_repository": "C:/code land/clean-rust/phoenix-native/crates/gpui-animated-gradient-text",
        "selection_method": "pre-existing targeted unit-test families and controlled candidate mutations; selected before observer output",
        "development": {
            "families": dev_families,
            "task_ids": dev_ids,
            "frame_lock_sha256": sha256(DEV / "frame-lock.json"),
            "candidate_lock_sha256": sha256(DEV / "candidate-lock.json"),
            "label_file_sha256": sha256(DEV / "sealed-labels.json"),
        },
        "heldout": {
            "families": heldout_families,
            "task_ids": heldout_ids,
            "frame_lock_sha256": sha256(HELDOUT / "frame-lock.json"),
            "candidate_lock_sha256": sha256(HELDOUT / "candidate-lock.json"),
            "label_file_sha256": sha256(HELDOUT / "sealed-labels.json"),
        },
        "previously_scored_pilot_families_excluded": sorted(pilot_families),
        "family_disjointness_verified": True,
        "repository_holdout": False,
        "scope_limit": "task-family transfer within one product repository; no cross-repository generalization claim",
    }
    write_json(ROOT / "tasks" / "expanded" / "split-manifest.json", split)
    print(f"development={len(dev_ids)} heldout={len(heldout_ids)}; four disjoint families per bank; pilot families excluded")


if __name__ == "__main__":
    main()
