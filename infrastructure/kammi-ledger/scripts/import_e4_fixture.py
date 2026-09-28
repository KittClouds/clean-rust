"""Disposable E4-0 import proving future Merkle successors stay compact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.core import Ledger

WORKSPACE = Path(
    r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust"
)
BASE = WORKSPACE / "experiments/fas-frozen-observer-bundle-engineering-v01"
SEAL = BASE / "seals/e4-0-contract-v16-v09-seal.json"
CONTRACT = BASE / "contracts/e4-0-contract-v16-v09-final.json"
HERE = Path(__file__).resolve().parents[1]
AUDIT = HERE / "acceptance/e4-0/legacy-flat-verification-v1.json"
OUTPUT = HERE / "acceptance/e4-0/merkle-import-v1.json"
STORE = HERE / ".kammi-dev/e4-import"


def request_for(label: str) -> str:
    return "e4-legacy-" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if audit["status"] != "PASS" or audit["verified_entries"] != 447:
        raise ValueError("legacy flat audit must pass first")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    ledger = Ledger(STORE)
    members: set[str] = set()
    for entry in seal["entries"]:
        source = WORKSPACE / entry["path"]
        artifact_id, _ = ledger.register_file(
            source,
            kind="legacy-e4-member",
            media_type="application/octet-stream",
            schema_id="FAS_E4_0_ARTIFACT_SEAL_V01-member",
            actor="chief-kammi",
            request_id=request_for("member:" + entry["artifact_id"]),
        )
        if artifact_id[7:] != entry["sha256"]:
            raise ValueError("fixture changed during import")
        members.add(artifact_id)
    base_root, _ = ledger.create_seal(
        sorted(members), [], "chief-kammi", request_for("base-seal")
    )
    seal_id, _ = ledger.register_file(
        SEAL, kind="legacy-seal", media_type="application/json",
        schema_id="FAS_E4_0_ARTIFACT_SEAL_V01",
        actor="chief-kammi", request_id=request_for("legacy-seal-file"),
    )
    contract_id, _ = ledger.register_file(
        CONTRACT, kind="legacy-scientific-contract", media_type="application/json",
        schema_id="FAS_E4_0_CONTRACT_V16_V09",
        actor="chief-kammi", request_id=request_for("legacy-contract-file"),
    )
    successor_root, _ = ledger.create_seal(
        [seal_id, contract_id], [base_root],
        "chief-kammi", request_for("successor-seal"),
    )
    closure = ledger.verify_seal(successor_root)
    successor_payload = json.loads(ledger.cas.get(ledger.seal_artifacts[successor_root]))
    report = {
        "schema": "KAMMI_E4_LEGACY_MERKLE_IMPORT_V1",
        "status": "PASS",
        "legacy_entry_count": seal["entry_count"],
        "unique_legacy_byte_objects": len(members),
        "base_root": base_root,
        "successor_root": successor_root,
        "successor_direct_member_count": len(successor_payload["direct_members"]),
        "successor_parent_count": len(successor_payload["parents"]),
        "successor_verified_closure_count": len(closure),
        "projection": ledger.status(),
        "disposable_store": str(STORE),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "base_root": base_root,
        "successor_root": successor_root,
        "direct": report["successor_direct_member_count"],
        "parents": report["successor_parent_count"],
        "closure": report["successor_verified_closure_count"],
    }))


if __name__ == "__main__":
    main()

