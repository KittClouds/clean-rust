"""Capture Chief's exact-byte, no-exposure E4-0 live preflight and custody seal."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.identity import canonical


GOV = Path(__file__).resolve().parent
INBOX = GOV / "inbox/20260928"
LEDGER = GOV.parent / "kammi-ledger"
OP = LEDGER / ".kammi-dev/operational"
LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
PACKET = LAB / "audits/e4-0-scoring-stage-candidate-v02"
WRAPPER = PACKET / "e4-0-scoring-execution-spec-candidate-v02.json"
NATIVE = PACKET / "kammi-local-execution-v1-candidate-v02.json"
FABRIQUE_RECEIPT = PACKET / "e4-0-scoring-candidate-receipt-v02.json"
CANDIDATE_AUDIT = PACKET / "e4-0-scoring-candidate-audit-v02.json"
PREPARED = INBOX / "E4-0-SCORING-STAGE-PREPARED-v1.json"
PREPARED_LEDGER = INBOX / "E4-0-SCORING-PREPARED-LEDGER-RECEIPT-v1.json"
REVIEW_PACKET = INBOX / "E4-0-ENGINEERING-REVIEWER-PACKET-v1.md"
ACCEPTANCE = LEDGER / "acceptance/endstate/qualified-20260928T034745805426Z/TERMINAL.json"
OUT = INBOX / "E4-0-SCORING-LIVE-PREFLIGHT-v1.json"
LEDGER_OUT = INBOX / "E4-0-SCORING-LIVE-PREFLIGHT-LEDGER-RECEIPT-v1.json"

RUN = "frozen-fabrique.e4-0.supervised.v1"
STAGE = "E4_0_FRESH_QUALIFICATION_SCORING_V1"
ACTOR = "fabrique-e4-supervisor-v1"
PANEL = "e4-0-primary-terminal-v01"
PANEL_REL = "e4-0-scoring-input-v01/ledger-inputs/primary-panel-e4-v01.jsonl"
PANEL_BYTES = 39_363_264
PANEL_SHA256 = "sha256:225787239ffb3d3920e2c299f0f05cdb59df88a89ddc11ed22edde9ac312a365"
PARENT_SEAL = "sha256:251a3e980c1923664b2b6b2aa7fefd9976ba5c64a67d8ba7910ba055537e23a9"
LIBRARY_ACCEPTANCE = "sha256:78fa6f1daa99134b3e5e50f6823c547582325657175d86d7e852e26c6ab0a029"
LIBRARY_SOURCE_ROOT = "sha256:be4a2f627bb31e1a01b4097594414729b728806b3c13380763ffd8125edf696b"
EXPECTED = {
    WRAPPER: "sha256:80e24afa298c8db0c8300e83715155d10e131762bbef0cf9ac51049e13c1acfa",
    NATIVE: "sha256:d3c38aabd7da770bc3d417d48e4aa03c8d784954cd7713725842cba40c7d2e1f",
    FABRIQUE_RECEIPT: "sha256:1673b234263217bca517eb114728181e7227937f9e2ffdef024254e9cac2cfe8",
    CANDIDATE_AUDIT: "sha256:dba837f7a928eb4ea7c8b6734dd1f95e4baeee8ce0afcdb503baed3694c0faeb",
    PREPARED: "sha256:d807cbdc2cc53fcb83804690cfb281f4ae4b67c37f07b6e3a48e4c7ff58ef851",
    PREPARED_LEDGER: "sha256:d21ea525654229a87d83983fb20764d06d17bdd396b9e6b6383c87dbe4e2fb68",
}
EXPECTED_OUTPUTS = [
    "score/predictions-v01.jsonl",
    "score/scored-rows-v01.jsonl",
    "score/metrics-v01.json",
    "score/bootstrap-v01.npz",
    "score/label-open-receipt-v01.json",
    "score/terminal-receipt-v01.json",
    "score/stage-seal-v01.json",
]
PROJECTED_OUTPUT_BYTES = 1_877_705_408


def digest(path: Path) -> tuple[str, int]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing or linked input: {path}")
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest(), path.stat().st_size


def require_digest(path: Path, expected: str) -> dict:
    actual, size = digest(path)
    if actual != expected:
        raise ValueError(f"identity changed: {path}; expected {expected}, got {actual}")
    return {"path": str(path), "sha256": actual, "bytes": size}


def build_receipt() -> dict:
    if OUT.exists() or LEDGER_OUT.exists():
        raise ValueError("live preflight receipt already exists; preserve and inspect it")
    file_identities = [require_digest(path, expected) for path, expected in EXPECTED.items()]
    native = json.loads(NATIVE.read_bytes())
    if (native.get("run_id"), native.get("stage_id"), native.get("actor_id")) != (RUN, STAGE, ACTOR):
        raise ValueError("bound execution scope changed")
    sources = native.get("source_files", [])
    if len(sources) != 35 or len({item.get("path") for item in sources}) != 35:
        raise ValueError("source manifest count or uniqueness changed")
    if native.get("expected_outputs") != EXPECTED_OUTPUTS:
        raise ValueError("seven-output inventory changed")
    staged = [item for item in sources if Path(item["path"]).as_posix().endswith(PANEL_REL)]
    if len(staged) != 1 or staged[0].get("bytes") != PANEL_BYTES or staged[0].get("sha256") != PANEL_SHA256:
        raise ValueError("reserved panel identity changed")
    panel_path = Path(staged[0]["path"])
    if panel_path.exists() or panel_path.is_symlink():
        raise ValueError("protected panel already materialized at the worker staging path")

    source_checks = []
    for item in sources:
        path = Path(item["path"])
        if path == panel_path:
            source_checks.append({"path": str(path), "status": "NOT_MATERIALIZED_EXPECTED",
                                  "bytes": item["bytes"], "sha256": item["sha256"]})
            continue
        actual, size = digest(path)
        if actual != item["sha256"] or size != item["bytes"]:
            raise ValueError(f"worker source manifest mismatch: {path}")
        source_checks.append({"path": str(path), "status": "EXACT_MATCH", "bytes": size, "sha256": actual})

    output_root = Path(native["output_root"])
    if output_root.exists() or output_root.is_symlink():
        raise ValueError("scoring output root is not fresh")
    command = native.get("command", [])
    dynamic = {}
    for flag in ("--invocation", "--delivery"):
        if flag not in command or command.index(flag) + 1 >= len(command):
            raise ValueError(f"execution command missing {flag}")
        path = Path(command[command.index(flag) + 1])
        if path.exists() or path.is_symlink():
            raise ValueError(f"scoring handoff already exists: {path}")
        dynamic[flag] = str(path)

    terminal_sha256, _ = digest(ACCEPTANCE)
    acceptance_file = json.loads(ACCEPTANCE.read_bytes())
    if (acceptance_file.get("status") != "PASS" or acceptance_file.get("flight_state") != "OPEN"
            or acceptance_file.get("acceptance_identity") != LIBRARY_ACCEPTANCE
            or acceptance_file.get("source_root") != LIBRARY_SOURCE_ROOT
            or acceptance_file.get("scientific_flight_authorized") is not False
            or acceptance_file.get("scientific_observer_contact") is not False):
        raise ValueError("live Library acceptance terminal is not qualified")

    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    before = client.status()
    history = client.history_summary(RUN)
    if (before.get("flight_gate") != "OPEN" or before.get("acceptance_identity") != acceptance_file["acceptance_identity"]
            or before.get("journal_head") != before.get("projection_head")
            or before.get("panel_exposures") != 0 or before.get("active_lease_resources")
            or history.get("authorization_conferred") is not False or history.get("other_attempts")
            or history.get("stopped_attempts") or history.get("heads")):
        raise ValueError("live Ledger or stage history is not at the required preflight state")
    try:
        client.call("GET", f"/v1/panels/{PANEL}/exposure")
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc) or "unknown panel" not in str(exc):
            raise
    else:
        raise ValueError("reserved primary panel is already registered")

    total, used, free = shutil.disk_usage("D:\\")
    reserve = total // 10
    if free < reserve + PROJECTED_OUTPUT_BYTES:
        raise ValueError("D: free-space floor does not cover scoring outputs plus 10% reserve")
    after = client.status()
    if (after.get("journal_head") != before.get("journal_head")
            or after.get("projection_head") != before.get("projection_head")
            or after.get("panel_exposures") != 0 or after.get("active_lease_resources")):
        raise ValueError("Ledger moved during read-only preflight")

    reviewer_sha256, _ = digest(REVIEW_PACKET)
    if reviewer_sha256 != "sha256:306de3acb16cdca0e50432eb57b66ef4114a16d17c1a87f7356840f20c6b1006":
        raise ValueError("review packet identity changed")

    return {
        "schema": "CHIEF_E4_0_SCORING_LIVE_PREFLIGHT_V1",
        "status": "PASS_VISIBLE_ONLY_PREAUTHORIZATION",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"run_id": RUN, "stage_id": STAGE, "actor_id": ACTOR},
        "reviewer_decision": "READY_FOR_SCOPED_E4_0_SCORING_AUTHORIZATION",
        "review_source": "user-supplied independent reviewer response; recommendation only",
        "review_packet_sha256": reviewer_sha256,
        "review_packet_expected_sha256": "sha256:306de3acb16cdca0e50432eb57b66ef4114a16d17c1a87f7356840f20c6b1006",
        "library_acceptance": {
            "acceptance_identity": acceptance_file["acceptance_identity"],
            "source_root": acceptance_file["source_root"],
            "runtime_identity": acceptance_file["runtime_identity"],
            "terminal_path": str(ACCEPTANCE),
            "terminal_sha256": terminal_sha256,
        },
        "ledger_before_registration": {
            "journal_head": before["journal_head"], "projection_head": before["projection_head"],
            "panel_exposures": 0, "active_lease_resources": [],
            "run_authorization_conferred": False, "run_attempts": 0,
            "reserved_panel_registered": False,
        },
        "prepared_binding": {
            "prepared_artifact_id": EXPECTED[PREPARED], "prepared_seal_root": PARENT_SEAL,
            "parent_spec_seal_root": "sha256:b78318974edf607d22136279f35164c6505c8bcf9e7ba4a160f5269083f28c18",
            "policy_hash": "sha256:2478b6df065e1fbc65a34d326bc33f9b636c42342cc33ed4974a0798f93eb3d3",
        },
        "candidate_files": file_identities,
        "source_manifest": {"declared": 35, "exact_match": 34, "panel_not_materialized": 1,
                            "checks": source_checks},
        "reserved_panel": {"panel_id": PANEL, "bytes": PANEL_BYTES, "sha256": PANEL_SHA256,
                           "staging_path": str(panel_path), "staging_path_absent": True,
                           "panel_body_read": False},
        "execution_freshness": {"output_root": str(output_root), "output_root_absent": True,
                                 "dynamic_handoffs": dynamic, "dynamic_handoffs_absent": True,
                                 "expected_outputs": EXPECTED_OUTPUTS},
        "disk_preflight": {"drive": "D:", "total_bytes": total, "used_bytes": used,
                           "free_bytes": free, "reserve_floor_bytes": reserve,
                           "projected_scoring_bytes": PROJECTED_OUTPUT_BYTES, "passed": True},
        "authorization_state": {"scoring_authorized": False, "stage_authorization_issued": False,
                                "panel_open_grant_issued": False, "lease_issued": False,
                                "panel_opened": False, "scoring_started": False,
                                "e4_01_entry_open": False},
        "after_preflight_journal_head": after["journal_head"],
        "preflight_tool_sha256": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "The protected panel bytes were not materialized, opened, or hashed in this preflight.",
            "The reviewer readiness decision is a recommendation, not a scoring grant.",
            "This receipt does not authorize panel registration, exposure, execution, or E4-01.",
        ],
    }


def main() -> None:
    receipt = build_receipt()
    INBOX.mkdir(parents=True, exist_ok=True)
    with OUT.open("xb") as stream:
        stream.write(canonical(receipt))
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    artifact = client.register_file(OUT, "chief-stage-preflight", "chief-kammi",
                                    "chief-e4-score-live-preflight-v1:artifact")
    artifact_id = artifact["artifact_id"]
    if artifact_id != "sha256:" + hashlib.sha256(OUT.read_bytes()).hexdigest():
        raise ValueError("Ledger artifact identity does not match the preflight bytes")
    seal = client.create_seal([artifact_id], [PARENT_SEAL], "chief-kammi",
                              "chief-e4-score-live-preflight-v1:seal")
    after = client.status()
    if (after.get("journal_head") != after.get("projection_head")
            or after.get("panel_exposures") != 0 or after.get("active_lease_resources")):
        raise ValueError("post-registration custody state is not coherent")
    ledger_receipt = {
        "schema": "CHIEF_E4_0_SCORING_LIVE_PREFLIGHT_LEDGER_RECEIPT_V1",
        "status": "PREFLIGHT_REGISTERED_NO_SCORING_AUTHORITY",
        "preflight_artifact_id": artifact_id, "preflight_seal_root": seal["root"],
        "parent_prepared_seal_root": PARENT_SEAL,
        "journal_head": after["journal_head"], "projection_head": after["projection_head"],
        "panel_exposures": 0, "scoring_authorized": False, "e4_01_entry_open": False,
    }
    with LEDGER_OUT.open("xb") as stream:
        stream.write(canonical(ledger_receipt))
    print(json.dumps({"preflight": str(OUT), "ledger_receipt": str(LEDGER_OUT),
                      "artifact_id": artifact_id, "seal_root": seal["root"],
                      "journal_head": after["journal_head"], "scoring_authorized": False}, indent=2))


if __name__ == "__main__":
    main()
