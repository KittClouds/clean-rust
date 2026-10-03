"""Register the bounded E4 inheritance receipt through the live Ledger API."""
from __future__ import annotations

import json
from pathlib import Path

from ledgerd.client import KammiClient


LIB = Path(r"C:\code land\clean-rust\program-infrastructure\kammi-ledger")
HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
RECEIPT = INBOX / "E4-0-INHERITANCE-BRIDGE-v1.json"
PREVIOUS = INBOX / "E4-0-MODEL-CONTACT-CUSTODY-RECEIPT-v1.json"
OUT = INBOX / "E4-0-INHERITANCE-LEDGER-RECEIPT-v1.json"


def main() -> None:
    bridge = json.loads(RECEIPT.read_bytes())
    if bridge["authorization_conferred"] or bridge["truth_label_bytes_opened"]:
        raise ValueError("inheritance bridge cannot confer flight or open labels")
    token_path = LIB / ".kammi-dev/operational/admin.secret"
    client = KammiClient("http://127.0.0.1:8765", token_path.read_text().strip())
    status = client.status()
    if status["flight_gate"] != "OPEN":
        raise ValueError("Library acceptance gate is closed")
    artifacts = []
    for label, item in bridge["contracts"].items():
        artifacts.append((label, Path(item["path"])))
    for stage in bridge["stages"]:
        artifacts.append((stage["stage"] + "-manifest", Path(stage["manifest"]["path"])))
    artifacts.append(("inheritance-bridge", RECEIPT))
    registered = {}
    for label, path in artifacts:
        response = client.register_file(path, "e4-inheritance-visible", "chief-kammi",
                                        "chief-e4-inheritance-v1:" + label)
        registered[label] = response
    parent = json.loads(PREVIOUS.read_bytes())["seal"]["root"]
    seal = client.create_seal([row["artifact_id"] for row in registered.values()], [parent],
                              "chief-kammi", "chief-e4-inheritance-v1:seal")
    result = {"schema": "CHIEF_E4_INHERITANCE_LEDGER_RECEIPT_V1",
              "status": "VISIBLE_INHERITANCE_REGISTERED",
              "artifacts": registered, "seal": seal,
              "scientific_stage_authorized": False, "model_contact_authorized": False,
              "protected_label_bytes_opened": False,
              "flight_gate_at_registration": status["flight_gate"]}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "seal_root": seal["root"],
                      "artifacts": len(registered), "model_contact_authorized": False}))


if __name__ == "__main__":
    main()
