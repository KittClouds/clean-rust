"""Chief issues one scoped E4-0 parity handoff; the lab owns launch."""
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
PREPARED = INBOX / "E4-0-PARITY-STAGE-PREPARED-v1.json"
SPEC = INBOX / "E4-0-PARITY-EXECUTION-SPEC-v1.json"
REQUEST = INBOX / "E4-0-PARITY-WORKER-REQUEST-v1.json"
RECEIPT = INBOX / "E4-0-PARITY-HANDOFF-ISSUED-v1.json"
LAB_REVIEW = Path(
    r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust"
    r"\experiments\fas-frozen-observer-bundle-engineering-v01"
    r"\audits\e4-0-supervised-adapter-v02"
    r"\ledger-parity-spec-compatibility-review-v01.json"
)
RECEIPT_ROOT = Path(
    r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01"
    r"\e4-0-ledger-run-v02\ledger-receipts"
)
PREFIX = "chief-e4-parity-handoff-v1"


def identity(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("bound input is absent or linked: " + str(path))
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def require_fresh() -> None:
    if REQUEST.exists() or RECEIPT.exists() or RECEIPT_ROOT.exists():
        raise ValueError("handoff or receipt path already exists")


def main() -> None:
    require_fresh()
    prepared = json.loads(PREPARED.read_bytes())
    spec = json.loads(SPEC.read_bytes())
    review = json.loads(LAB_REVIEW.read_bytes())
    if prepared["status"] != "SPECS_BOUND_SEAL_VERIFIED_FLIGHT_AUTHORITY_WITHHELD":
        raise ValueError("prior stage is not in the prepared state")
    if identity(SPEC) != prepared["execution_spec_artifact_id"]:
        raise ValueError("execution spec differs from bound artifact")
    if identity(LAB_REVIEW) != "sha256:083bb01909d00b0699ca2cdb1ecf9f4231e1caa12ad12b1c52d229510ad8c196":
        raise ValueError("lab compatibility review differs")
    if review["status"] != "PASS_RUNNER_SPEC_OUTPUT_PATH_COMPATIBILITY_NO_EXECUTION":
        raise ValueError("lab compatibility review did not pass")
    if Path(spec["output_root"]).exists():
        raise ValueError("fresh parity output root already exists")
    for source in spec["source_files"]:
        path = Path(source["path"])
        if path.stat().st_size != source["bytes"] or identity(path) != source["sha256"]:
            raise ValueError("bound source changed: " + str(path))

    admin = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    actor = KammiClient(admin.base_url, (OP / "fabrique-e4-supervisor-v1.secret").read_text().strip())
    status = admin.status()
    if status["flight_gate"] != "OPEN" or status["acceptance_identity"] != prepared["library_acceptance_id"]:
        raise ValueError("Library acceptance is no longer current")
    if status["journal_head"] != status["projection_head"]:
        raise ValueError("Library projection is behind the journal")
    if admin.history_summary(prepared["run_id"])["authorization_conferred"]:
        raise ValueError("E4 parity stage has already been authorized")

    review_artifact = admin.register_file(LAB_REVIEW, "e4-parity-compatibility-review", "chief-kammi",
                                          PREFIX + ":review-artifact")["artifact_id"]
    review_seal = admin.create_seal([review_artifact], [prepared["spec_seal_root"]],
                                    "chief-kammi", PREFIX + ":review-seal")["root"]
    now = datetime.now(timezone.utc)
    grant_expiry = (now + timedelta(hours=3)).isoformat()
    authorization_expiry = (now + timedelta(hours=2)).isoformat()
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
        "purpose": "e4_0_online_cache_parity", "ttl_seconds": 1800,
        "request_id": PREFIX + ":lease",
    })["receipt"]
    if lease["decision"] != "GRANTED":
        raise ValueError("E4 GPU lease denied: " + lease.get("reason", "unknown"))
    try:
        authorization = actor.authorization_request({
            "actor_id": prepared["actor_id"], "run_id": prepared["run_id"],
            "stage_id": prepared["stage_id"], "expires_utc": authorization_expiry,
            "request_id": PREFIX + ":authorize",
        })
        if authorization["receipt"]["decision"] != "AUTHORIZED":
            raise ValueError("E4 stage authorization denied: " + ",".join(authorization["receipt"]["reasons"]))
        request = {
            "actor_id": prepared["actor_id"], "run_id": prepared["run_id"],
            "stage_id": prepared["stage_id"], "authorization_id": authorization["event_id"],
            "lease_id": lease["lease_id"], "resource_id": prepared["resource_id"],
            "fencing_token": lease["fencing_token"],
            "attempt_id": "frozen-fabrique.e4-0.parity.supervised.v1",
            "request_id": PREFIX + ":execute",
        }
        scope = {key: value for key, value in request.items() if key not in {"attempt_id", "request_id"}}
        resolved = actor.call("POST", "/v1/local/resolve", scope, timeout_seconds=120)
        if not resolved["valid"] or resolved["execution_spec"] != spec:
            raise ValueError("live local resolve did not return the bound execution spec")
        with REQUEST.open("xb") as stream:
            stream.write(canonical(request))
        request_artifact = admin.register_file(REQUEST, "e4-parity-worker-request", "chief-kammi",
                                               PREFIX + ":request-artifact")["artifact_id"]
        handoff = {
            "schema": "CHIEF_E4_0_PARITY_HANDOFF_ISSUED_V1",
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
            "execution_spec_artifact_id": prepared["execution_spec_artifact_id"],
            "scientific_spec_artifact_id": prepared["scientific_spec_artifact_id"],
            "review_seal_root": review_seal,
            "library_acceptance_id": status["acceptance_identity"],
            "worker_cwd": str(LIB),
            "worker_module": "ledgerd.local_client",
            "actor_token_file": str(OP / "fabrique-e4-supervisor-v1.secret"),
            "model_contact_made": False, "e4_01_entry_open": False,
        }
        with RECEIPT.open("x", encoding="utf-8") as stream:
            json.dump(handoff, stream, indent=2)
            stream.write("\n")
        receipt_artifact = admin.register_file(RECEIPT, "e4-parity-handoff-receipt", "chief-kammi",
                                               PREFIX + ":receipt-artifact")["artifact_id"]
        custody_seal = admin.create_seal([receipt_artifact, request_artifact],
                                         [review_seal], "chief-kammi", PREFIX + ":handoff-seal")
        print(json.dumps({"status": handoff["status"], "authorization_id": handoff["authorization_id"],
                          "lease_id": handoff["lease_id"], "request_path": str(REQUEST),
                          "receipt_path": str(RECEIPT), "custody_seal_root": custody_seal["root"]}))
    except BaseException:
        actor.call("POST", f"/v1/leases/{lease['lease_id']}/release", {
            "actor_id": prepared["actor_id"], "fencing_token": lease["fencing_token"],
            "request_id": PREFIX + ":failed-handoff-release",
        })
        raise


if __name__ == "__main__":
    main()
