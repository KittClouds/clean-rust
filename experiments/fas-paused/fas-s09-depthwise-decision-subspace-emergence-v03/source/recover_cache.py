from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np
import torch
from transformers import AutoModel

from s09_common import (
    DIMENSION,
    EVENTS,
    FEATURE_ROOT,
    LAYERS,
    MODEL_ID,
    MODEL_ROOT,
    QUARTETS,
    REVISION,
    RUN_ROOT,
    S01_2_ROOT,
    SOURCE_RUN_ROOT,
    SURFACES,
    canonical_json,
    configure_determinism,
    entry_for,
    read_json,
    sha256_file,
    tensor_state_identity,
    token_ids_sha256,
    tree_root,
    write_json,
)
from s09_math import layer_surface_vectors


EXPECTED_MATRIX_BYTES = EVENTS * DIMENSION * 4
EXPECTED_OLD_PREFLIGHT = "3fad97ccd593a508ca3dc1e5a8ae87998e490338d8a95fd1facb084c0343e946"
EXPECTED_OLD_PROTOCOL = "274b8291e208017555f922544f43694e9d30cab6141f47d4d8a68772c3a76c19"
EXPECTED_TOKEN_MANIFEST = "591e86a5ba01006d77a25299ce6606daaa1cf6bfcf26ace92352abdff29e6aed"
EXPECTED_MODEL_MANIFEST = "9760947e0c2840829e6553d73ac2108adbf7db845cc99da9e0bfe91cce6d12f3"


def verify_old_preflight() -> dict[str, Any]:
    seal = read_json(RUN_ROOT / "history-v02" / "preflight-seal-v02.json")
    if seal.get("root_sha256") != EXPECTED_OLD_PREFLIGHT:
        raise RuntimeError("historical v02 preflight root differs from frozen parent binding")
    actual = [entry_for(SOURCE_RUN_ROOT.joinpath(*item["path"].split("/")), SOURCE_RUN_ROOT) for item in seal["entries"]]
    actual.sort(key=lambda item: item["path"])
    if actual != seal["entries"] or tree_root(actual) != EXPECTED_OLD_PREFLIGHT:
        raise RuntimeError("historical v02 preflight inputs changed after model contact")
    receipt = read_json(SOURCE_RUN_ROOT / "parent-verification-receipt-v02.json")
    if receipt.get("project_protocol_root_sha256") != EXPECTED_OLD_PROTOCOL:
        raise RuntimeError("historical v02 protocol root differs from frozen parent binding")
    return {"root_sha256": EXPECTED_OLD_PREFLIGHT, "entry_count": len(actual), "protocol_root_sha256": EXPECTED_OLD_PROTOCOL}


