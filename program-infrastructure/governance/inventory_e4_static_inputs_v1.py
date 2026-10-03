"""Hash only the visible inherited inputs needed by E4 online parity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
RUN = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-v01")
OLD_BINDING = LAB / "audits/e4-0-auth-issuer-v02/online-parity-bindings-v01.json"
OLD_AUTH = LAB / "audits/e4-0-auth-issuer-v02/online-parity-authorization-v01.json"
OUT = Path(__file__).parent / "inbox/20260927/E4-0-STATIC-INPUT-INVENTORY-v1.json"
ROLES = (
    "e4_contract", "e4_contract_seal_manifest", "e4_contract_audit",
    "e1_audit", "e2_audit", "e3_audit", "population_seal",
    "population_audit", "population_inputs", "population_rows",
    "parity_panel_seal", "parity_inputs", "parity_rows",
    "parity_selection_receipt", "representation_abi", "model_manifest",
    "tokenizer_manifest", "e2_cache", "e3_bundle",
)


def digest(path: Path) -> dict:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return {"path": str(path.resolve(strict=True)), "sha256": h.hexdigest(), "bytes": size}


def main():
    old = json.loads(OLD_BINDING.read_bytes())
    prior = json.loads(OLD_AUTH.read_bytes())
    paths = dict(old["artifacts"])
    paths.update({
        "e4_contract": str(LAB / "contracts/e4-0-contract-v16-v09-final.json"),
        "e4_contract_seal_manifest": str(LAB / "seals/e4-0-contract-v16-v09-seal.json"),
        "e4_contract_audit": str(LAB / "audits/e4-0-track-e/track-e-postseal-receipt-v16-v11.json"),
        "population_inputs": str(RUN / "population/panel-inputs-v01.jsonl"),
        "population_rows": str(RUN / "population/row-manifest-v01.jsonl"),
    })
    if set(ROLES) - set(paths):
        raise ValueError("missing static parity role")
    entries = {}
    for role in ROLES:
        path = Path(paths[role])
        if any(part.lower() == "labels" for part in path.parts):
            raise ValueError("protected label path entered visible inventory")
        entry = digest(path)
        older = prior.get("artifacts", {}).get(role)
        if older and role not in {"e4_contract", "e4_contract_seal_manifest", "e4_contract_audit"}:
            if (older.get("sha256"), older.get("bytes")) != (entry["sha256"], entry["bytes"]):
                raise ValueError("visible input differs from prior sealed identity: " + role)
        entries[role] = entry
    if entries["e4_contract"]["sha256"] != "21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f":
        raise ValueError("current E4 contract identity changed")
    result = {"schema": "CHIEF_E4_0_STATIC_INPUT_INVENTORY_V1",
              "status": "PARITY_VISIBLE_INPUTS_HASHED",
              "scope": "Current v16-v09 contract plus inherited visible parity inputs; no protected label bytes opened. Prior v06 path map is provenance, not authorization.",
              "source_path_map": digest(OLD_BINDING),
              "source_prior_authorization": digest(OLD_AUTH),
              "artifacts": entries, "paths": old["paths"],
              "e4_0_authorization_issued": False,
              "extraction_dynamic_inputs_ready": False,
              "protected_label_bytes_opened": False}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "roles": len(entries),
                      "output": str(OUT)}))


if __name__ == "__main__":
    main()
