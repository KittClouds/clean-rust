from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch

from common import jsonl_rows, read_json, sha256_bytes, sha256_file, verify_parent_bundle


MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
FEATURE_CONTRACT_SHA = "08ddd42795d71d9b598da5015d5541316c6cf1f2c0761ce3c0890229cda4d5b0"
VIEW_ORDER = (
    "V0_MEAN_FULL", "V1_FINAL_POSITION", "V2_FIRST_POSITION",
    "V3_CONTEXT_SPAN_MEAN", "V4_ENTITY_SPAN_MEAN", "V5_RELATION_SPAN_MEAN", "V6_FIXED_SPAN_CONCAT",
)
BASE_VIEWS = VIEW_ORDER[:6]
VIEW_DIMS = {name: (6144 if name == "V6_FIXED_SPAN_CONCAT" else 2048) for name in VIEW_ORDER}
VARIANTS = ("A", "C", "E", "P")


class RunState:
    def __init__(self) -> None:
        self.stage = "START"
        self.model_loaded = False
        self.events_completed = 0
        self.features_written = 0
        self.failure: str | None = None
        self.parameter_hash_before: str | None = None
        self.parameter_hash_after: str | None = None


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def verify_preflight(root: Path) -> dict[str, Any]:
    seal = read_json(root / "seals" / "preflight-seal-v01.json")
    actual = []
    for item in seal["entries"]:
        digest, size = sha256_file(root.joinpath(*item["path"].split("/")))
        actual.append({"path": item["path"], "bytes": size, "sha256": digest})
    if actual != seal["entries"] or sha256_bytes(b"".join(f"{x['path']}\t{x['bytes']}\t{x['sha256']}\n".encode() for x in actual)) != seal["root_sha256"]:
        raise RuntimeError("frozen preflight packet failed verification")
    return seal


def tensor_state_identity(model: torch.nn.Module) -> dict[str, Any]:
    digest = hashlib.sha256()
    tensor_count = 0
    element_count = 0
    byte_count = 0
    for name, tensor in sorted(model.state_dict().items(), key=lambda item: item[0]):
        if not isinstance(tensor, torch.Tensor):
            raise RuntimeError(f"non-tensor model state entry: {name}")
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tensor.dtype).encode("ascii") + b"\0")
        digest.update(canonical_json(list(tensor.shape)) + b"\0")
        cpu = tensor.detach().contiguous().reshape(-1).view(torch.uint8).to(device="cpu").numpy()
        view = memoryview(cpu).cast("B")
        for offset in range(0, len(view), 8 * 1024 * 1024):
            chunk = view[offset:offset + 8 * 1024 * 1024]
            digest.update(chunk)
            byte_count += len(chunk)
        tensor_count += 1
        element_count += tensor.numel()
        del cpu, view
    return {
        "sha256": digest.hexdigest(),
        "state_tensor_count": tensor_count,
        "state_element_count": element_count,
        "serialized_state_bytes": byte_count,
    }


def feature_bytes(vector: torch.Tensor) -> bytes:
    if vector.dtype != torch.float32 or vector.ndim != 1:
        raise RuntimeError(f"feature view has unexpected tensor dtype/shape: {vector.dtype} {tuple(vector.shape)}")
    array = vector.detach().contiguous().cpu().numpy().astype("<f4", copy=False)
    if not np.isfinite(array).all():
        raise RuntimeError("non-finite feature value")
    return array.tobytes(order="C")


