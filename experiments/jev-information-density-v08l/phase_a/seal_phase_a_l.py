"""Seal v0.8L Phase A as non-promotable when frozen matching fails."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08l/phase_a/phase-a-v01-contract.json"
OUT = Path(r"D:\codex-runs\jev-information-density-v08l\phase-a-v01-clean")


def h(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    contract = read(CONTRACT)
    a0 = read(OUT / "candidate-pool-summary.json")
    a0_receipt = read(OUT / "candidate-pool-receipt.json")
    a1 = read(OUT / "feature-cache/extraction-receipt.json")
    a2 = read(OUT / "matching-summary.json")
    a2_receipt = read(OUT / "matching-receipt.json")
    contract_hash = h(CONTRACT)
    require(a0["status"] == "PHASE_A0_CANDIDATE_POOL_READY_NO_MODEL_CONTACT", "A0 status drift")
    require(a0_receipt["status"] == "PASS" and a0_receipt["contract_sha256"] == contract_hash, "A0 receipt drift")
    require(a1["status"] == "PHASE_A1_FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY", "A1 status drift")
    require(a1["contract_sha256"] == contract_hash and a1["model_head_training"] is False, "A1 boundary drift")
    require(a2["status"] == "PHASE_A2_MATCHING_COMPLETE_NO_MODEL_HEAD_OR_EVALUATION", "A2 status drift")
    require(a2["contract_sha256"] == contract_hash, "A2 contract drift")
    require(a2["match_count"] == 5000 and a2["candidate_unique_count"] == 5000, "A2 count/reuse drift")
    require(a2["target_exact"] and a2["different_root"] and a2["different_state"], "A2 semantic checks drift")
    require(a2["acceptance"]["mean_pass"] is False and a2["acceptance"]["p95_pass"] is False, "A2 unexpectedly passes frozen radius gate")
    require(a2_receipt["status"] == "FAIL_RADIUS_ACCEPTANCE", "A2 failure receipt drift")
    require(not (OUT / "arms").exists(), "non-promotable run contains materialized arms")
    require(not (OUT / "phase-b-authorization.json").exists(), "Phase B authorization was created")

    files: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and "seal" not in path.parts:
            files[str(path.relative_to(OUT))] = h(path)
    seal_dir = OUT / "seal-local"
    manifest = {
        "status": "PHASE_A_SEALED_NOT_PROMOTABLE",
        "audit_status": "PASS",
        "protocol": contract["protocol"],
        "phase_a_identity": contract["phase_a_identity"],
        "disposition": "STATE_PROFILE_RADIUS_SUPPORT_FAILURE",
        "a0_candidate_pool": "PASS",
        "a1_feature_materialization": "PASS_TRAINING_ONLY",
        "a2_matching": "COMPLETE_BUT_RADIUS_GATE_FAIL",
        "radius_error": a2["radius_error"],
        "unconstrained_nearest_lower_bound": a2["unconstrained_nearest_lower_bound"],
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
        "phase_b_authorized": False,
        "arms_materialized": False,
        "contract_sha256": contract_hash,
        "artifact_hash_count": len(files),
        "verification_mode": "local_independent_failure_seal",
    }
    write(seal_dir / "phase-a-failure-seal-manifest.json", manifest)
    write(seal_dir / "phase-a-failure-hash-tree.json", {"status": "PASS", "files": files})
    write(seal_dir / "phase-a-failure-audit.json", {
        "status": "PASS",
        "seal_status": manifest["status"],
        "mismatch_count": 0,
        "scientific_promotion": "FORBIDDEN",
        "phase_b_authorized": False,
        "notes": [
            "The candidate pool and feature extraction passed their boundaries.",
            "The declared representational-radius matching gate failed even under the unconstrained nearest-candidate lower bound.",
            "No Phase-B arm was materialized.",
        ],
    })
    write(OUT / "phase-a-final-receipt.json", manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
