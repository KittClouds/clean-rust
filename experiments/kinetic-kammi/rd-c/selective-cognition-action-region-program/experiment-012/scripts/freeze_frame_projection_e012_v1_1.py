from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
OUT = ROOT / "bank" / "construction-01" / "frame-projection-lock-v1.1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite frame-projection lock")
    projected = [
        BANK / "observer-frames.json",
        BANK / "vault" / "frame-truth-index.json",
        BANK / "vault" / "presentation-receipts.json",
    ]
    if any(path.exists() for path in projected):
        raise SystemExit("frame artifacts already exist; projection lock must precede generation")
    paths = [
        ROOT / "amendments" / "bank-amendment-04.json",
        ROOT / "amendments" / "bank-amendment-05.json",
        ROOT / "amendments" / "bank-amendment-08.json",
        ROOT / "task-construction-spec-v1.1.json",
        ROOT / "bank" / "construction-01" / "task-construction-lock-v1.1.json",
        ROOT / "bank" / "construction-01" / "scored-check-run-lock-v1.2.json",
        ROOT / "bank" / "construction-01" / "label-finalization-lock-v1.json",
        BANK / "vault" / "task-source-fixtures-final-v1.json",
        BANK / "vault" / "candidate-check-labels-final-v1.json",
        BANK / "vault" / "label-finalization-report-v1.json",
        BANK / "vault" / "candidate-check-results.json",
        BANK / "vault" / "task-source-fixtures.json",
        ROOT / "scripts" / "project_frames_e012_v1_2.py",
        ROOT / "scripts" / "audit_task_bank_e012_v1_1.py",
        ROOT / "scripts" / "freeze_frame_projection_e012_v1_1.py",
        Path(r"D:\rdc-e012-target\runtime-integration\release\e011-presentation.exe"),
        Path(r"D:\rdc-e012-target\runtime-integration\release\e011-hash.exe"),
    ]
    files = []
    for path in paths:
        label = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else f"external::{path.as_posix()}"
        files.append({"path": label, "sha256": digest(path), "bytes": path.stat().st_size})
    body = {
        "schema_version": 1,
        "experiment": "E012 Prospective Frame Decomposition",
        "state": "FROZEN_BEFORE_FRAME_PROJECTION",
        "model_contact_authorized": False,
        "task_count": 48,
        "conditions_per_task": 26,
        "expected_frame_count": 1248,
        "task_source_fixture_sha256": digest(BANK / "vault" / "task-source-fixtures-final-v1.json"),
        "candidate_label_sha256": digest(BANK / "vault" / "candidate-check-labels-final-v1.json"),
        "projector": "scripts/project_frames_e012_v1_2.py",
        "projector_sha256": digest(ROOT / "scripts" / "project_frames_e012_v1_2.py"),
        "presentation_binary_sha256": digest(Path(r"D:\rdc-e012-target\runtime-integration\release\e011-presentation.exe")),
        "hash_binary_sha256": digest(Path(r"D:\rdc-e012-target\runtime-integration\release\e011-hash.exe")),
        "files": files,
        "sha256_self_excluded": True,
    }
    OUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": body["state"], "locked_files": len(files), "lock": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
