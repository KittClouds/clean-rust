"""Read-only independent verification of the Q panel-only terminal seal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
SEAL_PATH = RUN_ROOT / "seals/q-panel-phase-terminal-seal-v01.json"


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
    seal = read_json(SEAL_PATH)
    if seal.get("status") != "Q_FRESH_PANEL_FEATURE_CACHE_RADIUS_AND_TARGETS_SEALED_NO_TRAINING":
        raise RuntimeError("Q terminal seal status mismatch")
    if any(seal.get(key) for key in ("head_initialization", "checkpoint_loading", "training", "heldout_inference", "outcome_analysis", "schedule_materialized", "full_experiment_authorized")):
        raise RuntimeError("Q terminal seal overstates downstream authorization or execution")
    entry_map = {entry["path"]: entry for entry in seal["entries"]}
    if len(entry_map) != len(seal["entries"]):
        raise RuntimeError("duplicate path in Q terminal seal")
    observed = {path.relative_to(RUN_ROOT).as_posix() for path in RUN_ROOT.rglob("*") if path.is_file() and path != SEAL_PATH}
    if observed != set(entry_map):
        raise RuntimeError(f"Q terminal tree has missing or extra files: {observed ^ set(entry_map)}")
    for rel, entry in entry_map.items():
        path = RUN_ROOT / Path(rel)
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"Q terminal entry verification failed: {rel}")
    payload = "".join(f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n" for entry in sorted(seal["entries"], key=lambda row: row["path"]))
    if sha256_bytes(payload.encode("utf-8")) != seal.get("root_sha256"):
        raise RuntimeError("Q terminal root hash mismatch")
    for raw_path, expected in seal["external_receipts"].items():
        if sha256_file(Path(raw_path)) != expected:
            raise RuntimeError(f"Q external authorization/verification receipt hash mismatch: {raw_path}")
    panel_seal = read_json(RUN_ROOT / "seals/q-panel-construction-seal-v01.json")
    feature_seal = read_json(RUN_ROOT / "seals/q-feature-cache-seal-v01.json")
    radius = read_json(RUN_ROOT / "matching/radius-gate-report.json")
    target_join = read_json(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json")
    panel_verify = read_json(Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-panel-verify.json"))
    radius_verify = read_json(Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-radius-verify.json"))
    if panel_seal.get("root_sha256") != seal.get("panel_construction_root_sha256") or feature_seal.get("root_sha256") != seal.get("feature_cache_root_sha256"):
        raise RuntimeError("Q terminal seal panel/feature subroot mismatch")
    if radius.get("status") != "PASS" or target_join.get("status") != "Q_EXACT_WORLD_TARGET_JOIN_PASS":
        raise RuntimeError("Q terminal radius or target-join status mismatch")
    if panel_verify.get("status") != seal.get("panel_verification_status") or radius_verify.get("status") != seal.get("radius_verification_status"):
        raise RuntimeError("Q independent verifier status mismatch")
    if panel_verify.get("status") != "Q_INDEPENDENT_PANEL_VERIFICATION_PASS" or radius_verify.get("status") != "Q_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS":
        raise RuntimeError("Q independent panel/radius checks are not PASS")
    result = {
        "status": "Q_PANEL_PHASE_TERMINAL_SEAL_VERIFIED",
        "root_sha256": seal["root_sha256"],
        "entry_count": len(entry_map),
        "panel_construction_root_sha256": panel_seal["root_sha256"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "radius_gate": "PASS",
        "target_join": "PASS",
        "head_initialization": False,
        "training": False,
        "heldout_inference": False,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
