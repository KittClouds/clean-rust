from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
import torch
import torch.nn.functional as functional
import transformers

from s12_math import canonical_json, entry, matched_random_delta, pair_normals, projected, random_plane, seed_from_label, sha256_file, tree_root


RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02")
V01_RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v01")
S11 = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
S09 = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v09")
MODEL_ROOT = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v02\model-assets\snapshot")
S12_INPUTS = RUN / "inputs"
S11_FEATURES = S11 / "feature-cache-v01"
S11_TOKENS = S11 / "tokenization-v01"
S11_PANEL = S11 / "inputs" / "panel"
S11_SEAL = S11 / "s11-final-seal-v02.json"
S09_SEAL = S09 / "result-tree-seal-v09.json"
CONTRACT = RUN / "inputs" / "protocol" / "s12-execution-contract-v02.json"
ROWS = 21_272
DIMENSION = 2_048
MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
EXPECTED_STATE = "14b8ccb6c347eb5a91ccb718de39d70865f15410f5b6e62ca747aaf77f6bb9e5"
SITES = ((4, "M"), (4, "F"), (8, "M"), (8, "F"), (12, "M"), (12, "F"))
STRENGTHS = (0.0, 0.25, 0.5, 1.0)
ARMS = 9
ENDPOINTS = ("M", "F")
BRANCH_MICROBATCH = 8


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                raise RuntimeError(f"non-terminated JSONL row {line_no}: {path}")
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def verify_entries(base: Path, seal: dict[str, Any], relatives: list[str]) -> dict[str, dict[str, Any]]:
    expected = {item["path"]: item for item in seal["entries"]}
    result = {}
    for relative in relatives:
        if relative not in expected:
            raise RuntimeError(f"sealed parent lacks required file {relative}")
        actual = entry(base.joinpath(*relative.split("/")), base)
        if actual != expected[relative]:
            raise RuntimeError(f"sealed parent file mismatch: {relative}")
        result[relative] = actual
    return result


def verify_local_tree(base: Path, seal_path: Path) -> dict[str, Any]:
    seal = read_json(seal_path)
    actual = [entry(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    if actual != sorted(seal["entries"], key=lambda item: item["path"]) or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError(f"local S12 tree seal mismatch: {seal_path}")
    return seal


def verify_reused_v01_gates() -> dict[str, Any]:
    old_base = V01_RUN / "base-parity-v01"
    old_baseline = V01_RUN / "baseline-v01"
    new_base = RUN / "base-parity-v02"
    new_baseline = RUN / "baseline-v02"
    old_base_seal = verify_local_tree(old_base, old_base / "base-parity-seal-v01.json")
    old_baseline_seal = verify_local_tree(old_baseline, old_baseline / "baseline-seal-v01.json")
    new_base_seal = verify_local_tree(new_base, new_base / "base-parity-seal-v02.json")
    new_baseline_seal = verify_local_tree(new_baseline, new_baseline / "baseline-seal-v02.json")
    reuse = read_json(RUN / "reused-v01-gates-receipt-v02.json")
    expected = {
        "base_parity": (old_base_seal["root_sha256"], new_base_seal["root_sha256"]),
        "baseline_replay": (old_baseline_seal["root_sha256"], new_baseline_seal["root_sha256"]),
    }
    for key, (old_root, new_root) in expected.items():
        item = reuse.get(key, {})
        if item.get("source_root_sha256") != old_root or item.get("reused_root_sha256") != new_root:
            raise RuntimeError(f"S12 reused v01 {key} root binding mismatch")
    old_base_rows = sha256_file(old_base / "base-parity-rows-v01.jsonl")
    new_base_rows = sha256_file(new_base / "base-parity-rows-v02.jsonl")
    if old_base_rows != new_base_rows:
        raise RuntimeError("S12 reused v01 base/suffix row manifest is not byte-identical")
    for old_name, new_name in (
        ("baseline-probe-logits-v01.f32le", "baseline-probe-logits-v02.f32le"),
        ("baseline-probe-probabilities-v01.f32le", "baseline-probe-probabilities-v02.f32le"),
        ("baseline-predictions-v01.i64le", "baseline-predictions-v02.i64le"),
    ):
        if sha256_file(old_baseline / old_name) != sha256_file(new_baseline / new_name):
            raise RuntimeError(f"S12 reused v01 baseline bytes changed: {old_name}")
    return {
        "verified": True,
        "v01_base_root_sha256": old_base_seal["root_sha256"],
        "v02_reused_base_root_sha256": new_base_seal["root_sha256"],
        "v01_baseline_root_sha256": old_baseline_seal["root_sha256"],
        "v02_reused_baseline_root_sha256": new_baseline_seal["root_sha256"],
        "base_row_manifest_byte_equal": True,
        "baseline_arrays_byte_equal": True,
        "reuse_receipt_sha256": sha256_file(RUN / "reused-v01-gates-receipt-v02.json")[0],
    }


def verify_protocol_bundle() -> dict[str, Any]:
    seal_path = RUN / "inputs" / "protocol-bundle-seal-v02.json"
    seal = read_json(seal_path)
    actual = []
    for item in seal["entries"]:
        path = RUN.joinpath(*item["path"].split("/"))
        found = entry(path, RUN)
        if found != item:
            raise RuntimeError(f"S12 frozen bundle file mismatch: {item['path']}")
        actual.append(found)
    if tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError("S12 protocol bundle root mismatch")
    contract_path = CONTRACT.relative_to(RUN).as_posix()
    contract_row = next((item for item in actual if item["path"] == contract_path), None)
    if contract_row is None:
        raise RuntimeError("S12 execution contract is not in the sealed bundle")
    code_manifest_path = RUN / "implementation-code-manifest-v02.json"
    code_manifest = read_json(code_manifest_path)
    code_entries = []
    for item in code_manifest["entries"]:
        path = RUN.joinpath(*item["path"].split("/"))
        found = entry(path, RUN)
        if found != item:
            raise RuntimeError(f"S12 implementation code identity mismatch: {item['path']}")
        code_entries.append(found)
    if tree_root(code_entries) != code_manifest.get("code_root_sha256"):
        raise RuntimeError("S12 implementation code root mismatch")
    if not set(item["path"] for item in code_entries).issubset(set(item["path"] for item in actual)):
        raise RuntimeError("S12 implementation code is not fully covered by the protocol bundle")
    return {
        "root_sha256": seal["root_sha256"],
        "entries_verified": len(actual),
        "contract_sha256": contract_row["sha256"],
        "code_root_sha256": code_manifest["code_root_sha256"],
    }


def verify_parent_inputs(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], np.memmap, np.memmap, dict[str, Any]]:
    if contract["parents"]["s11_result_root_sha256"] != "23758806537df1895772025e97824393dd4cd79ede7956360cd93f341c30740a":
        raise RuntimeError("contract S11 result root changed")
    s11_seal = read_json(S11_SEAL)
    if s11_seal.get("root_sha256") != contract["parents"]["s11_result_root_sha256"]:
        raise RuntimeError("S11 final result seal root mismatch")
    s09_seal = read_json(S09_SEAL)
    if s09_seal.get("root_sha256") != contract["parents"]["s09_result_root_sha256"]:
        raise RuntimeError("S09 result-tree root mismatch")
    token_seal = read_json(S11_TOKENS / "tokenization-seal-v01.json")
    feature_seal = read_json(S11_FEATURES / "feature-cache-seal-v01.json")
    if token_seal.get("root_sha256") != contract["parents"]["s11_tokenization_root_sha256"]:
        raise RuntimeError("S11 tokenization root mismatch")
    if feature_seal.get("root_sha256") != contract["parents"]["s11_feature_cache_root_sha256"]:
        raise RuntimeError("S11 feature-cache root mismatch")
    s11_required = [
        "inputs/panel/selected-events-v02.jsonl",
        "inputs/panel/selected-quartets-v02.jsonl",
        "inputs/panel/panel-tree-seal-v02.json",
        "tokenization-v01/token-inputs-v01.jsonl",
        "tokenization-v01/token-rows-v01.jsonl",
        "tokenization-v01/tokenization-seal-v01.json",
        "feature-cache-v01/feature-cache-seal-v01.json",
        "feature-cache-v01/feature-extraction-receipt-v01.json",
        "feature-cache-v01/feature-rows-v01.jsonl",
        "feature-cache-v01/matrices/layer-16-M.f32le",
        "feature-cache-v01/matrices/layer-16-F.f32le",
        "transport-v01/predictions/M-src-16-tgt-16.npy",
        "transport-v01/predictions/F-src-16-tgt-16.npy",
        "analysis-v01/s11-confirmatory-analysis-v01.json",
        "inputs/tokenizer-identity-v01.json",
        "inputs/parent/s09-model-asset-manifest-v02.json",
    ]
    s11_files = verify_entries(S11, s11_seal, s11_required)
    model_manifest = read_json(S11 / "inputs" / "parent" / "s09-model-asset-manifest-v02.json")
    if model_manifest.get("asset_manifest_root_sha256") != contract["model"]["asset_root_sha256"]:
        raise RuntimeError("model asset manifest root mismatch")
    for item in model_manifest["assets"]:
        path = MODEL_ROOT / item["path"].split("/")[-1]
        digest, size = sha256_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"pinned model asset mismatch: {path}")

    parent_binding_path = RUN / contract["parents"]["parent_binding_path"]
    parent_binding_hash = sha256_file(parent_binding_path)[0]
    if parent_binding_hash != contract["parents"]["parent_binding_sha256"]:
        raise RuntimeError("S12 parent binding hash mismatch")
    parent_binding = read_json(parent_binding_path)
    if sha256_file(S11_SEAL)[0] != parent_binding["parents"]["s11"]["final_seal_file_sha256"]:
        raise RuntimeError("S11 final seal file hash mismatch")
    if sha256_file(S09_SEAL)[0] != parent_binding["parents"]["s09"]["result_tree_seal_file_sha256"]:
        raise RuntimeError("S09 result-tree seal file hash mismatch")
    s09_observer_entries = {item["path"]: item for item in parent_binding["parents"]["s09"]["observer_entries"]}
    for layer in (4, 8, 12, 16):
        for surface in ENDPOINTS:
            relative = f"analysis-v09/probes/layer-{layer:02d}/{surface}/probe-state-v09.npz"
            if relative not in s09_observer_entries:
                raise RuntimeError(f"S12 parent binding lacks frozen probe {relative}")
            actual = entry(S09.joinpath(*relative.split("/")), S09)
            if actual != s09_observer_entries[relative]:
                raise RuntimeError(f"S09 frozen observer hash mismatch: {relative}")

    token_inputs = read_jsonl(S11_TOKENS / "token-inputs-v01.jsonl")
    token_rows = read_jsonl(S11_TOKENS / "token-rows-v01.jsonl")
    feature_rows = read_jsonl(S11_FEATURES / "feature-rows-v01.jsonl")
    if not (len(token_inputs) == len(token_rows) == len(feature_rows) == ROWS):
        raise RuntimeError("S11 token or feature row count mismatch")
    for i, (inp, tok, feat) in enumerate(zip(token_inputs, token_rows, feature_rows, strict=True)):
        if inp["row_index"] != i or tok["row_index"] != i or inp["event_id"] != tok["event_id"] or tok["event_id"] != feat["event_id"]:
            raise RuntimeError(f"S11 event row identity mismatch at {i}")
        if inp["input_sha256"] != tok["input_sha256"] or tok["input_sha256"] != feat["input_sha256"]:
            raise RuntimeError(f"S11 input identity mismatch at {i}")
        if hashlib.sha256(inp["input_text"].encode("utf-8")).hexdigest() != inp["input_sha256"]:
            raise RuntimeError(f"S11 rendered input byte hash mismatch at {i}")
        ids = tok["token_ids"]
        token_hash = hashlib.sha256(struct.pack(f"<{len(ids)}I", *ids)).hexdigest()
        if len(ids) != tok["sequence_length"] or token_hash != tok["token_ids_sha256"] or tok["token_ids_sha256"] != feat["token_ids_sha256"]:
            raise RuntimeError(f"S11 token identity mismatch at {i}")
    m = np.memmap(S11_FEATURES / "matrices" / "layer-16-M.f32le", dtype="<f4", mode="r", shape=(ROWS, DIMENSION))
    f = np.memmap(S11_FEATURES / "matrices" / "layer-16-F.f32le", dtype="<f4", mode="r", shape=(ROWS, DIMENSION))
    if m.dtype != np.float32 or f.dtype != np.float32 or not m.flags.c_contiguous or not f.flags.c_contiguous:
        raise RuntimeError("S11 terminal feature matrices have invalid layout")
    plane_meta = contract["parents"]["plane_bank"]
    plane_path = RUN / plane_meta["path"]
    if sha256_file(plane_path)[0] != plane_meta["sha256"]:
        raise RuntimeError("S12 frozen plane bank hash mismatch")
    centers_meta = contract["parents"]["source_centers"]
    centers_path = RUN / centers_meta["path"]
    if sha256_file(centers_path)[0] != centers_meta["sha256"]:
        raise RuntimeError("S12 frozen source centers hash mismatch")
    for key in ("bootstrap_plan", "repeat_quartets"):
        metadata = contract["parents"][key]
        if sha256_file(RUN / metadata["path"])[0] != metadata["sha256"]:
            raise RuntimeError(f"S12 frozen {key} hash mismatch")
    preparation_path = RUN / contract["parents"]["preparation_receipt_path"]
    if sha256_file(preparation_path)[0] != contract["parents"]["preparation_receipt_sha256"]:
        raise RuntimeError("S12 preparation receipt hash mismatch")
    plane_bank = np.memmap(plane_path, dtype="<f8", mode="r", shape=(6, 9, 2, DIMENSION))
    centers = np.memmap(centers_path, dtype="<f8", mode="r", shape=(6, DIMENSION))
    parent_info = {"s11_files_verified": len(s11_files), "s11_result_root_sha256": s11_seal["root_sha256"], "s09_result_root_sha256": s09_seal["root_sha256"], "token_rows": ROWS, "feature_rows": ROWS}
    return token_rows, feature_rows, m, f, {"parent_info": parent_info, "plane_bank": plane_bank, "centers": centers, "model_manifest": model_manifest}


