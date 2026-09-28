"""Run the frozen Phase 2C raw-record validator with an Eval-ID type fix."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_CONTRACT = HERE / "v08c-phase2c-validation-v02-contract.json"
DEFAULT_RECEIPT = Path(
    r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\cross-atom-search-v01\validation-v02\freeze-receipt.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(contract_path: Path, receipt_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if contract.get("status") != "frozen_before_independent_validation":
        raise ValueError("validation v02 contract is not frozen")
    if receipt.get("status") != "SEALED_BEFORE_INDEPENDENT_VALIDATION_V02":
        raise ValueError("validation v02 freeze receipt status mismatch")
    if receipt.get("contract_sha256") != sha256_file(contract_path):
        raise ValueError("validation v02 contract hash mismatch")
    for relative, expected in receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"frozen validation source changed: {relative}")
    for name, item in receipt["external_inputs"].items():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"frozen validation input changed: {name}")
    return contract


def load_legacy_validator(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("phase2c_candidate_validator_v01", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load pinned validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def eval_id_membership(values: dict[str, str]) -> set[str]:
    return set(values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    contract = verify(args.contract, args.freeze_receipt)

    # v01 returns {group_id: episode_id} for all manifests. Its Eval intersection
    # check expects a set; convert only the 83,328-row Eval result, leaving the
    # candidate/reference mappings intact for the unchanged validation logic.
    validator_path = HERE / "validate_phase2c_cross_atom_candidate.py"
    validator = load_legacy_validator(validator_path)
    legacy_read_ids = validator.read_ids

    def corrected_read_ids(path: Path, expected: int = 100_000) -> Any:
        result = legacy_read_ids(path, expected)
        return eval_id_membership(result) if expected == 83_328 else result

    validator.read_ids = corrected_read_ids
    candidate = Path(contract["candidate"]["path"])
    output = Path(contract["output"]["path"])
    search_contract = Path(contract["search_contract_path"])
    if not search_contract.is_absolute():
        search_contract = ROOT / search_contract
    if output.exists():
        raise FileExistsError(f"refusing to overwrite validation result: {output}")
    sys.argv = [
        str(validator_path),
        "--bank", contract["candidate"]["bank"],
        "--contract", str(search_contract),
        "--freeze-receipt", str(contract["search_freeze_receipt_path"]),
        "--candidate", str(candidate),
        "--out", str(output),
    ]
    return validator.main()


if __name__ == "__main__":
    raise SystemExit(main())
