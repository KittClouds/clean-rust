from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
OUT = ROOT / "bank" / "construction-01" / "precontact-audit-lock-v1.3.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite pre-contact audit lock v1.3")
    if (BANK / "vault" / "precontact-audit-v1.json").exists():
        raise SystemExit("pre-contact audit output already exists")
    paths = [
        ROOT / "amendments" / "bank-amendment-10.md",
        ROOT / "amendments" / "bank-amendment-10.json",
        ROOT / "scripts" / "audit_task_bank_e012_v1_3.py",
        ROOT / "scripts" / "freeze_precontact_audit_e012_v1_3.py",
        ROOT / "bank" / "construction-01" / "precontact-audit-lock-v1.2.json",
        BANK / "attempts" / "precontact-audit-attempt-01.json",
        BANK / "attempts" / "precontact-audit-attempt-02.json",
        BANK / "observer-frames.json",
        BANK / "vault" / "frame-truth-index.json",
        BANK / "vault" / "presentation-receipts.json",
        BANK / "vault" / "task-source-fixtures-final-v1.json",
        BANK / "vault" / "candidate-check-labels-final-v1.json",
        BANK / "vault" / "candidate-check-results.json",
    ]
    files = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}
        for path in paths
    ]
    body = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_PRECONTACT_AUDIT_RERUN",
        "model_contact_authorized": False,
        "audit": "scripts/audit_task_bank_e012_v1_3.py",
        "audit_sha256": digest(ROOT / "scripts" / "audit_task_bank_e012_v1_3.py"),
        "prior_audit_attempts": [
            digest(BANK / "attempts" / "precontact-audit-attempt-01.json"),
            digest(BANK / "attempts" / "precontact-audit-attempt-02.json"),
        ],
        "frame_count": 1248,
        "files": files,
        "sha256_self_excluded": True,
    }
    OUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": body["state"], "files": len(files), "lock": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
