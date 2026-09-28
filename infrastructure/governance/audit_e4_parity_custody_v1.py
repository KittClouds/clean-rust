"""Chief audits the supervised E4 parity return without opening labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
HANDOFF = INBOX / "E4-0-PARITY-HANDOFF-ISSUED-v1.json"
AUDIT = INBOX / "E4-0-PARITY-CUSTODY-AUDIT-v1.json"
ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-ledger-run-v02")
RECEIPTS = ROOT / "ledger-receipts"
PARITY = ROOT / "parity"
PARENT_SEAL = "sha256:b9c89f4006e578dd78d9e35601e1917fce4f10ce67310809fb68b90b8c762a19"


def file_id(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("returned artifact missing or linked: " + str(path))
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_bytes())


def main() -> None:
    if AUDIT.exists():
        raise ValueError("custody audit already exists")
    handoff = read_json(HANDOFF)
    result, finish, release = (
        read_json(RECEIPTS / name) for name in ("RESULT.json", "FINISH.json", "RELEASE.json")
    )
    parity = read_json(PARITY / "parity-receipt-v01.json")
    seal = read_json(PARITY / "stage-seal-v01.json")
    expected = {"parity-online-features.f32le", "parity-receipt-v01.json", "stage-seal-v01.json"}
    if set(result["outputs"]) != expected:
        raise ValueError("returned output inventory differs from the bound spec")
    if result["status"] != "OUTPUTS_REGISTERED" or result["exit_code"] != 0:
        raise ValueError("worker did not register clean outputs")
    if finish["outcome"] != "COMPLETE" or not release.get("event_id"):
        raise ValueError("finish or lease release was not recorded")
    for key in ("run_id", "stage_id", "authorization_id", "lease_id", "fencing_token"):
        if result[key] != handoff[key]:
            raise ValueError("worker result scope differs: " + key)
    if result["library_acceptance"] != handoff["library_acceptance_id"]:
        raise ValueError("worker used a different Library acceptance")
    output_hashes = {}
    for name, entry in result["outputs"].items():
        path = PARITY / name
        actual = file_id(path)
        if actual != entry["artifact_id"] or path.stat().st_size != entry["bytes"]:
            raise ValueError("registered output differs from current bytes: " + name)
        output_hashes[name] = actual
    if parity["online_feature_sha256"] != output_hashes["parity-online-features.f32le"].split(":", 1)[1]:
        raise ValueError("parity receipt feature identity differs")
    for entry in seal["entries"]:
        name = Path(entry["path"]).name
        if name not in output_hashes or "sha256:" + entry["sha256"] != output_hashes[name]:
            raise ValueError("lab stage seal entry differs: " + name)
    if parity["status"] != "ONLINE_CACHE_PARITY_PASS":
        raise ValueError("lab parity receipt does not claim pass")

    admin = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    actor = KammiClient(admin.base_url, (OP / "fabrique-e4-supervisor-v1.secret").read_text().strip())
    fence = actor.call("POST", f"/v1/leases/{handoff['lease_id']}/validate", {
        "actor_id": handoff["actor_id"], "run_id": handoff["run_id"],
        "resource_id": handoff["resource_id"], "fencing_token": handoff["fencing_token"],
    })
    if fence["valid"]:
        raise ValueError("released GPU fence remains live")
    status = admin.status()
    if status["journal_head"] != status["projection_head"]:
        raise ValueError("custody projection is not at journal head")
    audit = {
        "schema": "CHIEF_E4_0_PARITY_CUSTODY_AUDIT_V1",
        "status": "PASS_SUPERVISED_OUTPUT_CUSTODY",
        "scope": "output identities, worker completion, returned stage entries, released fence; no independent scientific parity recomputation",
        "run_id": handoff["run_id"], "stage_id": handoff["stage_id"],
        "authorization_id": handoff["authorization_id"],
        "lease_id": handoff["lease_id"], "fencing_token": handoff["fencing_token"],
        "model_launch_contact_event": result["model_launch_contact_event"],
        "finish_event": finish["event_id"], "release_event": release["event_id"],
        "output_artifact_ids": output_hashes,
        "parity_receipt_claim": parity["status"],
        "lab_stage_seal_root_claim": seal["root_sha256"],
        "fence_valid_after_release": fence["valid"],
        "library_acceptance_id": status["acceptance_identity"],
        "journal_projection_match": True,
        "protected_label_bytes_opened_by_chief": False,
        "e4_01_entry_open": False,
    }
    with AUDIT.open("x", encoding="utf-8") as stream:
        json.dump(audit, stream, indent=2)
        stream.write("\n")
    artifact = admin.register_file(AUDIT, "e4-parity-custody-audit", "chief-kammi",
                                   "chief-e4-parity-audit-v1:artifact")["artifact_id"]
    seal_result = admin.create_seal([artifact, *output_hashes.values()], [PARENT_SEAL],
                                    "chief-kammi", "chief-e4-parity-audit-v1:seal")
    print(json.dumps({"status": audit["status"], "audit_artifact": artifact,
                      "seal_root": seal_result["root"], "fence_valid": fence["valid"]}))


if __name__ == "__main__":
    main()