def extract_views(model: torch.nn.Module, token_ids: list[int], assignments: dict[str, Any], device: torch.device) -> dict[str, torch.Tensor]:
    if not token_ids or len(token_ids) > 2048:
        raise RuntimeError("empty or contract-exceeding token sequence")
    ids = torch.tensor(token_ids, dtype=torch.long, device=device).reshape(1, -1)
    output = model(input_ids=ids, use_cache=False, return_dict=True)
    hidden = output.last_hidden_state
    if hidden.dtype != torch.float32 or tuple(hidden.shape) != (1, len(token_ids), 2048):
        raise RuntimeError(f"model hidden state differs from frozen shape/dtype: {hidden.dtype} {tuple(hidden.shape)}")
    states = hidden[0]
    view_spec = assignments["view_assignments"]
    if view_spec["V0_MEAN_FULL"]["position_range_half_open"] != [0, len(token_ids)]:
        raise RuntimeError("S01-2C V0 assignment does not cover exact model-visible sequence")
    if view_spec["V1_FINAL_POSITION"]["positions"] != [len(token_ids) - 1] or view_spec["V2_FIRST_POSITION"]["positions"] != [0]:
        raise RuntimeError("S01-2C first/final position assignment mismatch")
    if view_spec["V0_MEAN_FULL"]["position_count"] != len(token_ids):
        raise RuntimeError("S01-2C full-view position count differs")
    def span_mean(view_id: str) -> torch.Tensor:
        positions = view_spec[view_id]["positions"]
        if not positions or positions != sorted(set(positions)) or positions[0] < 0 or positions[-1] >= len(token_ids):
            raise RuntimeError(f"invalid sealed position assignment for {view_id}")
        idx = torch.tensor(positions, dtype=torch.long, device=device)
        return states.index_select(0, idx).mean(dim=0)

    context = span_mean("V3_CONTEXT_SPAN_MEAN")
    entity = span_mean("V4_ENTITY_SPAN_MEAN")
    relation = span_mean("V5_RELATION_SPAN_MEAN")
    return {
        "V0_MEAN_FULL": states.mean(dim=0),
        "V1_FINAL_POSITION": states[len(token_ids) - 1],
        "V2_FIRST_POSITION": states[0],
        "V3_CONTEXT_SPAN_MEAN": context,
        "V4_ENTITY_SPAN_MEAN": entity,
        "V5_RELATION_SPAN_MEAN": relation,
        "V6_FIXED_SPAN_CONCAT": torch.cat((context, entity, relation), dim=0),
    }


def self_test() -> None:
    sequence = torch.arange(5 * 2048, dtype=torch.float32).reshape(5, 2048)
    context = sequence[[1, 2]].mean(dim=0)
    entity = sequence[[3]].mean(dim=0)
    relation = sequence[[4]].mean(dim=0)
    views = {
        "V0_MEAN_FULL": sequence.mean(dim=0),
        "V1_FINAL_POSITION": sequence[4],
        "V2_FIRST_POSITION": sequence[0],
        "V3_CONTEXT_SPAN_MEAN": context,
        "V4_ENTITY_SPAN_MEAN": entity,
        "V5_RELATION_SPAN_MEAN": relation,
        "V6_FIXED_SPAN_CONCAT": torch.cat((context, entity, relation)),
    }
    assert [tuple(views[v].shape) for v in VIEW_ORDER] == [(2048,)] * 6 + [(6144,)]
    assert torch.equal(views["V6_FIXED_SPAN_CONCAT"], torch.cat((views["V3_CONTEXT_SPAN_MEAN"], views["V4_ENTITY_SPAN_MEAN"], views["V5_RELATION_SPAN_MEAN"])))
    assert feature_bytes(views["V0_MEAN_FULL"]) == feature_bytes(sequence.mean(dim=0))


