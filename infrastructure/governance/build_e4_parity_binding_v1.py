"""Chief-only visible static binding for a corrected Fabrique parity adapter."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
INVENTORY = HERE / "inbox/20260927/E4-0-STATIC-INPUT-INVENTORY-v1.json"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
OLD_AUTH = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01/"
    "audits/e4-0-auth-issuer-v02/online-parity-authorization-v01.json"
)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_bytes())
    inventory = json.loads(INVENTORY.read_bytes())
    old = json.loads(OLD_AUTH.read_bytes())
    if (not isinstance(plan.get("status"), str)
            or not plan["status"].startswith("FABRIQUE_CANDIDATE_")
            or not plan["status"].endswith("NOT_REGISTERED_NOT_AUTHORIZED")):
        raise ValueError("Fabrique plan is not a candidate-only spec")
    if inventory["status"] != "PARITY_VISIBLE_INPUTS_HASHED":
        raise ValueError("visible input inventory is not qualified")
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    status = client.status()
    if status["flight_gate"] != "OPEN" or plan["library_acceptance_id"] != status["acceptance_identity"]:
        raise ValueError("candidate plan does not bind current Library acceptance")
    modes = [stage for stage in plan["stages"] if stage["mode"] == "parity"]
    if len(modes) != 1:
        raise ValueError("candidate plan needs one parity stage")
    parity = modes[0]
    if Path(parity["output_root"]).exists():
        raise ValueError("fresh parity output root already exists")
    module_spec = importlib.util.spec_from_file_location("e4_corrected_adapter", args.adapter)
    if module_spec is None or module_spec.loader is None:
        raise ValueError("corrected adapter cannot be loaded")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if plan["adapter_id"] != module.ADAPTER_ID:
        raise ValueError("adapter identity differs from candidate plan")
    current = inventory["artifacts"]
    roots = old["exact_predecessor_roots"]
    binding = {
        "schema": module.SCHEMA, "adapter_id": module.ADAPTER_ID,
        "mode": "parity", "stage": "ONLINE_CACHE_PARITY",
        "contract_sha256": current["e4_contract"]["sha256"],
        "contract_seal_manifest_sha256": current["e4_contract_seal_manifest"]["sha256"],
        "contract_seal_root_sha256": plan["scientific_contract_seal_root_sha256"],
        "output_root": plan["shared_e4_output_root"],
        "supervised_output_root": parity["output_root"],
        "inherited_stage_root": plan["inherited_stage_root"],
        "expected_outputs": parity["expected_outputs"],
        "exact_predecessor_roots": roots,
        "artifacts": current,
        "paths": inventory["paths"],
        "library_handoff": {
            "library_acceptance_id": status["acceptance_identity"],
            "handoff_seal_root_sha256": plan["library_handoff_seal_root_sha256"],
            "visible_inheritance_bridge_root_sha256": plan["visible_inheritance_bridge_root_sha256"],
        },
    }
    module.validate_binding_document(binding, "parity")
    for role, item in current.items():
        path = Path(item["path"])
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("visible input changed since inventory: " + role)
    output = Path(parity["binding_path"])
    if output.exists():
        raise ValueError("static binding path exists; preserve prior attempt")
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(binding, indent=2, sort_keys=True) + "\n").encode()
    with output.open("xb") as stream:
        stream.write(encoded)
    loaded, actual = module.load_binding(output, "parity")
    if loaded != binding or actual != hashlib.sha256(encoded).hexdigest():
        raise ValueError("static binding replay differs")
    print(json.dumps({"path": str(output), "sha256": actual,
                      "bytes": len(encoded), "roles": len(current),
                      "model_contact": False}))


if __name__ == "__main__":
    main()
