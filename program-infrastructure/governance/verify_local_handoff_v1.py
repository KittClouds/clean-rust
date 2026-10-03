"""Independent post-run checks for the disposable local handoff fixture."""
import hashlib
import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
LIB = HERE.parent / "kammi-ledger"
ROOT = LIB / ".kammi-dev/operational/local-qualification-v1"
OUT = HERE / "inbox/20260927/KAMMI-LOCAL-HANDOFF-AUDIT-v1.json"


def main():
    request = json.loads((ROOT / "request.json").read_bytes())
    result = json.loads((ROOT / "receipts/RESULT.json").read_bytes())
    finish = json.loads((ROOT / "receipts/FINISH.json").read_bytes())
    release = json.loads((ROOT / "receipts/RELEASE.json").read_bytes())
    path = ROOT / "output/large-output.bin"
    with path.open("rb") as stream:
        identity = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    client = KammiClient("http://127.0.0.1:8765",
                         (ROOT / "actor.secret").read_text().strip())
    scope = {key: value for key, value in request.items()
             if key not in {"attempt_id", "request_id"}}
    try:
        client.call("POST", "/v1/local/validate", scope)
        stale_rejected = False
        rejection = "unexpectedly accepted"
    except RuntimeError as exc:
        stale_rejected = "HTTP 423" in str(exc)
        rejection = str(exc)
    item = result["outputs"]["large-output.bin"]
    checks = {
        "output_exceeds_normal_upload_cap": path.stat().st_size > 16 * 1024 * 1024,
        "output_digest_matches_registered_artifact": identity == item["artifact_id"],
        "completion_receipt_registered": finish["outcome"] == "COMPLETE"
            and finish["receipt_artifact_id"].startswith("sha256:"),
        "lease_release_recorded": release["event_id"].startswith("sha256:"),
        "stale_fence_rejected_after_release": stale_rejected,
    }
    audit = {"schema": "KAMMI_LOCAL_HANDOFF_AUDIT_V1",
             "status": "PASS" if all(checks.values()) else "FAIL",
             "checks": checks, "stale_validation_response": rejection,
             "output_artifact_id": identity, "output_bytes": path.stat().st_size,
             "completion_receipt_artifact_id": finish["receipt_artifact_id"],
             "lease_release_event": release["event_id"],
             "model_under_test": False, "e4_authorization_conferred": False}
    OUT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "checks": checks}))
    if audit["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
