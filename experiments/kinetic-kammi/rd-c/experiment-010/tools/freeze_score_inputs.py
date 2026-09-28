from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "e010-20260925-cross-repo-01"
RUN = ROOT / "artifacts" / "runs" / RUN_ID
BANK = ROOT / "tasks" / "heldout-bank-v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    input_lock_path = RUN / "frozen-input-lock.json"
    input_lock = read_json(input_lock_path)
    frame_lock_path = BANK / "frame-lock.json"
    frame_count = len(read_json(frame_lock_path)["frames"])
    if input_lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT" or frame_count != 16:
        raise SystemExit("precontact observer lock or task count is invalid")
    small_dir = RUN / "heldout-shadow-small"
    large_dir = RUN / "heldout-shadow-large"
    expected_names = {item["frame"]["task_id"] + ".json" for item in read_json(frame_lock_path)["frames"]}
    for role, directory in (("small", small_dir), ("large", large_dir)):
        names = {path.name for path in directory.glob("*.json")}
        if names != expected_names:
            raise SystemExit(f"{role} observer output set does not match the frozen frame set")
        for path in directory.glob("*.json"):
            record = read_json(path)
            if record.get("http_status") != 200 or record.get("normalized_output") is None:
                raise SystemExit(f"invalid {role} observer result: {path.name}")
    threshold_path = ROOT / "models" / "bundle-lineage" / "selected-thresholds-v5.json"
    bundle_path = ROOT / "models" / "bundle-lineage" / "v5-final" / "bundle-lock.json"
    values = {
        "observation_run_id": RUN_ID,
        "heldout_frame_lock_sha256": sha256(frame_lock_path.read_bytes()),
        "heldout_labels_sha256": sha256((BANK / "sealed-labels.json").read_bytes()),
        "heldout_candidate_lock_sha256": sha256((BANK / "candidate-lock.json").read_bytes()),
        "heldout_build_receipt_sha256": sha256((BANK / "bank-build-receipt.json").read_bytes()),
        "heldout_freeze_sha256": sha256((BANK / "bank-freeze.json").read_bytes()),
        "heldout_bank_tree_sha256": tree_hash(BANK),
        "small_observer_outputs_sha256": tree_hash(small_dir),
        "large_observer_outputs_sha256": tree_hash(large_dir),
        "thresholds_sha256": sha256(threshold_path.read_bytes()),
        "bundle_lock_sha256": sha256(bundle_path.read_bytes()),
        "frozen_input_lock_sha256": sha256(input_lock_path.read_bytes()),
        "evaluator_sha256": sha256((ROOT / "scripts" / "score_e010.py").read_bytes()),
        "completion_mode": "live",
        "labels_opened_after_observer_capture": True,
    }
    output = RUN / "score-replay-input-lock.json"
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing score lock: {output}")
    output.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(values, indent=2))


if __name__ == "__main__":
    main()
