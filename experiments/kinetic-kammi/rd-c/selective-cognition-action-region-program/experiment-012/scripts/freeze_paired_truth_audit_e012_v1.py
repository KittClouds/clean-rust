from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
OUTPUT = ROOT / "bank" / "construction-01" / "paired-truth-audit-lock-v1.json"
INPUTS = [
    ROOT / "scripts" / "audit_paired_truth_e012_v1.py",
    ROOT / "scripts" / "freeze_paired_truth_audit_e012_v1.py",
    BANK / "vault" / "task-source-fixtures-final-v1.json",
    BANK / "vault" / "candidate-check-labels-final-v1.json",
    BANK / "observer-frames.json",
    BANK / "vault" / "frame-truth-index.json",
    BANK / "vault" / "presentation-receipts.json",
    BANK / "vault" / "precontact-audit-v1.json",
]


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT}")
    missing = [str(path) for path in INPUTS if not path.is_file()]
    if missing:
        raise SystemExit("missing locked inputs: " + ", ".join(missing))
    files = []
    for path in INPUTS:
        data = path.read_bytes()
        files.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    body = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_PAIRED_TRUTH_DIAGNOSTIC",
        "model_contact_authorized": False,
        "audit": "scripts/audit_paired_truth_e012_v1.py",
        "audit_sha256": files[0]["sha256"],
        "files": files,
        "sha256_self_excluded": True,
    }
    OUTPUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"state": body["state"], "locked_inputs": len(files), "lock": str(OUTPUT)}, indent=2))


if __name__ == "__main__":
    main()
