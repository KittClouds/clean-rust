from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_LOCK = HERE / "protocol-lock-v0.2.json"
AMENDMENT_MD = HERE / "amendments" / "protocol-amendment-03.md"
AMENDMENT_JSON = HERE / "amendments" / "protocol-amendment-03.json"
FREEZER = HERE / "freeze_protocol_v0_3.py"
OUTPUT = HERE / "protocol-lock-v0.3.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = json.loads(BASE_LOCK.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT_JSON.read_text(encoding="utf-8"))
    if base.get("effective_protocol_version") != "0.2":
        raise SystemExit("base lock is not protocol v0.2")
    if base.get("state") != "FROZEN_FOR_BANK_CONSTRUCTION" or base.get("task_construction_started"):
        raise SystemExit("base lock is not preconstruction")
    if base.get("model_contact_authorized") is not False:
        raise SystemExit("base lock unexpectedly authorizes model contact")
    if amendment.get("amendment_id") != "E012-PROTOCOL-A03":
        raise SystemExit("unexpected amendment identity")
    if amendment.get("model_contact_authorized") is not False or amendment.get("task_construction_started"):
        raise SystemExit("amendment crossed the preconstruction boundary")

    body = {
        "schema_version": 1,
        "program": base["program"],
        "experiment": base["experiment"],
        "effective_protocol_version": "0.3",
        "state": "FROZEN_FOR_BANK_CONSTRUCTION",
        "model_contact_authorized": False,
        "task_construction_started": False,
        "base_lock_sha256": digest(BASE_LOCK),
        "amendments": base["amendments"] + [
            {
                "id": amendment["amendment_id"],
                "markdown_sha256": digest(AMENDMENT_MD),
                "json_sha256": digest(AMENDMENT_JSON),
            }
        ],
        "effective_repository_requirement": base["effective_repository_requirement"],
        "effective_candidate_channel": amendment["candidate_channel"],
        "effective_support_sets": amendment["effective_support_sets"],
        "diagnostic_only_cells": amendment["diagnostic_only_cells"],
        "effective_pair_sufficiency_cells": amendment["valid_sufficiency_cells"],
        "necessary_channel_test": amendment["necessary_channel_test"],
        "coordinate_contract": amendment["coordinate_contract"],
        "inherited_switchboard": base["inherited_switchboard"],
        "freezer_source_sha256": digest(FREEZER),
    }
    if OUTPUT.exists():
        current = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if current != body:
            raise SystemExit("v0.3 lock already exists and differs; create another amendment")
    else:
        OUTPUT.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(body, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
