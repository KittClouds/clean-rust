"""Independent, read-only validator for the v0.8N Road-A atlas receipt."""

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

    road = args.run / "road-a"
    receipt_path = road / "road-a-receipt.json"
    report_path = road / "road-a-geometry-atlas.json"
    cache_receipt_path = args.run / "shared-feature-cache" / "shared-feature-cache-receipt.json"
    failures: list[str] = []
    for path in (receipt_path, report_path, cache_receipt_path):
        if not path.exists():
            failures.append(f"missing:{path}")
    if failures:
        seal = {"status": "V08N_ROAD_A_SEAL_FAIL", "failures": failures}
        write_json(args.output, seal)
        print(json.dumps(seal, indent=2))
        return 1

    receipt = read_json(receipt_path)
    report = read_json(report_path)
    cache = read_json(cache_receipt_path)
    checks = {
        "receipt_status": receipt.get("status") == "V08N_ROAD_A_GEOMETRY_ATLAS_PASS",
        "report_status": report.get("status") == "V08N_ROAD_A_GEOMETRY_ATLAS_PASS",
        "report_hash": receipt.get("report_sha256") == sha256_file(report_path),
        "training_only": report.get("training_only") is True and receipt.get("training_only") is True,
        "no_head_training": report.get("model_head_training") is False and receipt.get("no_model_head_training") is True,
        "no_eval": report.get("evaluation_inference") is False and receipt.get("no_evaluation_inference") is True,
        "no_protected": report.get("protected_evaluation_bodies_opened") is False and receipt.get("no_protected_evaluation_bodies_opened") is True,
        "no_phoenix": report.get("phoenix_access") is False and receipt.get("no_phoenix") is True,
        "road_b_not_selected": receipt.get("road_b_not_selected") is True and report.get("road_b_selection_forbidden") is True,
        "direction_unconstrained": report.get("direction_matching") is False,
        "no_feature_selection": report.get("selection_after_features") is False,
        "cache_status": cache.get("status") == "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY",
        "cache_shape": cache.get("feature_tensor", {}).get("shape") == [55_000, 2_048],
        "cache_no_eval": cache.get("evaluation_inference") is False and cache.get("protected_evaluation_bodies_opened") is False,
        "neighborhood_count": report.get("neighborhoods") == 5_000,
        "feature_shape": report.get("feature_shape") == [55_000, 2_048],
        "all_axes_present": set(report.get("neutral_axes", {})) == {f"neutral_{i}" for i in range(1, 9)},
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    seal = {
        "status": "V08N_ROAD_A_SEAL_PASS" if not failures else "V08N_ROAD_A_SEAL_FAIL",
        "phase_identity": "v0.8N-road-a-atlas-v01",
        "report_sha256": sha256_file(report_path),
        "receipt_sha256": sha256_file(receipt_path),
        "cache_receipt_sha256": sha256_file(cache_receipt_path),
        "checks": checks,
        "failures": failures,
        "training_only": True,
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "road_b_selection_used": False,
        "independent_local_fallback_seal": True,
    }
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite Road-A seal: {args.output}")
    write_json(args.output, seal)
    print(json.dumps(seal, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