def configure_runtime(contract: dict[str, Any]) -> torch.device:
    runtime = contract["runtime"]
    if sys.version.split()[0] != runtime["python"] or np.__version__ != runtime["numpy"] or torch.__version__ != runtime["torch"] or transformers.__version__ != runtime["transformers"]:
        raise RuntimeError("S12 runtime package version mismatch")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != runtime["device"]:
        raise RuntimeError("contracted single CUDA device is unavailable")
    torch.set_num_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision("highest")
    torch.use_deterministic_algorithms(True)
    torch.cuda.manual_seed_all(0)
    return torch.device("cuda:0")


def tensor_state_identity(model: torch.nn.Module) -> dict[str, Any]:
    digest = hashlib.sha256()
    tensor_count = element_count = byte_count = 0
    for name, tensor in sorted(model.state_dict().items(), key=lambda item: item[0]):
        if not isinstance(tensor, torch.Tensor):
            raise RuntimeError(f"non-tensor model state entry: {name}")
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tensor.dtype).encode("ascii") + b"\0")
        digest.update(canonical_json(list(tensor.shape)) + b"\0")
        cpu = tensor.detach().contiguous().reshape(-1).view(torch.uint8).to(device="cpu").numpy()
        view = memoryview(cpu).cast("B")
        for offset in range(0, len(view), 8 * 1024 * 1024):
            part = view[offset:offset + 8 * 1024 * 1024]
            digest.update(part)
            byte_count += len(part)
        tensor_count += 1
        element_count += tensor.numel()
        del cpu, view
    return {"sha256": digest.hexdigest(), "state_tensor_count": tensor_count, "state_element_count": element_count, "serialized_state_bytes": byte_count}


def load_model(device: torch.device) -> torch.nn.Module:
    from transformers import AutoModel

    model = AutoModel.from_pretrained(str(MODEL_ROOT), local_files_only=True, trust_remote_code=False, dtype=torch.float32)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.to(device)
    config = getattr(model.config, "text_config", model.config)
    if config.hidden_size != DIMENSION or config.num_hidden_layers != 16:
        raise RuntimeError("pinned model dimensions mismatch")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("backbone contains trainable parameters")
    return model


