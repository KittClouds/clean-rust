"""Seal Q-R1's immutable panel/feature/matching/target input package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
REPO_ROOT = Path(r"C:\code land\clean-rust")
PACKET_SEAL = REPO_ROOT / "experiments/jev-information-density-v08q-r1/seals/q-r1-packet-seal-and-authorization-v01.json"
PANEL_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-verification-v02.json")
RADIUS_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-radius-verification-v01.json")
TARGET_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-target-join-verification-v01.json")
SEAL = RUN_ROOT / "seals/q-r1-panel-input-terminal-seal-v01.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if SEAL.exists():
        raise RuntimeError("refusing to replace an existing Q-R1 panel-input terminal seal")
    packet_seal = read_json(PACKET_SEAL)
    panel_seal = read_json(RUN_ROOT / "seals/q-r1-panel-construction-seal-v01.json")
    feature_seal = read_json(RUN_ROOT / "seals/q-r1-feature-cache-seal-v01.json")
    feature_receipt = read_json(RUN_ROOT / "features/r1-feature-extraction-receipt.json")
    match_receipt = read_json(RUN_ROOT / "matching/r1-matching-and-join-receipt.json")
    radius = read_json(RUN_ROOT / "matching/radius-gate-report.json")
    target_join = read_json(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json")
    panel_verification = read_json(PANEL_VERIFY)
    radius_verification = read_json(RADIUS_VERIFY)
    target_verification = read_json(TARGET_VERIFY)
    if packet_seal.get("status") != "SEALED_AUTHORIZED_PENDING_EXECUTION":
        raise RuntimeError("Q-R1 packet is not authorized")
    if panel_seal.get("status") != "Q_R1_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING" or feature_seal.get("status") != "Q_R1_FEATURE_CACHE_SEALED":
        raise RuntimeError("Q-R1 construction or feature-cache seal state mismatch")
    if feature_receipt.get("status") != "Q_R1_FROZEN_PANEL_FEATURE_EXTRACTION_PASS" or match_receipt.get("status") != "Q_R1_MATCHING_AND_JOIN_PASS" or radius.get("status") != "PASS" or target_join.get("status") != "Q_R1_EXACT_WORLD_TARGET_JOIN_PASS":
        raise RuntimeError("Q-R1 panel-input prerequisite did not PASS")
    if panel_verification.get("status") != "Q_R1_INDEPENDENT_PANEL_VERIFICATION_PASS" or radius_verification.get("status") != "Q_R1_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS":
        raise RuntimeError("independent Q-R1 panel/radius verifier did not PASS")
    if target_verification.get("status") != "Q_R1_INDEPENDENT_EXACT_WORLD_TARGET_JOIN_VERIFICATION_PASS":
        raise RuntimeError("independent Q-R1 exact-world target verifier did not PASS")
    if panel_verification.get("panel_root_sha256") != panel_seal.get("root_sha256") or panel_verification.get("panel_manifest_sha256") != panel_seal.get("panel_manifest_sha256"):
        raise RuntimeError("independent panel verification refers to another construction root")
    if radius_verification.get("matching_receipt_sha256") != sha256_file(RUN_ROOT / "matching/r1-matching-and-join-receipt.json"):
        raise RuntimeError("independent radius verification refers to another matching receipt")
    if target_join.get("target_rows") != 22_000 or target_join.get("join_summary", {}).get("fact_map_flip_count") != 2_000:
        raise RuntimeError("Q-R1 exact-world target join cardinality mismatch")
    if target_verification.get("target_join_receipt_sha256") != sha256_file(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json"):
        raise RuntimeError("independent target verification refers to another target-join receipt")

    allowed_dirs = {"exclusions", "panel", "panel-audit", "provenance", "seals", "features", "matching", "target-joins"}
    entries = []
    for path in RUN_ROOT.rglob("*"):
        if not path.is_file() or path == SEAL:
            continue
        rel = path.relative_to(RUN_ROOT).as_posix()
        if rel.split("/", 1)[0] not in allowed_dirs:
            raise RuntimeError(f"unexpected path in Q-R1 panel-input root: {rel}")
        entries.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    entries.sort(key=lambda row: row["path"])
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    external = {
        str(PACKET_SEAL): sha256_file(PACKET_SEAL),
        str(PANEL_VERIFY): sha256_file(PANEL_VERIFY),
        str(RADIUS_VERIFY): sha256_file(RADIUS_VERIFY),
        str(TARGET_VERIFY): sha256_file(TARGET_VERIFY),
    }
    source_paths = [
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/generator/src/main.rs",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/generator/Cargo.toml",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/generator/Cargo.lock",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/seal_q_r1_panel_construction_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/verify_q_r1_panel_construction_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/extract_q_r1_panel_features_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/seal_q_r1_feature_cache_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/match_q_r1_panel_radius_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/verify_q_r1_radius_matching_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/join_q_r1_exact_world_targets_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/verify_q_r1_exact_world_targets_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/seal_q_r1_panel_phase_v01.py",
        REPO_ROOT / "experiments/jev-information-density-v08q-r1/source/verify_q_r1_panel_phase_v01.py",
        REPO_ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py",
        REPO_ROOT / "experiments/jev-information-density-v08p-r2/runner/r2_panel_target_join.py",
    ]
    implementation_sources = {str(path): sha256_file(path) for path in source_paths}
    generator_binary = Path(r"D:\cargo-targets\jev-information-density-v08q-r1\release\jev-information-density-v08q-panel-generator.exe")
    seal = {
        "schema": "jev-v08q-r1-panel-input-terminal-seal-v01",
        "status": "Q_R1_PANEL_FEATURE_CACHE_RADIUS_AND_TARGETS_SEALED_TRAINING_PENDING",
        "root_sha256": sha256_bytes(payload.encode("utf-8")),
        "entry_count": len(entries),
        "entries": entries,
        "external_receipts": external,
        "implementation_sources_sha256": implementation_sources,
        "generator_binary_sha256": sha256_file(generator_binary),
        "feature_extractor_adapter_sha256": implementation_sources[str(REPO_ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py")],
        "panel_construction_root_sha256": panel_seal["root_sha256"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "radius_gate_report_sha256": sha256_file(RUN_ROOT / "matching/radius-gate-report.json"),
        "target_join_receipt_sha256": sha256_file(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json"),
        "panel_verification_status": panel_verification["status"],
        "radius_verification_status": radius_verification["status"],
        "target_verification_status": target_verification["status"],
        "head_initialization": False,
        "checkpoint_loading": False,
        "training": False,
        "heldout_inference": False,
        "outcome_analysis": False,
        "schedule_materialized": False,
        "training_authorized_by_packet": True,
        "full_experiment_authorized_by_packet": True,
        "training_executed": False,
        "heldout_inference_executed": False,
    }
    SEAL.write_text(json.dumps(seal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": seal["status"], "root_sha256": seal["root_sha256"], "entry_count": len(entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
