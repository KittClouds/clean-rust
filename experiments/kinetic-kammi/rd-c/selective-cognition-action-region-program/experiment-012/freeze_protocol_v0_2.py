from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_LOCK = HERE / "protocol-lock-v0.1.json"
AMENDMENT_01_MD = HERE / "amendments" / "protocol-amendment-01.md"
AMENDMENT_01_JSON = HERE / "amendments" / "protocol-amendment-01.json"
AMENDMENT_02_MD = HERE / "amendments" / "protocol-amendment-02.md"
AMENDMENT_02_JSON = HERE / "amendments" / "protocol-amendment-02.json"
FREEZER = HERE / "freeze_protocol_v0_2.py"
OUTPUT = HERE / "protocol-lock-v0.2.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = json.loads(BASE_LOCK.read_text(encoding="utf-8"))
    a01 = json.loads(AMENDMENT_01_JSON.read_text(encoding="utf-8"))
    a02 = json.loads(AMENDMENT_02_JSON.read_text(encoding="utf-8"))
    if base.get("state") != "FROZEN_FOR_BANK_CONSTRUCTION" or base.get("task_construction_started"):
        raise SystemExit("v0.1 base is not a preconstruction protocol")
    if base.get("model_contact_authorized") is not False or a01.get("model_contact_authorized") is not False:
        raise SystemExit("an earlier lock unexpectedly authorizes observer contact")
    if a01.get("effective_requirement", {}).get("all_absent_as_evaluation_repositories_in") != ["E009", "E010", "E011"]:
        raise SystemExit("repository exclusion amendment drift")
    if a02.get("amendment_id") != "E012-PROTOCOL-A02" or a02.get("model_contact_authorized") is not False:
        raise SystemExit("candidate identifiability amendment drift")

    body = {
        "schema_version": 1,
        "program": base["program"],
        "experiment": base["experiment"],
        "effective_protocol_version": "0.2",
        "state": "FROZEN_FOR_BANK_CONSTRUCTION",
        "model_contact_authorized": False,
        "task_construction_started": False,
        "base_lock_sha256": digest(BASE_LOCK),
        "amendments": [
            {
                "id": a01["amendment_id"],
                "markdown_sha256": digest(AMENDMENT_01_MD),
                "json_sha256": digest(AMENDMENT_01_JSON),
            },
            {
                "id": a02["amendment_id"],
                "markdown_sha256": digest(AMENDMENT_02_MD),
                "json_sha256": digest(AMENDMENT_02_JSON),
            },
        ],
        "effective_repository_requirement": a01["effective_requirement"],
        "effective_candidate_channel": a02["candidate_channel"],
        "effective_support_sets": a02["support_sets"],
        "effective_pair_sufficiency_cells": a02["pair_sufficiency_cells"],
        "inherited_switchboard": base["inherited_switchboard"],
        "freezer_source_sha256": digest(FREEZER),
    }
    if OUTPUT.exists():
        current = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if current != body:
            raise SystemExit("v0.2 lock already exists and differs; create another amendment")
    else:
        OUTPUT.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(body, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
