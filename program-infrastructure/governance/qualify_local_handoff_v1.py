"""Qualify current Library local route with a CPU fixture in the live ledger."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.identity import canonical


HERE = Path(__file__).parent
LIB = HERE.parent / "kammi-ledger"
OP = LIB / ".kammi-dev/operational"
FIXTURE = HERE / "fixtures/local_qualification_child.py"
ROOT = OP / "local-qualification-v1"
OUT = HERE / "inbox/20260927/KAMMI-LOCAL-HANDOFF-QUALIFICATION-v1.json"
RUN = "library.local.handoff.qual.v1"
STAGE = "LIB_LOCAL_HANDOFF_QUAL_V1"
ACTOR = "library-local-qual-v1"
RESOURCE = "cpu.library.local.qual.v1"


def file_identity(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return "sha256:" + digest, path.stat().st_size


def main() -> None:
    if ROOT.exists():
        raise ValueError("qualification root already exists; preserve prior attempt")
    ROOT.mkdir(parents=True)
    admin = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    before = admin.status()
    if before["flight_gate"] != "OPEN":
        raise ValueError("Library acceptance gate is not open")
    token = secrets.token_urlsafe(48)
    token_file = ROOT / "actor.secret"
    token_file.write_text(token, encoding="utf-8")
    actor = KammiClient(admin.base_url, token)
    admin.create_run(RUN, "library", "chief-kammi", "library-local-qual-v1:run")
    admin.call("POST", "/v1/actors", {"actor_id": ACTOR, "kind": "service", "lab": "library",
        "credential_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "request_id": "library-local-qual-v1:actor"})
    policy = {"schema": "KAMMI_POLICY_V1", "stage_id": STAGE, "version": "v1",
              "requires": {"actor": "AUTHORIZED", "scientific_spec": "SEALED",
                           "execution_spec": "SEALED", "predecessor_seal": "VERIFIED"},
              "forbids": {"truth_label_contact": True, "eval_panel_opened": True}}
    policy_hash = admin.call("POST", "/v1/policies", {
        "policy": policy, "request_id": "library-local-qual-v1:policy"})["policy_hash"]
    admin.call("POST", "/v1/resources", {"resource_id": RESOURCE, "kind": "CPU_POOL",
        "host": "local", "constraints": {"fixture": "no-model"},
        "request_id": "library-local-qual-v1:resource"})
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    grants = {}
    for action in ("bind_spec", "authorize_stage", "acquire_lease", "execute_local"):
        grants[action] = admin.call("POST", "/v1/grants", {
            "grant_id": "library-local-qual-v1-" + action,
            "actor_id": ACTOR, "action": action, "run_id": RUN, "stage_id": STAGE,
            "policy_hash": policy_hash, "expires_utc": expiry,
            "request_id": "library-local-qual-v1:grant:" + action})["event_id"]
    output_root = ROOT / "output"
    source_id, source_bytes = file_identity(FIXTURE)
    scientific = {"schema": "KAMMI_LOCAL_QUAL_SCIENTIFIC_V1",
                  "meaning": "CPU fixture only; no E4 execution authority"}
    execution = {"schema": "KAMMI_LOCAL_EXECUTION_V1", "run_id": RUN,
        "stage_id": STAGE, "actor_id": ACTOR,
        "command": [sys.executable, str(FIXTURE), str(output_root)],
        "cwd": str(HERE), "output_root": str(output_root),
        "expected_outputs": ["large-output.bin"], "max_output_bytes": 64 * 1024 * 1024,
        "timeout_seconds": 120, "poll_seconds": 1,
        "source_files": [{"path": str(FIXTURE), "sha256": source_id, "bytes": source_bytes}]}
    spec_ids = {}
    for kind, value in (("SCIENTIFIC", scientific), ("EXECUTION", execution)):
        p = ROOT / (kind.lower() + ".json")
        p.write_bytes(canonical(value))
        spec_ids[kind] = admin.register_file(p, "library-local-qualification-spec",
                                              "chief-kammi", "library-local-qual-v1:artifact:" + kind)["artifact_id"]
    seal = admin.create_seal(list(spec_ids.values()), [], "chief-kammi",
                             "library-local-qual-v1:seal")
    for kind, identity in spec_ids.items():
        actor.call("POST", "/v1/specs/bind", {"run_id": RUN, "stage_id": STAGE,
            "spec_kind": kind, "artifact_id": identity, "seal_root": seal["root"],
            "actor_id": ACTOR, "request_id": "library-local-qual-v1:bind:" + kind})
    actor.call("POST", f"/v1/seals/{seal['root']}/verify-for-run", {
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "request_id": "library-local-qual-v1:verify-seal"})
    lease = actor.acquire_lease({"resource_id": RESOURCE, "run_id": RUN,
        "stage_id": STAGE, "actor_id": ACTOR, "purpose": "local_qualification",
        "ttl_seconds": 600, "request_id": "library-local-qual-v1:lease"})["receipt"]
    if lease["decision"] != "GRANTED":
        raise ValueError("qualification lease denied")
    auth = actor.authorization_request({"actor_id": ACTOR, "run_id": RUN,
        "stage_id": STAGE, "expires_utc": expiry,
        "request_id": "library-local-qual-v1:authorize"})
    if auth["receipt"]["decision"] != "AUTHORIZED":
        raise ValueError("qualification stage denied")
    request = {"actor_id": ACTOR, "run_id": RUN, "stage_id": STAGE,
        "authorization_id": auth["event_id"], "lease_id": lease["lease_id"],
        "resource_id": RESOURCE, "fencing_token": lease["fencing_token"],
        "attempt_id": "library.local.qual.attempt.v1", "request_id": "library-local-qual-v1:execute"}
    request_path = ROOT / "request.json"
    request_path.write_bytes(canonical(request))
    env = {**os.environ, "KAMMI_ACTOR_TOKEN_FILE": str(token_file), "KAMMI_URL": admin.base_url}
    proc = subprocess.run([sys.executable, "-m", "ledgerd.local_client",
        "--request", str(request_path), "--receipt-root", str(ROOT / "receipts")],
        cwd=LIB, env=env, capture_output=True, text=True, timeout=180)
    result_path = ROOT / "receipts/RESULT.json"
    result = json.loads(result_path.read_bytes()) if result_path.exists() else {}
    after = admin.status()
    qualification = {"schema": "KAMMI_LOCAL_HANDOFF_QUALIFICATION_V1",
        "status": "PASS" if proc.returncode == 0 and result.get("status") == "OUTPUTS_REGISTERED" else "FAIL",
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "resource_id": RESOURCE, "policy_hash": policy_hash, "grants": grants,
        "scientific_spec": spec_ids["SCIENTIFIC"], "execution_spec": spec_ids["EXECUTION"],
        "seal_root": seal["root"], "authorization_id": auth["event_id"],
        "lease_id": lease["lease_id"], "fencing_token": lease["fencing_token"],
        "execution_exit": proc.returncode, "execution_stdout": proc.stdout[-2000:],
        "execution_stderr": proc.stderr[-2000:],
        "result_path": str(result_path), "result": result,
        "journal_head_before": before["journal_head"],
        "journal_head_after": after["journal_head"],
        "scope": "CPU-only Library fixture; does not qualify Fabrique adaptation or confer E4 authority"}
    OUT.write_text(json.dumps(qualification, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": qualification["status"], "execution_exit": proc.returncode,
                      "output_bytes": (output_root / "large-output.bin").stat().st_size
                      if (output_root / "large-output.bin").exists() else 0,
                      "result_path": str(result_path)}))
    if qualification["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
