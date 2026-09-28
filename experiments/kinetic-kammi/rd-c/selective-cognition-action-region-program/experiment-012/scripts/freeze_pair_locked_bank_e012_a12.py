from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
OUTPUT = CONSTRUCTION / "a12-design-lock-v1.json"
FILES = [
    "amendments/bank-amendment-11.md",
    "amendments/bank-amendment-11.json",
    "amendments/bank-amendment-12.md",
    "amendments/bank-amendment-12.json",
    "bank-construction-plan-v1.4.md",
    "task-construction-spec-v1.2.md",
    "scripts/prepare_pair_locked_bank_e012_a12.py",
    "scripts/freeze_pair_locked_bank_e012_a12.py",
    "scripts/finalize_pair_locked_bank_e012_a12.py",
    "scripts/test_finalize_pair_locked_bank_a12.py",
    "scripts/run_scored_checks_e012_a12_v1.py",
    "scripts/audit_paired_truth_e012_a12_v1.py",
    "scripts/audit_nuisance_baselines_e012_a12_v1.py",
    "scripts/audit_paired_truth_e012_v1.py",
    "scripts/freeze_paired_truth_audit_e012_v1.py",
    "bank/construction-01/paired-truth-audit-lock-v1.json",
    "bank/construction-01/scored-bank-v1/vault/paired-truth-audit-v1.json",
    "bank/construction-01/task-construction-lock-v1.1.json",
    "bank/construction-01/label-finalization-lock-v1.json",
    "bank/construction-01/frame-projection-lock-v1.1.json",
    "bank/construction-01/precontact-audit-lock-v1.3.json",
    "bank/construction-01/family-design-lock-v1.3.json",
    "bank/construction-01/feasibility-input-manifest-v1.3.json",
    "bank/construction-01/scored-bank-v1/vault/task-source-fixtures-final-v1.json",
    "bank/construction-01/scored-bank-v1/vault/candidate-check-labels-final-v1.json",
    "bank/construction-01/task-harnesses/clap-color-repair-01/Cargo.toml",
    "bank/construction-01/task-harnesses/clap-color-repair-01/tests/contract.rs",
    "bank/construction-01/task-harnesses/serde-map-order-repair-02/Cargo.toml",
    "bank/construction-01/task-harnesses/serde-map-order-repair-02/tests/contract.rs",
]


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT}")
    files = []
    for relative in FILES:
        path = ROOT / Path(relative)
        if not path.is_file():
            raise SystemExit(f"missing A12 design input: {relative}")
        data = path.read_bytes()
        files.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    body = {
        "schema_version": 1,
        "experiment": "E012 Prospective Frame Decomposition",
        "amendment": "E012-BANK-A12",
        "state": "FROZEN_BEFORE_A12_TASK_PREPARATION",
        "model_contact_authorized": False,
        "design": "bank-construction-plan-v1.4.md",
        "preparer": "scripts/prepare_pair_locked_bank_e012_a12.py",
        "files": files,
        "sha256_self_excluded": True,
    }
    OUTPUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"state": body["state"], "locked_files": len(files), "lock": str(OUTPUT)}, indent=2))


if __name__ == "__main__":
    main()
