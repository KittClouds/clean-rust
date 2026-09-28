from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
OUTPUT = CONSTRUCTION / "a13-retry-design-lock-v1.json"
FILES = [
    "amendments/bank-amendment-11.md",
    "amendments/bank-amendment-11.json",
    "amendments/bank-amendment-12.md",
    "amendments/bank-amendment-12.json",
    "amendments/bank-amendment-13.md",
    "amendments/bank-amendment-13.json",
    "bank-construction-plan-v1.4.md",
    "task-construction-spec-v1.2.md",
    "scripts/prepare_pair_locked_bank_e012_a13_v1.py",
    "scripts/finalize_pair_locked_bank_e012_a13_v2.py",
    "scripts/test_finalize_pair_locked_bank_a13.py",
    "scripts/run_scored_checks_e012_a13_v2.py",
    "scripts/freeze_scored_check_runner_e012_a13_v1.py",
    "scripts/audit_paired_truth_e012_a13_v1.py",
    "scripts/audit_nuisance_baselines_e012_a13_v1.py",
    "scripts/project_frames_e012_a13_v1.py",
    "scripts/freeze_frame_projection_e012_a13_v1.py",
    "scripts/audit_task_bank_e012_a13_v1.py",
    "scripts/freeze_precontact_audit_e012_a13_v1.py",
    "scripts/freeze_pair_locked_bank_e012_a13.py",
    "scripts/audit_paired_truth_e012_v1.py",
    "scripts/freeze_paired_truth_audit_e012_v1.py",
    "bank/construction-01/a12-design-lock-v1.json",
    "bank/construction-01/scored-check-run-lock-a12-v1.json",
    "bank/construction-01/paired-truth-audit-lock-v1.json",
    "bank/construction-01/scored-bank-v1/vault/paired-truth-audit-v1.json",
    "bank/construction-01/scored-bank-a12/attempts/scored-check-attempt-01.json",
    "bank/construction-01/scored-bank-a12/vault/task-source-fixtures-precheck-v1.json",
    "bank/construction-01/task-construction-lock-v1.1.json",
    "bank/construction-01/label-finalization-lock-v1.json",
    "bank/construction-01/frame-projection-lock-v1.1.json",
    "bank/construction-01/precontact-audit-lock-v1.3.json",
    "bank/construction-01/family-design-lock-v1.3.json",
    "bank/construction-01/feasibility-input-manifest-v1.3.json",
    "bank/construction-01/repository-source-inventory.json",
    "bank/construction-01/repository-source-audit-v1.json",
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
    rows = []
    for relative in FILES:
        path = ROOT / Path(relative)
        if not path.is_file():
            raise SystemExit(f"missing A13 retry design input: {relative}")
        data = path.read_bytes()
        rows.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    body = {
        "schema_version": 1,
        "experiment": "E012 Prospective Frame Decomposition",
        "amendment": "E012-BANK-A13-RETRY",
        "state": "FROZEN_BEFORE_A13_RETRY",
        "model_contact_authorized": False,
        "prior_failed_attempt_preserved": "bank/construction-01/scored-bank-a12/attempts/scored-check-attempt-01.json",
        "design": "bank-construction-plan-v1.4.md",
        "files": rows,
        "sha256_self_excluded": True,
    }
    OUTPUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"state": body["state"], "locked_files": len(rows), "lock": str(OUTPUT)}, indent=2))


if __name__ == "__main__":
    main()
