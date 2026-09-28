from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any


PROJECT = "fas-frozen-observer-bundle-engineering-v01"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
MODEL_CONFIG_SHA256 = "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185"
MODEL_WEIGHTS_SHA256 = "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff"
TOKENIZER_MANIFEST_SHA256 = "c5e9a5b08ec5658ef2a8760d8230bbe9367bea124451488e164baf0eeca95afc"
EXPECTED_RUNTIME = {
    "python": "3.13.15",
    "torch": "2.11.0+cu128",
    "transformers": "5.17.0",
    "tokenizers": "0.23.2",
    "huggingface_hub": "1.32.0",
    "safetensors": "0.8.0",
    "numpy": "2.5.3",
}
EXPECTED_ROWS = 106_496
HIDDEN_DIMENSION = 2_048
REPEAT_ROWS = 256


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        line = f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def verify_seal(root: Path, seal_path: Path, expected_status: str) -> dict[str, Any]:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("status") != expected_status:
        raise RuntimeError(f"unexpected seal status: {seal.get('status')!r}")
    actual_entries: list[dict[str, Any]] = []
    for entry in seal["entries"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("seal contains a path outside its root")
        path = root / relative
        digest, size = sha256_file(path)
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"sealed file changed: {relative.as_posix()}")
        actual_entries.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if tree_root(actual_entries) != seal.get("root_sha256"):
        raise RuntimeError("seal root does not match verified files")
    return seal


def read_authorization(path: Path) -> dict[str, Any]:
    authorization = json.loads(path.read_text(encoding="utf-8"))
    if authorization.get("model_contact_authorized") is not True:
        raise RuntimeError("model contact is not authorized; refusing tokenizer/model access")
    if authorization.get("fitting_authorized") is not False:
        raise RuntimeError("feature extraction authorization cannot authorize observer fitting")
    if authorization.get("project_id") != PROJECT:
        raise RuntimeError("authorization names another project")
    return authorization


def verify_pre_model_bindings(authorization: dict[str, Any]) -> tuple[Path, Path, Path, dict[str, Any]]:
    run_root = Path(authorization["e1_run_root"]).resolve(strict=True)
    e1_seal = verify_seal(
        run_root,
        run_root / "e1-seal-v01.json",
        "E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED",
    )
    if e1_seal["root_sha256"] != authorization.get("e1_root_sha256"):
        raise RuntimeError("authorization names a different E1 panel root")
    if e1_seal.get("model_contact_authorized") is not False or e1_seal.get("fitting_authorized") is not False:
        raise RuntimeError("E1 seal has an invalid authority state")

    e0_path = Path(authorization["e0_seal_manifest_path"]).resolve(strict=True)
    repo_root = Path(authorization["repo_root"]).resolve(strict=True)
    e0_seal = verify_seal(
        repo_root,
        e0_path,
        "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
    )
    if e0_seal.get("root_sha256") != authorization.get("e0_root_sha256"):
        raise RuntimeError("authorization names a different E0 root")
    if e0_seal.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 seal has an invalid authority state")

    abi_path = Path(authorization["representation_abi_path"]).resolve(strict=True)
    abi_rel = abi_path.relative_to(repo_root).as_posix()
    abi_entry = next((row for row in e0_seal["entries"] if row["path"] == abi_rel), None)
    if abi_entry is None or sha256_file(abi_path)[0] != abi_entry["sha256"]:
        raise RuntimeError("representation ABI file is not part of the verified E0 seal")
    abi = json.loads(abi_path.read_text(encoding="utf-8"))
    extractor_sha, _ = sha256_file(Path(__file__).resolve())
    if abi.get("extractor_source_sha256") != extractor_sha:
        raise RuntimeError("extractor source differs from the frozen representation ABI")
    if abi.get("model_revision") != MODEL_REVISION:
        raise RuntimeError("ABI model revision differs from this extractor")
    if abi.get("model_config_sha256") != MODEL_CONFIG_SHA256:
        raise RuntimeError("ABI model config digest differs from this extractor")
    if abi.get("model_weights_sha256") != MODEL_WEIGHTS_SHA256:
        raise RuntimeError("ABI model weights digest differs from this extractor")
    if abi.get("tokenizer_assets_manifest_sha256") != TOKENIZER_MANIFEST_SHA256:
        raise RuntimeError("ABI tokenizer manifest differs from this extractor")
    abi_versions = abi.get("runtime_versions", {})
    if {name: abi_versions.get(name) for name in EXPECTED_RUNTIME} != EXPECTED_RUNTIME:
        raise RuntimeError("ABI runtime versions differ from this extractor")
    if abi.get("forward_call", {}).get("tensor_identity") != "output.last_hidden_state[0, sequence_length - 1, :]":
        raise RuntimeError("ABI tensor identity differs from this extractor")
    return run_root, abi_path, Path(authorization["feature_output_root"]), abi


