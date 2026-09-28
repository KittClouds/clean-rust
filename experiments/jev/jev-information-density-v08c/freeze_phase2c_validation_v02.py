"""Freeze the narrow v02 validator repair against the fixed RM100 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTRACT = HERE / "v08c-phase2c-validation-v02-contract.json"
DEFAULT_OUT = Path(
    r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\cross-atom-search-v01\validation-v02"
)
SOURCES = (
    "experiments/jev-information-density-v08c/validate_phase2c_candidate_v02.py",
    "experiments/jev-information-density-v08c/tests/test_phase2c_candidate_validation_v02.py",
    "experiments/jev-information-density-v08c/validate_phase2c_cross_atom_candidate.py",
    "experiments/jev-information-density-v08c/v08c-phase2c-search-contract.json",
    "experiments/jev-information-density-v08c/freeze_phase2c_search.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_validation_v02.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "frozen_before_independent_validation":
        raise ValueError("validation v02 contract is not prospectively frozen")
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite validation freeze directory: {args.out}")

    external: dict[str, dict[str, str]] = {}
    for name, item in contract["pinned_files"].items():
        path = Path(item["path"])
        actual = sha256_file(path)
        if actual != item["sha256"]:
            raise ValueError(f"validation input hash mismatch: {name}")
        external[name] = {"path": str(path), "sha256": actual}

    search_receipt_path = Path(contract["search_freeze_receipt_path"])
    search_receipt = json.loads(search_receipt_path.read_text(encoding="utf-8"))
    if search_receipt.get("status") != "SEALED_BEFORE_CROSS_ATOM_SEARCH":
        raise ValueError("parent search is not frozen")
    source_hashes = {relative: sha256_file(ROOT / relative) for relative in SOURCES}
    args.out.mkdir(parents=True, exist_ok=False)
    receipt: dict[str, Any] = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-validation-v02-freeze",
        "status": "SEALED_BEFORE_INDEPENDENT_VALIDATION_V02",
        "contract_sha256": sha256_file(CONTRACT),
        "repository_sources": source_hashes,
        "external_inputs": external,
        "parent_search_freeze_receipt_sha256": sha256_file(search_receipt_path),
        "scope": {
            "change": "convert Eval manifest mapping to an ID set for the intersection check only",
            "candidate_or_search_changed": False,
            "model_contact": False,
            "training": False,
            "phoenix_access": False,
        },
    }
    receipt_path = args.out / "freeze-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "contract_sha256": receipt["contract_sha256"], "receipt": str(receipt_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