def stock_forward(model: torch.nn.Module, token_ids: list[int], device: torch.device):
    ids = torch.tensor(token_ids, dtype=torch.long, device=device).reshape(1, -1)
    return model(input_ids=ids, output_hidden_states=True, use_cache=False, return_dict=True)


def terminal_views(hidden: torch.Tensor) -> tuple[np.ndarray, np.ndarray]:
    sequence = hidden[0]
    mean = sequence.mean(dim=0).detach().contiguous().cpu().numpy().astype("<f4", copy=False)
    final = sequence[-1].detach().contiguous().cpu().numpy().astype("<f4", copy=False)
    return np.ascontiguousarray(mean), np.ascontiguousarray(final)


def suffix_forward(model: torch.nn.Module, source_hidden: torch.Tensor, first_zero_based_layer: int) -> torch.Tensor:
    from transformers.models.lfm2 import modeling_lfm2

    batch, sequence_length, dimension = source_hidden.shape
    if dimension != DIMENSION or first_zero_based_layer < 1 or first_zero_based_layer > 12:
        raise RuntimeError("invalid suffix input")
    config = getattr(model.config, "text_config", model.config)
    positions = torch.arange(sequence_length, dtype=torch.long, device=source_hidden.device).unsqueeze(0)
    mask_kwargs = {
        "config": config,
        "inputs_embeds": source_hidden,
        "attention_mask": None,
        "past_key_values": None,
        "position_ids": positions,
    }
    masks = {
        "full_attention": modeling_lfm2.create_causal_mask(**mask_kwargs),
        "conv": modeling_lfm2.create_recurrent_attention_mask(**mask_kwargs),
    }
    rotary = model.rotary_emb(source_hidden, position_ids=positions)
    hidden = source_hidden
    for layer_index in range(first_zero_based_layer, 16):
        hidden = model.layers[layer_index](
            hidden,
            attention_mask=masks[config.layer_types[layer_index]],
            position_embeddings=rotary,
            position_ids=positions,
            past_key_values=None,
        )
    return model.embedding_norm(hidden)


