"""Fail-closed OBS-OPEN-03 protocol-completeness preflight.

This tool reads contracts and partition metadata only. It never opens market
observations from discovery or confirmation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
UNIVERSE_ROOT = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235"
PROTOCOL_ROOT = "141344869c5e6aba6bc7346594872efdc196cb246c834f8d510a0aad90831bb5"
REPAIR_ROOT = "dc8826042d490c5b1e868b836f4c187af8e2baedf9454d11b2be2a5a5aae3da7"


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect() -> dict[str, object]:
    base = ROOT / "studies/obs-open-01"
    measurement_path = base / "contracts/obs_open_02_discovery_measurement_v1.json"
    repair_path = base / "contracts/obs_open_02r1_familywise_rule_v1.json"
    partition_path = base / "qualification/universe/universe/partition_manifest.tsv"
    repair_receipt_path = base / "qualification/universe/obs-open-02r1-seal/obs_open_02r1_repair_root_receipt.json"
    measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    repair_receipt = json.loads(repair_receipt_path.read_text(encoding="utf-8"))
    if measurement["parent_qualification_root_sha256"] != UNIVERSE_ROOT:
        raise ValueError("universe root mismatch")
    if repair["parent_protocol_root_sha256"] != PROTOCOL_ROOT:
        raise ValueError("protocol root mismatch")
    if repair_receipt["repair_root_sha256"] != REPAIR_ROOT:
        raise ValueError("repair root mismatch")

    with partition_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    counts = Counter(row["partition"] for row in rows)
    if counts != Counter({"DISCOVERY": 257, "CONFIRMATION": 69}):
        raise ValueError("partition count mismatch")

    required_estimand_fields = {
        "population",
        "eligibility_denominator",
        "availability_rules",
        "future_confirmation_estimand",
    }
    missing_by_template = {
        row["template_id"]: sorted(required_estimand_fields - set(row))
        for row in repair["formal_estimand_templates"]
        if required_estimand_fields - set(row)
    }
    temporal = repair["temporal_stability"]
    missing_temporal = sorted({
        "chronological_block_definition",
        "leave_one_month_out_definition",
        "slice_support_by_view",
    } - set(temporal))

    issues: list[dict[str, object]] = []
    if "measurement_definitions" not in measurement:
        issues.append({
            "code": "DESCRIPTIVE_MEASUREMENT_FORMULAS_UNDEFINED",
            "detail": "measurement names exist without executable formulas for the complete census",
        })
    if missing_by_template:
        issues.append({
            "code": "FORMAL_ESTIMAND_REGISTRY_INCOMPLETE",
            "detail": missing_by_template,
        })
    if missing_temporal:
        issues.append({
            "code": "TEMPORAL_ROBUSTNESS_CONSTRUCTION_UNDEFINED",
            "detail": missing_temporal,
        })
    if not isinstance(repair.get("promotion", {}).get("future_confirmation_estimand_complete"), dict):
        issues.append({
            "code": "CONFIRMATION_ESTIMAND_EMITTER_UNDEFINED",
            "detail": "boolean declaration exists without an executable output schema or constructor",
        })
    if "candidate_rejection_transition_table" not in repair:
        issues.append({
            "code": "REJECTION_LEDGER_TRANSITIONS_INCOMPLETE",
            "detail": "reason vocabulary exists without exhaustive state-transition semantics",
        })

    receipt: dict[str, object] = {
        "schema": "OBS_OPEN_03_PROTOCOL_COMPLETENESS_PREFLIGHT_V1",
        "study_id": "OBS-OPEN-01",
        "gate": "OBS-OPEN-03",
        "outcome": "ABORTED_PREEXECUTION_PROTOCOL_INCOMPLETE" if issues else "PASS",
        "universe_root_sha256": UNIVERSE_ROOT,
        "protocol_root_sha256": PROTOCOL_ROOT,
        "repair_root_sha256": REPAIR_ROOT,
        "discovery_sessions_declared": counts["DISCOVERY"],
        "confirmation_sessions_declared": counts["CONFIRMATION"],
        "discovery_census_rows_produced": 0,
        "formal_estimands_evaluated": 0,
        "candidate_rows_produced": 0,
        "confirmation_observations_read": False,
        "confirmation_status": "FROZEN_UNOPENED",
        "source_schema_probe": {
            "rows_materialized": 2,
            "rows_inside_admitted_opening_windows": 0,
            "aggregate_or_candidate_computation": False,
        },
        "issues": issues,
        "authority_hashes": {
            "measurement_contract_sha256": sha256(measurement_path),
            "repair_contract_sha256": sha256(repair_path),
            "partition_manifest_sha256": sha256(partition_path),
        },
        "economic_authority": False,
        "trading_authority": False,
    }
    logical = dict(receipt)
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(logical)).hexdigest()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = inspect()
    args.output.write_bytes(canonical_json(receipt))
    print(receipt["outcome"])
    return 3 if receipt["outcome"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
