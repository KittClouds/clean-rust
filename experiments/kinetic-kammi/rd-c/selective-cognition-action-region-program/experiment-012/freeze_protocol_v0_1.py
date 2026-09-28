from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_LOCK = HERE / "protocol-lock-v0.json"
AMENDMENT_MD = HERE / "amendments" / "protocol-amendment-01.md"
AMENDMENT_JSON = HERE / "amendments" / "protocol-amendment-01.json"
FREEZER = HERE / "freeze_protocol_v0_1.py"
OUTPUT = HERE / "protocol-lock-v0.1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = json.loads(BASE_LOCK.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT_JSON.read_text(encoding="utf-8"))
    if base.get("state") != "FROZEN_FOR_BANK_CONSTRUCTION":
        raise SystemExit("base E012 protocol is not frozen")
    if base.get("task_construction_started") or base.get("model_contact_authorized"):
        raise SystemExit("base lock crossed the task/model boundary unexpectedly")
    if amendment.get("amendment_id") != "E012-PROTOCOL-A01":
        raise SystemExit("unexpected amendment identity")

    body = {
        "schema_version": 1,
        "program": base["program"],
        "experiment": base["experiment"],
        "effective_protocol_version": "0.1",
        "state": "FROZEN_FOR_BANK_CONSTRUCTION",
        "model_contact_authorized": False,
        "task_construction_started": False,
        "base_lock_sha256": digest(BASE_LOCK),
        "amendment_id": amendment["amendment_id"],
        "amendment_sha256": {
            "markdown": digest(AMENDMENT_MD),
            "json": digest(AMENDMENT_JSON),
        },
        "effective_repository_requirement": amendment["effective_requirement"],
        "effective_bank_minimums": base["bank_requirements"],
        "inherited_switchboard": base["inherited_switchboard"],
        "freezer_source_sha256": digest(FREEZER),
    }
    if OUTPUT.exists():
        current = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if current != body:
            raise SystemExit("v0.1 lock already exists and differs; create another amendment")
    else:
        OUTPUT.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(body, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
