"""Chief reconciles E4 extraction outputs and the released Ledger fence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
LAB_RECEIPT = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust"
                   r"\experiments\fas-frozen-observer-bundle-engineering-v01"
                   r"\audits\e4-0-supervised-adapter-v02\ledger-extract-execution-receipt-v01.json")
HANDOFF = INBOX / "E4-0-EXTRACT-HANDOFF-ISSUED-v1.json"
OUT = INBOX / "E4-0-EXTRACT-CUSTODY-AUDIT-v1.json"
ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-ledger-run-v02")
RECEIPTS = ROOT / "extract-ledger-receipts"
FEATURES = ROOT / "features"
PARENT_SEAL = "sha256:7bc911f8ae01d99c309e8a5307340af2be1ead61d8c36a558acf1b9a9734ff8d"
LAB_RECEIPT_ID = "sha256:a8e3d844ecade6020d2c3b9bc7d61d6b870704ad9b1542a65daa61f1edde3a85"


def file_id(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("returned file is missing or linked: " + str(path))
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_bytes())


def seal_root(entries: list[dict]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8")):
        digest.update(f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode("utf-8"))
    return digest.hexdigest()


def main() -> None:
    if OUT.exists():
        raise ValueError("extract custody audit already exists")
    handoff = read_json(HANDOFF)
    result = read_json(RECEIPTS / "RESULT.json")
    finish = read_json(RECEIPTS / "FINISH.json")
    release = read_json(RECEIPTS / "RELEASE.json")
    runner = read_json(FEATURES / "feature-extraction-receipt-v01.json")
    stage_seal = read_json(FEATURES / "stage-seal-v01.json")
    lab_receipt = read_json(LAB_RECEIPT)
    if file_id(LAB_RECEIPT) != LAB_RECEIPT_ID:
        raise ValueError("lab extraction disposition bytes changed")
    if result["status"] != "OUTPUTS_REGISTERED" or result["exit_code"] != 0:
        raise ValueError("supervised worker did not complete outputs")
    if finish["outcome"] != "COMPLETE" or not release.get("event_id"):
        raise ValueError("Ledger finish or release is missing")
    for key in ("run_id", "stage_id", "authorization_id", "lease_id", "fencing_token"):
        if result[key] != handoff[key]:
            raise ValueError("returned scope differs from handoff: " + key)
    if result["library_acceptance"] != handoff["library_acceptance_id"]:
        raise ValueError("Library acceptance changed during worker return")
    expected_names = {"V1_FINAL_POSITION.f32le", "feature-extraction-receipt-v01.json",
                      "population-row-manifest-v01.jsonl", "stage-seal-v01.json"}
    if set(result["outputs"]) != expected_names:
        raise ValueError("output inventory differs from frozen execution spec")
    outputs = {}
    for name, item in result["outputs"].items():
        path = FEATURES / name
        digest = file_id(path)
        if digest != item["artifact_id"] or path.stat().st_size != item["bytes"]:
            raise ValueError("returned output differs from Ledger registration: " + name)
        outputs[name] = digest
    if runner["status"] != "FEATURE_CACHE_COMPLETE_GATE_PASS":
        raise ValueError("runner receipt does not report cache gate pass")
    feature = runner["feature_cache"]
    if (feature["rows"], feature["dimension"], feature["bytes"]) != (149336, 2048, 1223360512):
        raise ValueError("frozen feature geometry differs")
    if "sha256:" + feature["sha256"] != outputs["V1_FINAL_POSITION.f32le"]:
        raise ValueError("feature receipt hash differs")
    if (stage_seal["status"] != "SEALED" or stage_seal["stage"] != "FRESH_FEATURE_EXTRACTION"
            or stage_seal["entry_count"] != len(stage_seal["entries"])):
        raise ValueError("feature stage seal shape differs")
    for entry in stage_seal["entries"]:
        name = Path(entry["path"]).name
        if outputs.get(name) != "sha256:" + entry["sha256"] or result["outputs"][name]["bytes"] != entry["bytes"]:
            raise ValueError("stage seal entry differs: " + name)
    actual_root = seal_root(stage_seal["entries"])
    if actual_root != stage_seal["root_sha256"]:
        raise ValueError("feature stage seal root does not recompute")
    if runner["labels_opened"] or runner["scoring_performed"] or runner["predictions_emitted"]:
        raise ValueError("extraction receipt claims forbidden truth/scoring contact")
    if lab_receipt["status"] != "FEATURE_EXTRACTION_PASS_ARTIFACTS_VERIFIED_NO_SCORING":
        raise ValueError("lab extraction disposition is not pass")

    admin = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    actor = KammiClient(admin.base_url, (OP / "fabrique-e4-supervisor-v1.secret").read_text().strip())
    fence = actor.call("POST", f"/v1/leases/{handoff['lease_id']}/validate", {
        "actor_id": handoff["actor_id"], "run_id": handoff["run_id"],
        "resource_id": handoff["resource_id"], "fencing_token": handoff["fencing_token"],
    })
    if fence["valid"]:
        raise ValueError("released extraction fence remains valid")
    status = admin.status()
    if status["journal_head"] != status["projection_head"]:
        raise ValueError("custody projection is behind journal")
    audit = {
        "schema": "CHIEF_E4_0_EXTRACT_CUSTODY_AUDIT_V1",
        "status": "PASS_SUPERVISED_FEATURE_CUSTODY",
        "scope": "worker completion, output hashes and sizes, lab seal root, released fence; no primary truth opened",
        "run_id": handoff["run_id"], "stage_id": handoff["stage_id"],
        "authorization_id": handoff["authorization_id"],
        "model_launch_contact_event": result["model_launch_contact_event"],
        "finish_event": finish["event_id"], "release_event": release["event_id"],
        "output_artifact_ids": outputs,
        "feature_stage_seal_root": actual_root,
        "lab_execution_receipt_sha256": LAB_RECEIPT_ID,
        "fence_valid_after_release": False,
        "library_acceptance_id": status["acceptance_identity"],
        "journal_projection_match": True,
        "protected_label_bytes_opened_by_chief": False,
        "primary_scoring_authorized": False,
        "e4_01_entry_open": False,
    }
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(audit, stream, indent=2)
        stream.write("\n")
    lab_artifact = admin.register_file(LAB_RECEIPT, "e4-extract-lab-disposition", "chief-kammi",
                                       "chief-e4-extract-audit-v1:lab-receipt")["artifact_id"]
    audit_artifact = admin.register_file(OUT, "e4-extract-custody-audit", "chief-kammi",
                                         "chief-e4-extract-audit-v1:audit")["artifact_id"]
    seal = admin.create_seal([lab_artifact, audit_artifact, *outputs.values()], [PARENT_SEAL],
                             "chief-kammi", "chief-e4-extract-audit-v1:seal")
    print(json.dumps({"status": audit["status"], "audit_artifact": audit_artifact,
                      "seal_root": seal["root"], "feature_stage_root": actual_root,
                      "fence_valid": False}))


if __name__ == "__main__":
    main()
