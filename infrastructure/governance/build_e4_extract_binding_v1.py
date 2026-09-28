"""Chief constructs the visible-only E4 extraction binding after parity."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
ADAPTER = LAB / "source/scripts/e4_supervised_execution_adapter_v02.py"
PLAN = LAB / "plans/E4-0-LEDGER-EXECUTION-SPEC-CANDIDATES-v02.json"
ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-ledger-run-v02")
PARITY_BINDING = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01"
                      r"\e4-0-ledger-bindings-v02\online-cache-parity-binding-v02.json")
AUDIT = INBOX / "E4-0-PARITY-CUSTODY-AUDIT-v1.json"


def artifact(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("prerequisite is absent or linked: " + str(path))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve(strict=True)), "sha256": digest,
            "bytes": path.stat().st_size}


def main() -> None:
    plan = json.loads(PLAN.read_bytes())
    stage, = (item for item in plan["stages"] if item["mode"] == "extract-e4")
    parity_binding = json.loads(PARITY_BINDING.read_bytes())
    audit = json.loads(AUDIT.read_bytes())
    parity_seal = json.loads((ROOT / "parity/stage-seal-v01.json").read_bytes())
    if audit["status"] != "PASS_SUPERVISED_OUTPUT_CUSTODY":
        raise ValueError("Chief parity custody audit did not pass")
    if parity_binding["mode"] != "parity" or parity_seal["status"] != "SEALED":
        raise ValueError("prior parity binding or seal differs")
    if Path(stage["output_root"]).exists():
        raise ValueError("fresh feature output root already exists")
    module_spec = importlib.util.spec_from_file_location("e4_supervised_adapter", ADAPTER)
    if module_spec is None or module_spec.loader is None:
        raise ValueError("adapter module cannot be loaded")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    artifacts = {key: value for key, value in parity_binding["artifacts"].items()
                 if key not in {"e2_cache", "e3_bundle"}}
    output_artifacts = {
        "parity_receipt_seal": ROOT / "parity/stage-seal-v01.json",
        "parity_receipt": ROOT / "parity/parity-receipt-v01.json",
        "online_feature_cache": ROOT / "parity/parity-online-features.f32le",
    }
    artifacts.update({key: artifact(path) for key, path in output_artifacts.items()})
    roots = {**parity_binding["exact_predecessor_roots"],
             "e4_parity_receipt_root_sha256": parity_seal["root_sha256"]}
    binding = {**parity_binding,
               "mode": "extract-e4", "stage": "FRESH_FEATURE_EXTRACTION",
               "supervised_output_root": stage["output_root"],
               "expected_outputs": stage["expected_outputs"],
               "exact_predecessor_roots": roots, "artifacts": artifacts}
    module.validate_binding_document(binding, "extract-e4")
    if set(artifacts) != module.COMMON_ARTIFACTS | module.MODE_ARTIFACTS["extract-e4"]:
        raise ValueError("derived extraction artifact inventory differs")
    for name, entry in artifacts.items():
        if artifact(Path(entry["path"])) != entry:
            raise ValueError("visible predecessor changed: " + name)
    output = Path(stage["binding_path"])
    if output.exists():
        raise ValueError("extract binding path exists; preserve previous attempt")
    encoded = (json.dumps(binding, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with output.open("xb") as stream:
        stream.write(encoded)
    loaded, digest = module.load_binding(output, "extract-e4")
    if loaded != binding or digest != hashlib.sha256(encoded).hexdigest():
        raise ValueError("extract binding replay differs")
    print(json.dumps({"path": str(output), "sha256": digest, "bytes": len(encoded),
                      "roles": len(artifacts), "parity_root": parity_seal["root_sha256"],
                      "model_contact": False}))


if __name__ == "__main__":
    main()
