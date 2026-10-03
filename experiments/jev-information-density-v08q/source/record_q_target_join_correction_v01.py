"""Preserve the failed Q target-join runner and seal its narrow correction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
PROJECT = ROOT / "experiments/jev-information-density-v08q"
PACKET = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-execution-packet.json")
FAILED_RUNNER = PROJECT / "source/join_q_exact_world_targets_v02.py"
CORRECTED_RUNNER = PROJECT / "source/join_q_exact_world_targets_v03.py"
LOCKED_HELPER = ROOT / "experiments/jev-information-density-v08p-r2/runner/r2_panel_target_join.py"
FAILURE_RECEIPT = RUN_ROOT / "provenance/q-target-join-v02-failure-receipt.json"
CORRECTION_RECORD = RUN_ROOT / "provenance/q-target-join-correction-v01.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    if FAILURE_RECEIPT.exists() or CORRECTION_RECORD.exists():
        raise RuntimeError("refusing to replace existing Q target-join correction records")
    if (RUN_ROOT / "target-joins").exists() or (RUN_ROOT / "seals/q-panel-phase-terminal-seal-v01.json").exists():
        raise RuntimeError("Q target-join output or terminal seal already exists")
    packet = read_json(PACKET)
    panel_seal = read_json(RUN_ROOT / "seals/q-panel-construction-seal-v01.json")
    feature_seal = read_json(RUN_ROOT / "seals/q-feature-cache-seal-v01.json")
    radius_report = read_json(RUN_ROOT / "matching/radius-gate-report.json")
    match_receipt = read_json(RUN_ROOT / "matching/q-matching-and-join-receipt.json")
    radius_verify = read_json(Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-radius-verify.json"))
    failed_identity = packet["runner_sources"]["source/join_q_exact_world_targets_v02.py"]["sha256"]
    if sha256_file(FAILED_RUNNER) != failed_identity:
        raise RuntimeError("failed Q v02 target-join runner no longer matches its sealed execution packet")
    if sha256_file(LOCKED_HELPER) != "e7673ba4bdf0bbac924ffe863dfb7cd2f1aa60ac2dfe8d7e0919fda1e9b350eb":
        raise RuntimeError("hash-locked target-join helper changed")
    if panel_seal.get("status") != "Q_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING" or feature_seal.get("status") != "Q_FEATURE_CACHE_SEALED":
        raise RuntimeError("Q panel/feature parent seal is not PASS")
    if radius_report.get("status") != "PASS" or match_receipt.get("status") != "Q_MATCHING_AND_JOIN_PASS" or radius_verify.get("status") != "Q_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS":
        raise RuntimeError("Q target-join correction is not downstream of a passed radius gate")

    failure = {
        "schema": "jev-v08q-target-join-failure-receipt-v01",
        "status": "Q_TARGET_JOIN_V02_ABORTED_IMPLEMENTATION_SCHEMA_KEY_MISMATCH",
        "failed_runner_sha256": failed_identity,
        "locked_helper_sha256": sha256_file(LOCKED_HELPER),
        "exception": "ValueError: episode/schema family mismatch at helper validation",
        "cause": "v02 supplied schema_orders keyed by full schema_family_id; the hash-locked helper indexes schema_orders by family_slug",
        "panel_construction_root_sha256": panel_seal["root_sha256"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "matching_receipt_sha256": sha256_file(RUN_ROOT / "matching/q-matching-and-join-receipt.json"),
        "independent_radius_receipt_sha256": sha256_file(Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-radius-verify.json")),
        "target_join_output_directory_created": False,
        "target_rows_written": False,
        "training": False,
        "inference": False,
        "outcome_analysis": False,
        "truth_access": {
            "exact_and_canonical_input_rows_deserialized": True,
            "target_join_helper_rejected_schema_before_reading_gold_targets_field": True,
            "target_vectors_emitted": False,
        },
        "correction_scope": "runner argument-map key only; no panel, labels, feature rows, contract, matching, or model changes",
    }
    write_new(FAILURE_RECEIPT, failure)
    correction = {
        "schema": "jev-v08q-target-join-runner-correction-v01",
        "status": "Q_TARGET_JOIN_RUNNER_CORRECTION_V01_SEALED",
        "failed_attempt_receipt_sha256": sha256_file(FAILURE_RECEIPT),
        "failed_runner_path": str(FAILED_RUNNER),
        "failed_runner_sha256": failed_identity,
        "corrected_runner_path": str(CORRECTED_RUNNER),
        "corrected_runner_sha256": sha256_file(CORRECTED_RUNNER),
        "correction_record_writer_sha256": sha256_file(Path(__file__).resolve()),
        "locked_helper_path": str(LOCKED_HELPER),
        "locked_helper_sha256": sha256_file(LOCKED_HELPER),
        "correction": "pass schema_orders keyed by family_slug, while deriving the family slug from each candidate schema ID; keep candidate order frozen",
        "parent_execution_packet_sha256": sha256_file(PACKET),
        "panel_construction_root_sha256": panel_seal["root_sha256"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "matching_receipt_sha256": sha256_file(RUN_ROOT / "matching/q-matching-and-join-receipt.json"),
        "radius_report_sha256": sha256_file(RUN_ROOT / "matching/radius-gate-report.json"),
        "independent_radius_receipt_sha256": sha256_file(Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-radius-verify.json")),
        "contract_changed": False,
        "panel_replaced": False,
        "feature_extraction_repeated": False,
        "model_reloaded": False,
        "head_initialization": False,
        "training": False,
        "inference": False,
        "outcome_analysis": False,
    }
    write_new(CORRECTION_RECORD, correction)
    print(json.dumps({
        "status": correction["status"],
        "failed_runner_sha256": failed_identity,
        "corrected_runner_sha256": correction["corrected_runner_sha256"],
        "failure_receipt_sha256": sha256_file(FAILURE_RECEIPT),
        "correction_record_sha256": sha256_file(CORRECTION_RECORD),
        "panel_feature_radius_inputs_unchanged": True,
        "model_contact": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
