"""Read-only independent verification of the sealed Q-R1 pretraining inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
SEAL_PATH = RUN_ROOT / "seals/q-r1-panel-input-terminal-seal-v01.json"


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
    if seal.get("status") != "Q_R1_PANEL_FEATURE_CACHE_RADIUS_AND_TARGETS_SEALED_TRAINING_PENDING":
        raise RuntimeError("Q-R1 input terminal seal status mismatch")
    if any(seal.get(key) for key in ("head_initialization", "checkpoint_loading", "training", "heldout_inference", "outcome_analysis", "training_executed", "heldout_inference_executed")):
        raise RuntimeError("Q-R1 input seal overstates downstream execution")
    if not seal.get("training_authorized_by_packet") or not seal.get("full_experiment_authorized_by_packet"):
        raise RuntimeError("Q-R1 packet authority was not carried into the input seal")
    entry_map = {entry["path"]: entry for entry in seal["entries"]}
    if len(entry_map) != len(seal["entries"]):
        raise RuntimeError("duplicate path in Q terminal seal")
    observed = {path.relative_to(RUN_ROOT).as_posix() for path in RUN_ROOT.rglob("*") if path.is_file() and path != SEAL_PATH}
    if observed != set(entry_map):
        raise RuntimeError(f"Q-R1 input tree has missing or extra files: {observed ^ set(entry_map)}")
    for rel, entry in entry_map.items():
        path = RUN_ROOT / Path(rel)
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"Q-R1 input entry verification failed: {rel}")
    payload = "".join(f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n" for entry in sorted(seal["entries"], key=lambda row: row["path"]))
    if sha256_bytes(payload.encode("utf-8")) != seal.get("root_sha256"):
        raise RuntimeError("Q-R1 input root hash mismatch")
    for raw_path, expected in seal["external_receipts"].items():
        if sha256_file(Path(raw_path)) != expected:
            raise RuntimeError(f"Q-R1 external authorization/verification receipt hash mismatch: {raw_path}")
    for raw_path, expected in seal["implementation_sources_sha256"].items():
        source_path = Path(raw_path)
        if not source_path.is_file() or sha256_file(source_path) != expected:
            raise RuntimeError(f"Q-R1 implementation source hash mismatch: {raw_path}")
    generator_binary = Path(r"D:\cargo-targets\jev-information-density-v08q-r1\release\jev-information-density-v08q-panel-generator.exe")
    if not generator_binary.is_file() or sha256_file(generator_binary) != seal.get("generator_binary_sha256"):
        raise RuntimeError("Q-R1 generator binary hash mismatch")
    panel_seal = read_json(RUN_ROOT / "seals/q-r1-panel-construction-seal-v01.json")
    feature_seal = read_json(RUN_ROOT / "seals/q-r1-feature-cache-seal-v01.json")
    radius = read_json(RUN_ROOT / "matching/radius-gate-report.json")
    target_join = read_json(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json")
    panel_verify = read_json(Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-verification-v02.json"))
    radius_verify = read_json(Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-radius-verification-v01.json"))
    target_verify = read_json(Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-target-join-verification-v01.json"))
    if panel_seal.get("root_sha256") != seal.get("panel_construction_root_sha256") or feature_seal.get("root_sha256") != seal.get("feature_cache_root_sha256"):
        raise RuntimeError("Q-R1 input seal panel/feature subroot mismatch")
    if radius.get("status") != "PASS" or target_join.get("status") != "Q_R1_EXACT_WORLD_TARGET_JOIN_PASS":
        raise RuntimeError("Q-R1 terminal radius or target-join status mismatch")
    if panel_verify.get("status") != seal.get("panel_verification_status") or radius_verify.get("status") != seal.get("radius_verification_status"):
        raise RuntimeError("Q-R1 independent verifier status mismatch")
    if panel_verify.get("status") != "Q_R1_INDEPENDENT_PANEL_VERIFICATION_PASS" or radius_verify.get("status") != "Q_R1_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS":
        raise RuntimeError("Q-R1 independent panel/radius checks are not PASS")
    if target_verify.get("status") != "Q_R1_INDEPENDENT_EXACT_WORLD_TARGET_JOIN_VERIFICATION_PASS" or target_verify.get("status") != seal.get("target_verification_status"):
        raise RuntimeError("Q-R1 independent exact-world target check is not PASS")
    if target_verify.get("target_join_receipt_sha256") != sha256_file(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json"):
        raise RuntimeError("Q-R1 target verifier refers to another target-join receipt")
    if target_verify.get("target_rows") != 22_000 or target_verify.get("neighborhoods") != 2_000 or target_verify.get("fact_map_flip_count") != 2_000:
        raise RuntimeError("Q-R1 exact-world target verifier cardinality mismatch")
    if target_verify.get("head_loaded") or target_verify.get("training") or target_verify.get("inference"):
        raise RuntimeError("Q-R1 target verifier overstates model contact")
    result = {
        "status": "Q_R1_PANEL_INPUT_TERMINAL_SEAL_VERIFIED_TRAINING_PENDING",
        "root_sha256": seal["root_sha256"],
        "entry_count": len(entry_map),
        "panel_construction_root_sha256": panel_seal["root_sha256"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "radius_gate": "PASS",
        "target_join": "PASS",
        "target_verifier": "PASS",
        "implementation_sources": len(seal["implementation_sources_sha256"]),
        "generator_binary": "PASS",
        "head_initialization": False,
        "training": False,
        "heldout_inference": False,
        "training_authorized": True,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
