"""Register Chief's extraction preparation receipt without opening flight."""
from __future__ import annotations

import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
PREPARED = INBOX / "E4-0-EXTRACT-STAGE-PREPARED-v1.json"
OUT = INBOX / "E4-0-EXTRACT-PREPARED-LEDGER-RECEIPT-v1.json"


def main() -> None:
    if OUT.exists():
        raise ValueError("prepared Ledger receipt already exists")
    prepared = json.loads(PREPARED.read_bytes())
    if prepared["status"] != "SPECS_BOUND_SEAL_VERIFIED_FLIGHT_AUTHORITY_WITHHELD":
        raise ValueError("extract stage is not prepared")
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    artifact = client.register_file(PREPARED, "e4-extract-prepared-receipt", "chief-kammi",
                                    "chief-e4-extract-prepared-v1:artifact")
    seal = client.create_seal([artifact["artifact_id"]], [prepared["spec_seal_root"]],
                              "chief-kammi", "chief-e4-extract-prepared-v1:seal")
    result = {
        "schema": "CHIEF_E4_0_EXTRACT_PREPARED_LEDGER_RECEIPT_V1",
        "status": "PREPARED_REGISTERED_FLIGHT_AUTHORITY_WITHHELD",
        "artifact_id": artifact["artifact_id"], "seal_root": seal["root"],
        "stage_id": prepared["stage_id"],
        "model_contact_authorized": False, "e4_01_entry_open": False,
    }
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "seal_root": seal["root"]}))


if __name__ == "__main__":
    main()
