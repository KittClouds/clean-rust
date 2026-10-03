"""Preserve the rejected Fabrique v01 adapter and Chief review in custody."""
import json
from pathlib import Path

from ledgerd.client import KammiClient


HERE = Path(__file__).parent
INBOX = HERE / "inbox/20260927"
OP = HERE.parent / "kammi-ledger/.kammi-dev/operational"
PLAN = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01/plans/"
    "E4-0-LEDGER-EXECUTION-SPEC-CANDIDATES-v01.json"
)
QUAL = PLAN.parent.parent / "audits/e4-0-supervised-adapter-v01/qualification-receipt.json"
OUT = INBOX / "E4-0-ADAPTER-REVIEW-LEDGER-RECEIPT-v1.json"


def main():
    plan = json.loads(PLAN.read_bytes())
    review = json.loads((INBOX / "E4-0-ADAPTER-REVIEW-v1.json").read_bytes())
    if plan["status"] != "FABRIQUE_CANDIDATE_ONLY_NOT_REGISTERED_NOT_AUTHORIZED":
        raise ValueError("candidate status changed")
    if review["status"] != "HOLD_VERSIONED_REPAIR_REQUIRED":
        raise ValueError("Chief review is not a hold")
    client = KammiClient("http://127.0.0.1:8765", (OP / "admin.secret").read_text().strip())
    inputs = [("candidate-plan", PLAN), ("synthetic-qualification", QUAL),
              ("chief-review", INBOX / "E4-0-ADAPTER-REVIEW-v1.json")]
    inputs.extend((f"source-{index}", Path(item["path"]))
                  for index, item in enumerate(plan["shared_runtime_source_files"]))
    receipts = {}
    for label, path in inputs:
        receipts[label] = client.register_file(path, "e4-adapter-review-v1", "chief-kammi",
                                               "chief-e4-adapter-review-v1:" + label)
    parent = json.loads((INBOX / "E4-0-SUPERVISED-HANDOFF-LEDGER-RECEIPT-v1.json").read_bytes())[
        "seal"]["root"]
    seal = client.create_seal([item["artifact_id"] for item in receipts.values()],
                              [parent], "chief-kammi", "chief-e4-adapter-review-v1:seal")
    result = {"schema": "CHIEF_E4_0_ADAPTER_REVIEW_LEDGER_RECEIPT_V1",
              "status": "REJECTED_CANDIDATE_PRESERVED",
              "artifacts": receipts, "seal": seal,
              "e4_0_authorization_issued": False, "gpu_lease_issued": False,
              "e4_01_entry_open": False}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "seal_root": seal["root"],
                      "artifacts": len(receipts)}))


if __name__ == "__main__":
    main()
