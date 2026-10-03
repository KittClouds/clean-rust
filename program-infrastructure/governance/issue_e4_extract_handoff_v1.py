"""Chief issues a separate, fenced E4-0 feature extraction handoff."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.identity import canonical


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
LIB = HERE.parent / "kammi-ledger"
LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
REVIEW = LAB / "audits/e4-0-supervised-adapter-v02/ledger-extract-spec-compatibility-review-v01.json"
PREPARED = INBOX / "E4-0-EXTRACT-STAGE-PREPARED-v1.json"
SPEC = INBOX / "E4-0-EXTRACT-EXECUTION-SPEC-v1.json"
REQUEST = INBOX / "E4-0-EXTRACT-WORKER-REQUEST-v1.json"
RECEIPT = INBOX / "E4-0-EXTRACT-HANDOFF-ISSUED-v1.json"
RECEIPT_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01"
                    r"\e4-0-ledger-run-v02\extract-ledger-receipts")
PREFIX = "chief-e4-extract-handoff-v1"
REVIEW_SHA = "sha256:a4a42330a634ae576e7122e5e332313c73b66f6d70eb3b31abaf3f4b13c0563f"
PARENT_SEAL = "sha256:97c40e99d41b38dc29528938a9b63fcbda6a137831bb200658a638a825afe569"


def identity(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("bound file missing or linked: " + str(path))
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    if REQUEST.exists() or RECEIPT.exists() or RECEIPT_ROOT.exists():
        raise ValueError("extract handoff paths must be fresh")
    prepared = json.loads(PREPARED.read_bytes())
    spec = json.loads(SPEC.read_bytes())
    review = json.loads(REVIEW.read_bytes())
    if prepared["status"] != "SPECS_BOUND_SEAL_VERIFIED_FLIGHT_AUTHORITY_WITHHELD":
        raise ValueError("extract stage is not in the prepared state")
    if identity(SPEC) != prepared["execution_spec_artifact_id"] or identity(REVIEW) != REVIEW_SHA:
        raise ValueError("execution spec or lab review bytes differ")
    if not str(review.get("status", "")).startswith("PASS"):
        raise ValueError("lab's static review did not pass")
    if Path(spec["output_root"]).exists():
        raise ValueError("fresh extract output root already exists")
    for source in spec["source_files"]:
        path = Path(source["path"])
        if path.stat().st_size != source["bytes"] or identity(path) != source["sha256"]:
            raise ValueError("bound source changed: " + str(path))
    admin = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    actor = KammiClient(admin.base_url, (OP / "fabrique-e4-supervisor-v1.secret").read_text().strip())
    status = admin.status()
    if status["flight_gate"] != "OPEN" or status["acceptance_identity"] != prepared["library_acceptance_id"]:
        raise ValueError("Library acceptance changed")
    if status["journal_head"] != status["projection_head"]:
        raise ValueError("custody projection is behind the journal")
    review_artifact = admin.register_file(REVIEW, "e4-extract-compatibility-review", "chief-kammi",
                                          PREFIX + ":review-artifact")["artifact_id"]
    review_seal = admin.create_seal([review_artifact], [PARENT_SEAL],
                                    "chief-kammi", PREFIX + ":review-seal")["root"]
    now = datetime.now(timezone.utc)
    grant_expiry = (now + timedelta(hours=7)).isoformat()
    authorization_expiry = (now + timedelta(hours=6)).isoformat()
    grants = {}
    for action in ("authorize_stage", "acquire_lease", "execute_local"):
        grants[action] = admin.call("POST", "/v1/grants", {
            "grant_id": PREFIX + "-" + action,
            "actor_id": prepared["actor_id"], "action": action,
            "run_id": prepared["run_id"], "stage_id": prepared["stage_id"],
            "policy_hash": prepared["policy_hash"], "expires_utc": grant_expiry,
            "request_id": PREFIX + ":grant:" + action,
        })["event_id"]
    lease = actor.acquire_lease({
        "resource_id": prepared["resource_id"], "run_id": prepared["run_id"],
        "stage_id": prepared["stage_id"], "actor_id": prepared["actor_id"],
        "purpose": "e4_0_fresh_feature_extraction", "ttl_seconds": 1800,
        "request_id": PREFIX + ":lease",
    })["receipt"]
    if lease["decision"] != "GRANTED":
        raise ValueError("extract GPU lease denied: " + lease.get("reason", "unknown"))
    try:
        authorization = actor.authorization_request({
            "actor_id": prepared["actor_id"], "run_id": prepared["run_id"],
            "stage_id": prepared["stage_id"], "expires_utc": authorization_expiry,
            "request_id": PREFIX + ":authorize",
        })
        if authorization["receipt"]["decision"] != "AUTHORIZED":
            raise ValueError("extract authorization denied: " + ",".join(authorization["receipt"]["reasons"]))
        request = {
            "actor_id": prepared["actor_id"], "run_id": prepared["run_id"],
            "stage_id": prepared["stage_id"], "authorization_id": authorization["event_id"],
            "lease_id": lease["lease_id"], "resource_id": prepared["resource_id"],
            "fencing_token": lease["fencing_token"],
            "attempt_id": "frozen-fabrique.e4-0.extract.supervised.v1",
            "request_id": PREFIX + ":execute",
        }
        scope = {key: value for key, value in request.items() if key not in {"attempt_id", "request_id"}}
        resolved = actor.call("POST", "/v1/local/resolve", scope, timeout_seconds=120)
        if not resolved["valid"] or resolved["execution_spec"] != spec:
            raise ValueError("live resolve differs from bound extraction spec")
        with REQUEST.open("xb") as stream:
            stream.write(canonical(request))
        request_artifact = admin.register_file(REQUEST, "e4-extract-worker-request", "chief-kammi",
                                               PREFIX + ":request-artifact")["artifact_id"]
        receipt = {
            "schema": "CHIEF_E4_0_EXTRACT_HANDOFF_ISSUED_V1",
            "status": "AUTHORIZED_AWAITING_FABRIQUE_LAUNCH",
            "run_id": prepared["run_id"], "stage_id": prepared["stage_id"],
            "actor_id": prepared["actor_id"], "resource_id": prepared["resource_id"],
            "policy_hash": prepared["policy_hash"], "grant_events": grants,
            "grant_expiry_utc": grant_expiry,
            "authorization_id": authorization["event_id"],
            "authorization_expiry_utc": authorization_expiry,
            "lease_id": lease["lease_id"], "fencing_token": lease["fencing_token"],
            "lease_expiry_utc": lease["expires_utc"],
            "request_path": str(REQUEST), "request_sha256": identity(REQUEST),
            "receipt_root": str(RECEIPT_ROOT),
            "scientific_spec_artifact_id": prepared["scientific_spec_artifact_id"],
            "execution_spec_artifact_id": prepared["execution_spec_artifact_id"],
            "review_seal_root": review_seal,
            "library_acceptance_id": status["acceptance_identity"],
            "worker_cwd": str(LIB), "worker_module": "ledgerd.local_client",
            "actor_token_file": str(OP / "fabrique-e4-supervisor-v1.secret"),
            "model_contact_made": False, "labels_opened": False,
            "e4_01_entry_open": False,
        }
        with RECEIPT.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
            stream.write("\n")
        receipt_artifact = admin.register_file(RECEIPT, "e4-extract-handoff-receipt", "chief-kammi",
                                               PREFIX + ":receipt-artifact")["artifact_id"]
        seal = admin.create_seal([receipt_artifact, request_artifact], [review_seal],
                                 "chief-kammi", PREFIX + ":handoff-seal")
        print(json.dumps({"status": receipt["status"],
                          "authorization_id": receipt["authorization_id"],
                          "lease_id": receipt["lease_id"],
                          "request_path": str(REQUEST), "receipt_path": str(RECEIPT),
                          "custody_seal_root": seal["root"]}))
    except BaseException:
        actor.call("POST", f"/v1/leases/{lease['lease_id']}/release", {
            "actor_id": prepared["actor_id"], "fencing_token": lease["fencing_token"],
            "request_id": PREFIX + ":failed-handoff-release",
        })
        raise


if __name__ == "__main__":
    main()
