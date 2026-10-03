"""Chief binds the next E4-0 extraction stage without execution authority."""
from __future__ import annotations

import hashlib
import json
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
               r"\e4-0-ledger-bindings-v02\fresh-feature-extraction-binding-v02.json")
PREFLIGHT = INBOX / "E4-0-EXTRACT-PREMODEL-PREFLIGHT-v1.json"
PARITY_AUDIT = INBOX / "E4-0-PARITY-CUSTODY-AUDIT-v1.json"
PARITY_HANDOFF = INBOX / "E4-0-PARITY-HANDOFF-ISSUED-v1.json"
SPEC_PATH = INBOX / "E4-0-EXTRACT-EXECUTION-SPEC-v1.json"
OUT = INBOX / "E4-0-EXTRACT-STAGE-PREPARED-v1.json"
RUN = "frozen-fabrique.e4-0.supervised.v1"
STAGE = "E4_0_FRESH_FEATURE_EXTRACTION_V1"
ACTOR = "fabrique-e4-supervisor-v1"
RESOURCE = "gpu.local.cuda0.e850fbf0"
PARENT_SEAL = "sha256:7feff4b681264214935e8ddb7ccddeccc8c9964362042553cbcaffcc984e4572"


def file_id(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("source file is absent or linked: " + str(path))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve(strict=True)), "sha256": "sha256:" + digest,
            "bytes": path.stat().st_size}


def main() -> None:
    if OUT.exists():
        raise ValueError("extract stage preparation receipt already exists")
    plan = json.loads(PLAN.read_bytes())
    binding = json.loads(BINDING.read_bytes())
    preflight = json.loads(PREFLIGHT.read_bytes())
    parity_audit = json.loads(PARITY_AUDIT.read_bytes())
    handoff = json.loads(PARITY_HANDOFF.read_bytes())
    stage, = (item for item in plan["stages"] if item["mode"] == "extract-e4")
    if preflight["status"] != "PASS_VISIBLE_ONLY_PREMODEL" or parity_audit["status"] != "PASS_SUPERVISED_OUTPUT_CUSTODY":
        raise ValueError("predecessor parity audit or extract preflight did not pass")
    if file_id(BINDING)["sha256"] != "sha256:" + preflight["binding_sha256"]:
        raise ValueError("extract binding changed after preflight")
    if binding["exact_predecessor_roots"]["e4_parity_receipt_root_sha256"] != parity_audit["lab_stage_seal_root_claim"]:
        raise ValueError("parity seal root differs from extract predecessor")
    if Path(stage["output_root"]).exists():
        raise ValueError("fresh extraction output root already exists")
    if stage["known_exact_output_bytes"]["V1_FINAL_POSITION.f32le"] > stage["max_output_bytes_per_file"]:
        raise ValueError("output cap is smaller than frozen feature tensor")
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    status = client.status()
    if status["flight_gate"] != "OPEN" or status["acceptance_identity"] != handoff["library_acceptance_id"]:
        raise ValueError("Library acceptance changed")
    if status["journal_head"] != status["projection_head"]:
        raise ValueError("custody projection is behind journal")
    sources = [file_id(Path(item["path"])) for item in plan["shared_runtime_source_files"]]
    sources.extend((file_id(BINDING), file_id(Path(plan["python_executable"]))))
    sources.extend(file_id(Path(item["path"])) for item in binding["artifacts"].values())
    if len({item["path"] for item in sources}) != len(sources):
        raise ValueError("duplicate source path in extract execution spec")
    spec = {
        "schema": "KAMMI_LOCAL_EXECUTION_V1", "run_id": RUN,
        "stage_id": STAGE, "actor_id": ACTOR,
        "command": stage["command"], "cwd": plan["cwd"],
        "output_root": stage["output_root"],
        "expected_outputs": stage["expected_outputs"],
        "max_output_bytes": stage["max_output_bytes_per_file"],
        "timeout_seconds": stage["timeout_seconds"],
        "poll_seconds": stage["poll_seconds"], "source_files": sources,
    }
    with SPEC_PATH.open("xb") as stream:
        stream.write(canonical(spec))
    prefix = "chief-e4-extract-v1"
    policy_hash = client.call("POST", "/v1/policies", {"policy": {
        "schema": "KAMMI_POLICY_V1", "stage_id": STAGE, "version": "v1",
        "requires": {"scientific_spec": "SEALED", "execution_spec": "SEALED",
                     "predecessor_seal": "VERIFIED", "actor": "AUTHORIZED",
                     "resource.gpu": "LEASED"},
        "forbids": {"truth_label_contact": True, "eval_panel_opened": True},
    }, "request_id": prefix + ":policy"})["policy_hash"]
    client.call("POST", "/v1/grants", {
        "grant_id": prefix + "-bind-spec", "actor_id": ACTOR,
        "action": "bind_spec", "run_id": RUN, "stage_id": STAGE,
        "policy_hash": policy_hash, "expires_utc": "2026-09-29T12:00:00Z",
        "request_id": prefix + ":bind-grant",
    })
    artifact_ids = [
        client.register_file(BINDING, "e4-extract-input-binding", "chief-kammi",
                             prefix + ":binding-artifact")["artifact_id"],
        client.register_file(PREFLIGHT, "e4-extract-premodel-preflight", "chief-kammi",
                             prefix + ":preflight-artifact")["artifact_id"],
        client.register_file(SPEC_PATH, "e4-local-execution-spec", "chief-kammi",
                             prefix + ":execution-spec-artifact")["artifact_id"],
    ]
    scientific = handoff["scientific_spec_artifact_id"]
    seal = client.create_seal([scientific, *artifact_ids], [PARENT_SEAL],
                              "chief-kammi", prefix + ":spec-seal")
    actor = KammiClient(client.base_url, (OP / "fabrique-e4-supervisor-v1.secret").read_text().strip())
    for kind, artifact in (("SCIENTIFIC", scientific), ("EXECUTION", artifact_ids[-1])):
        actor.call("POST", "/v1/specs/bind", {
            "run_id": RUN, "stage_id": STAGE, "spec_kind": kind,
            "artifact_id": artifact, "seal_root": seal["root"],
            "actor_id": ACTOR, "request_id": prefix + ":bind:" + kind,
        })
    verified = actor.call("POST", f"/v1/seals/{seal['root']}/verify-for-run", {
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "request_id": prefix + ":verify-seal",
    })
    prepared = {
        "schema": "CHIEF_E4_0_EXTRACT_STAGE_PREPARED_V1",
        "status": "SPECS_BOUND_SEAL_VERIFIED_FLIGHT_AUTHORITY_WITHHELD",
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "resource_id": RESOURCE, "policy_hash": policy_hash,
        "scientific_spec_artifact_id": scientific,
        "execution_spec_artifact_id": artifact_ids[-1],
        "binding_artifact_id": artifact_ids[0],
        "preflight_artifact_id": artifact_ids[1],
        "spec_seal_root": seal["root"],
        "seal_verification_event": verified["event_id"],
        "parity_custody_parent_seal": PARENT_SEAL,
        "library_acceptance_id": status["acceptance_identity"],
        "authorization_grant_issued": False, "gpu_lease_issued": False,
        "stage_authorization_issued": False, "extraction_started": False,
        "labels_opened": False, "e4_01_entry_open": False,
    }
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(prepared, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": prepared["status"], "spec_seal_root": seal["root"],
                      "execution_spec": artifact_ids[-1], "source_count": len(sources)}))


if __name__ == "__main__":
    main()
