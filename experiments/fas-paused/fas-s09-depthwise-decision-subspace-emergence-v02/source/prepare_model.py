from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from s09_common import REVISION, RUN_ROOT, S01_2_ROOT, entry_for, read_json, sha256_file, tree_root, write_json


def main() -> int:
    preflight_path = RUN_ROOT / "seals" / "preflight-seal-v02.json"
    if not preflight_path.is_file():
        raise RuntimeError("sealed preflight is required before model asset preparation")
    if (RUN_ROOT / "model-assets").exists():
        raise RuntimeError("S09 model-assets already exists; refusing in-place retry")
    available = shutil.disk_usage(RUN_ROOT).free
    reserve = int(read_json(RUN_ROOT / "inputs" / "project-snapshot" / "contracts" / "s09-contract-v02.json")["runtime"]["post_copy_extraction_reserve_bytes"])
    expected_feature_bytes = int(read_json(RUN_ROOT / "inputs" / "project-snapshot" / "contracts" / "s09-contract-v02.json")["runtime"]["expected_feature_cache_bytes"])
    manifest = read_json(RUN_ROOT / "inputs" / "S01-2" / "model-asset-manifest-v01.json")
    if manifest.get("model_id") != "LiquidAI/LFM2.5-1.2B-Base" or manifest.get("resolved_revision") != REVISION:
        raise RuntimeError("S01 pinned model asset identity changed")
    source_root = S01_2_ROOT.joinpath(*manifest["snapshot_path"].split("/"))
    total_bytes = sum(int(item["bytes"]) for item in manifest["assets"])
    if available < total_bytes + expected_feature_bytes + reserve:
        raise RuntimeError("free space does not cover model copy, feature cache, and frozen reserve")

    out_root = RUN_ROOT / "model-assets" / "snapshot"
    out_root.mkdir(parents=True, exist_ok=False)
    copied = []
    for item in manifest["assets"]:
        relative = Path(*item["path"].split("/"))
        source = S01_2_ROOT / relative
        # All selected S01-2 assets are top-level snapshot files.
        target = out_root / relative.name
        source_hash, source_bytes = sha256_file(source)
        if source_hash != item["sha256"] or source_bytes != item["bytes"]:
            raise RuntimeError(f"pinned source model asset changed: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied_hash, copied_bytes = sha256_file(target)
        if copied_hash != source_hash or copied_bytes != source_bytes:
            raise RuntimeError(f"copied model asset differs: {target}")
        copied.append({"path": target.relative_to(RUN_ROOT).as_posix(), "bytes": copied_bytes, "sha256": copied_hash})

    config_path = out_root / "config.json"
    config = read_json(config_path)
    if config.get("model_type") != "lfm2" or config.get("num_hidden_layers") != 16 or config.get("hidden_size") != 2048:
        raise RuntimeError("pinned model config differs from frozen 16-layer, 2048-wide contract")
    canonical_assets = json.dumps(copied, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result = {
        "manifest_id": "FAS_S09_MODEL_ASSET_MANIFEST_V02",
        "model_id": "LiquidAI/LFM2.5-1.2B-Base",
        "requested_revision": REVISION,
        "resolved_revision": REVISION,
        "source_asset_manifest_sha256": sha256_file(RUN_ROOT / "inputs" / "S01-2" / "model-asset-manifest-v01.json")[0],
        "asset_manifest_root_sha256": hashlib.sha256(canonical_assets).hexdigest(),
        "snapshot_path": "model-assets/snapshot",
        "layers": 16,
        "hidden_dimension": 2048,
        "tokenizer_copied_or_loaded": False,
        "assets": copied,
    }
    write_json(RUN_ROOT / "model-asset-manifest-v02.json", result)
    model_entries = [entry_for(out_root / item["path"].split("/")[-1], RUN_ROOT) for item in copied]
    model_entries.sort(key=lambda item: item["path"])
    write_json(RUN_ROOT / "model-assets-seal-v02.json", {
        "seal_id": "FAS_S09_MODEL_ASSETS_SEAL_V02",
        "entries": model_entries,
        "root_sha256": tree_root(model_entries),
        "model_asset_manifest_sha256": sha256_file(RUN_ROOT / "model-asset-manifest-v02.json")[0],
    })
    print(f"model_asset_root_sha256={result['asset_manifest_root_sha256']} files={len(copied)} copied_bytes={sum(x['bytes'] for x in copied)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
