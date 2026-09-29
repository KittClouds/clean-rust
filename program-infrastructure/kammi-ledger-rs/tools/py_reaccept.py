"""Rollback step: re-accept the unchanged Python Library on a store where Rust was accepted.

  python tools/py_reaccept.py <v1 store> <request id>

The flight gate follows the latest `LibraryAccepted`. After a Rust tenure that is Rust's, so
a rolled-back Python would stay CLOSED. This issues a new `LibraryAcceptanceV1` through the
Python Library's own `accept_library`, re-binding the evidence of the most recent Python
acceptance. It succeeds only if that evidence still proves the *current* Python source and
runtime (Python's own checks), i.e. only if the Python tree is unchanged since then.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent / "kammi-ledger"))

from ledgerd.core import Ledger  # noqa: E402
from ledgerd.identity import strict_json  # noqa: E402

root, request_id = Path(sys.argv[1]), sys.argv[2]
ledger = Ledger(root)
try:
    current = ledger.library_acceptance
    prior_python = None
    for event, _ in ledger.journal:
        if event["type"] == "LibraryAccepted":
            payload = strict_json(ledger.cas.get(event["payload_artifact"]))
            acceptance = strict_json(ledger.cas.get(payload["acceptance_artifact"]))
            if acceptance.get("schema") == "LibraryAcceptanceV1":
                prior_python = acceptance
    if prior_python is None:
        raise SystemExit("no Python acceptance in this history")
    renewed = {**prior_python, "issued_at": datetime.now(timezone.utc).isoformat(), "predecessor_acceptance": current,
               "scope": prior_python.get("scope", "") + " Re-accepted after rollback from the Rust Library."}
    identity, event = ledger.accept_library(renewed, request_id)
    state = ledger.flight_state()
    print(json.dumps({"status": "PASS" if state["state"] == "OPEN" else "FAIL", "acceptance_identity": identity, "event_id": event,
                      "flight_state": state, "predecessor_acceptance": current, "journal_head": ledger.journal.head}))
finally:
    ledger.close()
