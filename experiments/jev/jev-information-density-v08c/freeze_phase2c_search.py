"""Freeze a bounded atom-count search protocol before running it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_CONTRACT = HERE / "v08c-phase2c-search-contract.json"
DEFAULT_OUT = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\cross-atom-search-v01")
SOURCES = (
    "docs/jev-information-density-v0.8c-phase2c-search.md",
    "experiments/jev-information-density-v08c/v08c-phase2c-search-contract.json",
    "experiments/jev-information-density-v08c/run_phase2c_cross_atom_search.py",
    "experiments/jev-information-density-v08c/validate_phase2c_cross_atom_candidate.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_search.py",
    "experiments/jev-information-density-v08c/tests/test_phase2c_cross_atom_search.py",
    "experiments/jev-information-density-v08c/optimize_matched_banks.py",
    "experiments/jev-information-density-v08c/phase2c_training_signatures.py",
    "experiments/jev-information-density-v08c/audit_phase2c_training_signatures.py",
    "experiments/jev-information-density-v08c/validate_phase2b_candidates.py",
    "experiments/jev-information-density-v08/select_banks.py",
    "experiments/jev-information-density-v08b/build_factorial_banks.py",
    "experiments/jev-information-density-v08c/solve_feasibility.py",
    "experiments/jev-information-density-v08c/v08c-phase2-contract.json",
    "experiments/jev-information-density-v08c/v08c-phase2c-contract.json",
    "experiments/jev-information-density-v08c/v08c-phase2c-mobility-contract.json",
    "experiments/jev-information-density-v08c/audit_phase2c_support_mobility.py",
    "experiments/jev-information-density-v08c/audit_phase2c_support_mobility_v02.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_mobility.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_mobility_v02.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if contract.get("status") != "frozen_before_candidate_optimization":
        raise ValueError("search contract is not prospectively frozen")
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite search run directory: {args.out}")
    parent_phase2c = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\phase2c-freeze-receipt.json")
    parent_receipt = json.loads(parent_phase2c.read_text(encoding="utf-8"))
    if parent_receipt.get("status") != "SEALED_BEFORE_SIGNATURE_AUDIT":
        raise ValueError("parent Phase 2C freeze is not sealed")
    parent_contract = ROOT / "experiments/jev-information-density-v08c/v08c-phase2c-contract.json"
    if parent_receipt.get("contract_sha256") != sha256_file(parent_contract):
        raise ValueError("parent Phase 2C contract no longer matches its freeze")
    for relative, expected in parent_receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"parent frozen source changed: {relative}")

    source_hashes = {relative: sha256_file(ROOT / relative) for relative in SOURCES}
    external_inputs: dict[str, dict[str, str]] = {}
    for name, record in contract["inputs"].items():
        path = Path(record["path"])
        actual = sha256_file(path)
        if actual != record["sha256"]:
            raise ValueError(f"frozen search input hash mismatch: {name}")
        external_inputs[name] = {"path": str(path), "sha256": actual}
    mobility_receipt = json.loads(Path(contract["inputs"]["mobility_freeze_receipt"]["path"]).read_text(encoding="utf-8"))
    if mobility_receipt.get("status") != "SEALED_BEFORE_SUPPORT_MOBILITY_CENSUS":
        raise ValueError("parent mobility receipt is not sealed")
    args.out.mkdir(parents=True, exist_ok=False)
    receipt: dict[str, Any] = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-search-freeze",
        "status": "SEALED_BEFORE_CROSS_ATOM_SEARCH",
        "contract_sha256": sha256_file(args.contract),
        "parent_phase2c_freeze_receipt_sha256": sha256_file(parent_phase2c),
        "parent_mobility_freeze_receipt_sha256": sha256_file(Path(contract["inputs"]["mobility_freeze_receipt"]["path"])),
        "repository_sources": source_hashes,
        "external_inputs": external_inputs,
        "runtime": {"ortools_expected_version": "9.15.6755", "workers": 1, "python_entrypoint": "solver-venv/Scripts/python.exe"},
        "authorization": {"cross_atom_search": True, "independent_candidate_validation": True, "model_contact": False, "training": False, "phoenix_access": False},
    }
    receipt_path = args.out / "freeze-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "contract_sha256": receipt["contract_sha256"], "receipt": str(receipt_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
