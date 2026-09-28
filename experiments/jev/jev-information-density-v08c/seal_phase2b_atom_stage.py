"""Seal the exact-equivalent-atom construction stage before materialization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUN = Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests-passed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite freeze receipt: {args.out}")
    if args.tests_passed < 1:
        raise ValueError("at least one passing test is required")

    parent_freeze = json.loads((RUN / "phase2b-freeze-receipt.json").read_text(encoding="utf-8"))
    baseline_path = RUN / "instrumented-baseline" / "baseline-summary.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    contract_path = HERE / "v08c-phase2b-atom-stage-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    parent_contract = HERE / "v08c-phase2b-contract.json"
    if sha256_file(parent_contract) != contract["parent_phase2b_contract_sha256"]:
        raise ValueError("parent Phase 2B contract hash mismatch")
    if parent_freeze.get("status") != "FROZEN_PRE_SEARCH":
        raise ValueError("Phase 2B parent freeze receipt is not sealed")
    if baseline.get("status") != "SEARCH_EXHAUSTED" or baseline.get("candidate_manifest_path") is not None:
        raise ValueError("expected the bounded baseline to end without a candidate")

    files = {
        "stage_contract": contract_path,
        "stage_protocol": REPO / "docs" / "jev-information-density-v0.8c-phase2b-atom-substitution.md",
        "builder": HERE / "build_phase2b_atom_candidates.py",
        "independent_validator": HERE / "validate_phase2b_candidates.py",
        "builder_tests": HERE / "tests" / "test_atom_substitution.py",
        "seal_utility": Path(__file__).resolve(),
    }
    receipt = {
        "receipt": "jev-information-density-v08c-phase2b-atom-stage-freeze/v1",
        "status": "FROZEN_PRE_MATERIALIZATION",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_phase2b_freeze_sha256": sha256_file(RUN / "phase2b-freeze-receipt.json"),
        "parent_phase2b_contract_sha256": sha256_file(parent_contract),
        "baseline_summary_sha256": sha256_file(baseline_path),
        "sources": {name: sha256_file(path) for name, path in files.items()},
        "tests": {"passed": args.tests_passed, "result": "PASS"},
        "authorization": {
            "atom_preserving_candidate_materialization": True,
            "independent_candidate_audit": True,
            "model_contact": False,
            "phoenix_access": False,
            "training_materialization": False,
            "further_neighborhood_search": False,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.out)
    print(json.dumps({"status": receipt["status"], "path": str(args.out), "sources": receipt["sources"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
