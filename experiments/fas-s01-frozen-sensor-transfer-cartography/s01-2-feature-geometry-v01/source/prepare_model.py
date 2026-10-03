from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
from pathlib import Path
from typing import Any

from common import canonical, jsonl_rows, read_json, sha256_bytes, sha256_file, verify_parent_bundle


REPO_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
ALLOW_PATTERNS = ("config.json", "*.safetensors", "*.safetensors.index.json")
FORBIDDEN_SUFFIXES = (".bin", ".pt", ".pth", ".gguf", ".onnx", ".h5", ".msgpack")


def selected_file(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in ALLOW_PATTERNS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download only the pinned LFM config and safetensors")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    binding = read_json(root / "inputs" / "input-binding-v01.json")
    preflight = read_json(root / "seals" / "preflight-seal-v01.json")
    if preflight.get("model_loaded") is not False or preflight.get("feature_extraction_performed") is not False:
        raise SystemExit("invalid preflight authority state")
    if sha256_file(root / "inputs" / "extraction-execution-contract-v01.json")[0] != binding["contract_sha256"]["extraction"]:
        raise SystemExit("frozen extraction contract changed after preflight")

    # Verify the authorized corpus and alignment parents before downloading model files.
    parent_receipt = verify_parent_bundle(binding)
    parent_path = root / "parent-verification-receipt-v01.json"
    if parent_path.exists():
        raise SystemExit("parent verification receipt already exists")
    parent_path.write_text(json.dumps(parent_receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    import huggingface_hub
    from huggingface_hub import HfApi, snapshot_download

    if huggingface_hub.__version__ != binding["runtime_versions"]["huggingface_hub"]:
        raise RuntimeError("huggingface_hub version differs from the frozen runtime")
    api = HfApi()
    info = api.model_info(REPO_ID, revision=REVISION, files_metadata=True)
    if info.sha != REVISION:
        raise RuntimeError(f"Hub resolved a different model revision: {info.sha}")
    repo_files = sorted(sibling.rfilename for sibling in info.siblings if selected_file(sibling.rfilename))
    if "config.json" not in repo_files or not any(name.endswith(".safetensors") for name in repo_files):
        raise RuntimeError("pinned model revision lacks the contracted config or safetensors")
    if any(name.endswith(FORBIDDEN_SUFFIXES) for name in repo_files):
        raise RuntimeError("forbidden model serialization appeared in the selected asset list")

    model_root = root / "model-assets"
    if model_root.exists():
        raise SystemExit("model-assets directory already exists; refusing reuse or overwrite")
    if shutil.disk_usage(root).free < binding["minimum_free_disk_bytes"]:
        raise RuntimeError("available disk space fell below the frozen execution floor")
    model_root.mkdir()
    snapshot = snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        cache_dir=str(model_root / "hub-cache"),
        allow_patterns=list(ALLOW_PATTERNS),
        local_files_only=False,
        max_workers=4,
    )
    snapshot_path = Path(snapshot).resolve()
    if not snapshot_path.is_relative_to(root):
        raise RuntimeError("resolved model snapshot escaped the isolated S01-2 run root")

    assets = []
    for path in sorted(snapshot_path.rglob("*"), key=lambda item: item.relative_to(snapshot_path).as_posix()):
        relative = path.relative_to(snapshot_path).as_posix()
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            raise RuntimeError(f"model snapshot symlink escaped the isolated run: {relative}")
        if not path.is_file():
            continue
        if not selected_file(relative):
            raise RuntimeError(f"unexpected model asset in pinned snapshot: {relative}")
        digest, size = sha256_file(path)
        assets.append({"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": digest})
    if not assets or not any(item["path"].endswith("config.json") for item in assets) or not any(item["path"].endswith(".safetensors") for item in assets):
        raise RuntimeError("downloaded snapshot is missing required model assets")
    config_path = snapshot_path / "config.json"
    config = read_json(config_path)
    hidden_size = config.get("hidden_size")
    if hidden_size is None and isinstance(config.get("text_config"), dict):
        hidden_size = config["text_config"].get("hidden_size")
    if hidden_size != 2048:
        raise RuntimeError(f"pinned model hidden dimension differs from contract: {hidden_size}")
    if config.get("auto_map"):
        raise RuntimeError("custom remote code is declared; trust_remote_code remains forbidden")

    asset_root = sha256_bytes(canonical(assets))
    manifest = {
        "manifest_id": "FASS01_S01_2_MODEL_ASSET_MANIFEST_V01",
        "model_id": REPO_ID,
        "requested_revision": REVISION,
        "resolved_revision": info.sha,
        "snapshot_path": snapshot_path.relative_to(root).as_posix(),
        "hidden_size": hidden_size,
        "model_type": config.get("model_type"),
        "config_torch_dtype": config.get("torch_dtype"),
        "downloaded_file_allowlist": list(ALLOW_PATTERNS),
        "assets": assets,
        "asset_manifest_root_sha256": asset_root,
        "tokenizer_downloaded_or_loaded_in_this_phase": False,
        "model_loaded_in_this_phase": False,
    }
    manifest_path = root / "model-asset-manifest-v01.json"
    if manifest_path.exists():
        raise SystemExit("model asset manifest already exists")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"pinned_revision={info.sha}")
    print(f"model_assets={len(assets)} hidden_size={hidden_size} root={asset_root}")
    print(f"snapshot={snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
