"""Chief prepares the E4 parity run/spec under Ledger, without flight authority."""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.identity import canonical


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
PLAN = LAB / "plans/E4-0-LEDGER-EXECUTION-SPEC-CANDIDATES-v02.json"
BINDING = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01"
               r"\e4-0-ledger-bindings-v02\online-cache-parity-binding-v02.json")
INVENTORY = INBOX / "E4-0-STATIC-INPUT-INVENTORY-v1.json"
SPEC_PATH = INBOX / "E4-0-PARITY-EXECUTION-SPEC-v1.json"
OUT = INBOX / "E4-0-PARITY-STAGE-PREPARED-v1.json"
RUN = "frozen-fabrique.e4-0.supervised.v1"
STAGE = "E4_0_ONLINE_CACHE_PARITY_V1"
ACTOR = "fabrique-e4-supervisor-v1"
RESOURCE = "gpu.local.cuda0.e850fbf0"
GRANT_EXPIRY = "2026-09-28T12:00:00Z"


def file_id(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("source file is absent or a symlink: " + str(path))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve(strict=True)), "sha256": "sha256:" + digest,
            "bytes": path.stat().st_size}


def main():
    plan = json.loads(PLAN.read_bytes())
    inventory = json.loads(INVENTORY.read_bytes())
    parity, = (stage for stage in plan["stages"] if stage["mode"] == "parity")
    if Path(parity["output_root"]).exists():
        raise ValueError("fresh parity output already exists")
    if file_id(BINDING)["sha256"] != "sha256:c2888a7cea6a3999e0f1b3b395fb26b99b56e120c75be261f0a6d1c1cd5e6bc4":
        raise ValueError("Chief static parity binding changed")
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    status = client.status()
    if status["flight_gate"] != "OPEN" or status["acceptance_identity"] != plan["library_acceptance_id"]:
        raise ValueError("current Library acceptance differs from v02 packet")
    sources = [file_id(Path(item["path"])) for item in plan["shared_runtime_source_files"]]
    sources.append(file_id(BINDING))
    sources.append(file_id(Path(plan["python_executable"])))
    sources.extend(file_id(Path(item["path"])) for item in inventory["artifacts"].values())
    if len({entry["path"] for entry in sources}) != len(sources):
        raise ValueError("duplicate source path in local execution spec")
    spec = {"schema": "KAMMI_LOCAL_EXECUTION_V1", "run_id": RUN,
            "stage_id": STAGE, "actor_id": ACTOR,
            "command": parity["command"], "cwd": plan["cwd"],
            "output_root": parity["output_root"],
            "expected_outputs": parity["expected_outputs"],
            "max_output_bytes": parity["max_output_bytes_per_file"],
            "timeout_seconds": parity["timeout_seconds"],
            "poll_seconds": parity["poll_seconds"], "source_files": sources}
    encoded = canonical(spec)
    if SPEC_PATH.exists():
        if SPEC_PATH.read_bytes() != encoded:
            raise ValueError("existing execution spec differs; preserve prior attempt")
    else:
        with SPEC_PATH.open("xb") as stream:
            stream.write(encoded)
    token_file = OP / "fabrique-e4-supervisor-v1.secret"
    if token_file.exists():
        token = token_file.read_text().strip()
    else:
        token = secrets.token_urlsafe(48)
        with token_file.open("x", encoding="utf-8") as stream:
            stream.write(token)
    client.create_run(RUN, "frozen-fabrique", "chief-kammi", "chief-e4-parity-v1:run")
    client.call("POST", "/v1/actors", {"actor_id": ACTOR, "kind": "service",
        "lab": "frozen-fabrique", "credential_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "request_id": "chief-e4-parity-v1:actor"})
    client.call("POST", "/v1/resources", {"resource_id": RESOURCE, "kind": "GPU",
        "host": "local", "constraints": {"cuda_index": "0",
            "uuid": "GPU-e850fbf0-df85-9230-9d82-d284b236261e",
            "name": "NVIDIA GeForce RTX 3080"},
        "request_id": "chief-e4-parity-v1:resource"})
    policy = {"schema": "KAMMI_POLICY_V1", "stage_id": STAGE, "version": "v1",
        "requires": {"scientific_spec": "SEALED", "execution_spec": "SEALED",
                     "predecessor_seal": "VERIFIED", "actor": "AUTHORIZED",
                     "resource.gpu": "LEASED"},
        "forbids": {"truth_label_contact": True, "eval_panel_opened": True}}
    policy_hash = client.call("POST", "/v1/policies", {"policy": policy,
        "request_id": "chief-e4-parity-v1:policy"})["policy_hash"]
    bind_grant = client.call("POST", "/v1/grants", {
        "grant_id": "chief-e4-parity-v1-bind-spec", "actor_id": ACTOR,
        "action": "bind_spec", "run_id": RUN, "stage_id": STAGE,
        "policy_hash": policy_hash, "expires_utc": GRANT_EXPIRY,
        "request_id": "chief-e4-parity-v1:bind-grant"})["event_id"]
    spec_artifact = client.register_file(SPEC_PATH, "e4-local-execution-spec",
                                         "chief-kammi", "chief-e4-parity-v1:execution-spec")
    scientific = "sha256:" + inventory["artifacts"]["e4_contract"]["sha256"]
    registered = json.loads((INBOX / "E4-0-INHERITANCE-LEDGER-RECEIPT-v1.json").read_bytes())[
        "artifacts"]["current_contract"]["artifact_id"]
    if scientific != registered:
        raise ValueError("scientific contract differs from registered inherited artifact")
    parent = json.loads((INBOX / "E4-0-PARITY-PREMODEL-LEDGER-RECEIPT-v1.json").read_bytes())[
        "seal"]["root"]
    seal = client.create_seal([scientific, spec_artifact["artifact_id"],
                               "sha256:c2888a7cea6a3999e0f1b3b395fb26b99b56e120c75be261f0a6d1c1cd5e6bc4"],
                              [parent], "chief-kammi", "chief-e4-parity-v1:spec-seal")
    actor = KammiClient(client.base_url, token)
    for kind, artifact in (("SCIENTIFIC", scientific), ("EXECUTION", spec_artifact["artifact_id"])):
        actor.call("POST", "/v1/specs/bind", {"run_id": RUN, "stage_id": STAGE,
            "spec_kind": kind, "artifact_id": artifact, "seal_root": seal["root"],
            "actor_id": ACTOR, "request_id": "chief-e4-parity-v1:bind:" + kind})
    verified = actor.call("POST", f"/v1/seals/{seal['root']}/verify-for-run", {
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "request_id": "chief-e4-parity-v1:verify-seal"})
    result = {"schema": "CHIEF_E4_0_PARITY_STAGE_PREPARED_V1",
        "status": "SPECS_BOUND_SEAL_VERIFIED_FLIGHT_AUTHORITY_WITHHELD",
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "resource_id": RESOURCE, "policy_hash": policy_hash,
        "bind_spec_grant_event": bind_grant,
        "scientific_spec_artifact_id": scientific,
        "execution_spec_artifact_id": spec_artifact["artifact_id"],
        "spec_seal_root": seal["root"], "seal_verification_event": verified["event_id"],
        "library_acceptance_id": status["acceptance_identity"],
        "authorization_grant_issued": False, "gpu_lease_issued": False,
        "stage_authorization_issued": False, "model_contact_authorized": False,
        "e4_01_entry_open": False}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "run_id": RUN,
                      "stage_id": STAGE, "seal_root": seal["root"],
                      "execution_spec": spec_artifact["artifact_id"]}))


if __name__ == "__main__":
    main()