def verify_v03_protocol_snapshot() -> dict[str, Any]:
    base = RUN_ROOT / "inputs" / "project-snapshot"
    seal = read_json(base / "seals" / "protocol-seal-v03.json")
    actual = [entry_for(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    actual.sort(key=lambda item: item["path"])
    if actual != seal["entries"] or tree_root(actual) != seal.get("root_sha256"):
        raise RuntimeError("v03 protocol snapshot differs from its pre-contact seal")
    return {"root_sha256": seal["root_sha256"], "entry_count": len(actual)}


def verify_model_assets() -> dict[str, Any]:
    manifest_path = SOURCE_RUN_ROOT / "model-asset-manifest-v02.json"
    manifest_hash, _ = sha256_file(manifest_path)
    if manifest_hash != EXPECTED_MODEL_MANIFEST:
        raise RuntimeError("v02 model asset manifest identity differs")
    manifest = read_json(manifest_path)
    if manifest.get("model_id") != MODEL_ID or manifest.get("resolved_revision") != REVISION:
        raise RuntimeError("pinned model/revision differs from S09 contract")
    if manifest.get("layers") != 16 or manifest.get("hidden_dimension") != DIMENSION or manifest.get("tokenizer_copied_or_loaded") is not False:
        raise RuntimeError("pinned model manifest dimensions or tokenizer boundary differ")
    for item in manifest["assets"]:
        path = SOURCE_RUN_ROOT.joinpath(*item["path"].split("/"))
        digest, size = sha256_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"pinned model asset changed: {item['path']}")
    canonical_assets = canonical_json(manifest["assets"])
    if hashlib.sha256(canonical_assets).hexdigest() != manifest.get("asset_manifest_root_sha256"):
        raise RuntimeError("pinned model asset root differs")
    seal = read_json(SOURCE_RUN_ROOT / "model-assets-seal-v02.json")
    actual = [entry_for(SOURCE_RUN_ROOT.joinpath(*item["path"].split("/")), SOURCE_RUN_ROOT) for item in seal["entries"]]
    actual.sort(key=lambda item: item["path"])
    if actual != seal["entries"] or tree_root(actual) != seal.get("root_sha256"):
        raise RuntimeError("pinned model asset tree seal differs")
    return {"model_id": MODEL_ID, "revision": REVISION, "manifest_sha256": manifest_hash, "asset_root_sha256": manifest["asset_manifest_root_sha256"], "assets_verified": len(actual)}


def verify_feature_matrices() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    started = time.perf_counter()
    for layer in LAYERS:
        for surface in SURFACES:
            name = f"layer-{layer:02d}-{surface}.f32le"
            path = FEATURE_ROOT / name
            if not path.is_file() or path.stat().st_size != EXPECTED_MATRIX_BYTES:
                raise RuntimeError(f"feature matrix missing or wrong size: {name}")
            digest = hashlib.sha256()
            finite_count = 0
            with path.open("rb") as stream:
                while chunk := stream.read(16 * 1024 * 1024):
                    if len(chunk) % 4:
                        raise RuntimeError(f"feature matrix chunk is not float32 aligned: {name}")
                    values = np.frombuffer(chunk, dtype="<f4")
                    finite = np.isfinite(values)
                    if not finite.all():
                        raise RuntimeError(f"feature matrix contains non-finite values: {name}")
                    finite_count += int(values.size)
                    digest.update(chunk)
            if finite_count != EVENTS * DIMENSION:
                raise RuntimeError(f"feature matrix element count differs: {name}")
            entries.append({"path": name, "bytes": EXPECTED_MATRIX_BYTES, "sha256": digest.hexdigest()})
            print(f"requalified_matrix={len(entries)}/32 name={name} elapsed_seconds={time.perf_counter()-started:.1f}", flush=True)
    entries.sort(key=lambda item: item["path"])
    return entries, {"matrices": len(entries), "finite_elements": len(entries) * EVENTS * DIMENSION, "sha256_stream_seconds": round(time.perf_counter() - started, 3)}


def verify_terminal_parent(entries: list[dict[str, Any]]) -> dict[str, Any]:
    parent_seal = read_json(RUN_ROOT / "inputs" / "S01-2" / "feature-cache-seal-v01.json")
    parent_entries = {item["path"]: item for item in parent_seal["entries"]}
    expected = {
        "layer-16-M.f32le": ("feature-cache-v01/V0_MEAN_FULL.f32le", "M"),
        "layer-16-F.f32le": ("feature-cache-v01/V1_FINAL_POSITION.f32le", "F"),
    }
    current_entries = {item["path"]: item for item in entries}
    results = {}
    for name, (parent_relative, surface) in expected.items():
        parent_item = parent_entries.get(parent_relative)
        current_item = current_entries[name]
        if parent_item is None:
            raise RuntimeError(f"S01 parent cache seal lacks terminal surface {surface}")
        parent_path = S01_2_ROOT.joinpath(*parent_relative.split("/"))
        parent_digest, parent_bytes = sha256_file(parent_path)
        if parent_digest != parent_item["sha256"] or parent_bytes != parent_item["bytes"]:
            raise RuntimeError(f"S01 sealed terminal parent changed: {surface}")
        if current_item["sha256"] != parent_digest or current_item["bytes"] != parent_bytes:
            raise RuntimeError(f"v02 terminal matrix fails exact S01 parent parity: {surface}")
        results[surface] = {"source_sha256": current_item["sha256"], "parent_sha256": parent_digest, "byte_equal": True}
    return {"M_byte_equal_to_S01_V0": True, "F_byte_equal_to_S01_V1": True, "events_compared": EVENTS, "max_abs_error": 0.0, "surfaces": results}


def repeat_first_256(model: torch.nn.Module, device: torch.device) -> dict[str, Any]:
    rows_path = RUN_ROOT / "inputs" / "token-only-feature-rows-v02.jsonl"
    rows_digest, _ = sha256_file(rows_path)
    if rows_digest != EXPECTED_TOKEN_MANIFEST:
        raise RuntimeError("token-only manifest differs from frozen S09 parent")
    matrices = {
        (layer, surface): np.memmap(FEATURE_ROOT / f"layer-{layer:02d}-{surface}.f32le", dtype="<f4", mode="r", shape=(EVENTS, DIMENSION), order="C")
        for layer in LAYERS for surface in SURFACES
    }
    ids: list[str] = []
    with rows_path.open("r", encoding="utf-8") as stream, torch.inference_mode():
        for expected_index in range(256):
            line = stream.readline()
            if not line:
                raise RuntimeError("token-only manifest ended before repeat sample")
            row = json.loads(line)
            tokens = row["token_ids"]
            if row.get("row_index") != expected_index or row.get("sequence_length") != len(tokens):
                raise RuntimeError(f"repeat input row identity/length mismatch at {expected_index}")
            if token_ids_sha256(tokens) != row.get("token_ids_sha256"):
                raise RuntimeError(f"repeat input token hash mismatch at {expected_index}")
            input_ids = torch.tensor(tokens, dtype=torch.long, device=device).reshape(1, -1)
            output = model(input_ids=input_ids, use_cache=False, output_hidden_states=True, return_dict=True)
            if output.hidden_states is None or len(output.hidden_states) != 17 or not torch.equal(output.hidden_states[-1], output.last_hidden_state):
                raise RuntimeError(f"repeat hidden-state identity failed at row {expected_index}")
            vectors = layer_surface_vectors(output.hidden_states, len(tokens), DIMENSION).detach().cpu().numpy().astype("<f4", copy=False)
            if not np.isfinite(vectors).all():
                raise RuntimeError(f"non-finite deterministic repeat feature at row {expected_index}")
            for layer in LAYERS:
                for surface_index, surface in enumerate(SURFACES):
                    if not np.array_equal(vectors[layer - 1, surface_index], matrices[(layer, surface)][expected_index]):
                        raise RuntimeError(f"repeat mismatch at row {expected_index}, layer {layer}, surface {surface}")
            ids.append(row["event_id"])
    if len(ids) != 256:
        raise RuntimeError("deterministic repeat sample count differs")
    return {"sample_rows": len(ids), "event_ids_sha256": hashlib.sha256("\n".join(ids).encode("ascii")).hexdigest(), "all_32_layer_surface_vectors_byte_equal": True}


def main() -> int:
    started = time.perf_counter()
    if (RUN_ROOT / "recovery-extraction-receipt-v03.json").exists() or (RUN_ROOT / "recovery-feature-cache-seal-v03.json").exists():
        raise RuntimeError("v03 recovery outputs already exist; refusing in-place rerun")
    project_root = Path(__file__).resolve().parents[1]
    contract = read_json(project_root / "contracts" / "s09-recovery-contract-v03.json")
    protocol_snapshot = verify_v03_protocol_snapshot()
    bound = contract["recovery_inputs"]
    token_manifest_hash, _ = sha256_file(RUN_ROOT / "inputs" / "token-only-feature-rows-v02.jsonl")
    model_manifest_hash, _ = sha256_file(SOURCE_RUN_ROOT / "model-asset-manifest-v02.json")
    old_extractor_hash, _ = sha256_file(project_root.with_name("fas-s09-depthwise-decision-subspace-emergence-v02") / "source" / "extract_layers.py")
    linear_core_hash, _ = sha256_file(project_root / "source" / "linear_core.py")
    if token_manifest_hash != bound["token_manifest_sha256"] or model_manifest_hash != bound["source_model_asset_manifest_sha256"]:
        raise RuntimeError("contracted token manifest or model manifest identity differs")
    if old_extractor_hash != bound["v02_extractor_source_sha256"] or linear_core_hash != bound["s01_linear_core_sha256"]:
        raise RuntimeError("contracted extraction or linear-core source identity differs")
    parent_receipt = read_json(SOURCE_RUN_ROOT / "parent-verification-receipt-v02.json")
    if parent_receipt.get("verified_parent_roots") != contract["parent_roots"]:
        raise RuntimeError("verified scientific parent roots differ from v03 contract")
    old_preflight = verify_old_preflight()
    print("historical_v02_preflight=PASS", flush=True)
    model_assets = verify_model_assets()
    print("pinned_model_assets=PASS", flush=True)
    entries, matrix_scan = verify_feature_matrices()
    terminal = verify_terminal_parent(entries)
    print("terminal_parent_parity=PASS", flush=True)

    if torch.__version__ != "2.11.0+cu128" or np.__version__ != "2.5.3":
        raise RuntimeError("S09 frozen runtime versions differ")
    import transformers
    if transformers.__version__ != "5.17.0":
        raise RuntimeError("S09 frozen Transformers version differs")
    device = configure_determinism()
    model = AutoModel.from_pretrained(str(MODEL_ROOT), local_files_only=True, trust_remote_code=False, dtype=torch.float32)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.to(device)
    if getattr(model.config, "num_hidden_layers", None) != 16 or getattr(model.config, "hidden_size", None) != DIMENSION or getattr(model.config, "_attn_implementation", None) != "sdpa":
        raise RuntimeError("loaded pinned model configuration differs from S09 contract")
    before = tensor_state_identity(model)
    print("model_loaded_and_parameter_identity_recorded=true", flush=True)
    repeat = repeat_first_256(model, device)
    print("deterministic_repeat_256=PASS", flush=True)
    after = tensor_state_identity(model)
    if before["sha256"] != after["sha256"]:
        raise RuntimeError("backbone parameter identity changed during recovery repeat")

    cache_root = tree_root(entries)
    cache_seal = {
        "seal_id": "FAS_S09_RECOVERED_FEATURE_CACHE_SEAL_V03",
        "source_cache": str(FEATURE_ROOT),
        "source_attempt": "fas-s09-depthwise-decision-subspace-emergence-v02",
        "entries": entries,
        "root_sha256": cache_root,
        "rows": EVENTS,
        "matrices": len(entries),
    }
    write_json(RUN_ROOT / "recovery-feature-cache-seal-v03.json", cache_seal)
    receipt = {
        "receipt_id": "FAS_S09_RECOVERED_EXTRACTION_RECEIPT_V03",
        "model_id": MODEL_ID,
        "model_revision": REVISION,
        "feature_cache_root_sha256": cache_root,
        "rows": EVENTS,
        "quartets": QUARTETS,
        "matrices": len(entries),
        "terminal_parent_parity": terminal,
        "deterministic_repeat": repeat,
        "backbone_before": before,
        "backbone_after": after,
        "backbone_parameter_delta": 0,
        "single_row_exact_length_no_padding": True,
        "tokenizer_loaded": False,
        "full_corpus_reextracted": False,
        "probe_fitting_performed": False,
        "fas00_artifacts_read": False,
        "source_attempt": {
            "run_id": "fas-s09-depthwise-decision-subspace-emergence-v02",
            "protocol_root_sha256": EXPECTED_OLD_PROTOCOL,
            "preflight_root_sha256": EXPECTED_OLD_PREFLIGHT,
            "extractor_sha256": sha256_file(Path(__file__).resolve().parents[1].with_name("fas-s09-depthwise-decision-subspace-emergence-v02") / "source" / "extract_layers.py")[0],
            "receipt_assembly_failure": "NameError: name 'QUARTETS' is not defined",
            "failure_stage": "receipt assembly after full feature production; no extraction receipt or cache seal was written",
            "probe_fitting_started": False,
            "source_run_modified": False,
        },
        "recovery_qualification": {
            "matrix_manifest_root_sha256": cache_root,
            "matrix_count": len(entries),
            "rows": EVENTS,
            "quartets": QUARTETS,
            "width": DIMENSION,
            "dtype": "<f4",
            "matrix_bytes_each": EXPECTED_MATRIX_BYTES,
            "matrix_scan": matrix_scan,
            "terminal_parent_parity": terminal,
            "deterministic_repeat": repeat,
            "model_assets": model_assets,
            "backbone_before": before,
            "backbone_after": after,
            "backbone_parameter_delta": 0,
            "full_corpus_reextracted": False,
        },
        "parent_roots": parent_receipt["verified_parent_roots"],
        "fas00_artifacts_read": False,
        "probe_fitting_performed": False,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(RUN_ROOT / "recovery-extraction-receipt-v03.json", receipt)

    project_seal = read_json(RUN_ROOT / "inputs" / "project-snapshot" / "seals" / "protocol-seal-v03.json")
    parent_v03 = {
        "receipt_id": "FAS_S09_V03_PARENT_VERIFICATION_RECEIPT",
        "project_protocol_root_sha256": project_seal["root_sha256"],
        "protocol_snapshot_verified": protocol_snapshot,
        "superseded_v02_preflight_root_sha256": old_preflight["root_sha256"],
        "verified_parent_roots": parent_receipt["verified_parent_roots"],
        "recovered_feature_cache_root_sha256": cache_root,
        "fas00_access": False,
        "model_loaded_for_repeat_only": True,
        "probe_fitting_performed": False,
    }
    write_json(RUN_ROOT / "parent-verification-receipt-v03.json", parent_v03)
    preflight_paths = [path for path in RUN_ROOT.rglob("*") if path.is_file() and path != RUN_ROOT / "seals" / "preflight-seal-v03.json"]
    preflight_entries = [entry_for(path, RUN_ROOT) for path in preflight_paths if path.is_relative_to(RUN_ROOT / "inputs") or path in (RUN_ROOT / "parent-verification-receipt-v03.json", RUN_ROOT / "recovery-feature-cache-seal-v03.json", RUN_ROOT / "recovery-extraction-receipt-v03.json")]
    preflight_entries.sort(key=lambda item: item["path"])
    preflight_root = tree_root(preflight_entries)
    write_json(RUN_ROOT / "seals" / "preflight-seal-v03.json", {"seal_id": "FAS_S09_RECOVERY_PREFLIGHT_SEAL_V03", "entries": preflight_entries, "root_sha256": preflight_root, "model_loaded_for_repeat_only": True, "probe_fitting_performed": False})
    print(f"recovery_ready=true feature_cache_root_sha256={cache_root} preflight_root_sha256={preflight_root} matrices={len(entries)} repeat_rows={repeat['sample_rows']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
