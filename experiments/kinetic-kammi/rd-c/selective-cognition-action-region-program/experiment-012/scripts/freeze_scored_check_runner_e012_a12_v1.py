from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
BANK = CONSTRUCTION / "scored-bank-a12"
OUTPUT = CONSTRUCTION / "scored-check-run-lock-a12-v1.json"
HARNESS_ROOT = CONSTRUCTION / "task-harnesses"
REPOSITORY_ROOT = CONSTRUCTION / "repositories"
ARCHIVE_ROOT = CONSTRUCTION / "source" / "repositories"
INVENTORY = CONSTRUCTION / "repository-source-inventory.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT}")
    design_lock = CONSTRUCTION / "a12-design-lock-v1.json"
    if not design_lock.is_file():
        raise SystemExit("A12 design lock is missing")
    design = json.loads(design_lock.read_text(encoding="utf-8"))
    if design.get("state") != "FROZEN_BEFORE_A12_TASK_PREPARATION" or design.get("model_contact_authorized") is not False:
        raise SystemExit("A12 design lock is invalid")
    source = BANK / "vault" / "task-source-fixtures-precheck-v1.json"
    if not source.is_file():
        raise SystemExit("A12 precheck source fixture is missing")
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    files = [
        "scripts/freeze_scored_check_runner_e012_a12_v1.py",
        "scripts/run_scored_checks_e012_a12_v1.py",
        "scripts/finalize_pair_locked_bank_e012_a12.py",
        "scripts/test_finalize_pair_locked_bank_a12.py",
        "bank/construction-01/a12-design-lock-v1.json",
        "bank/construction-01/scored-bank-a12/vault/task-source-fixtures-precheck-v1.json",
        "bank/construction-01/repository-source-inventory.json",
        "bank/construction-01/repository-source-audit-v1.json",
        "bank/construction-01/task-construction-lock-v1.1.json",
        "bank/construction-01/label-finalization-lock-v1.json",
        "bank/construction-01/family-design-lock-v1.3.json",
    ]
    file_records = []
    for relative in files:
        path = ROOT / Path(relative)
        if not path.is_file():
            raise SystemExit(f"missing A12 score input: {relative}")
        data = path.read_bytes()
        file_records.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    harness_records = []
    for path in sorted(item for item in HARNESS_ROOT.rglob("*") if item.is_file()):
        data = path.read_bytes()
        harness_records.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    repo_records = []
    for entry in sorted(inventory["selected_repositories"], key=lambda row: row["repository_id"]):
        repo_id = entry["repository_id"]
        checkout = REPOSITORY_ROOT / repo_id
        commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
        if commit != entry["commit"] or status.strip():
            raise SystemExit(f"repository is not the locked clean source snapshot: {repo_id}")
        archive = ARCHIVE_ROOT / Path(entry["archive_path"]).name
        if sha256(archive) != entry["archive_sha256"]:
            raise SystemExit(f"source archive hash mismatch: {repo_id}")
        repo_records.append({
            "repository_id": repo_id,
            "commit": commit,
            "source_archive_path": archive.relative_to(ROOT).as_posix(),
            "archive_sha256": sha256(archive),
            "root_cargo_toml_sha256": sha256(checkout / "Cargo.toml"),
            "working_tree_clean": True,
        })
    body = {
        "schema_version": 1,
        "experiment": "E012 Prospective Frame Decomposition",
        "amendment": "E012-BANK-A12",
        "state": "FROZEN_BEFORE_A12_CANDIDATE_CHECKS",
        "model_contact_authorized": False,
        "runner": "scripts/run_scored_checks_e012_a12_v1.py",
        "runner_sha256": sha256(ROOT / "scripts" / "run_scored_checks_e012_a12_v1.py"),
        "target_root": "D:/rdc-e012-target/scored-checks-a12",
        "cargo_incremental": False,
        "files": file_records,
        "task_harnesses": harness_records,
        "repositories": repo_records,
        "expected_candidate_rows": 192,
        "expected_candidate_case_invocations": 384,
        "expected_base_rows": 48,
        "expected_base_case_invocations": 96,
        "sha256_self_excluded": True,
    }
    OUTPUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "state": body["state"], "files": len(file_records),
        "harness_files": len(harness_records), "repositories": len(repo_records),
        "lock": str(OUTPUT),
    }, indent=2))


if __name__ == "__main__":
    main()
