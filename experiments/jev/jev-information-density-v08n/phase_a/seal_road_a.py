"""Independent local fallback seal for the immutable v0.8N Road-A atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/phase-a-v01-contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    args = parser.parse_args()

    road_a = args.run / "road-a"
    atlas_path = road_a / "road-a-geometry-atlas.json"
    receipt_path = road_a / "road-a-receipt.json"
    cache_dir = args.run / "shared-feature-cache"
    cache_receipt_path = cache_dir / "shared-feature-cache-receipt.json"
    scope_path = cache_dir / "training-only-feature-scope.jsonl"
    selection_path = args.selection / "selected-training-neighborhoods.jsonl"
    selection_receipt_path = args.selection / "selection-receipt.json"
    n0_validation = args.run / "n0-exact-world-validation.json"

    required = [atlas_path, receipt_path, cache_receipt_path, scope_path, selection_path, selection_receipt_path, n0_validation]
    if any(not path.is_file() for path in required):
        raise RuntimeError("Road-A seal input missing")

    contract = read_json(CONTRACT)
    atlas = read_json(atlas_path)
    road_a_receipt = read_json(receipt_path)
    cache_receipt = read_json(cache_receipt_path)
    selection_receipt = read_json(selection_receipt_path)
    validation = read_json(n0_validation)
    selected = read_jsonl(selection_path)
    scope = read_jsonl(scope_path)

    failures: list[str] = []
    if atlas.get("status") != "V08N_ROAD_A_GEOMETRY_ATLAS_PASS": failures.append("atlas status")
    if road_a_receipt.get("road_b_not_selected") is not True: failures.append("road B selection boundary")
    if cache_receipt.get("status") != "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY": failures.append("cache status")
    if cache_receipt.get("evaluation_inference") is not False or cache_receipt.get("protected_evaluation_bodies_opened") is not False: failures.append("cache boundary")
    if selection_receipt.get("status") != "V08N_N0_FEATURE_FREE_SELECTION_PASS" or len(selected) != 5_000: failures.append("selection")
    if len(scope) != 55_000 or cache_receipt.get("scope", {}).get("rows") != 55_000: failures.append("scope rows")
    if cache_receipt.get("feature_tensor", {}).get("shape") != [55_000, 2_048]: failures.append("feature shape")
    if validation.get("status") != "V08N_N0_EXACT_WORLD_VALIDATION_PASS": failures.append("N0 validation")
    if validation.get("model_contact") is not False or validation.get("training") is not False or validation.get("evaluation_inference") is not False: failures.append("N0 boundary")
    if atlas.get("feature_shape") != [55_000, 2_048]: failures.append("atlas feature shape")
    if atlas.get("training_only") is not True or atlas.get("model_head_training") is not False or atlas.get("evaluation_inference") is not False: failures.append("atlas boundary")
    if failures:
        raise RuntimeError("Road-A fallback seal failed: " + ", ".join(failures))

    files = [CONTRACT, atlas_path, receipt_path, cache_receipt_path, cache_dir / "shared-cache-authorization.json", scope_path, selection_path, args.selection / "selection-contract.json", selection_receipt_path, n0_validation, args.run / "generator-receipt.json"]
    hash_tree = {str(path): sha256_file(path) for path in files}
    seal = {
        "status": "V08N_ROAD_A_LOCAL_FALLBACK_SEAL_PASS",
        "phase_identity": "v0.8N-road-a-atlas-v01",
        "reviewer": {"type": "local-independent-fallback", "luna_status": "LUNA_PENDING_OR_NO_ARTIFACT", "scientific_cross_talk": False},
        "parent_hashes": {
            "contract": sha256_file(CONTRACT),
            "selection_manifest": sha256_file(selection_path),
            "cache_receipt": sha256_file(cache_receipt_path),
            "feature_tensor": cache_receipt["feature_tensor"]["sha256"],
            "atlas": sha256_file(atlas_path),
        },
        "counts": {"selected_neighborhoods": len(selected), "feature_scope_rows": len(scope), "episodes_per_neighborhood": 11},
        "model": cache_receipt["model"],
        "representation": cache_receipt["representation"],
        "boundary": {"training_only": True, "model_head_training": False, "evaluation_inference": False, "protected_evaluation_bodies_opened": False, "phoenix_access": False, "road_b_control_selected": False},
        "hash_tree": hash_tree,
    }
    seal_dir = road_a / "seal"
    if (seal_dir / "road-a-local-fallback-seal.json").exists():
        raise RuntimeError("refusing to overwrite Road-A seal")
    write_json(seal_dir / "road-a-local-fallback-seal.json", seal)
    write_json(seal_dir / "road-a-hash-tree.json", hash_tree)
    write_json(seal_dir / "road-a-lineage-receipt.json", {"phase_identity": seal["phase_identity"], "parent_hashes": seal["parent_hashes"], "status": seal["status"]})
    write_json(seal_dir / "road-a-audit.json", {"status": seal["status"], "failures": [], "luna_status": "LUNA_PENDING_OR_NO_ARTIFACT", "no_artifact_mutation": True})
    print(json.dumps({"status": seal["status"], "seal_sha256": sha256_file(seal_dir / "road-a-local-fallback-seal.json"), "seal_dir": str(seal_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
