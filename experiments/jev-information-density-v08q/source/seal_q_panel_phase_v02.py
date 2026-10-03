"""Seal the complete authorized Q panel-only phase after all gates pass."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
PACKET = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-execution-packet.json")
PANEL_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-panel-verify.json")
RADIUS_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-radius-verify.json")
SEAL = RUN_ROOT / "seals/q-panel-phase-terminal-seal-v01.json"


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
        raise RuntimeError("refusing to replace an existing Q terminal seal")
    panel_seal = read_json(RUN_ROOT / "seals/q-panel-construction-seal-v01.json")
    feature_seal = read_json(RUN_ROOT / "seals/q-feature-cache-seal-v01.json")
    feature_receipt = read_json(RUN_ROOT / "features/q-feature-extraction-receipt.json")
    match_receipt = read_json(RUN_ROOT / "matching/q-matching-and-join-receipt.json")
    radius = read_json(RUN_ROOT / "matching/radius-gate-report.json")
    target_join = read_json(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json")
    panel_verification = read_json(PANEL_VERIFY)
    radius_verification = read_json(RADIUS_VERIFY)
    if panel_seal.get("status") != "Q_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING" or feature_seal.get("status") != "Q_FEATURE_CACHE_SEALED":
        raise RuntimeError("Q construction or feature-cache seal state mismatch")
    if feature_receipt.get("status") != "Q_FROZEN_PANEL_FEATURE_EXTRACTION_PASS" or match_receipt.get("status") != "Q_MATCHING_AND_JOIN_PASS" or radius.get("status") != "PASS" or target_join.get("status") != "Q_EXACT_WORLD_TARGET_JOIN_PASS":
        raise RuntimeError("Q panel-only prerequisite did not PASS")
    if panel_verification.get("status") != "Q_INDEPENDENT_PANEL_VERIFICATION_PASS" or radius_verification.get("status") != "Q_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS":
        raise RuntimeError("independent Q panel/radius verifier did not PASS")
    if panel_verification.get("panel_root_sha256") != panel_seal.get("root_sha256") or panel_verification.get("panel_manifest_sha256") != panel_seal.get("panel_manifest_sha256"):
        raise RuntimeError("independent panel verification refers to another construction root")
    if radius_verification.get("matching_receipt_sha256") != sha256_file(RUN_ROOT / "matching/q-matching-and-join-receipt.json"):
        raise RuntimeError("independent radius verification refers to another matching receipt")
    if target_join.get("target_rows") != 22_000 or target_join.get("join_summary", {}).get("fact_map_flip_count") != 2_000:
        raise RuntimeError("Q exact-world target join cardinality mismatch")

    allowed_dirs = {"exclusions", "panel", "panel-audit", "provenance", "seals", "features", "matching", "target-joins"}
    entries = []
    for path in RUN_ROOT.rglob("*"):
        if not path.is_file() or path == SEAL:
            continue
        rel = path.relative_to(RUN_ROOT).as_posix()
        if rel.split("/", 1)[0] not in allowed_dirs:
            raise RuntimeError(f"unexpected path in Q panel-only run root: {rel}")
        entries.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    entries.sort(key=lambda row: row["path"])
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    external = {
        str(PACKET): sha256_file(PACKET),
        str(PANEL_VERIFY): sha256_file(PANEL_VERIFY),
        str(RADIUS_VERIFY): sha256_file(RADIUS_VERIFY),
    }
    seal = {
        "schema": "jev-v08q-panel-phase-terminal-seal-v01",
        "status": "Q_FRESH_PANEL_FEATURE_CACHE_RADIUS_AND_TARGETS_SEALED_NO_TRAINING",
        "root_sha256": sha256_bytes(payload.encode("utf-8")),
        "entry_count": len(entries),
        "entries": entries,
        "external_receipts": external,
        "panel_construction_root_sha256": panel_seal["root_sha256"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "radius_gate_report_sha256": sha256_file(RUN_ROOT / "matching/radius-gate-report.json"),
        "target_join_receipt_sha256": sha256_file(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json"),
        "panel_verification_status": panel_verification["status"],
        "radius_verification_status": radius_verification["status"],
        "head_initialization": False,
        "checkpoint_loading": False,
        "training": False,
        "heldout_inference": False,
        "outcome_analysis": False,
        "schedule_materialized": False,
        "full_experiment_authorized": False,
    }
    SEAL.write_text(json.dumps(seal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": seal["status"], "root_sha256": seal["root_sha256"], "entry_count": len(entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
