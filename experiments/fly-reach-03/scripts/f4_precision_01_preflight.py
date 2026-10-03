"""Fail-closed preflight for the qualification-only F4 precision audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
RUN = STUDY / "runs/qualification-v2/f4-precision-01-attempt-02"
MEASURED_PATHS = (
    STUDY / "runs/measured",
    STUDY / "inputs/measured",
    STUDY / "artifacts/measured",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    contract_path = STUDY / "F4-PRECISION-01-CONTRACT-v0.1.3.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("identity") != "F4-PRECISION-01":
        raise SystemExit("unexpected precision identity")
    if contract.get("status") != "QUALIFICATION_ONLY_FROZEN":
        raise SystemExit("contract is not frozen for qualification-only work")
    if contract.get("measured_execution_authorized") is not False:
        raise SystemExit("precision branch may not authorize measured execution")
    if sha(Path(__file__).resolve()) != contract["preflight_script_sha256"]:
        raise SystemExit("preflight script differs from frozen contract")
    if sha(STUDY / "scripts/f4_precision_01.py") != contract["analysis_script_sha256"]:
        raise SystemExit("analysis script differs from frozen contract")

    verified = []
    for entry in contract["frozen_inputs"]:
        path = STUDY / entry["path"]
        if not path.is_file():
            raise SystemExit(f"missing frozen input: {entry['path']}")
        actual = sha(path)
        if actual != entry["sha256"]:
            raise SystemExit(f"frozen input hash mismatch: {entry['path']}")
        verified.append({"path": entry["path"], "sha256": actual, "bytes": path.stat().st_size})

    parent_path = STUDY / "F4-CAPACITY-01-TERMINAL-RECEIPT.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    if parent.get("status") != "DIAGNOSTIC_COMPLETE_REPRESENTATION_PRECISION_PRESSURE":
        raise SystemExit("parent F4-CAPACITY-01 terminal status changed")
    if parent.get("measured_namespace_created") is not False:
        raise SystemExit("parent qualification boundary changed")
    if len(list((STUDY / "runs/qualification-v2/f4-features-v1").glob("*.bin"))) != 72:
        raise SystemExit("Arm A stream count is not 72")
    if RUN.exists():
        raise SystemExit("precision output identity already exists; preserve and stop")
    preflight_path = STUDY / contract["preflight_receipt_path"]
    if preflight_path.exists():
        raise SystemExit("preflight receipt already exists; preserve and stop")
    for path in MEASURED_PATHS:
        if path.exists():
            raise SystemExit(f"measured namespace exists: {path}")

    receipt = {
        "schema": "FLY-REACH-03-F4-PRECISION-01-preflight-v1",
        "identity": "F4-PRECISION-01",
        "status": "PASS",
        "contract_sha256": sha(contract_path),
        "parent_terminal_receipt_sha256": sha(parent_path),
        "frozen_input_count": len(verified),
        "frozen_inputs": verified,
        "arm_a_stream_count": 72,
        "precision_output_absent_before_collection": True,
        "measured_namespace_absent": True,
        "measured_execution_authorized": False,
        "result_interpretation_opened": False,
    }
    output = preflight_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "contract_sha256": receipt["contract_sha256"], "inputs": len(verified)}))


if __name__ == "__main__":
    main()
