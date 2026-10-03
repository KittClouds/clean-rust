"""Run the single authorized Q panel/cache phase and stop before training."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "experiments/jev-information-density-v08q"
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
TARGET_DIR = Path(r"D:\cargo-targets\jev-information-density-v08q-panel")
PACKET = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-execution-packet.json")
LOCK_RECEIPT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-source-lock-preflight.json")
PANEL_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-panel-verify.json")
RADIUS_VERIFY = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-radius-verify.json")
MANIFEST = PROJECT / "panel-generator/Cargo.toml"
MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify_frozen_packet() -> dict[str, Any]:
    packet = read_json(PACKET)
    require(packet.get("schema") == "jev-v08q-panel-only-execution-packet-v01", "Q execution packet schema mismatch")
    require(packet.get("authorization", {}).get("phase") == "Q_FRESH_PANEL_CONSTRUCTION_AND_FEATURE_EXTRACTION_ONLY", "Q panel-only authorization mismatch")
    require(packet.get("sealed_bundle_root_sha256") == "118462335b94a41738e12c3af9b6b1647dc7fcc95cf88c9ae3cdc2ed0cbd43ae", "Q sealed bundle identity mismatch")
    require(packet.get("contract_sha256") == sha256_file(PROJECT / "contracts/q-panel-contract-v02.json"), "Q panel contract changed after packet seal")
    require(packet.get("source_lock", {}).get("preflight_receipt_sha256") == sha256_file(LOCK_RECEIPT), "Q source-lock preflight receipt changed")
    lock_receipt = read_json(LOCK_RECEIPT)
    require(lock_receipt.get("status") == "Q_SOURCE_LOCK_PREFLIGHT_PASS" and lock_receipt.get("source_lock_root_sha256") == packet["source_lock"]["root_sha256"], "Q source-lock preflight not PASS")
    for rel, identity in packet["runner_sources"].items():
        path = PROJECT / rel
        require(path.stat().st_size == identity["bytes"] and sha256_file(path) == identity["sha256"], f"Q runner source changed: {rel}")
    adapter = PROJECT.parent / "jev-lfm-variable-v07/extract_lfm.py"
    require(sha256_file(adapter) == packet["locked_lfm_adapter_sha256"], "locked LFM adapter changed")
    join_helper = PROJECT.parent / "jev-information-density-v08p-r2/runner/r2_panel_target_join.py"
    require(sha256_file(join_helper) == packet["locked_target_join_helper_sha256"], "locked target-join helper changed")
    require(not RUN_ROOT.exists(), "Q run root already exists; one-use run will not be resumed")
    require(not PANEL_VERIFY.exists() and not RADIUS_VERIFY.exists(), "Q independent verification receipt path already exists")
    return packet


def run_stage(label: str, command: list[str]) -> None:
    print(json.dumps({"stage": label, "status": "START", "command": command}), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    print(json.dumps({"stage": label, "status": "EXIT_ZERO"}), flush=True)


def run_generator(mode: str, output: Path) -> None:
    command = [
        "cargo", "run", "--release", "--locked",
        "--manifest-path", str(MANIFEST),
        "--target-dir", str(TARGET_DIR),
        "--", mode, str(output),
    ]
    run_stage(f"rust_{mode}", command)


def main() -> int:
    verify_frozen_packet()
    require(not RUN_ROOT.exists(), "Q run root appeared after packet preflight")

    run_generator("materialize-exclusions", RUN_ROOT / "exclusions")
    run_generator("admit-panel", RUN_ROOT / "panel")
    admission = read_json(RUN_ROOT / "panel/online-admission-receipt.json")
    require(admission.get("status") == "Q_ONLINE_PANEL_ADMISSION_PASS" and admission.get("accepted_total") == 2_000, "Q fixed candidate admission failed; preserve and stop")

    run_generator("final-audit", RUN_ROOT / "panel-audit")
    run_stage("seal_panel_construction", [sys.executable, str(PROJECT / "source/seal_q_panel_construction_v02.py")])
    run_stage("independent_panel_verification", [sys.executable, str(PROJECT / "source/verify_q_panel_construction_v02.py"), "--receipt", str(PANEL_VERIFY)])
    panel_result = read_json(PANEL_VERIFY)
    require(panel_result.get("status") == "Q_INDEPENDENT_PANEL_VERIFICATION_PASS", "Q independent panel verification failed; preserve and stop")

    run_stage("frozen_lfm_feature_extraction", [sys.executable, str(PROJECT / "source/extract_q_panel_features_v02.py"), "--model-root", str(MODEL_ROOT)])
    run_stage("independent_feature_validation_and_seal", [sys.executable, str(PROJECT / "source/seal_q_feature_cache_v02.py")])
    feature_seal = read_json(RUN_ROOT / "seals/q-feature-cache-seal-v01.json")
    require(feature_seal.get("status") == "Q_FEATURE_CACHE_SEALED", "Q feature cache validation failed; preserve and stop")

    run_stage("frozen_radius_match_and_target_free_join", [sys.executable, str(PROJECT / "source/match_q_panel_radius_v02.py")])
    radius = read_json(RUN_ROOT / "matching/radius-gate-report.json")
    match_receipt = read_json(RUN_ROOT / "matching/q-matching-and-join-receipt.json")
    require(radius.get("status") == "PASS" and match_receipt.get("status") == "Q_MATCHING_AND_JOIN_PASS", "Q radius or candidate join gate failed; preserve and stop")
    run_stage("independent_radius_and_candidate_join_verification", [sys.executable, str(PROJECT / "source/verify_q_radius_matching_v02.py"), "--receipt", str(RADIUS_VERIFY)])
    radius_result = read_json(RADIUS_VERIFY)
    require(radius_result.get("status") == "Q_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS", "Q independent radius verification failed; preserve and stop")

    run_stage("exact_world_target_join", [sys.executable, str(PROJECT / "source/join_q_exact_world_targets_v02.py")])
    target_receipt = read_json(RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json")
    require(target_receipt.get("status") == "Q_EXACT_WORLD_TARGET_JOIN_PASS", "Q exact-world target join failed; preserve and stop")
    run_stage("seal_panel_only_phase", [sys.executable, str(PROJECT / "source/seal_q_panel_phase_v02.py")])
    run_stage("independent_terminal_seal_verification", [sys.executable, str(PROJECT / "source/verify_q_panel_phase_v02.py")])

    terminal = read_json(RUN_ROOT / "seals/q-panel-phase-terminal-seal-v01.json")
    print(json.dumps({
        "status": terminal["status"],
        "root_sha256": terminal["root_sha256"],
        "panel_construction_root_sha256": terminal["panel_construction_root_sha256"],
        "feature_cache_root_sha256": terminal["feature_cache_root_sha256"],
        "radius_gate": "PASS",
        "independent_panel_verification": "PASS",
        "independent_radius_verification": "PASS",
        "exact_target_join": "PASS",
        "head_initialization": False,
        "training": False,
        "heldout_inference": False,
        "outcome_analysis": False,
        "full_experiment_authorized": False,
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
