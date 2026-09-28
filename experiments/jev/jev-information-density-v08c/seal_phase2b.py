"""Create the external v0.8C Phase 2B pre-search hash receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--witness-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unit-tests-passed", type=int, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite freeze receipt: {args.out}")
    witness = json.loads(args.witness_receipt.read_text(encoding="utf-8"))
    contract = HERE / "v08c-phase2b-contract.json"
    validator = HERE / "validate_phase2b_witnesses.py"
    if witness.get("result") != "PASS_PROFILE_WITNESSES_ONLY":
        raise ValueError("witness validation did not pass")
    if witness.get("source_hashes", {}).get("independent_validator") != sha256_file(validator):
        raise ValueError("witness receipt was not produced by the current validator source")
    if args.unit_tests_passed < 1:
        raise ValueError("unit test count must be positive")
    files = {
        "contract": contract,
        "protocol": REPO / "docs" / "jev-information-density-v0.8c-phase2b.md",
        "independent_witness_validator": validator,
        "instrumented_baseline_runner": HERE / "phase2b_instrumented_baseline.py",
        "witness_validator_tests": HERE / "tests" / "test_phase2b_witness_audit.py",
    }
    receipt = {
        "receipt": "jev-information-density-v08c-phase2b-pre-search-freeze/v1",
        "status": "FROZEN_PRE_SEARCH",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": {name: sha256_file(path) for name, path in files.items()},
        "witness_validation": {
            "path": str(args.witness_receipt),
            "sha256": sha256_file(args.witness_receipt),
            "result": witness["result"],
            "original_selector_reproduction": witness["original_selector_objective_reproduction"],
        },
        "unit_tests": {"passed": args.unit_tests_passed, "result": "PASS"},
        "authorization": {
            "candidate_search": True,
            "baseline_budget_seconds_after_source_load": 900,
            "model_contact": False,
            "phoenix_access": False,
            "training_materialization": False,
        },
        "parent_phase2_run": "INTERRUPTED_UNKNOWN; immutable; no output artifacts",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.out)
    print(json.dumps({"status": receipt["status"], "path": str(args.out), "hashes": receipt["protocol_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
