"""Independent E4 semantic-history audit from CAS plus journal only."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from ledgerd.core import Ledger

HERE = Path(__file__).resolve().parents[1]
IMPORT = HERE / "acceptance/e4-0/history-import-v3.json"
OUTPUT = HERE / "acceptance/e4-0/history-audit-v3.json"
SOURCE = HERE / ".kammi-dev/e4-import"


def main() -> None:
    imported = json.loads(IMPORT.read_text(encoding="utf-8"))
    source = Ledger(SOURCE)
    facts = source.history(imported["run_id"])
    if len(facts) != imported["fact_count"]:
        raise ValueError("source fact count mismatch")
    for fact in facts:
        if not source.cas.verify(fact["evidence_artifact"]):
            raise ValueError("fact cites corrupt evidence")
    temp = Path(tempfile.mkdtemp(prefix="kammi-e4-history-audit-"))
    shutil.copytree(SOURCE / "objects" / "sha256", temp / "objects" / "sha256")
    (temp / "journal").mkdir(parents=True)
    shutil.copy2(SOURCE / "journal" / "events.log", temp / "journal" / "events.log")
    rebuilt = Ledger(temp)
    second = rebuilt.history(imported["run_id"])
    counts = Counter(fact["kind"] for fact in second)
    heads = [f for f in second if f["kind"] == "HEAD"]
    contact_yes = [f for f in second if f["kind"] == "CONTACT" and f["value"] == "YES"]
    summary = rebuilt.history_summary(imported["run_id"])
    same = (
        facts == second
        and source.status()["journal_head"] == rebuilt.status()["journal_head"]
        and source.status()["counts"] == rebuilt.status()["counts"]
        and len(heads) == 1
        and heads[0]["value"] == "SEALED"
        and heads[0]["object"] == "sha256:21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f"
        and not contact_yes
        and len(summary["stopped_attempts"]) >= 1
        and len(summary["head_predecessor_chains"]) == 1
        and len(summary["head_predecessor_chains"][0]) >= 2
        and summary["contact_global_state"] == "UNKNOWN_GLOBALLY"
        and not summary["authorization_conferred"]
        and len(rebuilt.verify_seal(imported["source_merkle_root"])) == 493
    )
    report = {
        "schema": "KAMMI_E4_HISTORY_AUDIT_V3",
        "status": "PASS" if same else "FAIL",
        "source": "CAS plus journal",
        "source_head": source.status()["journal_head"],
        "rebuilt_head": rebuilt.status()["journal_head"],
        "source_fact_count": len(facts),
        "rebuilt_fact_count": len(second),
        "fact_kinds": dict(sorted(counts.items())),
        "head_fact": heads[0] if len(heads) == 1 else None,
        "positive_contact_assertions": len(contact_yes),
        "stopped_attempt_count": len(summary["stopped_attempts"]),
        "head_predecessor_chain": summary["head_predecessor_chains"][0] if same else [],
        "contact_global_conclusion": "UNKNOWN_OUTSIDE_EXPLICIT_RECEIPT_SCOPES",
        "flight_authorization_conferred": False,
        "fresh_projection": str(temp / "custody.lbdb"),
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "facts": len(second), "head": report["rebuilt_head"]}))
    if not same:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
