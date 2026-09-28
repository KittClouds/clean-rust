"""Write the immutable v0.8N umbrella synthesis receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    road_a = args.run / "road-a"
    road_b = args.run / "road-b"
    atlas_path = road_a / "road-a-geometry-atlas.json"
    a_seal_path = road_a / "seal" / "road-a-local-seal.json"
    if not a_seal_path.exists():
        a_seal_path = road_a / "seal" / "road-a-local-fallback-seal.json"
    b_receipt_path = road_b / "branch-receipt.json"
    b_validation_path = road_b / "independent-validation.json"
    b_seal_path = road_b / "seal-manifest.json"
    required = [atlas_path, a_seal_path, b_receipt_path, b_validation_path, b_seal_path]
    if any(not path.is_file() for path in required):
        raise RuntimeError("umbrella synthesis inputs are incomplete")
    atlas = read_json(atlas_path)
    a_seal = read_json(a_seal_path)
    b_receipt = read_json(b_receipt_path)
    b_validation = read_json(b_validation_path)
    b_seal = read_json(b_seal_path)
    if atlas.get("status") != "V08N_ROAD_A_GEOMETRY_ATLAS_PASS":
        raise RuntimeError("Road A is not sealed PASS")
    if b_receipt.get("status") != "ROAD_B_BRANCH_SEALED_GATE_PASS":
        raise RuntimeError("Road B is not sealed gate PASS")
    if b_validation.get("status") != "PASS":
        raise RuntimeError("Road B independent validation is not PASS")
    if b_seal.get("status") != "ROAD_B_RADIUS_GATE_PASS_READ_ONLY_NO_TRAINING":
        raise RuntimeError("Road B seal is not read-only PASS")
    receipt = {
        "status": "V08N_SYNTHESIS_SEALED_NO_MODEL_TRAINING",
        "protocol": "jev-information-density/v0.8n-synthesis-v01",
        "parent_identity": "v0.8N-base-v01",
        "road_a": {
            "status": atlas["status"],
            "report_sha256": sha256_file(atlas_path),
            "seal_sha256": sha256_file(a_seal_path),
            "seal_path": str(a_seal_path),
        },
        "road_b": {
            "status": b_receipt["status"],
            "independent_validation": b_validation["status"],
            "branch_receipt_sha256": sha256_file(b_receipt_path),
            "seal_manifest_sha256": sha256_file(b_seal_path),
            "branch_path": str(road_b),
            "phase_b_authorized": False,
        },
        "shared_feature_tensor_sha256": "d8f0f12296758f68c55b5e5660572dd48e4e90d1a3a1683844e59765826bafaa",
        "road_a_findings": {
            "sham_radius_mean": atlas["sham_radius"]["mean"],
            "nearest_radius_mean_absolute_error": atlas["nearest_sham_radius_error"]["mean"],
            "nearest_radius_p95_absolute_error": atlas["nearest_sham_radius_error"]["p95"],
            "nearest_radius_mean_relative_error": atlas["nearest_sham_relative_error"]["mean"],
        },
        "road_b_gates": b_receipt["gates"],
        "boundaries": {
            "head_training": False,
            "evaluation_inference": False,
            "protected_evaluation_bodies_opened": False,
            "newtight_access": False,
            "phoenix_access": False,
            "road_a_steered_road_b": False,
        },
    }
    if args.output.exists():
        raise RuntimeError("refusing to overwrite synthesis receipt")
    write_json(args.output, receipt)
    print(json.dumps({"status": receipt["status"], "sha256": sha256_file(args.output), "path": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
