"""Bind E4 handoff and local qualification to the prior Chief custody seal."""
import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
OUT = INBOX / "E4-0-SUPERVISED-HANDOFF-LEDGER-RECEIPT-v1.json"


def main():
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    names = ("KAMMI-LOCAL-HANDOFF-QUALIFICATION-v1.json",
             "KAMMI-LOCAL-HANDOFF-AUDIT-v1.json", "E4-0-SUPERVISED-HANDOFF-v1.md")
    for name in names[:2]:
        if json.loads((INBOX / name).read_bytes())["status"] != "PASS":
            raise ValueError("local qualification is not passing")
    records = [client.register_file(INBOX / name, "chief-supervised-handoff",
                                    "chief-kammi", "chief-e4-handoff-v1:" + name)
               for name in names]
    parent = json.loads((INBOX / "E4-0-INHERITANCE-LEDGER-RECEIPT-v1.json").read_bytes())[
        "seal"]["root"]
    seal = client.create_seal([row["artifact_id"] for row in records], [parent],
                              "chief-kammi", "chief-e4-handoff-v1:seal")
    result = {"schema": "CHIEF_E4_SUPERVISED_HANDOFF_LEDGER_RECEIPT_V1",
              "status": "LIBRARY_INTERFACE_QUALIFIED_E4_AUTH_WITHHELD",
              "artifacts": records, "seal": seal,
              "e4_0_model_contact_authorized": False,
              "e4_01_entry_open": False}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "seal_root": seal["root"]}))


if __name__ == "__main__":
    main()
