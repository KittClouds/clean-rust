from __future__ import annotations

from pathlib import Path
from typing import Any

from s04_common import (
    CONTRACT,
    PROTOCOL_SEAL,
    RUN,
    FailClosed,
    canonical_root,
    iter_jsonl,
    read_json,
    sha_file,
    verify_parents,
    verify_protocol_bundle,
    write_json,
)


def _entry(relative: str) -> dict[str, Any]:
    path = RUN / relative
    if not path.is_file():
        raise FailClosed(f"Missing required S04 result artifact: {relative}")
    return {"path": relative, "sha256": sha_file(path), "bytes": path.stat().st_size}


def _verify_jsonl_rows(path: Path, expected: int) -> None:
    count = 0
    for row in iter_jsonl(path):
        if row.get("track_id") != "FACTORIAL_BALANCED" or set(row.get("views", {})) != {"V0_MEAN_FULL", "V1_FINAL_POSITION"}:
            raise FailClosed("S04 ledger contains a row outside the frozen analysis scope")
        if set(row.get("surface_differentials_final_minus_mean", {})) != {"C", "E", "P"}:
            raise FailClosed("S04 ledger has invalid surface-differential factors")
        if set(row.get("surface_shift_final_minus_mean", {})) != {"A", "C", "E", "P"}:
            raise FailClosed("S04 ledger has invalid paired surface-shift variants")
        count += 1
    if count != expected:
        raise FailClosed(f"S04 ledger row count mismatch: {count} != {expected}")


def main() -> None:
    seal_path = RUN / "result-tree-seal-v01.json"
    if seal_path.exists():
        raise FailClosed("Refusing to replace an existing S04 result-tree seal")
    protocol = verify_protocol_bundle()
    parents = verify_parents()
    eligibility = read_json(RUN / "design-eligibility-v01.json")
    audit = read_json(RUN / "design-audit-receipt-v01.json")
    preflight = read_json(RUN / "preflight-receipt-v01.json")
    execution = read_json(RUN / "execution-receipt-v01.json")
    summary = read_json(RUN / "margin-summary-v01.json")
    contract = read_json(CONTRACT)
    expected_quartets = int(eligibility.get("selected_factorial_test_quartets", -1))
    if (eligibility.get("status") != "PASS" or audit.get("status") != "PASS" or
            preflight.get("S04_DESIGN_AUDIT_PASS") is not True or
            execution.get("status") != "COMPLETE" or
            execution.get("protocol_root_sha256") != protocol["root_sha256"] or
            execution.get("analysis_contract_sha256") != sha_file(CONTRACT) or
            execution.get("parents") != parents or preflight.get("parents") != parents or
            summary.get("status") != "COMPLETE" or summary.get("quartets") != expected_quartets or
            expected_quartets <= 0):
        raise FailClosed("S04 receipts or result disposition are inconsistent")
    for flag in (
        "model_contact", "LFM_loaded", "feature_extraction", "probe_fitting",
        "optimizer_continuation", "adaptive_mechanisms", "significance_tests",
        "confidence_intervals", "FAS00_PHASE4_AUTHORIZED", "SAE_ANALYSIS_AUTHORIZED",
        "FAS00_modified", "S01_modified",
    ):
        if execution.get(flag) is not False:
            raise FailClosed(f"S04 execution receipt violates authority boundary: {flag}")
    _verify_jsonl_rows(RUN / "quartet-margin-ledger-v01.jsonl", expected_quartets)

    required = list(contract["required_outputs"])
    if len(required) != len(set(required)):
        raise FailClosed("S04 contract contains duplicate required output names")
    entries = [_entry(relative) for relative in required]
    root = canonical_root(entries)
    result_seal = {
        "seal_id": "FAS_S04_RESULT_TREE_SEAL_V01",
        "experiment_id": "fas-s04-controlled-factor-to-decision-transfer-geometry-v01",
        "protocol_root_sha256": protocol["root_sha256"],
        "analysis_contract_sha256": sha_file(CONTRACT),
        "parent_roots": parents,
        "entries": entries,
        "root_sha256": root,
        "selected_quartets": expected_quartets,
        "selected_events": expected_quartets * 4,
        "S04_PROTOCOL_SEALED": True,
        "S04_DESIGN_AUDIT_PASS": True,
        "S04_MARGIN_ANALYSIS_COMPLETE": True,
        "S04_MODEL_CONTACT": False,
        "S04_PROBE_FITTING": False,
        "FAS00_SENSOR_PASS": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "SAE_ANALYSIS_AUTHORIZED": False,
    }
    write_json(seal_path, result_seal)

    independent_entries = []
    for row in result_seal["entries"]:
        path = RUN / row["path"]
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha_file(path) != row["sha256"]:
            raise FailClosed(f"Independent S04 result rehash failed: {row['path']}")
        independent_entries.append({"path": row["path"], "sha256": sha_file(path)})
    if canonical_root(independent_entries) != root:
        raise FailClosed("Independent S04 result-tree root does not reproduce")
    check = read_json(seal_path)
    if check.get("root_sha256") != root:
        raise FailClosed("S04 result seal did not persist")
    print(f"S04_RESULT_TREE_SEALED root={root} outputs={len(entries)} quartets={expected_quartets}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"S04_SEAL_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
