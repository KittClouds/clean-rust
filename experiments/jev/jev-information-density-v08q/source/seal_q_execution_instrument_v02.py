"""Seal the frozen Q execution code before head initialization."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
TRAIN = RUN / "training"
EVAL = RUN / "evaluation"
OUT = RUN / "instrument/q-execution-instrument-seal-v02.json"
SOURCES = (
    "source/run_q_training_v02.py",
    "source/evaluate_q_panel_v02.py",
    "source/analyze_q_results_v02.py",
    "source/verify_q_full_execution_v02.py",
    "source/q_analysis_rules_v02.py",
    "source/q_weighted_objective_v02.py",
    "source/seal_q_execution_instrument_v02.py",
    "source/seal_q_full_execution_packet_v02.py",
    "tests/test_q_rules_v02.py",
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def entries_root(entries: list[dict[str, Any]]) -> str:
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda x: x["path"]))
    return hashlib.sha256(payload.encode()).hexdigest()


def main() -> int:
    if OUT.exists() or TRAIN.exists() or EVAL.exists():
        raise RuntimeError("Q execution instrument is one-use; output/training/evaluation already exists")
    py = sys.executable
    compile_result = subprocess.run(
        [py, "-m", "py_compile", *(str(Q / path) for path in SOURCES)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if compile_result.returncode:
        raise RuntimeError(f"Q execution py_compile failed: {compile_result.stderr}")
    test_result = subprocess.run(
        [py, str(Q / "tests/test_q_rules_v02.py")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if test_result.returncode:
        raise RuntimeError(f"Q frozen unit tests failed: {test_result.stderr}")
    entries = []
    for relative in SOURCES:
        path = Q / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append({"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha(path)})
    root = entries_root(entries)
    payload = {
        "schema": "jev-v08q-execution-instrument-seal-v02",
        "identity": "JEV-V08Q-FROZEN-EXECUTION-INSTRUMENTS",
        "status": "Q_EXECUTION_INSTRUMENTS_SEALED_PRE_HEAD_INITIALIZATION",
        "root_sha256": root,
        "entry_count": len(entries),
        "entries": entries,
        "qualification": {
            "python_compile": "PASS",
            "unit_test_command": [py, str(Q / "tests/test_q_rules_v02.py")],
            "unit_test_exit_code": test_result.returncode,
            "unit_test_stdout_sha256": hashlib.sha256(test_result.stdout.encode()).hexdigest(),
            "unit_test_stderr_sha256": hashlib.sha256(test_result.stderr.encode()).hexdigest(),
            "q_analysis_rule_tests": 6,
        },
        "scope": {
            "panel_root_sha256": "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6",
            "run_contract_sha256": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
            "analysis_contract_sha256": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
            "execution_addendum_sha256": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
            "head_initialization": False,
            "training": False,
            "panel_opened": False,
            "analysis": False,
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": payload["status"], "instrument_root_sha256": root, "entries": len(entries), "tests": "PASS", "training": False, "panel_opened": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
