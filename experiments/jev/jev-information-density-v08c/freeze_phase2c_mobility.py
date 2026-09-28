"""Seal the support-mobility census inputs and code before reading the census."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_CONTRACT = HERE / "v08c-phase2c-mobility-contract.json"
DEFAULT_OUT = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\support-mobility-v01")
SOURCES = (
    "docs/jev-information-density-v0.8c-phase2c-cross-atom.md",
    "experiments/jev-information-density-v08c/v08c-phase2c-contract.json",
    "experiments/jev-information-density-v08c/v08c-phase2c-mobility-contract.json",
    "experiments/jev-information-density-v08c/audit_phase2c_support_mobility.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_mobility.py",
    "experiments/jev-information-density-v08c/tests/test_phase2c_support_mobility.py",
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
    if contract.get("status") != "frozen_before_support_mobility_census":
        raise ValueError("support-mobility contract is not frozen")
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite mobility freeze directory: {args.out}")
    args.out.mkdir(parents=True, exist_ok=False)
    repo_sources = {relative: sha256_file(ROOT / relative) for relative in SOURCES}
    external_inputs: dict[str, dict[str, str]] = {}
    for name, record in contract["inputs"].items():
        path = Path(record["path"])
        actual = sha256_file(path)
        if actual != record["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")
        external_inputs[name] = {"path": str(path), "sha256": actual}
    phase2c_receipt = json.loads(Path(contract["inputs"]["phase2c_freeze_receipt"]["path"]).read_text(encoding="utf-8"))
    if phase2c_receipt.get("status") != "SEALED_BEFORE_SIGNATURE_AUDIT":
        raise ValueError("parent Phase 2C receipt is not sealed")
    parent_audit_sha = sha256_file(Path(contract["inputs"]["training_equivalence_audit"]["path"]))
    receipt: dict[str, Any] = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-mobility-freeze",
        "status": "SEALED_BEFORE_SUPPORT_MOBILITY_CENSUS",
        "contract_sha256": sha256_file(args.contract),
        "parent_phase2c_freeze_receipt_sha256": sha256_file(Path(contract["inputs"]["phase2c_freeze_receipt"]["path"])),
        "parent_audit_sha256": parent_audit_sha,
        "repository_sources": repo_sources,
        "external_inputs": external_inputs,
        "authorization": {
            "metadata_support_census": True,
            "cross_atom_search": False,
            "model_contact": False,
            "training": False,
            "phoenix_access": False,
        },
    }
    out_path = args.out / "freeze-receipt.json"
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "contract_sha256": receipt["contract_sha256"], "receipt": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