def write_failure(root: Path, state: RunState) -> None:
    path = root / "execution-failure-v01.json"
    if path.exists():
        return
    record = {
        "failure_id": "FASS01_S01_2_EXTRACTION_FAILURE_V01",
        "phase_id": "S01-2-feature-geometry-v01",
        "stage": state.stage,
        "error": state.failure,
        "model_loaded": state.model_loaded,
        "events_completed": state.events_completed,
        "feature_rows_written": state.features_written,
        "parameter_hash_before": state.parameter_hash_before,
        "parameter_hash_after": state.parameter_hash_after,
        "features_sealed": False,
        "geometry_performed": False,
        "probe_training_performed": False,
        "S01_3_authorized": False,
    }
    path.write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def run(root: Path, state: RunState) -> None:
    binding = read_json(root / "inputs" / "input-binding-v01.json")
    contract = read_json(root / "inputs" / "extraction-execution-contract-v01.json")
    preflight = verify_preflight(root)
    if preflight.get("parents") != {key: value["result_tree_root_sha256"] for key, value in binding["parent_roots"].items()}:
        raise RuntimeError("preflight parent roots differ from run binding")
    parent_receipt = read_json(root / "parent-verification-receipt-v01.json")
    if parent_receipt.get("roots") != {key: value["result_tree_root_sha256"] for key, value in binding["parent_roots"].items()}:
        raise RuntimeError("parent verification receipt differs from execution binding")
    if binding["model_id"] != MODEL_ID or binding["model_revision"] != REVISION or contract["backbone"]["feature_extraction_dtype"] != "float32":
        raise RuntimeError("frozen model identity or execution dtype differs")
    if contract["input_protocol"]["feature_contract_sha256"] != FEATURE_CONTRACT_SHA:
        raise RuntimeError("feature contract hash differs")
    if torch.__version__ != binding["runtime_versions"]["torch"] or np.__version__ != binding["runtime_versions"]["numpy"]:
        raise RuntimeError("frozen torch or numpy runtime changed")
    import transformers
    if transformers.__version__ != binding["runtime_versions"]["transformers"]:
        raise RuntimeError("frozen transformers runtime changed")
    if not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("frozen CUDA device is unavailable or changed")
    torch.set_num_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.use_deterministic_algorithms(True)
    self_test()

    asset_manifest = read_json(root / "model-asset-manifest-v01.json")
    if asset_manifest.get("resolved_revision") != REVISION or asset_manifest.get("model_id") != MODEL_ID:
        raise RuntimeError("downloaded model asset identity differs")
    for asset in asset_manifest["assets"]:
        digest, size = sha256_file(root.joinpath(*asset["path"].split("/")))
        if digest != asset["sha256"] or size != asset["bytes"]:
            raise RuntimeError(f"pinned model asset changed before load: {asset['path']}")
    model_snapshot = root.joinpath(*asset_manifest["snapshot_path"].split("/"))

    state.stage = "MODEL_LOAD"
    from transformers import AutoModel
    model = AutoModel.from_pretrained(
        str(model_snapshot),
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.float32,
    )
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.to(torch.device("cuda:0"))
    state.model_loaded = True
    config_hidden = getattr(model.config, "hidden_size", None)
    if config_hidden is None and hasattr(model.config, "text_config"):
        config_hidden = getattr(model.config.text_config, "hidden_size", None)
    if config_hidden != 2048:
        raise RuntimeError(f"loaded LFM hidden size differs from frozen contract: {config_hidden}")
    state.stage = "PARAMETER_IDENTITY_BEFORE"
    identity_before = tensor_state_identity(model)
    state.parameter_hash_before = identity_before["sha256"]
    print(f"parameter_identity_before={identity_before['sha256']} tensors={identity_before['state_tensor_count']}", flush=True)

    corpus_path = Path(binding["inputs"]["corpus"])
    alignment_path = Path(binding["inputs"]["alignment_records"])
    assignment_path = Path(binding["inputs"]["alignment_assignments"])
    expected_input_hashes = binding["input_sha256"]
    for label, path in (("corpus", corpus_path), ("alignment_records", alignment_path), ("alignment_assignments", assignment_path)):
        digest, _ = sha256_file(path)
        if digest != expected_input_hashes[label]:
            raise RuntimeError(f"sealed input changed before feature extraction: {label}")

    cache_dir = root / "feature-cache-v01"
    if cache_dir.exists():
        raise RuntimeError("feature cache directory already exists; refusing reuse")
    cache_dir.mkdir()
    paths = {view: cache_dir / f"{view}.f32le" for view in VIEW_ORDER}
    if any(path.exists() for path in paths.values()):
        raise RuntimeError("feature view file already exists")
    view_streams = {view: paths[view].open("xb", buffering=8 * 1024 * 1024) for view in VIEW_ORDER}
    view_digests = {view: hashlib.sha256() for view in VIEW_ORDER}
    row_path = cache_dir / "feature-rows-v01.jsonl"
    row_stream = row_path.open("xb", buffering=8 * 1024 * 1024)
    repeat_records: list[dict[str, Any]] = []
    row_index = 0
    start_time = time.perf_counter()
    state.stage = "FEATURE_EXTRACTION"

    def paired_rows():
        align_iter = iter(jsonl_rows(alignment_path))
        assignment_iter = iter(jsonl_rows(assignment_path))
        event_count = 0
        for quartet in jsonl_rows(corpus_path):
            variants = quartet.get("variants", [])
            if len(variants) != 4 or [item.get("variant_id") for item in variants] != list(VARIANTS):
                raise RuntimeError(f"corpus quartet variant order/count mismatch: {quartet.get('quartet_id')}")
            for variant in variants:
                alignment = next(align_iter, None)
                assignment = next(assignment_iter, None)
                event_count += 1
                if alignment is None or assignment is None:
                    raise RuntimeError("sealed input rows ended before the corpus")
                if any(record.get(key) != value for record, key, value in (
                    (alignment, "quartet_id", quartet["quartet_id"]),
                    (assignment, "quartet_id", quartet["quartet_id"]),
                    (alignment, "event_id", variant["event_id"]),
                    (assignment, "event_id", variant["event_id"]),
                    (alignment, "variant_id", variant["variant_id"]),
                    (assignment, "variant_id", variant["variant_id"]),
                    (alignment, "input_sha256", variant["input_sha256"]),
                    (assignment, "input_sha256", variant["input_sha256"]),
                )):
                    raise RuntimeError(f"event identity mismatch for {variant['event_id']}")
                if assignment.get("quartet_eligible") is not True:
                    raise RuntimeError(f"S01-2C row is not eligible: {variant['event_id']}")
                if alignment.get("model_revision") != REVISION or alignment.get("model_id") != MODEL_ID:
                    raise RuntimeError(f"tokenizer/model identity mismatch: {variant['event_id']}")
                if assignment.get("token_ids_sha256") != alignment.get("token_ids_sha256") or assignment.get("sequence_length") != alignment.get("sequence_length"):
                    raise RuntimeError(f"S01-2C token identity mismatch: {variant['event_id']}")
                if alignment.get("feature_contract_sha256") != FEATURE_CONTRACT_SHA:
                    raise RuntimeError(f"feature contract mismatch: {variant['event_id']}")
                token_ids = alignment.get("token_ids", [])
                offsets = alignment.get("offset_mapping", [])
                special = alignment.get("special_tokens_mask", [])
                seq_len = alignment.get("sequence_length")
                if seq_len != len(token_ids) or seq_len != len(offsets) or seq_len != len(special):
                    raise RuntimeError(f"token sequence arrays have different lengths: {variant['event_id']}")
                if not token_ids:
                    raise RuntimeError(f"empty token IDs: {variant['event_id']}")
                views = assignment.get("view_assignments", {})
                for view in VIEW_ORDER:
                    if view not in views:
                        raise RuntimeError(f"missing S01-2C view assignment {view}: {variant['event_id']}")
                if alignment.get("token_ids_sha256") != assignment.get("token_ids_sha256"):
                    raise RuntimeError(f"token ID hash differs from S01-2C: {variant['event_id']}")
                if row_index >= 106496:
                    raise RuntimeError("more event rows than the sealed extraction contract")
                yield quartet, variant, alignment, assignment
        if next(align_iter, None) is not None or next(assignment_iter, None) is not None:
            raise RuntimeError("alignment or S01-2C assignment inputs have trailing rows")
        if event_count != 106496:
            raise RuntimeError(f"event count differs: {event_count}")

    with torch.inference_mode():
        for quartet, variant, alignment, assignment in paired_rows():
            event_id = variant["event_id"]
            tokens = alignment["token_ids"]
            if hashlib.sha256(struct.pack(f"<{len(tokens)}I", *tokens)).hexdigest() != alignment["token_ids_sha256"]:
                raise RuntimeError(f"token ID hash failed immediately before forward: {event_id}")
            if sha256_bytes(variant["input_text"].encode("ascii")) != variant["input_sha256"]:
                raise RuntimeError(f"rendered input hash mismatch: {event_id}")
            features = extract_views(model, tokens, assignment, torch.device("cuda:0"))
            feature_hashes = {}
            feature_shapes = {}
            for view in VIEW_ORDER:
                if tuple(features[view].shape) != (VIEW_DIMS[view],):
                    raise RuntimeError(f"feature shape mismatch for {event_id} / {view}")
                payload = feature_bytes(features[view])
                view_streams[view].write(payload)
                view_digests[view].update(payload)
                feature_hashes[view] = hashlib.sha256(payload).hexdigest()
                feature_shapes[view] = [VIEW_DIMS[view]]
            offset_hash = sha256_bytes(canonical_json(alignment["offset_mapping"]))
            record = {
                "row_index": row_index,
                "quartet_id": quartet["quartet_id"],
                "event_id": event_id,
                "variant_id": variant["variant_id"],
                "input_sha256": variant["input_sha256"],
                "input_text": variant["input_text"],
                "token_ids": tokens,
                "token_ids_sha256": alignment["token_ids_sha256"],
                "offset_mapping": alignment["offset_mapping"],
                "offset_mapping_sha256": offset_hash,
                "special_tokens_mask": alignment["special_tokens_mask"],
                "sequence_length": alignment["sequence_length"],
                "view_assignments": assignment["view_assignments"],
                "span_positions_by_type": assignment["span_positions_by_type"],
                "view_shapes": feature_shapes,
                "feature_sha256": feature_hashes,
                "model_id": MODEL_ID,
                "model_revision": REVISION,
                "feature_contract_sha256": FEATURE_CONTRACT_SHA,
                "tokenizer_asset_manifest_sha256": binding["tokenizer_asset_manifest_sha256"],
                "S01_2C_result_tree_root_sha256": binding["parent_roots"]["S01_2C"]["result_tree_root_sha256"],
                "S01_2C_assignment_manifest_sha256": binding["input_sha256"]["alignment_assignments"],
            }
            row_stream.write(canonical_json(record) + b"\n")
            if row_index < 256:
                repeat_records.append(record)
            row_index += 1
            state.events_completed = row_index
            state.features_written = row_index
            if row_index % 1024 == 0:
                print(f"features_extracted={row_index}/106496 elapsed_seconds={time.perf_counter()-start_time:.1f}", flush=True)
        row_stream.flush()
        os.fsync(row_stream.fileno())
        for stream in view_streams.values():
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        row_stream.close()

    if row_index != 106496 or len(repeat_records) != 256:
        raise RuntimeError(f"feature extraction row count mismatch: {row_index}")
    state.stage = "DETERMINISTIC_REPEAT"
    alignment_sample = iter(jsonl_rows(alignment_path))
    assignment_sample = iter(jsonl_rows(assignment_path))
    repeat_receipt_rows = []
    repeat_files = {view: paths[view].open("rb") for view in VIEW_ORDER}
    for expected in repeat_records:
        alignment = next(alignment_sample)
        assignment = next(assignment_sample)
        if alignment.get("event_id") != expected["event_id"] or assignment.get("event_id") != expected["event_id"]:
            raise RuntimeError("determinism sample source identities changed")
        if alignment.get("token_ids") != expected["token_ids"] or alignment.get("offset_mapping") != expected["offset_mapping"] or alignment.get("sequence_length") != expected["sequence_length"]:
            raise RuntimeError(f"determinism sample token/offset/length mismatch: {expected['event_id']}")
        if assignment.get("view_assignments") != expected["view_assignments"]:
            raise RuntimeError(f"determinism sample S01-2C position mismatch: {expected['event_id']}")
        repeated = extract_views(model, expected["token_ids"], assignment, torch.device("cuda:0"))
        row_matches = {}
        for view in VIEW_ORDER:
            payload = feature_bytes(repeated[view])
            if list(repeated[view].shape) != expected["view_shapes"][view]:
                raise RuntimeError(f"repeat feature shape mismatch: {expected['event_id']} / {view}")
            repeat_files[view].seek(expected["row_index"] * VIEW_DIMS[view] * 4)
            original = repeat_files[view].read(VIEW_DIMS[view] * 4)
            if payload != original or hashlib.sha256(payload).hexdigest() != expected["feature_sha256"][view]:
                raise RuntimeError(f"repeat feature bytes mismatch: {expected['event_id']} / {view}")
            row_matches[view] = True
        repeat_receipt_rows.append({"row_index": expected["row_index"], "event_id": expected["event_id"], "token_ids_match": True, "offset_mapping_match": True, "sequence_length_match": True, "view_shapes_match": True, "feature_bytes_match": row_matches})
    for stream in repeat_files.values():
        stream.close()

    state.stage = "PARAMETER_IDENTITY_AFTER"
    identity_after = tensor_state_identity(model)
    state.parameter_hash_after = identity_after["sha256"]
    if identity_after["sha256"] != identity_before["sha256"]:
        raise RuntimeError("backbone state tensor hash changed during extraction")
    if identity_after["state_tensor_count"] != identity_before["state_tensor_count"] or identity_after["state_element_count"] != identity_before["state_element_count"]:
        raise RuntimeError("backbone state tensor inventory changed")

    asset_hashes_after = []
    for item in asset_manifest["assets"]:
        digest, size = sha256_file(root.joinpath(*item["path"].split("/")))
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"pinned model asset changed during extraction: {item['path']}")
        asset_hashes_after.append({"path": item["path"], "bytes": size, "sha256": digest})

    view_files = {}
    for view, path in paths.items():
        digest, size = sha256_file(path)
        expected_bytes = 106496 * VIEW_DIMS[view] * 4
        if size != expected_bytes or digest != view_digests[view].hexdigest():
            raise RuntimeError(f"feature file size/hash mismatch for {view}")
        view_files[view] = {"path": path.relative_to(root).as_posix(), "shape": [106496, VIEW_DIMS[view]], "dtype": "<f4", "bytes": size, "sha256": digest}
    row_manifest_hash, row_manifest_bytes = sha256_file(row_path)
    if len(repeat_receipt_rows) != 256 or not all(all(row["feature_bytes_match"].values()) for row in repeat_receipt_rows):
        raise RuntimeError("fixed repeat sample did not match completely")
    parameter_receipt = {
        "receipt_id": "FASS01_S01_2_BACKBONE_IDENTITY_V01",
        "model_id": MODEL_ID,
        "model_revision": REVISION,
        "identity_method": "sorted state_dict name, dtype, shape, and raw tensor-byte SHA-256",
        "before": identity_before,
        "after": identity_after,
        "identical": identity_before["sha256"] == identity_after["sha256"],
        "parameter_delta": 0,
    }
    repeat_receipt = {
        "receipt_id": "FASS01_S01_2_DETERMINISM_REPEAT_V01",
        "sample_size": len(repeat_receipt_rows),
        "selection": "first 256 event rows in sealed corpus order",
        "tokenizer_invoked_for_repeat": False,
        "rows": repeat_receipt_rows,
        "pass": len(repeat_receipt_rows) == 256 and all(all(row["feature_bytes_match"].values()) for row in repeat_receipt_rows),
    }
    extraction_receipt = {
        "receipt_id": "FASS01_S01_2_FEATURE_EXTRACTION_EXECUTION_V01",
        "project_id": binding["project_id"],
        "phase_id": binding["phase_id"],
        "authorization_packet_sha256": binding["contract_sha256"]["authorization_packet"],
        "preflight_root_sha256": preflight["root_sha256"],
        "model_id": MODEL_ID,
        "model_revision": REVISION,
        "model_asset_manifest_sha256": sha256_file(root / "model-asset-manifest-v01.json")[0],
        "parent_roots": {key: item["result_tree_root_sha256"] for key, item in binding["parent_roots"].items()},
        "input_sha256": binding["input_sha256"],
        "events_extracted": row_index,
        "quartets": 26624,
        "view_files": view_files,
        "feature_row_manifest": {"path": row_path.relative_to(root).as_posix(), "rows": row_index, "bytes": row_manifest_bytes, "sha256": row_manifest_hash},
        "hidden_dimension": 2048,
        "inference_dtype": "float32",
        "device": torch.cuda.get_device_name(0),
        "model_attn_implementation": getattr(model.config, "_attn_implementation", None),
        "single_row_exact_length_no_padding": True,
        "tokenizer_invoked": False,
        "backbone_parameter_delta": 0,
        "model_parameters_frozen": all(not parameter.requires_grad for parameter in model.parameters()),
        "feature_extraction_complete": True,
    }
    for name, payload in (
        ("backbone-identity-receipt-v01.json", parameter_receipt),
        ("determinism-repeat-receipt-v01.json", repeat_receipt),
        ("feature-extraction-receipt-v01.json", extraction_receipt),
    ):
        target = root / name
        if target.exists():
            raise RuntimeError(f"receipt already exists: {name}")
        target.write_bytes(json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
    state.stage = "FEATURE_EXTRACTION_COMPLETE"
    print(f"feature_extraction_complete={row_index} events, 7 views")
    print(f"backbone_parameter_identity={identity_before['sha256']} Δθ_LFM=0")
    print(f"deterministic_repeat_sample=256 pass=true")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract the seven sealed S01-2 frozen-LFM views")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    state = RunState()
    try:
        run(root, state)
        return 0
    except BaseException as exc:
        state.failure = f"{type(exc).__name__}: {exc}"
        print(f"FAIL_CLOSED stage={state.stage} error={state.failure}", file=sys.stderr, flush=True)
        write_failure(root, state)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
