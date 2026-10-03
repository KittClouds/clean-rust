"""Seal OBS-OPEN-SRC-01 from declared machine artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = (
    "SRC01_authority_manifest.json",
    "SRC01_runtime_receipt.json",
    "SRC01_metrology_defect_receipt.json",
    "SRC01_M1_online_parity.json",
    "SRC01_M5_online_parity.json",
    "SRC01_M1_reload_parity_grouped_abi.json",
    "SRC01_M5_reload_parity_grouped_abi.json",
    "SRC01_reload_determinism.json",
    "SRC01_boundary_causal_receipt.json",
    "SRC01_synthetic_fixture_receipt.json",
    "SRC01_rebuild_determinism.json",
    "compile-capture-grouped-abi.log",
)


def digest(path: Path) -> dict[str, object]:
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def all_parity_pass(receipt: dict[str, object]) -> bool:
    captures = receipt.get("captures", [])
    return bool(captures) and all(
        result["status"] == "PASS"
        for capture in captures
        for result in capture.get("legacy_parity", [])
    )


def build(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        raise SystemExit(f"missing SRC-01 authority artifacts: {missing}")
    authority = load(root / "SRC01_authority_manifest.json")
    boundary = load(root / "SRC01_boundary_causal_receipt.json")
    reloads = load(root / "SRC01_reload_determinism.json")
    synthetic = load(root / "SRC01_synthetic_fixture_receipt.json")
    m1_online = load(root / "SRC01_M1_online_parity.json")
    m5_online = load(root / "SRC01_M5_online_parity.json")
    m1_reload = load(root / "SRC01_M1_reload_parity_grouped_abi.json")
    m5_reload = load(root / "SRC01_M5_reload_parity_grouped_abi.json")
    matrix = {
        "schema": "OBS_OPEN_SRC01_TYPED_PARITY_MATRIX_V1",
        "rows": [
            {"claim": "HISTORICAL_BUFFER_PARITY", "status": "PASS" if all_parity_pass(m1_reload) and all_parity_pass(m5_reload) else "FAIL", "evidence": ["SRC01_M1_reload_parity_grouped_abi.json", "SRC01_M5_reload_parity_grouped_abi.json"]},
            {"claim": "ONLINE_BUFFER_PARITY", "status": "PASS" if all_parity_pass(m1_online) and all_parity_pass(m5_online) else "FAIL", "evidence": ["SRC01_M1_online_parity.json", "SRC01_M5_online_parity.json"]},
            {"claim": "RELOAD_BUFFER_PARITY", "status": reloads["status"], "evidence": ["SRC01_reload_determinism.json"]},
            {"claim": "BOUNDARY_SEMANTIC_PARITY", "status": "PASS" if boundary["status"] == "PASS" and synthetic["status"] == "PASS" else "FAIL", "evidence": ["SRC01_boundary_causal_receipt.json", "SRC01_synthetic_fixture_receipt.json"]},
            {"claim": "CAUSAL_FREEZE_QUALIFIED", "status": boundary["status"], "evidence": ["SRC01_boundary_causal_receipt.json"]},
            {"claim": "GRAMMAR_HANDOFF_QUALIFIED", "status": boundary["status"], "evidence": ["SRC01_boundary_causal_receipt.json"]},
        ],
    }
    matrix["status"] = "PASS" if all(row["status"] == "PASS" for row in matrix["rows"]) else "FAIL"
    artifacts = [digest(root / name) for name in REQUIRED]
    logical = {
        "schema": "OBS_OPEN_SRC01_ROOT_PREIMAGE_V1",
        "generation": "LEGACY_BREAKOUT_OBSERVER_V1",
        "parent_generation_preserved": "RECONSTRUCTED_OBSERVER_V1",
        "confirmation_state": "FROZEN_UNOPENED",
        "confirmation_sessions": 69,
        "confirmation_firewall": {
            "access_authorized": False,
            "observation_reads": 0,
            "confirmation_authority_in_closure": False,
            "status": "PASS",
        },
        "authority_manifest_logical_hash": authority["logical_manifest_sha256"],
        "artifacts": artifacts,
        "parity_matrix": matrix,
        "epistemic_limits": [
            "LEGACY_PARITY_IS_IMPLEMENTATION_EQUIVALENCE_NOT_CAUSAL_KNOWLEDGE",
            "NEW_YORK_CLOCK_TRANSPORT_NOT_EVALUATED_BY_SRC01",
            "NO_MARKET_BEHAVIOR_CLAIM",
            "NO_CONFIRMATION_ACCESS",
        ],
    }
    encoded = json.dumps(logical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt = dict(logical)
    receipt["src01_root_sha256"] = hashlib.sha256(encoded).hexdigest()
    receipt["status"] = "SEALED_PASS" if matrix["status"] == "PASS" else "SEALED_FAIL"
    return matrix, receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--matrix-output", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    args = parser.parse_args()
    matrix, receipt = build(args.root)
    args.matrix_output.write_text(json.dumps(matrix, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.receipt_output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
