"""Seal the complete fresh-panel input tree after construction, features, matching, and exact targets pass."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01")
SEAL = PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json"
MATCHING = PANEL / "matching"
TARGETS = PANEL / "target-joins"
PANEL_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01-independent-verification-v01.json")
TARGET_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01-independent-target-join-verification-v01.json")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def main() -> int:
    require(not SEAL.exists(), "refusing to replace the Q-R2 panel-input terminal seal")
    construction = read_json(PANEL / "seals/q-r2-panel-construction-seal-v01.json")
    features = read_json(PANEL / "seals/q-r2-feature-cache-seal-v01.json")
    matching_receipt = read_json(MATCHING / "r2-matching-and-join-receipt.json")
    radius = read_json(MATCHING / "radius-gate-report.json")
    candidate_join = read_json(MATCHING / "whole-panel-join-preflight.json")
    target_receipt = read_json(TARGETS / "q-exact-world-target-join-receipt.json")
    panel_verification = read_json(PANEL_VERIFY)
    target_verification = read_json(TARGET_VERIFY)

    require(construction.get("status") == "Q_R2_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING",
            "Q-R2 construction seal is not valid")
    require(features.get("status") == "Q_R2_FEATURE_CACHE_SEALED" and
            features.get("feature_receipt_sha256") == sha(PANEL / "features/r2-feature-extraction-receipt.json"),
            "Q-R2 feature cache seal is not valid")
    require(matching_receipt.get("status") == "Q_R2_MATCHING_AND_JOIN_PASS" and
            radius.get("status") == "PASS" and candidate_join.get("status") == "PASS",
            "Q-R2 radius or candidate join gate failed")
    require(target_receipt.get("status") == "Q_R2_EXACT_WORLD_TARGET_JOIN_PASS" and
            target_verification.get("status") == "Q_R2_INDEPENDENT_EXACT_WORLD_TARGET_JOIN_VERIFICATION_PASS",
            "Q-R2 exact-world target join did not independently pass")
    require(panel_verification.get("status") == "Q_R2_INDEPENDENT_PANEL_VERIFICATION_PASS",
            "Q-R2 panel construction did not independently pass")
    require(radius.get("results", {}).get("decisions", {}).get("all_pass") is True,
            "Q-R2 radius gate decisions are not all PASS")
    require(candidate_join.get("neighborhoods") == 2_000 and candidate_join.get("resolved_candidate_rows") == 8_000
            and candidate_join.get("missing_duplicate_extra") == 0,
            "Q-R2 exact candidate join cardinality mismatch")
    require(target_verification.get("target_rows") == 22_000 and target_verification.get("neighborhoods") == 2_000,
            "Q-R2 target verification cardinality mismatch")

    explicit = {row["path"]: row for row in construction["entries"]}
    for row in features["entries"]:
        explicit[row["path"]] = row
    for directory in (MATCHING, TARGETS):
        for path in sorted(item for item in directory.iterdir() if item.is_file()):
            rel = path.relative_to(PANEL).as_posix()
            explicit[rel] = {"path": rel, "bytes": path.stat().st_size, "sha256": sha(path)}
    entries = [explicit[key] for key in sorted(explicit)]
    observed = {path.relative_to(PANEL).as_posix() for path in PANEL.rglob("*")
                if path.is_file() and path != SEAL}
    require(observed == set(explicit), f"Q-R2 terminal panel tree mismatch: {sorted(observed ^ set(explicit))[:20]}")
    for row in entries:
        path = PANEL / row["path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
                f"Q-R2 terminal panel entry changed: {row['path']}")

    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    seal = {
        "schema": "jev-v08q-r2-panel-input-terminal-seal-v01",
        "status": "Q_R2_PANEL_INPUTS_SEALED_TRAINING_PENDING",
        "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
        "entries": entries,
        "entry_count": len(entries),
        "root_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "construction_seal_sha256": sha(PANEL / "seals/q-r2-panel-construction-seal-v01.json"),
        "feature_cache_seal_sha256": sha(PANEL / "seals/q-r2-feature-cache-seal-v01.json"),
        "matching_receipt_sha256": sha(MATCHING / "r2-matching-and-join-receipt.json"),
        "target_join_receipt_sha256": sha(TARGETS / "q-exact-world-target-join-receipt.json"),
        "panel_verification_status": panel_verification["status"],
        "radius_verification_status": radius["status"],
        "target_verification_status": target_verification["status"],
        "external_receipts": {str(PANEL_VERIFY): sha(PANEL_VERIFY), str(TARGET_VERIFY): sha(TARGET_VERIFY)},
        "panel_opened": False,
        "head_initialization": False,
        "training": False,
        "inference": False,
    }
    SEAL.parent.mkdir(parents=True, exist_ok=True)
    SEAL.write_text(json.dumps(seal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": seal["status"], "root_sha256": seal["root_sha256"],
                      "entry_count": len(entries), "panel_opened": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
