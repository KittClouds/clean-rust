from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
SOURCE_FIXTURE = BANK / "vault" / "task-source-fixtures.json"
ATTEMPT = BANK / "attempts" / "scored-check-attempt-01.json"
TASK_LOCK = ROOT / "bank" / "construction-01" / "task-construction-lock-v1.1.json"
OUT = ROOT / "bank" / "construction-01" / "scored-check-run-lock-v1.1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return (result.stdout or result.stderr).strip().splitlines()[0]


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite scored-check runner lock")
    result_path = BANK / "vault" / "candidate-check-results.json"
    if result_path.exists():
        raise SystemExit("candidate results already exist; runner lock must precede retry")
    lock = json.loads(TASK_LOCK.read_text(encoding="utf-8"))
    if lock.get("model_contact_authorized") is not False:
        raise SystemExit("task-construction lock unexpectedly authorizes model contact")
    inputs = [
        ROOT / "amendments" / "bank-amendment-06.md",
        ROOT / "amendments" / "bank-amendment-06.json",
        ROOT / "scripts" / "run_scored_checks_e012_v1_1.py",
        ROOT / "scripts" / "freeze_scored_check_runner_e012_v1_1.py",
        TASK_LOCK,
        SOURCE_FIXTURE,
        ATTEMPT,
    ]
    files = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}
        for path in inputs
    ]
    body = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_SCORED_CHECK_RETRY",
        "model_contact_authorized": False,
        "failed_attempt_preserved": str(ATTEMPT.relative_to(ROOT).as_posix()),
        "task_construction_lock_sha256": digest(TASK_LOCK),
        "task_source_fixture_sha256": digest(SOURCE_FIXTURE),
        "runner": "scripts/run_scored_checks_e012_v1_1.py",
        "runner_sha256": digest(ROOT / "scripts" / "run_scored_checks_e012_v1_1.py"),
        "files": files,
        "toolchain": {
            "python": sys.version.split()[0],
            "cargo": version(["cargo", "--version"]),
            "rustc": version(["rustc", "--version"]),
            "cargo_target_root": r"D:\rdc-e012-target\scored-checks",
        },
        "sha256_self_excluded": True,
    }
    OUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": body["state"], "runner_sha256": body["runner_sha256"], "lock": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
