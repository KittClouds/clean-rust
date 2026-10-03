"""Bind E4-0 scoring inputs under Ledger without granting scoring or opening truth."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.identity import canonical
from ledgerd.local_execution import SPEC_FIELDS, valid_relative


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260928"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
PACKET = LAB / "audits/e4-0-scoring-stage-candidate-v02"
WRAPPER = PACKET / "e4-0-scoring-execution-spec-candidate-v02.json"
NATIVE = PACKET / "kammi-local-execution-v1-candidate-v02.json"
RECEIPT = PACKET / "e4-0-scoring-candidate-receipt-v02.json"
AUDIT = PACKET / "e4-0-scoring-candidate-audit-v02.json"
EXTRACT_AUDIT = HERE / "inbox/20260927/E4-0-EXTRACT-CUSTODY-AUDIT-v1.json"
OUT = INBOX / "E4-0-SCORING-STAGE-PREPARED-v1.json"
RUN = "frozen-fabrique.e4-0.supervised.v1"
STAGE = "E4_0_FRESH_QUALIFICATION_SCORING_V1"
ACTOR = "fabrique-e4-supervisor-v1"
PANEL = "e4-0-primary-terminal-v01"
PARENT = "sha256:cd0116883e679a83707c472f8edef0e08333773d971b1f3fc33ad22a22a1396e"
ACCEPTANCE = "sha256:2578de42c94f7f8cbed72521cb582a47bea465039f7a485ecce30ec1fcd7a898"
EXPECTED = {
    WRAPPER: "80e24afa298c8db0c8300e83715155d10e131762bbef0cf9ac51049e13c1acfa",
    NATIVE: "d3c38aabd7da770bc3d417d48e4aa03c8d784954cd7713725842cba40c7d2e1f",
    RECEIPT: "1673b234263217bca517eb114728181e7227937f9e2ffdef024254e9cac2cfe8",
    AUDIT: "dba837f7a928eb4ea7c8b6734dd1f95e4baeee8ce0afcdb503baed3694c0faeb",
}
PREFIX = "chief-e4-score-prepare-v1"


def digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing or linked candidate: " + str(path))
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def preflight() -> tuple[dict, dict]:
    if OUT.exists():
        raise ValueError("scoring preparation receipt already exists")
    for path, expected in EXPECTED.items():
        if digest(path) != "sha256:" + expected:
            raise ValueError("candidate changed: " + str(path))
    native = json.loads(NATIVE.read_bytes())
    wrapper = json.loads(WRAPPER.read_bytes())
    receipt = json.loads(RECEIPT.read_bytes())
    audit = json.loads(AUDIT.read_bytes())
    extract = json.loads(EXTRACT_AUDIT.read_bytes())
    if set(native) != SPEC_FIELDS or native["schema"] != "KAMMI_LOCAL_EXECUTION_V1":
        raise ValueError("candidate does not match exact native execution schema")
    if (native["run_id"], native["stage_id"], native["actor_id"]) != (RUN, STAGE, ACTOR):
        raise ValueError("native scoring scope differs")
    if len(native["source_files"]) != 35 or len(native["expected_outputs"]) != 7:
        raise ValueError("candidate source or output inventory differs")
    if len({item["path"] for item in native["source_files"]}) != 35:
        raise ValueError("duplicate scoring source path")
    for name in native["expected_outputs"]:
        valid_relative(name)
    if receipt["status"] != "CANDIDATE_ONLY_NOT_SEALED_NOT_AUTHORIZED":
        raise ValueError("lab receipt claims premature authority")
    if audit["status"] != "PASS_CANDIDATE_PACKET_IDENTITY_AUDIT" or not audit["native_schema_exact"]:
        raise ValueError("candidate identity audit did not pass")
    if receipt["qualification"]["tests_passed"] != 11 or receipt["qualification"]["tests_failed"]:
        raise ValueError("synthetic runner suite did not pass")
    if extract["status"] != "PASS_SUPERVISED_FEATURE_CUSTODY":
        raise ValueError("fresh feature custody audit did not pass")
    if wrapper["stage"]["stage_id"] != STAGE:
        raise ValueError("wrapper stage differs")
    staged = [s for s in native["source_files"] if s["path"].endswith("primary-panel-e4-v01.jsonl")]
    if len(staged) != 1 or staged[0]["sha256"] != (
        "sha256:225787239ffb3d3920e2c299f0f05cdb59df88a89ddc11ed22edde9ac312a365"
    ) or staged[0]["bytes"] != 39363264 or Path(staged[0]["path"]).exists():
        raise ValueError("future staged panel identity or freshness differs")
    if Path(native["output_root"]).exists():
        raise ValueError("scoring output root is not fresh")
    dynamic = [native["command"][native["command"].index(flag) + 1]
               for flag in ("--invocation", "--delivery")]
    if any(Path(path).exists() for path in dynamic):
        raise ValueError("dynamic scoring handoffs already exist")
    return native, extract


def main() -> None:
    native, extract = preflight()
    INBOX.mkdir(parents=True, exist_ok=True)
    admin = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    status = admin.status()
    if status["flight_gate"] != "OPEN" or status["acceptance_identity"] != ACCEPTANCE:
        raise ValueError("qualified Library acceptance changed")
    if status["journal_head"] != status["projection_head"] or status["panel_exposures"]:
        raise ValueError("custody projection is behind or protected panel was exposed")
    if status["active_lease_resources"]:
        raise ValueError("unexpected active lease before scoring preparation")
    policy_hash = admin.call("POST", "/v1/policies", {"policy": {
        "schema": "KAMMI_POLICY_V1", "stage_id": STAGE, "version": "v1",
        "requires": {"scientific_spec": "SEALED", "execution_spec": "SEALED",
                     "predecessor_seal": "VERIFIED", "actor": "AUTHORIZED"},
        "forbids": {"eval_panel_opened": True},
    }, "request_id": PREFIX + ":policy"})["policy_hash"]
    admin.call("POST", "/v1/grants", {
        "grant_id": PREFIX + "-bind-spec", "actor_id": ACTOR,
        "action": "bind_spec", "run_id": RUN, "stage_id": STAGE,
        "policy_hash": policy_hash, "expires_utc": "2026-10-01T12:00:00Z",
        "request_id": PREFIX + ":bind-grant",
    })
    kinds = (("wrapper", WRAPPER), ("execution-spec", NATIVE),
             ("lab-receipt", RECEIPT), ("lab-audit", AUDIT),
             ("extract-custody-audit", EXTRACT_AUDIT))
    artifacts = {name: admin.register_file(path, "e4-scoring-preauthorization",
        "chief-kammi", PREFIX + ":artifact:" + name)["artifact_id"] for name, path in kinds}
    scientific = "sha256:21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f"
    seal = admin.create_seal([scientific, *artifacts.values()], [PARENT],
                             "chief-kammi", PREFIX + ":spec-seal")
    actor = KammiClient(admin.base_url, (OP / "fabrique-e4-supervisor-v1.secret").read_text().strip())
    for kind, artifact in (("SCIENTIFIC", scientific), ("EXECUTION", artifacts["execution-spec"])):
        actor.call("POST", "/v1/specs/bind", {
            "run_id": RUN, "stage_id": STAGE, "spec_kind": kind,
            "artifact_id": artifact, "seal_root": seal["root"],
            "actor_id": ACTOR, "request_id": PREFIX + ":bind:" + kind,
        })
    verified = actor.call("POST", f"/v1/seals/{seal['root']}/verify-for-run", {
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "request_id": PREFIX + ":verify-seal",
    })
    prepared = {
        "schema": "CHIEF_E4_0_SCORING_STAGE_PREPARED_V1",
        "status": "SPECS_BOUND_SEAL_VERIFIED_SCORING_AUTHORITY_WITHHELD",
        "run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR,
        "panel_id_reserved": PANEL, "panel_registered": False,
        "policy_hash": policy_hash,
        "scientific_spec_artifact_id": scientific,
        "execution_spec_artifact_id": artifacts["execution-spec"],
        "candidate_artifact_ids": artifacts,
        "spec_seal_root": seal["root"],
        "seal_verification_event": verified["event_id"],
        "extract_custody_parent_seal": PARENT,
        "extract_finish_event": extract["finish_event"],
        "library_acceptance_id": ACCEPTANCE,
        "source_count": len(native["source_files"]),
        "expected_outputs": native["expected_outputs"],
        "authorization_grant_issued": False,
        "open_panel_grant_issued": False,
        "lease_issued": False,
        "stage_authorization_issued": False,
        "primary_panel_exposure_count": 0,
        "scoring_started": False,
        "e4_01_entry_open": False,
    }
    with OUT.open("xb") as stream:
        stream.write(canonical(prepared))
    print(json.dumps({"status": prepared["status"], "spec_seal_root": seal["root"],
                      "execution_spec": artifacts["execution-spec"],
                      "source_count": prepared["source_count"]}))


if __name__ == "__main__":
    main()
