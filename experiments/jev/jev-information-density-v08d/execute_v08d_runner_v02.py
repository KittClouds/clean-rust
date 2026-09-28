"""Execute the frozen v0.8D capacity protocol through a path-safe adapter."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V01_DIR = Path(r"D:\codex-runs\jev-information-density-v08d\common-support-v01")
V02_DIR = Path(r"D:\codex-runs\jev-information-density-v08d\common-support-v02")
V02_FREEZE = V02_DIR / "freeze-receipt.json"
ADAPTER_ID = "jev-v08d-runner-path-fix-v02"
sys.path.insert(0, str(HERE))
import discover_v08d_common_support as core  # noqa: E402

ADAPTER_SOURCES = (
    "docs/jev-information-density-v0.8d-runner-adapter-v0.2.md",
    "experiments/jev-information-density-v08d/execute_v08d_runner_v02.py",
    "experiments/jev-information-density-v08d/tests/test_v08d_runner.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_outputs(contract: dict[str, Any]) -> dict[str, str]:
    outputs = dict(contract["outputs"])
    locator = outputs.pop("external_run_directory", None)
    if locator is None or Path(locator) != V01_DIR:
        raise ValueError("contract run-directory locator differs from the sealed v0.8D v01 path")
    if any(Path(value).is_absolute() for value in outputs.values()):
        raise ValueError("artifact output list contains an absolute path after locator removal")
    return outputs


def verify_v01_abort(core_contract: dict[str, Any]) -> dict[str, Any]:
    if not V01_DIR.is_dir():
        raise ValueError("v0.8D v01 freeze directory is missing")
    names = sorted(path.name for path in V01_DIR.iterdir())
    if names != ["freeze-receipt.json"]:
        raise ValueError(f"v01 is not the expected pre-data abort state: {names}")
    receipt = read_json(V01_DIR / "freeze-receipt.json")
    if receipt.get("status") != "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION":
        raise ValueError("v01 freeze receipt status mismatch")
    if receipt.get("contract_sha256") != sha256_file(core.CONTRACT_PATH):
        raise ValueError("v01 freeze is not tied to the current sealed contract")
    artifact_outputs(core_contract)
    return receipt


def build_v02_receipt(core_contract: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    repository_sources = dict(parent["repository_sources"])
    for relative in ADAPTER_SOURCES:
        repository_sources[relative] = sha256_file(ROOT / relative)
    return {
        "protocol": core_contract["protocol"],
        "execution_adapter": ADAPTER_ID,
        "status": "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION",
        "contract_sha256": sha256_file(core.CONTRACT_PATH),
        "repository_sources": repository_sources,
        "external_inputs": dict(parent["external_inputs"]),
        "parent_v01_freeze": {
            "path": str(V01_DIR / "freeze-receipt.json"),
            "sha256": sha256_file(V01_DIR / "freeze-receipt.json"),
            "status": "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION",
        },
        "execution_correction": {
            "only_change": "exclude outputs.external_run_directory locator from artifact collision checks; run under common-support-v02",
            "scientific_contract_changed": False,
            "source_rows_read_during_v01_attempt": False,
            "v01_attempt_output_files": ["freeze-receipt.json"],
        },
        "authorization": dict(parent["authorization"]),
    }


def freeze() -> int:
    if V02_DIR.exists():
        raise FileExistsError(f"refusing to reuse v0.8D v02 run directory: {V02_DIR}")
    contract = core.verify_freeze()
    parent = verify_v01_abort(contract)
    receipt = build_v02_receipt(contract, parent)
    V02_DIR.mkdir(parents=True, exist_ok=False)
    with V02_FREEZE.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION",
        "execution_adapter": ADAPTER_ID,
        "contract_sha256": receipt["contract_sha256"],
        "parent_v01_freeze_sha256": receipt["parent_v01_freeze"]["sha256"],
        "adapter_source_count": len(ADAPTER_SOURCES),
        "run_directory": str(V02_DIR),
    }, separators=(",", ":")))
    return 0


def verify_v02_receipt() -> dict[str, Any]:
    if not V02_FREEZE.is_file():
        raise FileNotFoundError("v0.8D v02 is not frozen; run with 'freeze' first")
    receipt = read_json(V02_FREEZE)
    if receipt.get("status") != "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION":
        raise ValueError("v0.8D v02 freeze receipt status mismatch")
    if receipt.get("execution_adapter") != ADAPTER_ID:
        raise ValueError("v0.8D v02 adapter identity mismatch")
    if receipt.get("contract_sha256") != sha256_file(core.CONTRACT_PATH):
        raise ValueError("v0.8D v02 contract hash mismatch")
    if sha256_file(V01_DIR / "freeze-receipt.json") != receipt["parent_v01_freeze"]["sha256"]:
        raise ValueError("v0.8D v01 parent freeze changed")
    for relative, expected in receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"v0.8D v02 frozen source changed: {relative}")
    for name, item in receipt["external_inputs"].items():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"v0.8D v02 frozen input changed: {name}")
    original_contract = core.read_json(core.CONTRACT_PATH)
    verify_v01_abort(original_contract)
    adjusted = dict(original_contract)
    adjusted["outputs"] = artifact_outputs(original_contract)
    core.verify_source_authority(adjusted)
    return adjusted


def run() -> int:
    contract = verify_v02_receipt()
    core.RUN_DIR = V02_DIR
    core.FREEZE_PATH = V02_FREEZE
    core.verify_freeze = verify_v02_receipt
    return core.main()


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"freeze", "run"}:
        raise SystemExit("usage: execute_v08d_runner_v02.py {freeze|run}")
    return freeze() if sys.argv[1] == "freeze" else run()


if __name__ == "__main__":
    raise SystemExit(main())
