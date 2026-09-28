from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from s12_math import canonical_json, entry, sha256_file, tree_root


PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s12-observer-plane-causal-dependence-v01")
RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v01")
SOURCE_NAMES = (
    "analyze_s12_v01.py",
    "linear_core.py",
    "prepare_s12_v01.py",
    "run_s12_v01.py",
    "seal_s12_result_v01.py",
    "s12_math.py",
    "seal_s12_bundle_v01.py",
    "test_s12_analysis.py",
    "test_s12_math.py",
    "verify_s12_analysis_v01.py",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_frozen(source: Path, destination: Path) -> None:
    if destination.exists():
        if sha256_file(source)[0] != sha256_file(destination)[0]:
            raise RuntimeError(f"refusing to replace an existing frozen bundle file: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256_file(source) != sha256_file(destination):
        raise RuntimeError(f"copy verification failed: {destination}")


def main() -> int:
    seal_path = RUN / "inputs" / "protocol-bundle-seal-v01.json"
    if seal_path.exists():
        raise RuntimeError("S12 protocol bundle is already sealed; preserve it and use a versioned bundle")
    for relative in (
        "FAS-S12-PROTOCOL-V01.md",
        "contracts/s12-execution-contract-v01.json",
    ):
        source = PROJECT / relative
        target = RUN / "inputs" / "protocol" / Path(relative).name
        copy_frozen(source, target)
    for name in SOURCE_NAMES:
        copy_frozen(PROJECT / "source" / name, RUN / "source" / name)

    run_root_entries = [entry(RUN / "source" / name, RUN) for name in SOURCE_NAMES]
    run_root_entries.sort(key=lambda item: item["path"])
    code_root = tree_root(run_root_entries)
    code_manifest = {
        "manifest_id": "FAS_S12_IMPLEMENTATION_CODE_MANIFEST_V01",
        "entries": run_root_entries,
        "code_root_sha256": code_root,
    }
    code_manifest_path = RUN / "implementation-code-manifest-v01.json"
    if code_manifest_path.exists():
        raise RuntimeError("S12 code manifest already exists without a protocol seal")
    code_manifest_path.write_bytes(canonical_json(code_manifest) + b"\n")

    contract = read_json(RUN / "inputs" / "protocol" / "s12-execution-contract-v01.json")
    required_inputs = [
        contract["parents"]["parent_binding_path"],
        contract["parents"]["preparation_receipt_path"],
        contract["parents"]["plane_bank"]["path"],
        contract["parents"]["source_centers"]["path"],
        contract["parents"]["bootstrap_plan"]["path"],
        contract["parents"]["repeat_quartets"]["path"],
    ]
    for relative in required_inputs:
        path = RUN / relative
        if not path.is_file():
            raise RuntimeError(f"S12 sealed preparation input is missing: {relative}")
    for key in ("parent_binding_sha256", "preparation_receipt_sha256"):
        path = RUN / contract["parents"]["parent_binding_path" if key == "parent_binding_sha256" else "preparation_receipt_path"]
        if sha256_file(path)[0] != contract["parents"][key]:
            raise RuntimeError(f"S12 preparation identity mismatch: {key}")
    for key in ("plane_bank", "source_centers", "bootstrap_plan", "repeat_quartets"):
        item = contract["parents"][key]
        if sha256_file(RUN / item["path"])[0] != item["sha256"]:
            raise RuntimeError(f"S12 preparation artifact hash mismatch: {key}")

    bundle_relatives = [
        "inputs/protocol/FAS-S12-PROTOCOL-V01.md",
        "inputs/protocol/s12-execution-contract-v01.json",
        "implementation-code-manifest-v01.json",
        "inputs/parent-binding-v01.json",
        "preparation-receipt-v01.json",
        "inputs/plane-bank-v01.f64le",
        "inputs/source-centers-v01.f64le",
        "inputs/bootstrap-plan-v01.u32le",
        "inputs/repeat-quartets-v01.json",
        *[f"source/{name}" for name in SOURCE_NAMES],
    ]
    bundle_entries = [entry(RUN / relative, RUN) for relative in bundle_relatives]
    bundle_entries.sort(key=lambda item: item["path"])
    bundle = {
        "seal_id": "FAS_S12_PROTOCOL_BUNDLE_SEAL_V01",
        "entries": bundle_entries,
        "root_sha256": tree_root(bundle_entries),
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal_path.write_bytes(canonical_json(bundle) + b"\n")
    verify = read_json(seal_path)
    actual = [entry(RUN.joinpath(*item["path"].split("/")), RUN) for item in verify["entries"]]
    if actual != verify["entries"] or tree_root(actual) != verify["root_sha256"]:
        raise RuntimeError("S12 protocol bundle failed immediate independent hash verification")
    print(json.dumps({"protocol_bundle_root_sha256": verify["root_sha256"], "entries": len(actual), "code_root_sha256": code_root}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
