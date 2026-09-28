from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
OUT = ROOT / "bank" / "construction-01" / "scored-check-run-lock-v1.2.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return (result.stdout or result.stderr).strip().splitlines()[0]


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite scored-check runner lock v1.2")
    if (BANK / "vault" / "candidate-check-results.json").exists():
        raise SystemExit("a candidate result file exists; quarantine it before freezing a retry")
    locked = [
        ROOT / "amendments" / "bank-amendment-07.md",
        ROOT / "amendments" / "bank-amendment-07.json",
        ROOT / "scripts" / "run_scored_checks_e012_v1_2.py",
        ROOT / "scripts" / "freeze_scored_check_runner_e012_v1_2.py",
        ROOT / "bank" / "construction-01" / "task-construction-lock-v1.1.json",
        ROOT / "bank" / "construction-01" / "scored-check-run-lock-v1.1.json",
        BANK / "vault" / "task-source-fixtures.json",
        BANK / "attempts" / "scored-check-attempt-01.json",
        BANK / "attempts" / "scored-check-attempt-02-audit.json",
        BANK / "attempts" / "scored-check-results-attempt-02-quarantined.json",
    ]
    files = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}
        for path in locked
    ]
    body = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_SCORED_CHECK_RETRY",
        "model_contact_authorized": False,
        "attempt_02_conflicts": 15,
        "quarantined_result_sha256": digest(BANK / "attempts" / "scored-check-results-attempt-02-quarantined.json"),
        "source_fixture_sha256": digest(BANK / "vault" / "task-source-fixtures.json"),
        "runner": "scripts/run_scored_checks_e012_v1_2.py",
        "runner_sha256": digest(ROOT / "scripts" / "run_scored_checks_e012_v1_2.py"),
        "cargo_target_policy": "content-addressed by family, manifest hash, source hash, and test hash",
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
