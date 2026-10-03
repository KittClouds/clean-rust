"""Verify frozen Q inputs and record the explicit panel-only authorization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "experiments/jev-information-density-v08q"
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
PACKET = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-execution-packet.json")
LOCK_RECEIPT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-source-lock-preflight.json")
BUNDLE_SEAL = PROJECT / "seals/q-bundle-seal-v02.json"
SOURCE_LOCK = PROJECT / "contracts/q-source-lock-v02.json"
PANEL_CONTRACT = PROJECT / "contracts/q-panel-contract-v02.json"

RUNNER_FILES = [
    "panel-generator/Cargo.toml",
    "panel-generator/Cargo.lock",
    "panel-generator/src/main.rs",
    "source/build_q_execution_packet_v02.py",
    "source/extract_q_panel_features_v02.py",
    "source/match_q_panel_radius_v02.py",
    "source/seal_q_panel_construction_v02.py",
    "source/verify_q_panel_construction_v02.py",
    "source/join_q_exact_world_targets_v02.py",
    "source/seal_q_feature_cache_v02.py",
    "source/verify_q_radius_matching_v02.py",
    "source/seal_q_panel_phase_v02.py",
    "source/verify_q_panel_phase_v02.py",
    "source/run_q_panel_phase_v02.py",
]


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


def entries_root(entries: list[dict[str, Any]]) -> str:
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda row: row["path"]))
    return sha256_bytes(payload.encode("utf-8"))


def source_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    sidecars = [PACKET, LOCK_RECEIPT, Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-panel-verify.json"), Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02-independent-radius-verify.json")]
    if RUN_ROOT.exists() or any(path.exists() for path in sidecars):
        raise RuntimeError("Q panel run or one-use sidecar path already exists; refusing reuse")

    bundle = read_json(BUNDLE_SEAL)
    if bundle.get("root_sha256") != "118462335b94a41738e12c3af9b6b1647dc7fcc95cf88c9ae3cdc2ed0cbd43ae" or entries_root(bundle["entries"]) != bundle["root_sha256"]:
        raise RuntimeError("sealed Q bundle root mismatch")
    for entry in bundle["entries"]:
        path = PROJECT / entry["path"]
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"sealed Q bundle entry changed: {entry['path']}")

    panel_contract = read_json(PANEL_CONTRACT)
    source_lock = read_json(SOURCE_LOCK)
    if sha256_file(SOURCE_LOCK) != panel_contract["source_lock"]["file_sha256"]:
        raise RuntimeError("Q source-lock file identity mismatch")
    if entries_root(source_lock["entries"]) != panel_contract["source_lock"]["root_sha256"]:
        raise RuntimeError("Q source-lock metadata root mismatch")
    source_results = []
    total_bytes = 0
    for entry in source_lock["entries"]:
        path = source_path(entry["path"])
        if not path.is_file():
            raise RuntimeError(f"Q locked source is missing: {entry['path']}")
        actual_bytes = path.stat().st_size
        actual_sha = sha256_file(path)
        if actual_bytes != entry["bytes"] or actual_sha != entry["sha256"]:
            raise RuntimeError(f"Q locked source identity mismatch: {entry['path']}")
        source_results.append({"path": entry["path"], "bytes": actual_bytes, "sha256": actual_sha})
        total_bytes += actual_bytes
    lock_receipt = {
        "status": "Q_SOURCE_LOCK_PREFLIGHT_PASS",
        "source_lock_file_sha256": sha256_file(SOURCE_LOCK),
        "source_lock_root_sha256": panel_contract["source_lock"]["root_sha256"],
        "entry_count": len(source_results),
        "total_bytes": total_bytes,
        "entries": source_results,
        "application_level_read_only_hashing": True,
        "model_loaded": False,
        "feature_extraction": False,
        "training": False,
        "inference": False,
    }
    LOCK_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_RECEIPT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(lock_receipt, indent=2, ensure_ascii=False) + "\n")

    runner_sources = {}
    for rel in RUNNER_FILES:
        path = PROJECT / rel
        runner_sources[rel] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    if sha256_file(PROJECT / "../jev-lfm-variable-v07/extract_lfm.py") != "b8cd79a9a3265eca0fde5f509ba7c058bc2065d7747efe17ff7c7c1f6335b2d0":
        raise RuntimeError("locked LFM extraction adapter changed")

    authorization_text = (
        "Authorize Q fresh-panel construction, feature extraction, identity/radius validation, and sealing under the frozen v0.8Q contract. "
        "Do not initialize heads, train, load checkpoints, perform held-out inference, or analyze outcomes. "
        "Stop at the sealed panel/cache result and do not replace a failed panel."
    )
    packet = {
        "schema": "jev-v08q-panel-only-execution-packet-v01",
        "identity": "JEV-V08Q-FRESH-PANEL-AND-FEATURE-EXTRACTION",
        "authorization": {
            "phase": "Q_FRESH_PANEL_CONSTRUCTION_AND_FEATURE_EXTRACTION_ONLY",
            "source": "explicit user authorization in the current task thread",
            "statement": authorization_text,
            "statement_sha256": sha256_bytes(authorization_text.encode("utf-8")),
        },
        "sealed_bundle_root_sha256": bundle["root_sha256"],
        "contract_sha256": sha256_file(PANEL_CONTRACT),
        "source_lock": {
            "path": str(SOURCE_LOCK),
            "file_sha256": sha256_file(SOURCE_LOCK),
            "root_sha256": panel_contract["source_lock"]["root_sha256"],
            "preflight_receipt_path": str(LOCK_RECEIPT),
            "preflight_receipt_sha256": sha256_file(LOCK_RECEIPT),
            "entry_count": len(source_results),
            "total_bytes": total_bytes,
        },
        "run_root": str(RUN_ROOT),
        "runner_sources": runner_sources,
        "locked_lfm_adapter_sha256": sha256_file(PROJECT / "../jev-lfm-variable-v07/extract_lfm.py"),
        "locked_target_join_helper_sha256": "e7673ba4bdf0bbac924ffe863dfb7cd2f1aa60ac2dfe8d7e0919fda1e9b350eb",
        "fixed_inputs": {
            "namespace": panel_contract["namespace"],
            "seed": panel_contract["generator_seed"],
            "families": panel_contract["families"],
            "admission_per_family": panel_contract["admission"]["neighborhoods_per_family"],
            "candidate_ordinals": panel_contract["admission"]["candidate_ordinals_per_family"],
            "feature": panel_contract["feature_extraction"]["feature"],
            "feature_views": ["mean_full@16"],
            "radius_gates": panel_contract["matching"]["radius_gates"],
        },
        "construction_runner_qualification": {
            "python_compile": "PASS",
            "frozen_q_unit_tests": {"status": "PASS", "passed": 6, "failed": 0},
            "radius_matcher_deterministic_self_test": "PASS",
            "rust_release_tests": {"status": "PASS", "passed": 6, "failed": 0},
            "rust_clippy_d_warnings": "PASS",
        },
        "phase_sequence": [
            "verify sealed Q bundle and all source-lock entries",
            "materialize five-field exclusions",
            "admit the fixed Q stream online and emit accepted panel",
            "run generator-side final overlap audit",
            "seal construction manifest and tree",
            "run independent panel/hash/identity verifier",
            "only after panel pass, extract the one frozen Q feature view",
            "independently validate and seal feature cache",
            "run frozen radius-only matching and target-free candidate join",
            "independently replay radius gates and candidate join",
            "join exact-world targets after radius pass",
            "seal and independently verify the complete panel-only phase",
            "stop before schedule, head initialization, training, inference, and outcome analysis",
        ],
        "failure_policy": "preserve any failed one-use output and stop; no reseed, replacement, budget expansion, or rerun",
        "downstream_authority": {
            "head_initialization": False,
            "checkpoint_loading": False,
            "training": False,
            "heldout_inference": False,
            "outcome_analysis": False,
            "full_experiment": False,
        },
        "packet_builder_sha256": sha256_file(Path(__file__).resolve()),
    }
    with PACKET.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(packet, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "status": "Q_PANEL_ONLY_EXECUTION_PACKET_SEALED",
        "bundle_root_sha256": bundle["root_sha256"],
        "source_lock_root_sha256": panel_contract["source_lock"]["root_sha256"],
        "source_lock_entries_verified": len(source_results),
        "source_lock_bytes_verified": total_bytes,
        "packet_sha256": sha256_file(PACKET),
        "panel_or_feature_output_created": False,
        "model_loaded": False,
        "training": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
