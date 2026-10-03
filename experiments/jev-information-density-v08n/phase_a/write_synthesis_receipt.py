"""Write the immutable v0.8N umbrella synthesis receipt after both road seals."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DOC = Path(__file__).resolve().parents[3] / "docs/jev-information-density-v0.8n-synthesis.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    road_a = args.run / "road-a"
    road_b = args.run / "road-b"
    a_seal = read_json(road_a / "seal/road-a-local-fallback-seal.json")
    b_branch = read_json(road_b / "branch-receipt.json")
    b_validation = read_json(road_b / "independent-validation.json")
    b_seal = read_json(road_b / "seal-manifest.json")
    require(a_seal["status"] == "V08N_ROAD_A_LOCAL_FALLBACK_SEAL_PASS", "Road-A seal is not closed")
    require(b_branch["status"] == "ROAD_B_BRANCH_SEALED_GATE_PASS", "Road-B branch is not closed")
    require(b_validation["status"] == "PASS", "Road-B validation is not PASS")
    require(b_seal["seal_status"] == "ROAD_B_SEALED_NOT_AUTHORIZED_FOR_PHASE_B", "Road-B Phase-B boundary drift")
    require(b_seal["mismatch_count"] == 0, "Road-B seal mismatch")
    require(b_seal["promotable"] is False and b_seal["phase_b_authorized"] is False, "Road-B authorization drift")
    require(a_seal["boundary"]["model_head_training"] is False and a_seal["boundary"]["evaluation_inference"] is False, "Road-A boundary drift")

    synthesis_dir = args.run / "synthesis"
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    path = synthesis_dir / "v08n-synthesis-receipt.json"
    if path.exists():
        raise RuntimeError("refusing to overwrite synthesis receipt")
    receipt = {
        "status": "V08N_SYNTHESIS_SEALED_CONSTRUCTION_ONLY",
        "phase_identity": "v0.8N-synthesis-v01",
        "road_a": {
            "identity": a_seal["phase_identity"],
            "seal": sha256_file(road_a / "seal/road-a-local-fallback-seal.json"),
            "atlas": next(value for key, value in a_seal["hash_tree"].items() if key.endswith("road-a-geometry-atlas.json")),
            "luna_disposition": a_seal["reviewer"]["luna_status"],
        },
        "road_b": {
            "identity": b_branch["branch_identity"],
            "branch_receipt": sha256_file(road_b / "branch-receipt.json"),
            "validation": sha256_file(road_b / "independent-validation.json"),
            "seal_manifest": sha256_file(road_b / "seal-manifest.json"),
            "selected_control": b_seal["artifact_hashes"]["selected-control-manifest.jsonl"],
            "luna_disposition": b_seal["luna_extra_high"]["status"],
        },
        "synthesis_document": {"path": str(DOC), "sha256": sha256_file(DOC)},
        "shared_feature_tensor_sha256": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "phase_b_authorized": False,
        "promotable_for_training": False,
    }
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
