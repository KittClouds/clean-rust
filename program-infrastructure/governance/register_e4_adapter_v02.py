"""Register accepted v02 construction identities without E4 flight authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
PLAN = LAB / "plans/E4-0-LEDGER-EXECUTION-SPEC-CANDIDATES-v02.json"
QUAL = LAB / "audits/e4-0-supervised-adapter-v02/qualification-receipt.json"
BINDING = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01"
               r"\e4-0-ledger-bindings-v02\online-cache-parity-binding-v02.json")
OUT = INBOX / "E4-0-ADAPTER-V02-LEDGER-RECEIPT-v1.json"


def identity(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return digest, path.stat().st_size


def main():
    plan = json.loads(PLAN.read_bytes())
    qual = json.loads(QUAL.read_bytes())
    if not plan["status"].endswith("NOT_REGISTERED_NOT_AUTHORIZED"):
        raise ValueError("Fabrique plan does not remain candidate-only")
    if qual["status"] != "PASS_SYNTHETIC_NO_MODEL_CONTACT":
        raise ValueError("Fabrique synthetic qualification is not passing")
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    status = client.status()
    if status["flight_gate"] != "OPEN" or status["acceptance_identity"] != plan["library_acceptance_id"]:
        raise ValueError("Library acceptance differs from v02 adapter")
    binding = json.loads(BINDING.read_bytes())
    if binding["library_handoff"]["library_acceptance_id"] != status["acceptance_identity"]:
        raise ValueError("official binding points to another Library acceptance")
    files = [("candidate-plan", PLAN), ("synthetic-qualification", QUAL),
             ("chief-static-parity-binding", BINDING)]
    files.extend((f"runtime-source-{index}", Path(item["path"]))
                 for index, item in enumerate(plan["shared_runtime_source_files"]))
    test = qual["qualification_test"]
    files.append(("synthetic-test-source", Path(test["path"])))
    for item in plan["shared_runtime_source_files"]:
        if identity(Path(item["path"])) != (item["sha256"].removeprefix("sha256:"), item["bytes"]):
            raise ValueError("Fabrique source changed: " + item["path"])
    if identity(Path(test["path"])) != (test["sha256"], test["bytes"]):
        raise ValueError("Fabrique test source changed")
    records = {}
    for label, path in files:
        records[label] = client.register_file(path, "e4-supervised-adapter-v02",
                                              "chief-kammi", "chief-e4-adapter-v02:" + label)
    parent = json.loads((INBOX / "E4-0-STATIC-INPUT-LEDGER-RECEIPT-v1.json").read_bytes())[
        "seal"]["root"]
    seal = client.create_seal([item["artifact_id"] for item in records.values()],
                              [parent], "chief-kammi", "chief-e4-adapter-v02:seal")
    result = {"schema": "CHIEF_E4_0_ADAPTER_V02_LEDGER_RECEIPT_V1",
              "status": "V02_CONSTRUCTION_IDENTITIES_REGISTERED_AUTHORITY_WITHHELD",
              "artifacts": records, "seal": seal,
              "binding_sha256": "sha256:" + identity(BINDING)[0],
              "e4_0_stage_authorization_issued": False,
              "gpu_lease_issued": False, "e4_01_entry_open": False}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "seal_root": seal["root"],
                      "binding_sha256": result["binding_sha256"], "artifacts": len(records)}))


if __name__ == "__main__":
    main()
