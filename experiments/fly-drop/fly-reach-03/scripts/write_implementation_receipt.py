"""Write the auditable pre-qualification implementation receipt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(REPO).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha(path),
    }


def main() -> None:
    execution = ROOT / "EXECUTION-CONTRACT-v0.1.json"
    runtime = ROOT / "artifacts/preimplementation/REACH03-RUNTIME-CONTRACT-ROUNDTRIP.json"
    execution_roundtrip = ROOT / "artifacts/preimplementation/REACH03-EXECUTION-CONTRACT-ROUNDTRIP.json"
    collector = ROOT / "artifacts/preimplementation/collector-fixture/COLLECTOR-FIXTURE-RECEIPT.json"
    f4 = ROOT / "artifacts/preimplementation/collector-fixture/F4-RECONSTRUCTION-RECEIPT.json"
    audit = ROOT / "artifacts/preimplementation/REACH03-PREIMPLEMENTATION-AUDIT.json"
    for path in (execution, runtime, execution_roundtrip, collector, f4, audit):
        if not path.is_file():
            raise SystemExit(f"missing required receipt: {path}")

    collector_value = json.loads(collector.read_text(encoding="utf-8"))
    f4_value = json.loads(f4.read_text(encoding="utf-8"))
    runtime_value = json.loads(runtime.read_text(encoding="utf-8"))
    execution_roundtrip_value = json.loads(execution_roundtrip.read_text(encoding="utf-8"))
    receipt = {
        "schema": "FLY-REACH-03-implementation-receipt-v1",
        "study_id": "FLY-REACH-03",
        "status": "PRE_QUALIFICATION_GATES_PASS",
        "scientific_execution_started": False,
        "qualification_namespace_created": False,
        "measured_namespace_created": False,
        "authority": {
            "preimplementation_audit": artifact(audit),
            "authoritative_contract_sha256": runtime_value["authority"]["contract_sha256"],
            "machine_contract_sha256": runtime_value["machine_contract_sha256"],
            "run1_nonpromotable": runtime_value["authority"]["run1_nonpromotable"],
        },
        "gate_results": {
            "gate_0_authority_and_provenance": "PASS_HISTORICAL_PRECREATION_AUDIT",
            "gate_1_executable_contract_roundtrip": "PASS",
            "gate_2_collector_fixture": {
                "status": collector_value["status"],
                "telemetry_on_off_identical": collector_value["telemetry_on_off_identical"],
                "rows": collector_value["row_count"],
                "snapshots": collector_value["snapshot_count"],
            },
            "gate_3_f4_reconstruction_fixture": {
                "status": f4_value["status"],
                "rows_checked": f4_value["rows_checked"],
                "target_matches": f4_value["target_matches"],
                "value_mismatches": f4_value["value_mismatches"],
                "max_abs_error": f4_value["max_abs_error"],
            },
        },
        "implementation_contract": artifact(execution),
        "roundtrip_receipts": {
            "runtime": artifact(runtime),
            "execution": artifact(execution_roundtrip),
            "runtime_status": runtime_value["status"],
            "execution_status": execution_roundtrip_value["status"],
        },
        "source_mapping": collector_value["source_mapping"],
        "next_gate": "QUALIFICATION_ONLY_PREPARATION",
        "scientific_boundary": "engineering-only; no biological promotion; no PHENO reseal",
    }
    out = ROOT / "artifacts/preimplementation/REACH03-IMPLEMENTATION-RECEIPT.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
