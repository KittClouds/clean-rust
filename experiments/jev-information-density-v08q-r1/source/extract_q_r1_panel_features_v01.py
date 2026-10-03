"""Frozen single-row feature extraction for the sealed Q-R1 panel."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

import torch
import numpy
import transformers
import tokenizers


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
PANEL_ROOT = RUN_ROOT / "panel"
DEFAULT_MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")
OUTPUT_ROOT = RUN_ROOT / "features"
AUDIT_PATH = RUN_ROOT / "panel-audit/r1-final-panel-audit.json"
EXCLUSION_ROOT = RUN_ROOT / "exclusions"
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
PANEL_MANIFEST = RUN_ROOT / "provenance/q-r1-panel-manifest-v01.json"
PANEL_SEAL = RUN_ROOT / "seals/q-r1-panel-construction-seal-v01.json"
INDEPENDENT_PANEL_RECEIPT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-verification-v02.json")
PANEL_CONTRACT = ROOT / "experiments/jev-information-density-v08q-r1/contracts/q-r1-panel-contract-v01.json"
PACKET_SEAL = ROOT / "experiments/jev-information-density-v08q-r1/seals/q-r1-packet-seal-and-authorization-v01.json"
FEATURE_KEY = "mean_full@16"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
EXPECTED_ADAPTER_SHA256 = "b8cd79a9a3265eca0fde5f509ba7c058bc2065d7747efe17ff7c7c1f6335b2d0"


MODEL_FILES = {
    "config.json": "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185",
    "model.safetensors": "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff",
    "tokenizer.json": "d7a0ab0fc22e41ec8c6d7450a9ff9ce40e196ec5e5a2fa6a2105e064e0514ed7",
    "tokenizer_config.json": "8cba5b0c7acab23a0d4cc9ac587346c9220a1b6d288fc5346fe118202fd6f43e",
    "special_tokens_map.json": "742aefe2b7dec496e8caffdba03a75d0c1a9925d53bd3f3e0d388c96b591b6f4",
}
ROLE_ORDER = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, 9)]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


def tensor_sha256(tensor: torch.Tensor) -> str:
    return sha256_bytes(tensor.detach().cpu().contiguous().numpy().tobytes())


def load_adapter() -> Any:
    if sha256_file(ADAPTER) != EXPECTED_ADAPTER_SHA256:
        raise RuntimeError("frozen LFM adapter hash mismatch")
    spec = importlib.util.spec_from_file_location("jev_v08q_r1_lfm_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.MODEL_SPEC["revision"] != MODEL_REVISION:
        raise RuntimeError("adapter model revision mismatch")
    return module


def verify_panel(panel: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if sha256_file(PANEL_MANIFEST) != read_json(PANEL_SEAL).get("panel_manifest_sha256"):
        raise RuntimeError("Q-R1 panel manifest hash differs from construction seal")
    seal = read_json(PANEL_SEAL)
    manifest = read_json(PANEL_MANIFEST)
    if seal.get("status") != "Q_R1_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING":
        raise RuntimeError("Q-R1 panel is not at the sealed pre-feature state")
    if manifest.get("status") != "Q_R1_PANEL_CONSTRUCTION_AND_FIVE_FIELD_AUDIT_PASS":
        raise RuntimeError("Q-R1 panel construction manifest is not PASS")
    if sha256_file(AUDIT_PATH) != manifest["independent_final_audit"]["sha256"]:
        raise RuntimeError("Q-R1 generator audit hash mismatch")
    if read_json(AUDIT_PATH).get("status") != "Q_R1_FRESH_PANEL_FINAL_AUDIT_PASS":
        raise RuntimeError("Q-R1 generator audit is not PASS")
    if read_json(INDEPENDENT_PANEL_RECEIPT).get("status") != "Q_R1_INDEPENDENT_PANEL_VERIFICATION_PASS":
        raise RuntimeError("independent Q-R1 panel verification is not PASS")
    panel_root = panel.parent
    expected_entries = {row["path"]: row for row in seal["entries"]}
    actual_entries = {path.relative_to(panel_root).as_posix() for path in panel_root.rglob("*") if path.is_file() and path != PANEL_SEAL}
    if actual_entries != set(expected_entries):
        raise RuntimeError("Q-R1 sealed construction tree has missing or extra files")
    for rel, entry in expected_entries.items():
        path = panel_root / Path(rel)
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"Q-R1 construction seal entry mismatch: {rel}")
    payload = "".join(f"{e['path']}\t{e['bytes']}\t{e['sha256']}\n" for e in sorted(seal["entries"], key=lambda x: x["path"]))
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != seal["root_sha256"]:
        raise RuntimeError("Q-R1 construction seal root mismatch")
    if manifest.get("contract_sha256") != sha256_file(PANEL_CONTRACT):
        raise RuntimeError("Q-R1 panel contract hash mismatch")
    packet = read_json(PACKET_SEAL)
    if manifest.get("contract_bundle_root_sha256") != packet.get("contract_bundle_root_sha256"):
        raise RuntimeError("Q-R1 panel contract bundle mismatch")
    exclusion = manifest["exclusion_sets"]
    exclusion_path = EXCLUSION_ROOT / "five-field-exclusion-sets.json"
    if sha256_file(exclusion_path) != exclusion["sha256"]:
        raise RuntimeError("Q-R1 five-field exclusion set hash mismatch")
    if read_json(EXCLUSION_ROOT / "exclusion-set-receipt.json").get("exclusion_set_sha256") != exclusion["sha256"]:
        raise RuntimeError("Q-R1 exclusion receipt does not bind the exclusion set")

    scope = read_jsonl(panel / "panel-feature-scope.jsonl")
    candidates = read_jsonl(panel / "fresh-candidate-text-manifest.jsonl")
    identities = read_jsonl(panel / "panel-occurrence-identities.jsonl")
    if len(scope) != 22_000 or len(identities) != 22_000 or len(candidates) != 16:
        raise RuntimeError("Q-R1 panel input row counts differ from contract")
    if [row["index"] for row in scope] != list(range(22_000)):
        raise RuntimeError("Q-R1 scope index/order mismatch")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row, identity in zip(scope, identities, strict=True):
        if sha256_bytes(row["text"].encode("utf-8")) != row["input_sha256"]:
            raise RuntimeError("Q-R1 rendered text identity mismatch")
        if row["neighborhood_id"] != identity["anchor_id"] or row["family_id"] != identity["family_id"] or row["family_slug"] != identity["family_slug"] or row["sequence"] != identity["sequence"] or row["role"] != identity["role"] or row["episode_id"] != identity["episode_id"] or row["input_sha256"] != identity["full_rendered_input_hash"]:
            raise RuntimeError("Q-R1 scope-to-five-field identity row mismatch")
        groups.setdefault(row["neighborhood_id"], []).append(row)
    if len(groups) != 2_000 or any(len(rows) != 11 for rows in groups.values()):
        raise RuntimeError("Q-R1 panel neighborhood/role cardinality mismatch")
    for rows in groups.values():
        rows.sort(key=lambda row: row["index"])
        if [row["role"] for row in rows] != ROLE_ORDER:
            raise RuntimeError("Q-R1 role order mismatch")
    ids = [row["candidate_semantic_id"] for row in candidates]
    schemas = [row["schema_family_id"] for row in candidates]
    if len(set(ids)) != 16 or len(set(schemas)) != 4 or any(sha256_bytes(row["text"].encode("utf-8")) != row["text_sha256"] for row in candidates):
        raise RuntimeError("Q-R1 candidate catalog identity/text mismatch")
    if any(sum(1 for row in candidates if row["schema_family_id"] == schema) != 4 for schema in set(schemas)):
        raise RuntimeError("Q-R1 candidate catalog is not four-by-four")
    return scope, candidates, {"panel_manifest_sha256": sha256_file(PANEL_MANIFEST), "panel_seal_sha256": sha256_file(PANEL_SEAL), "panel_root_sha256": seal["root_sha256"], "panel_contract_sha256": manifest["contract_sha256"]}

def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def model_parameter_sha256(model: Any) -> str:
    digest = hashlib.sha256()
    for name, parameter in model.named_parameters():
        cpu = parameter.detach().to(device="cpu").contiguous()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(cpu.dtype).encode("ascii") + b"\0")
        digest.update(json.dumps(list(cpu.shape), separators=(",", ":")).encode("ascii") + b"\0")
        digest.update(cpu.view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()

def verify_runtime(torch_module: Any, model_root: Path, device: str) -> dict[str, Any]:
    if platform.python_version() != "3.13.15":
        raise RuntimeError(f"Python runtime mismatch: {platform.python_version()}")
    if torch_module.__version__ != "2.11.0+cu128" or transformers.__version__ != "5.17.0" or tokenizers.__version__ != "0.23.2" or numpy.__version__ != "2.5.3":
        raise RuntimeError("frozen Python package version mismatch")
    if not torch_module.cuda.is_available() or device != "cuda":
        raise RuntimeError("frozen CUDA runtime unavailable; CPU fallback is forbidden")
    name = torch_module.cuda.get_device_name(0)
    capability = list(torch_module.cuda.get_device_capability(0))
    if name != "NVIDIA GeForce RTX 3080" or capability != [8, 6]:
        raise RuntimeError(f"frozen CUDA device mismatch: {name} {capability}")
    if torch_module.version.cuda != "12.8" or torch_module.backends.cudnn.version() != 91900:
        raise RuntimeError("frozen CUDA/cuDNN runtime mismatch")
    if torch_module.backends.cuda.matmul.allow_tf32 or not torch_module.backends.cudnn.allow_tf32:
        raise RuntimeError("frozen TF32 settings mismatch")
    if torch_module.backends.cudnn.benchmark or torch_module.backends.cudnn.deterministic or torch_module.are_deterministic_algorithms_enabled():
        raise RuntimeError("frozen cuDNN/determinism settings mismatch")
    snapshot = model_root / "lfm2.5-1.2b-base"
    observed = {name: sha256_file(snapshot / name) for name in MODEL_FILES}
    if observed != MODEL_FILES:
        raise RuntimeError("pinned LFM snapshot hash mismatch")
    return {"python": platform.python_version(), "torch": torch_module.__version__, "transformers": transformers.__version__, "tokenizers": tokenizers.__version__, "numpy": numpy.__version__, "cuda": torch_module.version.cuda, "cudnn": torch_module.backends.cudnn.version(), "device": name, "compute_capability": capability, "snapshot_sha256": observed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=PANEL_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing existing feature output: {args.output}")
    scope, candidates, panel_provenance = verify_panel(args.panel)
    runtime = verify_runtime(torch, args.model_root, args.device)
    adapter = load_adapter()
    args.output.mkdir(parents=True, exist_ok=False)
    scope_texts = [row["text"] for row in scope]
    candidate_texts = [row["text"] for row in candidates]
    tokenizer, model = adapter.load_model(args.model_root, args.device)
    if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
        raise RuntimeError("frozen LFM architecture mismatch")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("LFM backbone is not frozen")
    parameter_sha_before = model_parameter_sha256(model)
    all_texts = scope_texts + candidate_texts
    tokenized = tokenizer(all_texts, add_special_tokens=True, padding=False, truncation=False)
    token_rows = tokenized["input_ids"]
    if len(token_rows) != 22_016 or any(not row or len(row) > 1024 for row in token_rows):
        raise RuntimeError("Q-R1 inputs are empty, truncated, or exceed the frozen maximum length")
    token_manifest = [
        {"index": i, "token_count": len(ids), "token_ids_sha256": sha256_bytes(json.dumps(ids, separators=(",", ":")).encode("ascii"))}
        for i, ids in enumerate(token_rows)
    ]
    smoke_texts = scope_texts[:8] + candidate_texts
    first = adapter.encode_lfm_texts(model, tokenizer, smoke_texts, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[FEATURE_KEY]
    second = adapter.encode_lfm_texts(model, tokenizer, smoke_texts, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[FEATURE_KEY]
    repeat_error = float((first - second).abs().max().cpu())
    if tuple(first.shape) != (24, 2048) or repeat_error > 1e-5:
        raise RuntimeError(f"frozen-feature repeat smoke failed: shape={tuple(first.shape)} error={repeat_error}")

    started = time.perf_counter()
    state_parts: list[torch.Tensor] = []
    for start in range(0, len(scope_texts), 128):
        end = min(start + 128, len(scope_texts))
        chunk = adapter.encode_lfm_texts(model, tokenizer, scope_texts[start:end], ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[FEATURE_KEY]
        if tuple(chunk.shape) != (end - start, 2048) or chunk.dtype != torch.float32 or not torch.isfinite(chunk).all():
            raise RuntimeError(f"state feature output invalid at rows {start}:{end}")
        state_parts.append(chunk.cpu().contiguous())
        print(json.dumps({"stage": "q_r1_state_feature_chunk", "start": start, "end": end}), flush=True)
    state_features = torch.cat(state_parts, dim=0)
    candidate_features = adapter.encode_lfm_texts(model, tokenizer, candidate_texts, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[FEATURE_KEY].cpu().contiguous()
    if tuple(state_features.shape) != (22_000, 2048) or tuple(candidate_features.shape) != (16, 2048) or not torch.isfinite(candidate_features).all():
        raise RuntimeError("complete Q-R1 feature tensor shape/finite-value check failed")

    state_rows = []
    for i, source in enumerate(scope):
        tokens = token_manifest[i]
        state_rows.append({"index": i, "neighborhood_id": source["neighborhood_id"], "family_id": source["family_id"], "family_slug": source["family_slug"], "role": source["role"], "episode_id": source["episode_id"], "input_sha256": source["input_sha256"], "token_count": tokens["token_count"], "token_ids_sha256": tokens["token_ids_sha256"], "feature_sha256": tensor_sha256(state_features[i]), "feature_key": FEATURE_KEY})
    candidate_rows = []
    for i, source in enumerate(candidates):
        tokens = token_manifest[len(scope) + i]
        candidate_rows.append({"index": i, "schema_family_id": source["schema_family_id"], "candidate_semantic_id": source["candidate_semantic_id"], "candidate_order": source["candidate_order"], "input_text_sha256": source["text_sha256"], "token_count": tokens["token_count"], "token_ids_sha256": tokens["token_ids_sha256"], "feature_sha256": tensor_sha256(candidate_features[i]), "feature_key": FEATURE_KEY})
    state_path = args.output / "r1-state-features.pt"
    candidate_path = args.output / "r1-candidate-features.pt"
    torch.save({"features": state_features, "scope_sha256": sha256_file(args.panel / "panel-feature-scope.jsonl"), "feature_key": FEATURE_KEY}, state_path)
    torch.save({"features": candidate_features, "candidate_ids": [row["candidate_semantic_id"] for row in candidates], "feature_key": FEATURE_KEY}, candidate_path)
    write_jsonl(args.output / "r1-state-feature-manifest.jsonl", state_rows)
    write_jsonl(args.output / "r1-candidate-feature-manifest.jsonl", candidate_rows)
    parameter_sha_after = model_parameter_sha256(model)
    if parameter_sha_after != parameter_sha_before:
        raise RuntimeError("backbone parameter identity changed during extraction")
    after = {name: sha256_file(args.model_root / "lfm2.5-1.2b-base" / name) for name in MODEL_FILES}
    if after != runtime["snapshot_sha256"]:
        raise RuntimeError("pinned frozen LFM snapshot changed during extraction")
    receipt = {
        "status": "Q_R1_FROZEN_PANEL_FEATURE_EXTRACTION_PASS",
        "panel_manifest_sha256": panel_provenance["panel_manifest_sha256"],
        "panel_seal_sha256": panel_provenance["panel_seal_sha256"],
        "panel_root_sha256": panel_provenance["panel_root_sha256"],
        "panel_contract_sha256": panel_provenance["panel_contract_sha256"],
        "extractor_sha256": sha256_file(Path(__file__).resolve()),
        "adapter_sha256": EXPECTED_ADAPTER_SHA256,
        "model_id": "LiquidAI/LFM2.5-1.2B-Base",
        "backbone_revision": MODEL_REVISION,
        "tokenizer_identity": {
            "tokenizer_json_sha256": runtime["snapshot_sha256"]["tokenizer.json"],
            "tokenizer_config_sha256": runtime["snapshot_sha256"]["tokenizer_config.json"],
            "special_tokens_map_sha256": runtime["snapshot_sha256"]["special_tokens_map.json"],
            "fast_tokenizer": bool(tokenizer.is_fast),
        },
        "feature_key": FEATURE_KEY,
        "representation": {"pooling": "mean_full", "layer": "final", "exact_length": True, "single_row": True, "padding": False, "maximum_length": 1024, "backbone_dtype": "bfloat16", "output_dtype": "float32", "dimension": 2048},
        "runtime": runtime,
        "backbone_snapshot_files_after_sha256": after,
        "backbone_snapshot_files_unchanged": after == runtime["snapshot_sha256"],
        "backbone_parameter_identity_before_sha256": parameter_sha_before,
        "backbone_parameter_identity_after_sha256": parameter_sha_after,
        "backbone_parameter_identity_unchanged": parameter_sha_before == parameter_sha_after,
        "input_counts": {"state_occurrences": len(scope), "candidate_texts": len(candidates), "total": len(all_texts)},
        "input_token_count_range": [min(row["token_count"] for row in token_manifest), max(row["token_count"] for row in token_manifest)],
        "repeat_smoke": {"rows": len(smoke_texts), "max_abs_error": repeat_error, "pass": repeat_error <= 1e-5},
        "state_tensor": {"path": str(state_path), "sha256": sha256_file(state_path), "tensor_sha256": tensor_sha256(state_features), "shape": list(state_features.shape)},
        "candidate_tensor": {"path": str(candidate_path), "sha256": sha256_file(candidate_path), "tensor_sha256": tensor_sha256(candidate_features), "shape": list(candidate_features.shape)},
        "state_manifest_sha256": sha256_file(args.output / "r1-state-feature-manifest.jsonl"),
        "candidate_manifest_sha256": sha256_file(args.output / "r1-candidate-feature-manifest.jsonl"),
        "extract_elapsed_seconds": time.perf_counter() - started,
        "head_loaded": False,
        "training": False,
        "inference": False,
        "evaluation": False,
        "feature_cache_seal_pending": True,
        "newtight": False,
        "phoenix_access": False,
    }
    write_json(args.output / "r1-feature-extraction-receipt.json", receipt)
    del model
    if args.device == "cuda":
        torch.cuda.empty_cache()
    print(json.dumps({"status": receipt["status"], "state_rows": len(scope), "candidate_rows": len(candidates), "repeat_max_abs_error": repeat_error, "elapsed_seconds": round(receipt["extract_elapsed_seconds"], 2)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