def observer_load(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        required = {"classes", "weights", "bias", "scaler_mean", "scaler_scale"}
        if set(data.files) != required:
            raise RuntimeError(f"unexpected frozen probe fields: {path}")
        result = {key: np.asarray(data[key]).copy() for key in required}
    if not np.array_equal(result["classes"], np.asarray([0, 1, 2], dtype=np.int64)):
        raise RuntimeError(f"frozen probe class order mismatch: {path}")
    return result


def score_batch(hidden: torch.Tensor, observer: dict[str, np.ndarray], surface: str) -> tuple[np.ndarray, np.ndarray]:
    raw = hidden.mean(dim=1) if surface == "M" else hidden[:, -1, :]
    mean = torch.as_tensor(observer["scaler_mean"], dtype=torch.float32, device=hidden.device)
    scale = torch.as_tensor(observer["scaler_scale"], dtype=torch.float32, device=hidden.device)
    weights = torch.as_tensor(observer["weights"], dtype=torch.float32, device=hidden.device)
    bias = torch.as_tensor(observer["bias"], dtype=torch.float32, device=hidden.device)
    standardized = raw.clone()
    standardized.sub_(mean).div_(scale)
    logits = functional.linear(standardized, weights, bias)
    probabilities = torch.softmax(logits, dim=1)
    return (
        logits.detach().contiguous().cpu().numpy().astype("<f4", copy=True),
        probabilities.detach().contiguous().cpu().numpy().astype("<f4", copy=True),
    )


def score_sealed_matrix(raw_matrix: np.memmap, observer: dict[str, np.ndarray], device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    from linear_core import standardized_raw_tensor

    all_logits = np.empty((ROWS, 3), dtype="<f4")
    all_probabilities = np.empty((ROWS, 3), dtype="<f4")
    weights = torch.as_tensor(observer["weights"], dtype=torch.float32, device=device)
    bias = torch.as_tensor(observer["bias"], dtype=torch.float32, device=device)
    for start in range(0, ROWS, 1024):
        stop = min(start + 1024, ROWS)
        chunk = np.ascontiguousarray(raw_matrix[start:stop], dtype=np.float32)
        standardized = standardized_raw_tensor(chunk, observer["scaler_mean"], observer["scaler_scale"], device)
        logits = functional.linear(standardized, weights, bias)
        probs = torch.softmax(logits, dim=1)
        all_logits[start:stop] = logits.cpu().numpy().astype("<f4", copy=False)
        all_probabilities[start:stop] = probs.cpu().numpy().astype("<f4", copy=False)
    return all_logits, all_probabilities


def verify_source_geometry(plane_bank: np.ndarray, centers: np.ndarray, source_observers: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    checks = []
    for slot, (layer, surface) in enumerate(SITES):
        target = np.asarray(plane_bank[slot, 0], dtype=np.float64)
        observer = source_observers[f"L{layer:02d}_{surface}"]
        normals = pair_normals(observer["weights"], observer["scaler_scale"])
        normal_residual = float(np.linalg.norm(normals - (normals @ target.T) @ target) / max(np.linalg.norm(normals), np.finfo(np.float64).tiny))
        if normal_residual > 1e-10:
            raise RuntimeError(f"source observer pair normals are outside sealed S12 plane at slot {slot}: {normal_residual}")
        center_error = float(np.max(np.abs(np.asarray(observer["scaler_mean"], dtype=np.float64) - np.asarray(centers[slot], dtype=np.float64))))
        if center_error != 0.0:
            raise RuntimeError(f"source observer center differs from sealed S12 center at slot {slot}")
        if target.shape != (2, DIMENSION) or float(np.max(np.abs(target @ target.T - np.eye(2)))) > 1e-10:
            raise RuntimeError(f"target plane failed orthonormality at slot {slot}")
        target_projector = target.T @ target
        symmetry = float(np.linalg.norm(target_projector - target_projector.T, ord="fro"))
        idempotence = float(np.linalg.norm(target_projector @ target_projector - target_projector, ord="fro"))
        if symmetry > 1e-10 or idempotence > 1e-9:
            raise RuntimeError(f"target projector invariant failed at slot {slot}")
        angles = []
        for control in range(1, 9):
            random = np.asarray(plane_bank[slot, control], dtype=np.float64)
            label = f"FAS-S12-V01-RANDOM-PLANE|layer={layer}|surface={surface}|control={control}"
            seed, _ = seed_from_label(label)
            if random.tobytes() != random_plane(seed).tobytes():
                raise RuntimeError(f"random plane seed reconstruction mismatch at slot {slot}, control {control}")
            if float(np.max(np.abs(random @ random.T - np.eye(2)))) > 1e-10:
                raise RuntimeError(f"random plane failed orthonormality at slot {slot}, control {control}")
            cosines = np.linalg.svd(target @ random.T, compute_uv=False)
            angles.append(np.degrees(np.arccos(np.clip(cosines, 0.0, 1.0))).tolist())
        checks.append({"slot": slot, "layer": layer, "surface": surface, "rank": 2, "source_pair_normal_relative_residual": normal_residual, "center_max_abs_error": center_error, "symmetry_frobenius": symmetry, "idempotence_frobenius": idempotence, "random_plane_angles_degrees": angles})
    return {"complete": True, "sites": checks}


def run_base_qualification(model: torch.nn.Module, token_rows: list[dict[str, Any]], feature_rows: list[dict[str, Any]], cache_m: np.memmap, cache_f: np.memmap, device: torch.device) -> dict[str, Any]:
    base_dir = RUN / "base-parity-v02"
    base_dir.mkdir(parents=True, exist_ok=True)
    seal_path = base_dir / "base-parity-seal-v02.json"
    if seal_path.exists():
        verify_local_tree(base_dir, seal_path)
        receipt = read_json(base_dir / "base-parity-receipt-v02.json")
        if receipt.get("complete") is not True or receipt.get("rows") != ROWS or receipt.get("byte_identical") is not True:
            raise RuntimeError("sealed S12 base parity receipt is incomplete")
        return receipt
    row_path = base_dir / "base-parity-rows-v02.jsonl"
    existing_rows = read_jsonl(row_path) if row_path.exists() else []
    if len(existing_rows) > ROWS:
        raise RuntimeError("S12 base parity journal has too many rows")
    for row_index, record in enumerate(existing_rows):
        feature = feature_rows[row_index]
        token = token_rows[row_index]
        if (
            record.get("row_index") != row_index
            or record.get("event_id") != token["event_id"]
            or record.get("input_sha256") != token["input_sha256"]
            or record.get("token_ids_sha256") != token["token_ids_sha256"]
            or record.get("sequence_length") != token["sequence_length"]
            or record.get("L16_M_sha256") != feature["features_sha256"]["L16_M"]
            or record.get("L16_F_sha256") != feature["features_sha256"]["L16_F"]
            or record.get("S11_terminal_byte_parity") is not True
            or record.get("unmodified_suffix_byte_parity") != {"4": 0.0, "8": 0.0, "12": 0.0}
        ):
            raise RuntimeError(f"S12 base parity journal identity mismatch at row {row_index}")
    matched_suffixes = len(existing_rows) * 3
    started = time.perf_counter()
    open_mode = "ab" if row_path.exists() else "wb"
    with torch.inference_mode(), row_path.open(open_mode) as stream:
        for row_index in range(len(existing_rows), ROWS):
            row = token_rows[row_index]
            output = stock_forward(model, row["token_ids"], device)
            if len(output.hidden_states) != 17:
                raise RuntimeError(f"hidden-state count mismatch at row {row_index}")
            mean16, final16 = terminal_views(output.hidden_states[16])
            if mean16.tobytes() != np.asarray(cache_m[row_index], dtype="<f4").tobytes() or final16.tobytes() != np.asarray(cache_f[row_index], dtype="<f4").tobytes():
                raise RuntimeError(f"S11 terminal feature parity failure at row {row_index}")
            hashes = {
                "L16_M": hashlib.sha256(memoryview(mean16).cast("B")).hexdigest(),
                "L16_F": hashlib.sha256(memoryview(final16).cast("B")).hexdigest(),
            }
            if hashes["L16_M"] != feature_rows[row_index]["features_sha256"]["L16_M"] or hashes["L16_F"] != feature_rows[row_index]["features_sha256"]["L16_F"]:
                raise RuntimeError(f"S11 row feature identity mismatch at row {row_index}")
            final_reference = output.hidden_states[16]
            suffix_errors = {}
            for layer in (4, 8, 12):
                reproduced = suffix_forward(model, output.hidden_states[layer], layer)
                reproduced_mean, reproduced_final = terminal_views(reproduced)
                ref_mean, ref_final = terminal_views(final_reference)
                if reproduced_mean.tobytes() != ref_mean.tobytes() or reproduced_final.tobytes() != ref_final.tobytes():
                    raise RuntimeError(f"unmodified suffix parity failure at row {row_index}, layer {layer}")
                suffix_errors[str(layer)] = 0.0
                matched_suffixes += 1
            record = {
                "row_index": row_index,
                "event_id": row["event_id"],
                "input_sha256": row["input_sha256"],
                "token_ids_sha256": row["token_ids_sha256"],
                "sequence_length": row["sequence_length"],
                "L16_M_sha256": hashes["L16_M"],
                "L16_F_sha256": hashes["L16_F"],
                "S11_terminal_byte_parity": True,
                "unmodified_suffix_byte_parity": suffix_errors,
            }
            payload = canonical_json(record) + b"\n"
            stream.write(payload)
            if (row_index + 1) % 1024 == 0:
                print(f"S12 base/parity {row_index + 1}/{ROWS} rows; {time.perf_counter()-started:.1f}s", flush=True)
            del output, final_reference
        stream.flush()
        os.fsync(stream.fileno())
    receipt = {
        "receipt_id": "FAS_S12_BASE_AND_SUFFIX_PARITY_V02",
        "complete": True,
        "rows": ROWS,
        "terminal_matrix_parity_rows": ROWS,
        "suffix_layer_parity_cells": matched_suffixes,
        "byte_identical": True,
        "row_manifest": {"path": row_path.name, "sha256": sha256_file(row_path)[0], "bytes": row_path.stat().st_size},
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(base_dir / "base-parity-receipt-v02.json", receipt)
    entries = [entry(path, base_dir) for path in base_dir.iterdir() if path.is_file() and path.name != "base-parity-seal-v02.json"]
    entries.sort(key=lambda item: item["path"])
    write_json(base_dir / "base-parity-seal-v02.json", {"seal_id": "FAS_S12_BASE_PARITY_SEAL_V02", "entries": entries, "root_sha256": tree_root(entries)})
    return receipt


def load_observers() -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, np.ndarray]]]:
    source: dict[str, dict[str, np.ndarray]] = {}
    terminal: dict[str, dict[str, np.ndarray]] = {}
    for layer, surface in SITES:
        source[f"L{layer:02d}_{surface}"] = observer_load(S09 / "analysis-v09" / "probes" / f"layer-{layer:02d}" / surface / "probe-state-v09.npz")
    for surface in ENDPOINTS:
        terminal[surface] = observer_load(S09 / "analysis-v09" / "probes" / "layer-16" / surface / "probe-state-v09.npz")
    return source, terminal


def run_baseline_replay(cache_m: np.memmap, cache_f: np.memmap, terminal: dict[str, dict[str, np.ndarray]], device: torch.device) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    baseline = RUN / "baseline-v02"
    seal_path = baseline / "baseline-seal-v02.json"
    if seal_path.exists():
        seal = verify_local_tree(baseline, seal_path)
        receipt = read_json(baseline / "baseline-replay-receipt-v02.json")
        if receipt.get("complete") is not True or receipt.get("rows") != ROWS:
            raise RuntimeError("sealed S12 baseline receipt is incomplete")
        logits = np.fromfile(baseline / "baseline-probe-logits-v02.f32le", dtype="<f4").reshape(ROWS, 2, 3)
        probabilities = np.fromfile(baseline / "baseline-probe-probabilities-v02.f32le", dtype="<f4").reshape(ROWS, 2, 3)
        predictions = np.fromfile(baseline / "baseline-predictions-v02.i64le", dtype="<i8").reshape(ROWS, 2)
        if not np.isfinite(logits).all() or not np.isfinite(probabilities).all():
            raise RuntimeError("sealed S12 baseline contains non-finite values")
        for index, surface in enumerate(ENDPOINTS):
            reference = np.load(S11 / "transport-v01" / "predictions" / f"{surface}-src-16-tgt-16.npy", allow_pickle=False)
            if not np.array_equal(predictions[:, index], reference):
                raise RuntimeError(f"sealed S12 baseline predictions no longer reproduce S11 for {surface}")
        if tree_root(seal["entries"]) != seal["root_sha256"]:
            raise RuntimeError("sealed S12 baseline root mismatch")
        return logits, probabilities, receipt
    if baseline.exists() and any(baseline.iterdir()):
        raise RuntimeError("incomplete S12 baseline exists without a seal; preserve it and use a versioned repair")

    results = np.empty((ROWS, 2, 3), dtype="<f4")
    probabilities = np.empty((ROWS, 2, 3), dtype="<f4")
    reference = {}
    for surface, raw in (("M", cache_m), ("F", cache_f)):
        logits, probs = score_sealed_matrix(raw, terminal[surface], device)
        pred = np.asarray(terminal[surface]["classes"][probs.argmax(axis=1)], dtype="<i8")
        ref_path = S11 / "transport-v01" / "predictions" / f"{surface}-src-16-tgt-16.npy"
        reference_pred = np.load(ref_path, allow_pickle=False)
        if reference_pred.shape != (ROWS,) or not np.array_equal(pred, reference_pred):
            raise RuntimeError(f"S11 native diagonal class prediction parity failed for {surface}")
        slot = 0 if surface == "M" else 1
        results[:, slot, :] = logits
        probabilities[:, slot, :] = probs
        reference[surface] = {
            "prediction_file_sha256": sha256_file(ref_path)[0],
            "prediction_id_sha256": hashlib.sha256(pred.tobytes(order="C")).hexdigest(),
            "predictions_byte_equal": True,
            "probability_reference_available_in_s11": False,
        }
    baseline.mkdir(parents=True)
    logits_path = baseline / "baseline-probe-logits-v02.f32le"
    probabilities_path = baseline / "baseline-probe-probabilities-v02.f32le"
    predictions_path = baseline / "baseline-predictions-v02.i64le"
    results.tofile(logits_path)
    probabilities.tofile(probabilities_path)
    pred_ids = np.stack([terminal[s]["classes"][probabilities[:, j].argmax(axis=1)] for j, s in enumerate(ENDPOINTS)], axis=1).astype("<i8")
    pred_ids.tofile(predictions_path)
    receipt = {
        "receipt_id": "FAS_S12_BASELINE_PROBE_REPLAY_V02",
        "complete": True,
        "rows": ROWS,
        "class_order": [0, 1, 2],
        "parents": reference,
        "probabilities_derived_from": "byte-verified S11 layer-16 feature matrices plus unchanged S09 layer-16 probes",
        "outputs": [
            {"path": logits_path.name, "shape": [ROWS, 2, 3], "dtype": "<f4", "sha256": sha256_file(logits_path)[0]},
            {"path": probabilities_path.name, "shape": [ROWS, 2, 3], "dtype": "<f4", "sha256": sha256_file(probabilities_path)[0]},
            {"path": predictions_path.name, "shape": [ROWS, 2], "dtype": "<i8", "sha256": sha256_file(predictions_path)[0]},
        ],
    }
    write_json(baseline / "baseline-replay-receipt-v02.json", receipt)
    entries = [entry(path, baseline) for path in baseline.iterdir() if path.is_file() and path.name != "baseline-seal-v02.json"]
    entries.sort(key=lambda item: item["path"])
    write_json(baseline / "baseline-seal-v02.json", {"seal_id": "FAS_S12_BASELINE_SEAL_V02", "entries": entries, "root_sha256": tree_root(entries)})
    return results, probabilities, receipt


def fill_strength_zero(logits: np.memmap, probabilities: np.memmap, checks: np.memmap, row_index: int, baseline_logits: np.ndarray, baseline_probs: np.ndarray) -> None:
    for site_index in range(6):
        for arm in range(ARMS):
            logits[row_index, site_index, 0, arm] = baseline_logits[row_index]
            probabilities[row_index, site_index, 0, arm] = baseline_probs[row_index]
            checks[row_index, site_index, 0, arm] = 0.0


def intervention_deltas(basis_bank: np.ndarray, center: np.ndarray, summary: np.ndarray, strength: float) -> tuple[list[np.ndarray], list[dict[str, float]]]:
    q = np.asarray(summary, dtype=np.float64) - np.asarray(center, dtype=np.float64)
    target_projection = projected(basis_bank[0], q)
    target_delta = strength * target_projection
    deltas = [target_delta]
    for control in range(1, 9):
        deltas.append(matched_random_delta(target_delta, basis_bank[control], q))
    requested_norm = float(np.linalg.norm(target_delta))
    checks = []
    for arm, delta in enumerate(deltas):
        if requested_norm == 0.0:
            checks.append({"requested_norm": 0.0, "actual_expected_norm": 0.0, "norm_relative_error": 0.0})
            continue
        f32 = np.asarray(delta, dtype=np.float32)
        actual_norm = float(np.linalg.norm(f32.astype(np.float64)))
        relative_error = abs(actual_norm - requested_norm) / requested_norm
        if relative_error > 1e-5 and abs(actual_norm - requested_norm) > 1e-7:
            raise RuntimeError(f"FP32 displacement norm match failed for arm {arm}: {relative_error}")
        checks.append({"requested_norm": requested_norm, "actual_expected_norm": actual_norm, "norm_relative_error": relative_error})
    return deltas, checks


def run_site_branches(
    model: torch.nn.Module,
    source_hidden: torch.Tensor,
    site_index: int,
    layer: int,
    surface: str,
    plane_bank: np.ndarray,
    centers: np.ndarray,
    terminal: dict[str, dict[str, np.ndarray]],
    logits_out: np.memmap,
    probabilities_out: np.memmap,
    checks_out: np.memmap,
    row_index: int,
) -> dict[str, Any]:
    summary_tensor = source_hidden[0].mean(dim=0) if surface == "M" else source_hidden[0, -1]
    summary = summary_tensor.detach().cpu().numpy().astype(np.float64)
    deltas_all: list[np.ndarray] = []
    metadata: list[tuple[int, int, float, list[float]]] = []
    max_norm_error = 0.0
    for strength_index, strength in enumerate(STRENGTHS[1:], start=1):
        deltas, norm_records = intervention_deltas(plane_bank[site_index], centers[site_index], summary, strength)
        for arm, delta in enumerate(deltas):
            deltas_all.append(delta)
            metadata.append((strength_index, arm, strength, [norm_records[arm]["requested_norm"], norm_records[arm]["actual_expected_norm"], norm_records[arm]["norm_relative_error"]]))
            max_norm_error = max(max_norm_error, norm_records[arm]["norm_relative_error"])

    all_actual_checks: list[dict[str, float]] = []
    for start in range(0, len(deltas_all), BRANCH_MICROBATCH):
        stop = min(start + BRANCH_MICROBATCH, len(deltas_all))
        deltas = deltas_all[start:stop]
        branch_count = len(deltas)
        delta_tensor = torch.as_tensor(np.asarray(deltas, dtype=np.float32), dtype=torch.float32, device=source_hidden.device)
        base = source_hidden[0]
        branches = base.unsqueeze(0).expand(branch_count, -1, -1).clone()
        if surface == "M":
            branches.sub_(delta_tensor[:, None, :])
        else:
            branches[:, -1, :].sub_(delta_tensor)

        edited_summary = branches.mean(dim=1) if surface == "M" else branches[:, -1, :]
        edited_cpu = edited_summary.detach().cpu().numpy().astype(np.float64)
        q0 = summary - np.asarray(centers[site_index], dtype=np.float64)
        base_tensor_norm = float(torch.linalg.vector_norm(base).item())
        edited_tensor_norm = torch.linalg.vector_norm(branches, dim=(1, 2)).detach().cpu().numpy().astype(np.float64)
        actual_tensor_delta = torch.linalg.vector_norm(branches - base.unsqueeze(0), dim=(1, 2)).detach().cpu().numpy().astype(np.float64)
        actual_summary_delta = torch.linalg.vector_norm(edited_summary - summary_tensor.unsqueeze(0), dim=1).detach().cpu().numpy().astype(np.float64)
        suffix = suffix_forward(model, branches, layer)
        logits_by_endpoint: dict[str, np.ndarray] = {}
        probs_by_endpoint: dict[str, np.ndarray] = {}
        for endpoint in ENDPOINTS:
            logits_by_endpoint[endpoint], probs_by_endpoint[endpoint] = score_batch(suffix, terminal[endpoint], endpoint)

        for local_index, global_variant_index in enumerate(range(start, stop)):
            strength_index, arm, strength, norm_meta = metadata[global_variant_index]
            qprime = edited_cpu[local_index] - centers[site_index]
            selected_basis = np.asarray(plane_bank[site_index, arm], dtype=np.float64)
            projected_before = projected(selected_basis, q0)
            projected_after = projected(selected_basis, qprime)
            applied_summary_displacement = edited_cpu[local_index] - summary
            requested_delta = np.asarray(deltas_all[global_variant_index], dtype=np.float64)
            if arm == 0:
                residual = float(np.linalg.norm(projected_after - (1.0 - strength) * projected_before))
                residual_limit = 5e-4 * max(1.0, float(np.linalg.norm(projected_before)))
                relation = "target_plane_remaining_component"
            else:
                off_plane = float(np.linalg.norm(requested_delta - projected(selected_basis, requested_delta)))
                displacement = float(np.linalg.norm(applied_summary_displacement + requested_delta))
                residual = max(off_plane, displacement)
                residual_limit = 5e-4 * max(1.0, float(np.linalg.norm(requested_delta)))
                relation = "control_plane_membership_and_applied_displacement"
            if residual > residual_limit:
                raise RuntimeError(f"plane-specific manipulation check failed row={row_index} layer={layer} surface={surface} strength={strength} arm={arm} relation={relation} residual={residual}")
            request_norm, rounded_norm, relative_error = norm_meta
            actual_snorm = float(actual_summary_delta[local_index])
            norm_error = abs(actual_snorm - request_norm)
            if request_norm > 0 and norm_error > max(1e-7, 1e-5 * request_norm):
                raise RuntimeError(f"applied summary displacement norm mismatch row={row_index} layer={layer} surface={surface} strength={strength} arm={arm}")
            tensor_expected = request_norm * (float(source_hidden.shape[1]) ** 0.5 if surface == "M" else 1.0)
            all_actual_checks.append({
                "requested_summary_delta_norm": request_norm,
                "applied_summary_delta_norm": actual_snorm,
                "expected_tensor_delta_norm": tensor_expected,
                "applied_tensor_delta_norm": float(actual_tensor_delta[local_index]),
                "base_tensor_norm": base_tensor_norm,
                "edited_tensor_norm": float(edited_tensor_norm[local_index]),
                "projected_residual_norm": residual,
                "projected_residual_limit": residual_limit,
                "plane_relation": relation,
                "rounding_relative_error": relative_error,
                "plane_component_norm_before": float(np.linalg.norm(projected_before)),
                "plane_component_norm_after": float(np.linalg.norm(projected_after)),
            })
            check_values = np.asarray([
                request_norm,
                actual_snorm,
                tensor_expected,
                float(actual_tensor_delta[local_index]),
                base_tensor_norm,
                float(edited_tensor_norm[local_index]),
                residual,
                residual_limit,
                relative_error,
                float(np.linalg.norm(projected_after)),
            ], dtype="<f4")
            checks_out[row_index, site_index, strength_index, arm] = check_values
            for endpoint_index, endpoint in enumerate(ENDPOINTS):
                logits_out[row_index, site_index, strength_index, arm, endpoint_index] = logits_by_endpoint[endpoint][local_index]
                probabilities_out[row_index, site_index, strength_index, arm, endpoint_index] = probs_by_endpoint[endpoint][local_index]
        del branches, suffix, delta_tensor, edited_summary, edited_cpu, actual_tensor_delta, edited_tensor_norm, actual_summary_delta
    return {"max_rounding_relative_error": max_norm_error, "max_projected_residual": max(item["projected_residual_norm"] for item in all_actual_checks), "max_tensor_norm_abs_error": max(abs(item["applied_tensor_delta_norm"] - item["expected_tensor_delta_norm"]) for item in all_actual_checks), "branches": len(all_actual_checks)}


def run_interventions(
    model: torch.nn.Module,
    token_rows: list[dict[str, Any]],
    cache_m: np.memmap,
    cache_f: np.memmap,
    baseline_logits: np.ndarray,
    baseline_probabilities: np.ndarray,
    plane_bank: np.ndarray,
    centers: np.ndarray,
    terminal: dict[str, dict[str, np.ndarray]],
    device: torch.device,
) -> dict[str, Any]:
    raw_dir = RUN / "raw-v02"
    shape = (ROWS, 6, 4, ARMS, 2, 3)
    logits_path = raw_dir / "intervention-probe-logits-v02.f32le"
    probs_path = raw_dir / "intervention-probe-probabilities-v02.f32le"
    checks_path = raw_dir / "intervention-checks-v02.f32le"
    progress_path = raw_dir / "completed-rows-v02.jsonl"
    if raw_dir.exists() and (raw_dir / "raw-seal-v02.json").exists():
        sealed = read_json(raw_dir / "raw-seal-v02.json")
        actual = [entry(raw_dir.joinpath(*item["path"].split("/")), raw_dir) for item in sealed["entries"]]
        if tree_root(actual) != sealed["root_sha256"] or actual != sorted(sealed["entries"], key=lambda item: item["path"]):
            raise RuntimeError("existing S12 raw output seal is corrupt")
        return read_json(raw_dir / "intervention-receipt-v02.json")
    raw_dir.mkdir(parents=True, exist_ok=True)
    expected_shapes = {
        logits_path: (shape, ROWS * 6 * 4 * ARMS * 2 * 3 * 4),
        probs_path: (shape, ROWS * 6 * 4 * ARMS * 2 * 3 * 4),
        checks_path: ((ROWS, 6, 4, ARMS, 10), ROWS * 6 * 4 * ARMS * 10 * 4),
    }
    for path, (_, expected_bytes) in expected_shapes.items():
        if path.exists() and path.stat().st_size != expected_bytes:
            raise RuntimeError(f"partial S12 output has an invalid byte length: {path}")
    existing_paths = [path.exists() for path in expected_shapes]
    if any(existing_paths) and not all(existing_paths):
        if progress_path.exists() and progress_path.stat().st_size:
            raise RuntimeError("S12 raw output files are incomplete after committed progress")
        # No row has been committed. Reinitialize the incomplete output set in place.
        for path in expected_shapes:
            if path.exists():
                path.unlink()
        existing_paths = [False] * len(existing_paths)
    if all(existing_paths):
        logits = np.memmap(logits_path, dtype="<f4", mode="r+", shape=shape)
        probabilities = np.memmap(probs_path, dtype="<f4", mode="r+", shape=shape)
        checks = np.memmap(checks_path, dtype="<f4", mode="r+", shape=(ROWS, 6, 4, ARMS, 10))
    else:
        logits = np.memmap(logits_path, dtype="<f4", mode="w+", shape=shape)
        probabilities = np.memmap(probs_path, dtype="<f4", mode="w+", shape=shape)
        checks = np.memmap(checks_path, dtype="<f4", mode="w+", shape=(ROWS, 6, 4, ARMS, 10))
        logits[:] = np.nan
        probabilities[:] = np.nan
        checks[:] = np.nan
        logits.flush()
        probabilities.flush()
        checks.flush()

    progress_rows = read_jsonl(progress_path) if progress_path.exists() else []
    if any(item.get("row_index") != i for i, item in enumerate(progress_rows)):
        raise RuntimeError("S12 completed-row journal is not a contiguous prefix")
    for item in progress_rows:
        i = int(item["row_index"])
        current = {
            "logits_sha256": hashlib.sha256(np.asarray(logits[i], dtype="<f4").tobytes(order="C")).hexdigest(),
            "probabilities_sha256": hashlib.sha256(np.asarray(probabilities[i], dtype="<f4").tobytes(order="C")).hexdigest(),
            "checks_sha256": hashlib.sha256(np.asarray(checks[i], dtype="<f4").tobytes(order="C")).hexdigest(),
        }
        if any(current[key] != item[key] for key in current):
            raise RuntimeError(f"S12 completed-row journal identity mismatch at row {i}")
    started = time.perf_counter()
    pending: list[dict[str, Any]] = []
    progress_stream = progress_path.open("ab")
    try:
        for row_index in range(len(progress_rows), ROWS):
            row = token_rows[row_index]
            output = stock_forward(model, row["token_ids"], device)
            mean16, final16 = terminal_views(output.hidden_states[16])
            if mean16.tobytes() != np.asarray(cache_m[row_index], dtype="<f4").tobytes() or final16.tobytes() != np.asarray(cache_f[row_index], dtype="<f4").tobytes():
                raise RuntimeError(f"base feature changed between qualification and intervention at row {row_index}")
            fill_strength_zero(logits, probabilities, checks, row_index, baseline_logits, baseline_probabilities)
            for site_index, (layer, surface) in enumerate(SITES):
                result = run_site_branches(
                    model,
                    output.hidden_states[layer],
                    site_index,
                    layer,
                    surface,
                    plane_bank,
                    centers,
                    terminal,
                    logits,
                    probabilities,
                    checks,
                    row_index,
                )
            del output
            pending.append({
                "row_index": row_index,
                "event_id": row["event_id"],
                "logits_sha256": hashlib.sha256(np.asarray(logits[row_index], dtype="<f4").tobytes(order="C")).hexdigest(),
                "probabilities_sha256": hashlib.sha256(np.asarray(probabilities[row_index], dtype="<f4").tobytes(order="C")).hexdigest(),
                "checks_sha256": hashlib.sha256(np.asarray(checks[row_index], dtype="<f4").tobytes(order="C")).hexdigest(),
            })
            if len(pending) >= 16 or row_index + 1 == ROWS:
                logits.flush()
                probabilities.flush()
                checks.flush()
                for item in pending:
                    progress_stream.write(canonical_json(item) + b"\n")
                progress_stream.flush()
                os.fsync(progress_stream.fileno())
                pending.clear()
            if (row_index + 1) % 64 == 0:
                print(f"S12 interventions {row_index + 1}/{ROWS} rows; {time.perf_counter()-started:.1f}s", flush=True)
    finally:
        progress_stream.close()
    logits.flush()
    probabilities.flush()
    checks.flush()
    # Recompute global manipulation maxima from the complete matrices so a resumed
    # run reports the entire population, not only the rows processed this session.
    max_projected_residual = 0.0
    max_projected_limit_excess = 0.0
    max_norm_relative_error = 0.0
    max_summary_norm_error = 0.0
    max_tensor_norm_error = 0.0
    for start in range(0, ROWS, 256):
        stop = min(start + 256, ROWS)
        block = np.asarray(checks[start:stop], dtype=np.float64)
        if not np.isfinite(block).all():
            raise RuntimeError(f"non-finite manipulation record in rows {start}:{stop}")
        max_projected_residual = max(max_projected_residual, float(block[..., 6].max()))
        max_projected_limit_excess = max(max_projected_limit_excess, float((block[..., 6] - block[..., 7]).max()))
        max_norm_relative_error = max(max_norm_relative_error, float(block[..., 8].max()))
        max_summary_norm_error = max(max_summary_norm_error, float(np.abs(block[..., 0] - block[..., 1]).max()))
        max_tensor_norm_error = max(max_tensor_norm_error, float(np.abs(block[..., 2] - block[..., 3]).max()))
    if max_projected_limit_excess > 1e-7 or max_norm_relative_error > 1e-5:
        raise RuntimeError("global S12 manipulation check failed after row completion")
    del logits, probabilities, checks

    repeat_index = read_json(S12_INPUTS / "repeat-quartets-v01.json")
    repeat_rows = repeat_index["selected_row_indices_sorted"]
    repeat_logits = np.memmap(logits_path, dtype="<f4", mode="r", shape=shape)
    repeat_probabilities = np.memmap(probs_path, dtype="<f4", mode="r", shape=shape)
    repeat_checks = np.memmap(checks_path, dtype="<f4", mode="r", shape=(ROWS, 6, 4, ARMS, 10))
    repeat_started = time.perf_counter()
    repeat_records = []
    for row_index in repeat_rows:
        row = token_rows[row_index]
        output = stock_forward(model, row["token_ids"], device)
        for site_index, (layer, surface) in enumerate(SITES):
            # Repeat only the sealed nonzero interventions; the repeated row's source state is recomputed.
            rerun = run_single_repeat_site(model, output.hidden_states[layer], site_index, layer, surface, plane_bank, centers, terminal, device)
            for strength_index in (1, 2, 3):
                for arm in range(ARMS):
                    if rerun["logits"][strength_index, arm].tobytes() != repeat_logits[row_index, site_index, strength_index, arm].tobytes():
                        raise RuntimeError(f"deterministic repeat logit mismatch row={row_index} site={site_index} strength={strength_index} arm={arm}")
                    if rerun["probabilities"][strength_index, arm].tobytes() != repeat_probabilities[row_index, site_index, strength_index, arm].tobytes():
                        raise RuntimeError(f"deterministic repeat probability mismatch row={row_index} site={site_index} strength={strength_index} arm={arm}")
                    if rerun["checks"][strength_index, arm].tobytes() != repeat_checks[row_index, site_index, strength_index, arm].tobytes():
                        raise RuntimeError(f"deterministic repeat check mismatch row={row_index} site={site_index} strength={strength_index} arm={arm}")
            repeat_records.append({"row_index": row_index, "event_id": row["event_id"], "site_index": site_index, "all_nonzero_branches_byte_equal": True})
        if len(repeat_records) % 24 == 0:
            print(f"S12 repeat checks {len(repeat_records)}/720 site-row cells", flush=True)
        del output
    del repeat_logits, repeat_probabilities, repeat_checks

    if any(not np.isfinite(np.memmap(path, dtype="<f4", mode="r", shape=shape if "checks" not in path.name else (ROWS, 6, 4, ARMS, 10))).all() for path in (logits_path, probs_path, checks_path)):
        raise RuntimeError("non-finite S12 raw output")
    model_after = tensor_state_identity(model)
    if model_after["sha256"] != EXPECTED_STATE:
        raise RuntimeError("LFM parameter identity changed during S12")

    report = {
        "receipt_id": "FAS_S12_RAW_INTERVENTION_RECEIPT_V02",
        "complete": True,
        "rows": ROWS,
        "sites": [{"index": i, "layer": layer, "surface": surface} for i, (layer, surface) in enumerate(SITES)],
        "strengths": list(STRENGTHS),
        "arms": ["target"] + [f"random_{i}" for i in range(1, 9)],
        "terminal_endpoints": list(ENDPOINTS),
        "logits_shape": list(shape),
        "probabilities_shape": list(shape),
        "checks_shape": [ROWS, 6, 4, ARMS, 10],
        "outputs": [
            {"path": logits_path.name, "bytes": sha256_file(logits_path)[1], "sha256": sha256_file(logits_path)[0], "dtype": "<f4"},
            {"path": probs_path.name, "bytes": sha256_file(probs_path)[1], "sha256": sha256_file(probs_path)[0], "dtype": "<f4"},
            {"path": checks_path.name, "bytes": sha256_file(checks_path)[1], "sha256": sha256_file(checks_path)[0], "dtype": "<f4"},
        ],
        "manipulation_summary": {
            "max_projected_residual_norm": max_projected_residual,
            "max_projected_residual_limit_excess": max_projected_limit_excess,
            "plane_relation_residual_tolerance": "target: norm(P_target q'-(1-lambda)P_target q) <= 5e-4*max(1,norm(P_target q)); control: max(norm(delta-P_control delta), norm((q'-q)+delta)) <= 5e-4*max(1,norm(delta))",
            "max_fp32_requested_vs_applied_relative_norm_error": max_norm_relative_error,
            "max_summary_norm_abs_error": max_summary_norm_error,
            "max_expected_vs_applied_tensor_norm_abs_error": max_tensor_norm_error,
            "all_plane_specific_manipulation_checks_passed": True,
            "all_norm_match_checks_passed": True,
        },
        "repeat": {
            "quartets": 30,
            "rows": len(repeat_rows),
            "site_row_cells": len(repeat_records),
            "nonzero_branches_per_site_row": 27,
            "all_logits_probabilities_and_checks_byte_equal": True,
            "receipt_rows": repeat_records,
            "elapsed_seconds": round(time.perf_counter() - repeat_started, 3),
        },
        "backbone_after": model_after,
        "parameter_delta": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(raw_dir / "intervention-receipt-v02.json", report)
    entries = [entry(path, raw_dir) for path in raw_dir.iterdir() if path.is_file() and path.name != "raw-seal-v02.json"]
    entries.sort(key=lambda item: item["path"])
    write_json(raw_dir / "raw-seal-v02.json", {"seal_id": "FAS_S12_RAW_OUTPUT_SEAL_V02", "entries": entries, "root_sha256": tree_root(entries)})
    return report


def run_single_repeat_site(model, source_hidden, site_index, layer, surface, plane_bank, centers, terminal, device):
    summary_tensor = source_hidden[0].mean(dim=0) if surface == "M" else source_hidden[0, -1]
    summary = summary_tensor.detach().cpu().numpy().astype(np.float64)
    logits = np.zeros((4, ARMS, 2, 3), dtype="<f4")
    probabilities = np.zeros_like(logits)
    checks = np.zeros((4, ARMS, 10), dtype="<f4")
    all_deltas: list[np.ndarray] = []
    metadata: list[tuple[int, int, float, float, float]] = []
    for strength_index, strength in enumerate(STRENGTHS[1:], start=1):
        deltas, norm_records = intervention_deltas(plane_bank[site_index], centers[site_index], summary, strength)
        for arm, delta in enumerate(deltas):
            all_deltas.append(delta)
            metadata.append((strength_index, arm, strength, norm_records[arm]["requested_norm"], norm_records[arm]["norm_relative_error"]))
    base = source_hidden[0]
    base_tensor_norm = float(torch.linalg.vector_norm(base).item())
    q0 = summary - centers[site_index]
    for start in range(0, len(all_deltas), BRANCH_MICROBATCH):
        stop = min(start + BRANCH_MICROBATCH, len(all_deltas))
        deltas = all_deltas[start:stop]
        batch = len(deltas)
        delta_tensor = torch.as_tensor(np.asarray(deltas, dtype=np.float32), dtype=torch.float32, device=device)
        branches = base.unsqueeze(0).expand(batch, -1, -1).clone()
        if surface == "M":
            branches.sub_(delta_tensor[:, None, :])
        else:
            branches[:, -1, :].sub_(delta_tensor)
        edited_summary = branches.mean(dim=1) if surface == "M" else branches[:, -1, :]
        edited_cpu = edited_summary.detach().cpu().numpy().astype(np.float64)
        edited_tensor_norm = torch.linalg.vector_norm(branches, dim=(1, 2)).detach().cpu().numpy().astype(np.float64)
        actual_tensor_delta = torch.linalg.vector_norm(branches - base.unsqueeze(0), dim=(1, 2)).detach().cpu().numpy().astype(np.float64)
        actual_summary_delta = torch.linalg.vector_norm(edited_summary - summary_tensor.unsqueeze(0), dim=1).detach().cpu().numpy().astype(np.float64)
        terminal_hidden = suffix_forward(model, branches, layer)
        endpoint_values = {}
        for endpoint_index, endpoint in enumerate(ENDPOINTS):
            endpoint_values[endpoint] = score_batch(terminal_hidden, terminal[endpoint], endpoint)
        for local, global_index in enumerate(range(start, stop)):
            strength_index, arm, strength, requested_norm, relative_error = metadata[global_index]
            basis = np.asarray(plane_bank[site_index, arm], dtype=np.float64)
            p0 = projected(basis, q0)
            qprime = edited_cpu[local] - centers[site_index]
            p1 = projected(basis, qprime)
            delta = np.asarray(all_deltas[global_index], dtype=np.float64)
            if arm == 0:
                residual = float(np.linalg.norm(p1 - (1.0 - strength) * p0))
                residual_limit = 5e-4 * max(1.0, float(np.linalg.norm(p0)))
            else:
                off_plane = float(np.linalg.norm(delta - projected(basis, delta)))
                applied_displacement = float(np.linalg.norm((edited_cpu[local] - summary) + delta))
                residual = max(off_plane, applied_displacement)
                residual_limit = 5e-4 * max(1.0, float(np.linalg.norm(delta)))
            actual_summary = float(actual_summary_delta[local])
            expected_tensor = requested_norm * (float(source_hidden.shape[1]) ** 0.5 if surface == "M" else 1.0)
            checks[strength_index, arm] = np.asarray([
                requested_norm,
                actual_summary,
                expected_tensor,
                float(actual_tensor_delta[local]),
                base_tensor_norm,
                float(edited_tensor_norm[local]),
                residual,
                residual_limit,
                relative_error,
                float(np.linalg.norm(p1)),
            ], dtype="<f4")
            for endpoint_index, endpoint in enumerate(ENDPOINTS):
                endpoint_logits, endpoint_probs = endpoint_values[endpoint]
                logits[strength_index, arm, endpoint_index] = endpoint_logits[local]
                probabilities[strength_index, arm, endpoint_index] = endpoint_probs[local]
        del branches, delta_tensor, edited_summary, edited_cpu, terminal_hidden, actual_tensor_delta, edited_tensor_norm, actual_summary_delta
    return {"logits": logits, "probabilities": probabilities, "checks": checks}


def main() -> int:
    started = time.perf_counter()
    bundle_verification = verify_protocol_bundle()
    contract_value = read_json(CONTRACT)
    contract_hash = sha256_file(CONTRACT)[0]
    if contract_hash != bundle_verification["contract_sha256"]:
        raise RuntimeError("S12 execution contract bundle hash mismatch")
    source_code_manifest = read_json(RUN / "implementation-code-manifest-v02.json")
    if source_code_manifest.get("code_root_sha256") != bundle_verification["code_root_sha256"]:
        raise RuntimeError("S12 source code manifest differs from verified protocol bundle")
    token_rows, feature_rows, cache_m, cache_f, inputs = verify_parent_inputs(contract_value)
    source_observers, terminal_observers = load_observers()
    geometry_receipt = verify_source_geometry(inputs["plane_bank"], inputs["centers"], source_observers)
    reused_gates = verify_reused_v01_gates()
    device = configure_runtime(contract_value)
    if "--preflight-only" in sys.argv[1:]:
        print(json.dumps({
            "preflight_complete": True,
            "protocol_bundle_root_sha256": bundle_verification["root_sha256"],
            "implementation_code_root_sha256": bundle_verification["code_root_sha256"],
            "parent_info": inputs["parent_info"],
            "source_geometry": geometry_receipt,
            "reused_v01_gates": reused_gates,
            "runtime_device": str(device),
            "model_loaded": False,
        }, indent=2), flush=True)
        return 0
    model = load_model(device)
    model_before = tensor_state_identity(model)
    if model_before["sha256"] != EXPECTED_STATE or model_before["state_element_count"] != 1_170_340_608:
        raise RuntimeError("pinned frozen model state identity mismatch")
    print("S12 pinned LFM loaded; pre-run parameter hash verified", flush=True)

    base_receipt = run_base_qualification(model, token_rows, feature_rows, cache_m, cache_f, device)
    if base_receipt["complete"] is not True:
        raise RuntimeError("S12 base parity receipt incomplete")
    baseline_logits, baseline_probabilities, baseline_receipt = run_baseline_replay(cache_m, cache_f, terminal_observers, device)
    gates = {
        "receipt_id": "FAS_S12_PRE_INTERVENTION_GATES_V02",
        "complete": True,
        "model_before": model_before,
        "model_revision": REVISION,
        "geometry": geometry_receipt,
        "base_suffix_parity": base_receipt,
        "baseline_probe_replay": baseline_receipt,
        "reused_v01_gates": reused_gates,
        "baseline_metric_context": contract_value["observers"]["terminal_s11_context"],
        "contract_sha256": contract_hash,
        "protocol_bundle_root_sha256": bundle_verification["root_sha256"],
    }
    gates_path = RUN / "pre-intervention-gates-v02.json"
    if gates_path.exists():
        existing_gates = read_json(gates_path)
        for key in ("receipt_id", "complete", "model_revision", "contract_sha256", "protocol_bundle_root_sha256"):
            if existing_gates.get(key) != gates.get(key):
                raise RuntimeError(f"existing S12 pre-intervention gate identity mismatch: {key}")
        if existing_gates.get("base_suffix_parity", {}).get("row_manifest") != gates["base_suffix_parity"].get("row_manifest"):
            raise RuntimeError("existing S12 base parity gate receipt differs")
        if existing_gates.get("baseline_probe_replay", {}).get("outputs") != gates["baseline_probe_replay"].get("outputs"):
            raise RuntimeError("existing S12 baseline gate receipt differs")
    else:
        write_json(gates_path, gates)
    print("S12 full base feature parity, all three suffix parity paths, and S11 prediction reproduction passed", flush=True)
    raw_receipt = run_interventions(
        model,
        token_rows,
        cache_m,
        cache_f,
        baseline_logits,
        baseline_probabilities,
        inputs["plane_bank"],
        inputs["centers"],
        terminal_observers,
        device,
    )
    if tensor_state_identity(model) != model_before:
        raise RuntimeError("LFM parameter state changed after S12 execution")
    execution = {
        "execution_id": "FAS_S12_FULL_EXECUTION_V02",
        "complete": True,
        "model_id": MODEL_ID,
        "revision": REVISION,
        "contract_sha256": contract_hash,
        "pre_intervention_gates_sha256": sha256_file(RUN / "pre-intervention-gates-v02.json")[0],
        "base_parity_root_sha256": read_json(RUN / "base-parity-v02" / "base-parity-seal-v02.json")["root_sha256"],
        "baseline_root_sha256": read_json(RUN / "baseline-v02" / "baseline-seal-v02.json")["root_sha256"],
        "raw_output_root_sha256": read_json(RUN / "raw-v02" / "raw-seal-v02.json")["root_sha256"],
        "source_code_root_sha256": source_code_manifest["code_root_sha256"],
        "model_before": model_before,
        "model_after": tensor_state_identity(model),
        "parameter_delta": 0,
        "parent_info": inputs["parent_info"],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(RUN / "execution-receipt-v02.json", execution)
    print(f"S12 raw intervention complete: {execution['raw_output_root_sha256']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
