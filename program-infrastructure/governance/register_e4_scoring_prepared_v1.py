"""Register Chief's sealed E4-0 scoring preparation receipt without flight authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.identity import canonical


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260928"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
SOURCE = INBOX / "E4-0-SCORING-STAGE-PREPARED-v1.json"
OUT = INBOX / "E4-0-SCORING-PREPARED-LEDGER-RECEIPT-v1.json"
SOURCE_ID = "sha256:d807cbdc2cc53fcb83804690cfb281f4ae4b67c37f07b6e3a48e4c7ff58ef851"
PARENT = "sha256:b78318974edf607d22136279f35164c6505c8bcf9e7ba4a160f5269083f28c18"


def main() -> None:
    if OUT.exists():
        raise ValueError("preparation registration already recorded")
    with SOURCE.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != SOURCE_ID:
        raise ValueError("Chief preparation receipt changed")
    prepared = json.loads(SOURCE.read_bytes())
    if (prepared["status"] != "SPECS_BOUND_SEAL_VERIFIED_SCORING_AUTHORITY_WITHHELD"
            or prepared["spec_seal_root"] != PARENT
            or prepared["stage_authorization_issued"]
            or prepared["primary_panel_exposure_count"]):
        raise ValueError("preparation receipt claims scoring authority or exposure")
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    status = client.status()
    if status["flight_gate"] != "OPEN" or status["panel_exposures"] != 0:
        raise ValueError("Library or panel state changed before registration")
    artifact = client.register_file(SOURCE, "e4-scoring-stage-prepared", "chief-kammi",
                                    "chief-e4-score-prepare-v1:prepared-artifact")["artifact_id"]
    if artifact != SOURCE_ID:
        raise ValueError("Ledger registered the wrong preparation bytes")
    seal = client.create_seal([artifact], [PARENT], "chief-kammi",
                              "chief-e4-score-prepare-v1:prepared-seal")
    after = client.status()
    if after["journal_head"] != after["projection_head"] or after["panel_exposures"]:
        raise ValueError("custody projection or panel exposure changed")
    receipt = {
        "schema": "CHIEF_E4_0_SCORING_PREPARED_LEDGER_RECEIPT_V1",
        "status": "PREPARED_AND_REGISTERED_NO_SCORING_AUTHORITY",
        "prepared_artifact_id": artifact,
        "prepared_seal_root": seal["root"],
        "parent_spec_seal_root": PARENT,
        "journal_head": after["journal_head"],
        "projection_head": after["projection_head"],
        "panel_exposures": 0,
        "scoring_authorized": False,
        "e4_01_entry_open": False,
    }
    with OUT.open("xb") as stream:
        stream.write(canonical(receipt))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
