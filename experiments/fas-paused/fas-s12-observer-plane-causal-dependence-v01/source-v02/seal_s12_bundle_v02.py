from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from s12_math import canonical_json, entry, sha256_file, tree_root


PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s12-observer-plane-causal-dependence-v01")
RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02")
SOURCE = PROJECT / "source-v02"
SOURCE_NAMES = (
    "analyze_s12_v02.py",
    "import_s12_v01_gates_v02.py",
    "linear_core.py",
    "run_s12_v02.py",
    "s12_math.py",
    "seal_s12_bundle_v02.py",
    "seal_s12_result_v02.py",
    "test_s12_analysis_v02.py",
    "test_s12_math.py",
    "verify_s12_analysis_v02.py",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"missing S12 bundle input: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256_file(source) != sha256_file(destination):
        raise RuntimeError(f"S12 bundle copy mismatch: {destination}")


def main() -> int:
    seal_path = RUN / "inputs" / "protocol-bundle-seal-v02.json"
    if seal_path.exists():
        raise RuntimeError("S12 v02 protocol bundle is already sealed")
    for relative in (
        "FAS-S12-PROTOCOL-V02.md",
        "s12-execution-contract-v02.json",
        "S12-V02-CONTROL-PLANE-CHECK.md",
    ):
        if relative == "s12-execution-contract-v02.json":
            project_file = PROJECT / "contracts" / relative
        elif relative == "FAS-S12-PROTOCOL-V02.md":
            project_file = PROJECT / relative
        else:
            project_file = PROJECT / "corrections" / relative
        target = RUN / "inputs" / "protocol" / Path(relative).name
        copy_file(project_file, target)
    for name in SOURCE_NAMES:
        copy_file(SOURCE / name, RUN / "source" / name)

    code_entries = [entry(RUN / "source" / name, RUN) for name in SOURCE_NAMES]
    code_entries.sort(key=lambda item: item["path"])
    code_root = tree_root(code_entries)
    code_manifest = {"manifest_id": "FAS_S12_IMPLEMENTATION_CODE_MANIFEST_V02", "entries": code_entries, "code_root_sha256": code_root}
    (RUN / "implementation-code-manifest-v02.json").write_bytes(canonical_json(code_manifest) + b"\n")

    contract_path = RUN / "inputs" / "protocol" / "s12-execution-contract-v02.json"
    contract = read_json(contract_path)
    required = [
        contract["parents"]["parent_binding_path"],
        contract["parents"]["preparation_receipt_path"],
        contract["parents"]["plane_bank"]["path"],
        contract["parents"]["source_centers"]["path"],
        contract["parents"]["bootstrap_plan"]["path"],
        contract["parents"]["repeat_quartets"]["path"],
        "reused-v01-gates-receipt-v02.json",
    ]
    required.extend(f"base-parity-v02/{name}" for name in ("base-parity-rows-v02.jsonl", "base-parity-receipt-v02.json", "base-parity-seal-v02.json"))
    required.extend(f"baseline-v02/{name}" for name in ("baseline-probe-logits-v02.f32le", "baseline-probe-probabilities-v02.f32le", "baseline-predictions-v02.i64le", "baseline-replay-receipt-v02.json", "baseline-seal-v02.json"))
    for relative in required:
        if not (RUN / relative).is_file():
            raise RuntimeError(f"S12 v02 sealed input missing: {relative}")
    for key, path_key in (("parent_binding_sha256", "parent_binding_path"), ("preparation_receipt_sha256", "preparation_receipt_path")):
        if sha256_file(RUN / contract["parents"][path_key])[0] != contract["parents"][key]:
            raise RuntimeError(f"S12 v02 parent input hash mismatch: {key}")
    for key in ("plane_bank", "source_centers", "bootstrap_plan", "repeat_quartets"):
        item = contract["parents"][key]
        if sha256_file(RUN / item["path"])[0] != item["sha256"]:
            raise RuntimeError(f"S12 v02 frozen parent hash mismatch: {key}")

    bundle_relatives = [
        "inputs/protocol/FAS-S12-PROTOCOL-V02.md",
        "inputs/protocol/s12-execution-contract-v02.json",
        "inputs/protocol/S12-V02-CONTROL-PLANE-CHECK.md",
        "implementation-code-manifest-v02.json",
        *required,
        *[f"source/{name}" for name in SOURCE_NAMES],
    ]
    entries = [entry(RUN / relative, RUN) for relative in bundle_relatives]
    entries.sort(key=lambda item: item["path"])
    bundle = {"seal_id": "FAS_S12_PROTOCOL_BUNDLE_SEAL_V02", "entries": entries, "root_sha256": tree_root(entries)}
    seal_path.write_bytes(canonical_json(bundle) + b"\n")
    actual = [entry(RUN.joinpath(*item["path"].split("/")), RUN) for item in entries]
    if actual != entries or tree_root(actual) != bundle["root_sha256"]:
        raise RuntimeError("S12 v02 bundle failed immediate hash verification")
    print(json.dumps({"protocol_bundle_root_sha256": bundle["root_sha256"], "code_root_sha256": code_root, "entries": len(entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
