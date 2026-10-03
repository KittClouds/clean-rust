"""Add contract-key normalization to the fresh v0.8D execution identity."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V02_DIR = Path(r"D:\codex-runs\jev-information-density-v08d\common-support-v02")
V03_DIR = Path(r"D:\codex-runs\jev-information-density-v08d\common-support-v03")
V03_FREEZE = V03_DIR / "freeze-receipt.json"
ADAPTER_ID = "jev-v08d-runner-contract-keys-v03"
sys.path.insert(0, str(HERE))
import execute_v08d_runner_v02 as parent_adapter  # noqa: E402

core = parent_adapter.core
ADAPTER_SOURCES = (
    "docs/jev-information-density-v0.8d-runner-adapter-v0.3.md",
    "experiments/jev-information-density-v08d/execute_v08d_runner_v03.py",
    "experiments/jev-information-density-v08d/tests/test_v08d_runner_v03.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_profile_tolerances(contract: dict[str, Any]) -> dict[str, Any]:
    """Expose implementation aliases only when all corresponding limits agree."""
    result = copy.deepcopy(contract)
    source = result["design"]["profile_constraints"]
    unique = (
        float(source["unique_input_relative_error_max"]),
        float(source["unique_root_relative_error_max"]),
    )
    histogram = (
        float(source["input_occurrence_histogram_tv_max"]),
        float(source["root_occurrence_histogram_tv_max"]),
    )
    marginal_names = (
        "extra_family_axis_tv_max", "task_kind_tv_max", "view_tv_max",
        "candidate_count_tv_max", "open_world_tv_max", "probability_source_tv_max",
    )
    marginals = tuple(float(source[name]) for name in marginal_names)
    if len(set(unique)) != 1 or len(set(histogram)) != 1 or len(set(marginals)) != 1:
        raise ValueError("the frozen implementation requires equal per-axis profile tolerances")
    if unique[0] != histogram[0] or unique[0] != marginals[0]:
        # The implementation accepts one scalar per family of checks, so this
        # adapter is valid only for the prospectively frozen common .02 limit.
        raise ValueError("frozen profile tolerances cannot be represented by the implementation aliases")
    source["unique_relative_error_max"] = unique[0]
    source["occurrence_histogram_tv_max"] = histogram[0]
    source["marginal_tv_max"] = marginals[0]
    return result


def verify_v02_state() -> dict[str, Any]:
    contract = parent_adapter.verify_v02_receipt()
    names = sorted(path.name for path in V02_DIR.iterdir())
    if names != ["freeze-receipt.json"]:
        raise ValueError(f"v02 is not the expected pre-output contract-key abort state: {names}")
    return contract


def build_receipt(contract: dict[str, Any]) -> dict[str, Any]:
    parent_receipt = read_json(parent_adapter.V02_FREEZE)
    sources = dict(parent_receipt["repository_sources"])
    for relative in ADAPTER_SOURCES:
        sources[relative] = sha256_file(ROOT / relative)
    return {
        "protocol": contract["protocol"],
        "execution_adapter": ADAPTER_ID,
        "status": "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION",
        "contract_sha256": sha256_file(core.CONTRACT_PATH),
        "repository_sources": sources,
        "external_inputs": dict(parent_receipt["external_inputs"]),
        "parent_v02_freeze": {
            "path": str(parent_adapter.V02_FREEZE),
            "sha256": sha256_file(parent_adapter.V02_FREEZE),
        },
        "execution_correction": {
            "path_locator_filtered": True,
            "profile_tolerance_aliases": {
                "unique_relative_error_max": "min(input,root); both frozen values equal 0.02",
                "occurrence_histogram_tv_max": "min(input,root); both frozen values equal 0.02",
                "marginal_tv_max": "minimum of all six frozen marginal limits; all equal 0.02",
            },
            "scientific_contract_changed": False,
            "scientific_thresholds_changed": False,
            "v02_source_rows_scanned": True,
            "v02_output_artifact_files": [],
        },
        "authorization": dict(parent_receipt["authorization"]),
    }


def freeze() -> int:
    if V03_DIR.exists():
        raise FileExistsError(f"refusing to reuse v0.8D v03 run directory: {V03_DIR}")
    contract = verify_v02_state()
    normalized = normalize_profile_tolerances(contract)
    receipt = build_receipt(normalized)
    V03_DIR.mkdir(parents=True, exist_ok=False)
    with V03_FREEZE.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": receipt["status"],
        "execution_adapter": ADAPTER_ID,
        "contract_sha256": receipt["contract_sha256"],
        "parent_v02_freeze_sha256": receipt["parent_v02_freeze"]["sha256"],
        "run_directory": str(V03_DIR),
        "normalized_limits": {
            "unique": normalized["design"]["profile_constraints"]["unique_relative_error_max"],
            "occurrence_histogram_tv": normalized["design"]["profile_constraints"]["occurrence_histogram_tv_max"],
            "marginal_tv": normalized["design"]["profile_constraints"]["marginal_tv_max"],
        },
    }, separators=(",", ":")))
    return 0


def verify_v03_receipt() -> dict[str, Any]:
    if not V03_FREEZE.is_file():
        raise FileNotFoundError("v0.8D v03 is not frozen; run with 'freeze' first")
    receipt = read_json(V03_FREEZE)
    if receipt.get("status") != "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION":
        raise ValueError("v0.8D v03 freeze status mismatch")
    if receipt.get("execution_adapter") != ADAPTER_ID:
        raise ValueError("v0.8D v03 adapter identity mismatch")
    if receipt.get("contract_sha256") != sha256_file(core.CONTRACT_PATH):
        raise ValueError("v0.8D v03 contract hash mismatch")
    if sha256_file(parent_adapter.V02_FREEZE) != receipt["parent_v02_freeze"]["sha256"]:
        raise ValueError("v0.8D v02 parent freeze changed")
    for relative, expected in receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"v0.8D v03 frozen source changed: {relative}")
    for name, item in receipt["external_inputs"].items():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"v0.8D v03 frozen input changed: {name}")
    contract = verify_v02_state()
    normalized = normalize_profile_tolerances(contract)
    core.verify_source_authority(normalized)
    return normalized


def run() -> int:
    contract = verify_v03_receipt()
    core.RUN_DIR = V03_DIR
    core.FREEZE_PATH = V03_FREEZE
    core.verify_freeze = verify_v03_receipt
    return core.main()


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"freeze", "run"}:
        raise SystemExit("usage: execute_v08d_runner_v03.py {freeze|run}")
    return freeze() if sys.argv[1] == "freeze" else run()


if __name__ == "__main__":
    raise SystemExit(main())