def verify_runtime() -> tuple[Any, Any, Any, dict[str, str]]:
    import importlib.metadata

    observed = {"python": platform.python_version()}
    for package in ("torch", "transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)
    if observed != EXPECTED_RUNTIME:
        raise RuntimeError(f"runtime mismatch: expected={EXPECTED_RUNTIME}, observed={observed}")
    import numpy as np
    import torch
    import transformers

    return np, torch, transformers, observed


def authorized_extract(authorization_path: Path) -> dict[str, Any]:
    authorization = read_authorization(authorization_path)
    run_root, _abi_path, output_root, abi = verify_pre_model_bindings(authorization)

    # No model or tokenizer library is imported until the explicit authorization and both seals pass.
    np, torch, transformers, versions = verify_runtime()
    model_root = Path(authorization["model_snapshot_root"]).resolve(strict=True)
    tokenizer_root = Path(authorization["tokenizer_snapshot_root"]).resolve(strict=True)
    model_config = model_root / "config.json"
    model_weights = model_root / "model.safetensors"
    if sha256_file(model_config)[0] != MODEL_CONFIG_SHA256:
        raise RuntimeError("pinned model config does not match the representation ABI")
    if sha256_file(model_weights)[0] != MODEL_WEIGHTS_SHA256:
        raise RuntimeError("pinned model weights do not match the representation ABI")
    tokenizer_manifest = Path(authorization["tokenizer_asset_manifest_path"]).resolve(strict=True)
    tokenizer_manifest_sha, _ = sha256_file(tokenizer_manifest)
    if tokenizer_manifest_sha != TOKENIZER_MANIFEST_SHA256:
        raise RuntimeError("tokenizer asset manifest differs from the historical pinned manifest")
    if tokenizer_manifest_sha != abi.get("tokenizer_assets_manifest_sha256"):
        raise RuntimeError("tokenizer asset manifest differs from the frozen ABI")

    input_path = run_root / "panel" / "panel-inputs-v01.jsonl"
    row_manifest_path = run_root / "panel" / "row-manifest-v01.jsonl"
    if not input_path.is_file() or not row_manifest_path.is_file():
        raise RuntimeError("sealed E1 model inputs or row identity manifest are missing")
    if output_root.exists():
        raise RuntimeError("feature output root already exists; preserving prior artifacts")
    output_root.mkdir(parents=True)
    feature_path = output_root / "V1_FINAL_POSITION.f32le"

    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.allow_tf32 = False
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise RuntimeError("frozen CUDA device is not available")
    device = torch.device("cuda:0")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        tokenizer_root,
        use_fast=True,
        local_files_only=True,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise RuntimeError("the pinned fast tokenizer did not load")
    model = transformers.AutoModel.from_pretrained(
        model_root,
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=torch.float32,
    )
    model.eval()
    model.to(device)
    if getattr(model.config, "hidden_size", None) != HIDDEN_DIMENSION:
        raise RuntimeError("loaded model hidden dimension differs from the ABI")

    repeat_rows: list[tuple[str, bytes]] = []
    started = time.perf_counter()
    row_count = 0
    with feature_path.open("xb", buffering=0) as output:
        with input_path.open("r", encoding="utf-8") as source, torch.inference_mode():
            for line in source:
                record = json.loads(line)
                if set(record) != {"row_id", "quartet_id", "variant_id", "input_text"}:
                    raise RuntimeError("model-input row contains unexpected metadata or labels")
                text = record["input_text"]
                token_ids = tokenizer.encode(text, add_special_tokens=True, truncation=False)
                if not token_ids or len(token_ids) > 2048:
                    raise RuntimeError(f"invalid token length for row {record['row_id']}")
                ids = torch.tensor([token_ids], dtype=torch.long, device=device)
                attention_mask = torch.ones_like(ids)
                output_state = model(
                    input_ids=ids,
                    attention_mask=attention_mask,
                    use_cache=False,
                    return_dict=True,
                )
                hidden = output_state.last_hidden_state
                if hidden.dtype != torch.float32 or tuple(hidden.shape) != (1, len(token_ids), HIDDEN_DIMENSION):
                    raise RuntimeError(f"hidden tensor ABI mismatch for row {record['row_id']}")
                vector = hidden[0, len(token_ids) - 1, :].detach().contiguous().cpu().numpy()
                encoded = np.asarray(vector, dtype="<f4", order="C").tobytes(order="C")
                if len(encoded) != HIDDEN_DIMENSION * 4 or not np.isfinite(vector).all():
                    raise RuntimeError(f"feature vector is invalid for row {record['row_id']}")
                output.write(encoded)
                if row_count < REPEAT_ROWS:
                    repeat_rows.append((text, encoded))
                row_count += 1
        output.flush()
        os.fsync(output.fileno())
    if row_count != EXPECTED_ROWS:
        raise RuntimeError(f"feature row count mismatch: {row_count} != {EXPECTED_ROWS}")

    for text, expected in repeat_rows:
        token_ids = tokenizer.encode(text, add_special_tokens=True, truncation=False)
        ids = torch.tensor([token_ids], dtype=torch.long, device=device)
        mask = torch.ones_like(ids)
        with torch.inference_mode():
            hidden = model(input_ids=ids, attention_mask=mask, use_cache=False, return_dict=True).last_hidden_state
        actual = hidden[0, len(token_ids) - 1, :].detach().contiguous().cpu().numpy().astype("<f4", copy=False).tobytes(order="C")
        if actual != expected:
            raise RuntimeError("256-row deterministic repeat did not match byte-for-byte")

    digest, size = sha256_file(feature_path)
    if size != EXPECTED_ROWS * HIDDEN_DIMENSION * 4:
        raise RuntimeError("feature cache byte length differs from the frozen ABI")
    receipt = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_FEATURE_CACHE_V01",
        "status": "FEATURE_CACHE_COMPLETE_PENDING_INDEPENDENT_SEAL",
        "e0_root_sha256": authorization["e0_root_sha256"],
        "e1_root_sha256": authorization["e1_root_sha256"],
        "representation_abi_sha256": sha256_file(Path(authorization["representation_abi_path"]))[0],
        "model_revision": MODEL_REVISION,
        "model_config_sha256": MODEL_CONFIG_SHA256,
        "model_weights_sha256": MODEL_WEIGHTS_SHA256,
        "tokenizer_assets_manifest_sha256": tokenizer_manifest_sha,
        "extractor_source_sha256": sha256_file(Path(__file__).resolve())[0],
        "runtime_versions": versions,
        "device": torch.cuda.get_device_name(0),
        "row_count": row_count,
        "hidden_dimension": HIDDEN_DIMENSION,
        "surface": "V1_FINAL_POSITION",
        "tensor_identity": "output.last_hidden_state[0, sequence_length - 1, :]",
        "feature_file": feature_path.name,
        "feature_bytes": size,
        "feature_sha256": digest,
        "extraction_seconds": time.perf_counter() - started,
        "deterministic_repeat_rows": len(repeat_rows),
        "deterministic_repeat_byte_exact": True,
        "labels_opened": False,
        "observer_fitting_performed": False,
        "model_parameters_updated": False,
        "gradients_present": any(parameter.grad is not None for parameter in model.parameters()),
    }
    receipt_path = output_root / "feature-cache-receipt-v01.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorized E2 extractor for the frozen LFM representation ABI")
    parser.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = authorized_extract(args.authorization.resolve(strict=True))
    except Exception as error:
        print(f"E2 extraction stopped: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": receipt["status"], "rows": receipt["row_count"], "feature_sha256": receipt["feature_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
