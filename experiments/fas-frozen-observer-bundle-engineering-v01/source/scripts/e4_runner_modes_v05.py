"""Authorized E4-0 tokenizer, parity, and feature-only execution modes."""

import math

from e4_runner_common_v05 import *  # noqa: F401,F403
from e4_runner_artifacts_v05 import *  # noqa: F401,F403
from e4_gpu_lease_v04 import (
    allocator_is_zero,
    feature_bytes,
    gpu_allocator_snapshot,
    make_gpu_lease,
    query_process_peak_working_set,
    verify_abi_contract_identity,
    verify_gpu_limits,
    verify_local_assets,
    verify_local_tokenizer_assets,
    verify_online_runtime,
    verify_runtime_metadata_only,
)

def materialize_parity_panel(authorization: Mapping[str, Any]) -> dict[str, Any]:
    raise E4RunnerError("the E1 FIT parity panel is inherited from sealed v06; v09 may not rematerialize it")
    verify_bound_artifacts(authorization, ("e1_inputs", "e1_rows", "e1_splits", "e1_terms", "representation_abi", "tokenizer_manifest"))
    output_root = stage_output_root(authorization, "materialize-parity-panel")
    if output_root.exists():
        raise E4RunnerError("parity-panel output root already exists; preserving prior attempt")
    paths = authorization.get("paths", {})
    tokenizer_root = Path(paths.get("tokenizer_snapshot", "")).resolve(strict=True)
    term_path = Path(authorization["artifacts"]["e1_terms"]["path"])
    contexts, entities = load_term_sets(term_path)
    abi_entry = authorization["artifacts"]["representation_abi"]
    abi = read_json(Path(abi_entry["path"]))
    contract = verify_contract_binding(authorization)["contract"]
    verify_abi_contract_identity(contract, abi_entry, abi)
    if abi.get("representation_surface_semantics_unchanged_from_v01") is not True:
        raise E4RunnerError("representation ABI does not preserve the qualified E2 surface")
    verify_runtime_metadata_only(abi)
    tokenizer_manifest_path = Path(paths.get("tokenizer_asset_manifest", "")).resolve(strict=True)
    verify_local_tokenizer_assets(tokenizer_root, tokenizer_manifest_path, abi)
    import sys as system_module
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_root,
        use_fast=True,
        local_files_only=True,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise E4RunnerError("pinned tokenizer is not the required fast tokenizer")
    torch_module = system_module.modules.get("torch")
    if torch_module is not None and bool(torch_module.cuda.is_initialized()):
        raise E4RunnerError("tokenizer-only stage unexpectedly initialized CUDA")
    input_path = Path(authorization["artifacts"]["e1_inputs"]["path"])
    manifest_path = Path(authorization["artifacts"]["e1_rows"]["path"])
    split_path = Path(authorization["artifacts"]["e1_splits"]["path"])
    quartets = build_parity_quartets(
        iter_jsonl(input_path), iter_jsonl(manifest_path), iter_jsonl(split_path), contexts, entities,
        lambda text: tokenizer.encode(text, add_special_tokens=True, truncation=False),
    )
    selected = select_parity_quartets(quartets)
    output_root.mkdir(parents=True)
    inputs_path = output_root / "panel-inputs-v01.jsonl"
    rows_path = output_root / "row-manifest-v01.jsonl"
    receipt_path = output_root / "selection-receipt-v01.json"
    input_count = 0
    manifest_count = 0
    cell_counts: dict[str, int] = {}
    with inputs_path.open("xb", buffering=0) as inputs, rows_path.open("xb", buffering=0) as manifest:
        for quartet in selected:
            query_id = quartet["query_template_id"]
            quartile = quartet["quartile_id"]
            cell_counts[f"q{query_id}_t{quartile}"] = cell_counts.get(f"q{query_id}_t{quartile}", 0) + 1
            for row in quartet["rows"]:
                input_obj = {key: row[key] for key in ("row_id", "quartet_id", "variant_id", "input_text")}
                manifest_obj = {
                    "panel_row_index": manifest_count,
                    "cache_row_index": row["cache_row_index"],
                    "row_id": row["row_id"],
                    "quartet_id": row["quartet_id"],
                    "variant_id": row["variant_id"],
                    "query_template_id": query_id,
                    "quartile_id": quartile,
                    "quartet_max_token_count": quartet["max_token_count"],
                    "source_partition": "E1_FIT",
                }
                inputs.write(canonical_json_bytes(input_obj))
                manifest.write(canonical_json_bytes(manifest_obj))
                input_count += 1
                manifest_count += 1
        inputs.flush()
        os.fsync(inputs.fileno())
        manifest.flush()
        os.fsync(manifest.fileno())
    if input_count != PARITY_ROWS or manifest_count != PARITY_ROWS or set(cell_counts.values()) != {8}:
        raise E4RunnerError("materialized parity panel does not satisfy the frozen 256-quartet selector")
    receipt = {
        "receipt_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_PARITY_PANEL_V01",
        "status": "PARITY_PANEL_SEALED",
        "authorization_sha256": sha256_file(Path(authorization["authorization_path"]))[0],
        "e4_contract_root_sha256": authorization["contract_seal_root_sha256"],
        "e1_root_sha256": E1_ROOT,
        "e1_inputs": verify_bound_artifacts(authorization, ("e1_inputs",))["e1_inputs"],
        "e1_rows": verify_bound_artifacts(authorization, ("e1_rows",))["e1_rows"],
        "e1_splits": verify_bound_artifacts(authorization, ("e1_splits",))["e1_splits"],
        "representation_abi_sha256": abi_entry["sha256"],
        "tokenizer_manifest_sha256": authorization["artifacts"]["tokenizer_manifest"]["sha256"],
        "selector": {
            "whole_quartets": PARITY_QUARTETS,
            "rows": PARITY_ROWS,
            "query_template_ids": 8,
            "token_length_quartiles": 4,
            "selected_per_cell": 8,
            "ordering": "selected quartets by original E1 cache-row index; rows A,C,E,P",
            "cell_quartet_counts": cell_counts,
        },
        "output": {
            "panel_inputs_path": str(inputs_path.resolve()),
            "panel_inputs_sha256": sha256_file(inputs_path)[0],
            "panel_inputs_bytes": inputs_path.stat().st_size,
            "row_manifest_path": str(rows_path.resolve()),
            "row_manifest_sha256": sha256_file(rows_path)[0],
            "row_manifest_bytes": rows_path.stat().st_size,
        },
        "tokenizer_loaded": True,
        "tokenizer_contact_performed": True,
        "model_loaded": False,
        "model_contact_performed": False,
        "cuda_initialized": False,
        "labels_opened": False,
        "predictions_emitted": False,
    }
    write_json_exclusive(receipt_path, receipt)
    write_stage_seal(
        authorization,
        "PARITY_PANEL_MATERIALIZATION",
        output_root,
        {"panel_inputs": inputs_path, "panel_row_manifest": rows_path, "selection_receipt": receipt_path},
    )
    return receipt


def load_e3_heads(bundle_path: Path, authorization: Mapping[str, Any], np: Any) -> dict[str, dict[str, Any]]:
    bundle = read_json(bundle_path)
    if bundle.get("status") != "FROZEN_CAPABILITY_FABRIC_V02_TRAINING_ONLY_SCORING_CLOSED":
        raise E4RunnerError("E3 observer bundle status differs from the sealed training-only bundle")
    substrate = bundle.get("substrate", {})
    if (
        substrate.get("e0_v10_root_sha256") != E0_ROOT
        or substrate.get("e1_v04_root_sha256") != E1_ROOT
        or substrate.get("e2_v07_root_sha256") != E2_ROOT
        or bundle.get("e3_root_sha256", E3_BUNDLE_ROOT) != E3_BUNDLE_ROOT
    ):
        raise E4RunnerError("E3 bundle substrate roots differ from the qualified predecessor identities")
    observers = bundle.get("observers")
    if not isinstance(observers, dict) or set(observers) != set(HEADS):
        raise E4RunnerError("E3 bundle does not contain exactly the five frozen observers")
    result: dict[str, dict[str, Any]] = {}
    for name, classes in HEADS.items():
        head = observers[name]
        files = head.get("files", {})
        arrays = {}
        shapes = {"mean": (DIMENSION,), "scale": (DIMENSION,), "weight": (classes, DIMENSION), "bias": (classes,)}
        for key, shape in shapes.items():
            item = files.get(key)
            if not isinstance(item, dict):
                raise E4RunnerError(f"E3 bundle lacks {name}.{key}")
            path = Path(item["path"]).resolve(strict=True)
            digest, size = sha256_file(path)
            if digest != item.get("sha256") or size != item.get("bytes"):
                raise E4RunnerError(f"frozen E3 head file integrity failed: {name}.{key}")
            values = np.fromfile(path, dtype="<f4")
            expected_count = math.prod(shape)
            if values.size != expected_count or not bool(np.isfinite(values).all()):
                raise E4RunnerError(f"frozen E3 head has invalid shape or nonfinite values: {name}.{key}")
            arrays[key] = values.reshape(shape)
        if bool((arrays["scale"] <= 0).any()):
            raise E4RunnerError(f"frozen E3 head has a nonpositive feature scale: {name}")
        result[name] = arrays
    return result


def head_predictions(feature_rows: Any, heads: Mapping[str, Mapping[str, Any]], np: Any) -> dict[str, Any]:
    predictions: dict[str, Any] = {}
    for name in HEADS:
        head = heads[name]
        standardized = (feature_rows - head["mean"]) / head["scale"]
        logits = standardized @ head["weight"].T + head["bias"]
        if not bool(np.isfinite(logits).all()):
            raise E4RunnerError(f"frozen {name} head produced a nonfinite parity logit")
        predictions[name] = np.argmax(logits, axis=1)
    return predictions


def authorized_tokenizer_panel(authorization: Mapping[str, Any]) -> dict[str, Any]:
    del authorization
    raise E4RunnerError("the E1 FIT parity panel is inherited from sealed v06; v09 tokenizer contact is not authorized")


def load_online_runtime_and_model(authorization: Mapping[str, Any], abi: Mapping[str, Any]) -> tuple[Any, Any, Any, Any, dict[str, str], dict[str, Any]]:
    model_root, tokenizer_root = verify_local_assets(authorization, abi)
    np, torch, transformers, versions = verify_online_runtime(abi)
    device = torch.device("cuda:0")
    initial = gpu_allocator_snapshot(torch, "after_cuda_initialization_before_peak_reset")
    if not allocator_is_zero(initial):
        raise E4RunnerError("CUDA allocator baseline is not exactly zero before peak reset")
    torch.cuda.reset_peak_memory_stats(device)
    post_reset = gpu_allocator_snapshot(torch, "after_peak_reset_before_tokenizer_or_model_load")
    if not allocator_is_zero(post_reset):
        raise E4RunnerError("CUDA allocator baseline is not exactly zero after peak reset")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        tokenizer_root,
        use_fast=True,
        local_files_only=True,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise E4RunnerError("pinned tokenizer is not fast")
    model = transformers.AutoModel.from_pretrained(
        model_root,
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=torch.float32,
    )
    model.eval()
    model.to(device)
    if getattr(model.config, "hidden_size", None) != DIMENSION:
        raise E4RunnerError("loaded model hidden dimension differs from the ABI")
    if any(parameter.grad is not None for parameter in model.parameters()):
        raise E4RunnerError("loaded frozen model unexpectedly has gradients")
    return np, torch, transformers, (model, tokenizer), versions, {"pre_reset": initial, "post_reset": post_reset}


def online_authorization_preflight(authorization: Mapping[str, Any], mode: str) -> tuple[dict[str, Any], dict[str, Any]]:
    verified_contract = validate_stage_authorization(authorization, mode)
    verify_predecessor_audits(authorization, mode)
    required = ["representation_abi", "model_manifest", "tokenizer_manifest"]
    if mode == "parity":
        required.extend(("parity_inputs", "parity_rows", "parity_selection_receipt", "e2_cache", "e3_bundle"))
    elif mode == "extract-e4":
        required.extend(("population_inputs", "population_rows"))
    verified = verify_bound_artifacts(authorization, required)
    abi = read_json(Path(verified["representation_abi"]["path"]))
    verify_abi_contract_identity(verified_contract["contract"], verified["representation_abi"], abi)
    if abi.get("representation_abi_id") != "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V07":
        raise E4RunnerError("E2 v07 representation ABI identity mismatch")
    if abi.get("surface_id") != "V1_FINAL_POSITION" and abi.get("forward_call", {}).get("surface_id") != "V1_FINAL_POSITION":
        raise E4RunnerError("online runner is not bound to V1_FINAL_POSITION")
    if abi.get("forward_call", {}).get("tensor_identity") != "output.last_hidden_state[0, sequence_length - 1, :]":
        raise E4RunnerError("online runner tensor identity differs from E2 v07")
    paths = authorization.get("paths", {})
    if Path(paths.get("model_asset_manifest", "")).resolve(strict=True) != Path(verified["model_manifest"]["path"]).resolve(strict=True):
        raise E4RunnerError("model asset manifest path differs from the authorized artifact identity")
    if Path(paths.get("tokenizer_asset_manifest", "")).resolve(strict=True) != Path(verified["tokenizer_manifest"]["path"]).resolve(strict=True):
        raise E4RunnerError("tokenizer asset manifest path differs from the authorized artifact identity")
    model_root, tokenizer_root = verify_local_assets(authorization, abi)
    preflight_inputs = {**verified, "abi": abi, "model_snapshot": model_root, "tokenizer_snapshot": tokenizer_root}
    if mode == "parity":
        verify_parity_panel_before_model(authorization, preflight_inputs)
    elif mode == "extract-e4":
        verify_population_rows_before_model(authorization)
    return verified_contract, preflight_inputs


def verify_parity_panel_before_model(authorization: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
    panel_receipt = read_json(Path(inputs["parity_selection_receipt"]["path"]))
    seal_artifact = read_json(Path(authorization["artifacts"]["parity_panel_seal"]["path"]))
    if panel_receipt.get("selector", {}).get("whole_quartets") != PARITY_QUARTETS:
        raise E4RunnerError("parity panel receipt does not bind 256 whole quartets")
    if panel_receipt.get("output", {}).get("panel_inputs_sha256") != inputs["parity_inputs"]["sha256"]:
        raise E4RunnerError("parity panel input hash differs from its selection receipt")
    entries = {entry["artifact_id"]: entry for entry in seal_artifact.get("entries", [])}
    for key, artifact_id in (("parity_inputs", "panel_inputs"), ("parity_rows", "panel_row_manifest"), ("parity_selection_receipt", "selection_receipt")):
        member = entries.get(artifact_id)
        if member is None or member["sha256"] != inputs[key]["sha256"] or int(member["bytes"]) != int(inputs[key]["bytes"]):
            raise E4RunnerError(f"parity panel seal does not contain the authorized {key}")
    rows = list(iter_jsonl(Path(inputs["parity_inputs"]["path"])))
    manifest = list(iter_jsonl(Path(inputs["parity_rows"]["path"])))
    if len(rows) != PARITY_ROWS or len(manifest) != PARITY_ROWS:
        raise E4RunnerError("sealed parity panel is not 256 quartets / 1,024 rows")
    cache_indices: set[int] = set()
    for index, (input_row, row) in enumerate(zip(rows, manifest)):
        expected_input = {"row_id", "quartet_id", "variant_id", "input_text"}
        expected_row = {"panel_row_index", "cache_row_index", "row_id", "quartet_id", "variant_id", "query_template_id", "quartile_id", "quartet_max_token_count", "source_partition"}
        if set(input_row) != expected_input or set(row) != expected_row or row.get("panel_row_index") != index:
            raise E4RunnerError("parity panel row schema or order is invalid")
        if row.get("source_partition") != "E1_FIT" or any(input_row.get(key) != row.get(key) for key in ("row_id", "quartet_id", "variant_id")):
            raise E4RunnerError("parity panel row identity/partition mismatch")
        cache_indices.add(int(row["cache_row_index"]))
    if len(cache_indices) != PARITY_ROWS or min(cache_indices) < 0 or max(cache_indices) >= E1_ROWS:
        raise E4RunnerError("parity panel cache row mapping is duplicated or outside E1")
    cache_digest, cache_size = sha256_file(Path(inputs["e2_cache"]["path"]))
    if cache_digest != E1_CACHE_SHA256 or cache_size != E1_CACHE_BYTES:
        raise E4RunnerError("pinned E2 v07 cache failed pre-model identity verification")


def run_online_mode(authorization: Mapping[str, Any], mode: str) -> dict[str, Any]:
    verified_contract, inputs = online_authorization_preflight(authorization, mode)
    output_root = stage_output_root(authorization, mode)
    if output_root.exists():
        raise E4RunnerError("online-mode output root already exists; preserving any prior attempt")
    lease = make_gpu_lease(authorization, mode, output_root)
    output_root.mkdir(parents=True)
    lease.acquire()
    terminal_status = "STOPPED_PRESERVED"
    lease_receipt: dict[str, Any] | None = None
    last_release_snapshot: dict[str, Any] = {}
    try:
        np, torch, _transformers, loaded, versions, allocator_baseline = load_online_runtime_and_model(
            authorization, inputs["abi"],
        )
        model, tokenizer = loaded
        if mode == "parity":
            receipt = run_parity_payload(authorization, inputs, model, tokenizer, torch, np, versions, allocator_baseline, output_root)
        elif mode == "extract-e4":
            receipt = run_e4_feature_payload(authorization, inputs, model, tokenizer, torch, np, versions, allocator_baseline, output_root)
        else:
            raise E4RunnerError(f"unsupported online mode: {mode}")
        terminal_status = receipt["status"]
        release_snapshot = gpu_allocator_snapshot(torch, "before_gpu_lease_release")
        ram_peak = query_process_peak_working_set(os.getpid())
        release_snapshot["process_peak_working_set_bytes"] = ram_peak
        release_snapshot["process_peak_working_set_measurement_source"] = "Windows Get-Process -Id <extractor PID>.PeakWorkingSet64"
        release_snapshot["process_peak_working_set_scope"] = "extractor process only; not machine-wide RAM"
        last_release_snapshot = release_snapshot
        verify_gpu_limits(release_snapshot, ram_peak)
        lease_receipt = lease.release(release_snapshot, terminal_status)
        receipt["gpu_lease_receipt"] = lease_receipt
        receipt["gpu_lease_receipt_sha256"] = sha256_file(lease.receipt_path)[0]
        receipt["extractor_process_memory"] = {
            "peak_working_set_bytes": ram_peak,
            "limit_bytes": HOST_RAM_LIMIT_BYTES,
            "measurement_source": "Windows Get-Process -Id <extractor PID>.PeakWorkingSet64",
            "scope": "extractor process only; not machine-wide RAM",
            "measurement_pid": os.getpid(),
        }
        if mode == "extract-e4":
            receipt["resource"]["gpu_allocator"] = release_snapshot
            receipt["resource"]["host_ram_process_peak_working_set_bytes"] = ram_peak
        else:
            receipt["gpu_allocator"] = release_snapshot
            receipt["host_ram_process_peak_working_set_bytes"] = ram_peak
        receipt_path = output_root / ("parity-receipt-v01.json" if mode == "parity" else "feature-extraction-receipt-v01.json")
        write_json_exclusive(receipt_path, receipt)
        artifacts: dict[str, Path] = {
            "gpu_lease_receipt": lease.receipt_path,
            "parity_receipt" if mode == "parity" else "feature_extraction_receipt": receipt_path,
        }
        if mode == "parity":
            artifacts["online_feature_cache"] = output_root / "parity-online-features.f32le"
            stage = "ONLINE_CACHE_PARITY"
        else:
            artifacts["feature_cache"] = output_root / "V1_FINAL_POSITION.f32le"
            artifacts["population_row_manifest"] = Path(inputs["population_rows"]["path"])
            stage = "FRESH_FEATURE_EXTRACTION"
        write_stage_seal(authorization, stage, output_root, artifacts)
        return receipt
    except Exception as error:
        if lease.acquired:
            snapshot: dict[str, Any] = {
                **last_release_snapshot,
                "release_reason": "preserve_after_runner_exception",
                "error": f"{type(error).__name__}: {error}",
            }
            try:
                snapshot["process_peak_working_set_bytes"] = query_process_peak_working_set(os.getpid())
                snapshot["process_peak_working_set_measurement_source"] = "Windows Get-Process -Id <extractor PID>.PeakWorkingSet64"
                snapshot["process_peak_working_set_scope"] = "extractor process only; not machine-wide RAM"
            except Exception as ram_error:
                snapshot["process_peak_working_set_error"] = f"{type(ram_error).__name__}: {ram_error}"
            lease_receipt = lease.release(snapshot, "STOPPED_PRESERVED")
        raise


def run_parity_payload(
    authorization: Mapping[str, Any],
    inputs: Mapping[str, Any],
    model: Any,
    tokenizer: Any,
    torch: Any,
    np: Any,
    versions: Mapping[str, str],
    allocator_baseline: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    panel_receipt_path = Path(inputs["parity_selection_receipt"]["path"])
    panel_receipt = read_json(panel_receipt_path)
    if panel_receipt.get("selector", {}).get("whole_quartets") != PARITY_QUARTETS or panel_receipt.get("output", {}).get("panel_inputs_sha256") != inputs["parity_inputs"]["sha256"]:
        raise E4RunnerError("sealed parity panel receipt does not bind the expected selector/input")
    panel_inputs = list(iter_jsonl(Path(inputs["parity_inputs"]["path"])))
    panel_rows = list(iter_jsonl(Path(inputs["parity_rows"]["path"])))
    if len(panel_inputs) != PARITY_ROWS or len(panel_rows) != PARITY_ROWS:
        raise E4RunnerError("sealed parity panel is not exactly 1,024 rows")
    cache_indices: list[int] = []
    for index, (input_row, manifest) in enumerate(zip(panel_inputs, panel_rows)):
        if set(input_row) != {"row_id", "quartet_id", "variant_id", "input_text"}:
            raise E4RunnerError("parity panel input contains a label or unexpected field")
        required = {"panel_row_index", "cache_row_index", "row_id", "quartet_id", "variant_id", "query_template_id", "quartile_id", "quartet_max_token_count", "source_partition"}
        if set(manifest) != required or manifest.get("panel_row_index") != index or manifest.get("source_partition") != "E1_FIT":
            raise E4RunnerError("parity row manifest differs from the frozen panel schema")
        for key in ("row_id", "quartet_id", "variant_id"):
            if input_row.get(key) != manifest.get(key):
                raise E4RunnerError("parity panel input and row map identity mismatch")
        cache_indices.append(int(manifest["cache_row_index"]))
    if len(set(cache_indices)) != PARITY_ROWS or min(cache_indices) < 0 or max(cache_indices) >= E1_ROWS:
        raise E4RunnerError("parity cache row indices are duplicate or out of range")
    e2_cache = read_numpy_cache(
        Path(inputs["e2_cache"]["path"]), E1_ROWS, E1_CACHE_SHA256, E1_CACHE_BYTES, np,
    )
    cache_rows = np.asarray(e2_cache[np.asarray(cache_indices, dtype=np.int64)], dtype="<f4", order="C")
    online_rows = np.empty((PARITY_ROWS, DIMENSION), dtype="<f4")
    temp_feature_path = output_root / "parity-online-features.f32le"
    with temp_feature_path.open("xb", buffering=0) as output:
        for index, input_row in enumerate(panel_inputs):
            encoded, _token_count = feature_bytes(model, tokenizer, torch, np, input_row["input_text"])
            output.write(encoded)
            online_rows[index] = np.frombuffer(encoded, dtype="<f4")
        output.flush()
        os.fsync(output.fileno())
    if temp_feature_path.stat().st_size != PARITY_ROWS * FEATURE_ROW_BYTES:
        raise E4RunnerError("online parity feature cache has the wrong byte length")
    differences = np.abs(online_rows - cache_rows)
    max_deviation = float(differences.max(initial=0.0))
    exact_bytes = temp_feature_path.read_bytes() == cache_rows.tobytes(order="C")
    bundle = Path(inputs["e3_bundle"]["path"])
    heads = load_e3_heads(bundle, authorization, np)
    cache_predictions = head_predictions(cache_rows, heads, np)
    online_predictions = head_predictions(online_rows, heads, np)
    head_agreement = {
        name: float(np.mean(cache_predictions[name] == online_predictions[name]))
        for name in HEADS
    }
    passed = exact_bytes and max_deviation == 0.0 and all(value == 1.0 for value in head_agreement.values())
    resource = gpu_allocator_snapshot(torch, "after_parity_extraction_and_heads")
    if resource["allocated_peak_since_reset_bytes"] > resource["reserved_peak_since_reset_bytes"] or resource["reserved_peak_since_reset_bytes"] > GPU_RESERVED_LIMIT_BYTES:
        passed = False
    receipt = {
        "receipt_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_ONLINE_CACHE_PARITY_V01",
        "status": "ONLINE_CACHE_PARITY_PASS" if passed else "FAIL_ONLINE_CACHE_PARITY_PRESERVED",
        "e4_contract_root_sha256": verified_contract_root(authorization),
        "e1_root_sha256": E1_ROOT,
        "e2_root_sha256": E2_ROOT,
        "e3_bundle_root_sha256": E3_BUNDLE_ROOT,
        "parity_panel_root_sha256": authorization.get("exact_predecessor_roots", {}).get("e4_parity_panel_root_sha256"),
        "panel_inputs_sha256": inputs["parity_inputs"]["sha256"],
        "panel_rows_sha256": inputs["parity_rows"]["sha256"],
        "feature_abi": {
            "surface": "V1_FINAL_POSITION",
            "tensor_identity": "output.last_hidden_state[0, sequence_length - 1, :]",
            "device": "cuda:0",
            "dtype": "float32",
            "batch_size": 1,
            "padding": False,
            "truncation": False,
            "dimension": DIMENSION,
        },
        "online_feature_sha256": sha256_file(temp_feature_path)[0],
        "online_feature_bytes": temp_feature_path.stat().st_size,
        "feature_cache_byte_equality": exact_bytes,
        "feature_byte_identical": exact_bytes,
        "maximum_absolute_feature_deviation": max_deviation,
        "feature_max_abs_deviation": max_deviation,
        "prediction_agreement_each_of_five_heads": head_agreement,
        "prediction_agreement_by_head": head_agreement,
        "heads_used": list(HEADS),
        "runtime_versions": dict(versions),
        "allocator_baseline": dict(allocator_baseline),
        "gpu_allocator": resource,
        "device_wide_gpu_memory_claimed": False,
        "total_gpu_memory_claimed": False,
        "labels_opened": False,
        "fresh_e4_rows_read": False,
        "fresh_e4_predictions_emitted": False,
        "heldout_template_or_joint_truth_opened": False,
        "scoring_performed": False,
    }
    if not passed:
        raise E4RunnerError("online/cache parity or resource gate failed; panel output and attempt preserved")
    return receipt


def run_e4_feature_payload(
    authorization: Mapping[str, Any],
    inputs: Mapping[str, Any],
    model: Any,
    tokenizer: Any,
    torch: Any,
    np: Any,
    versions: Mapping[str, str],
    allocator_baseline: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    input_path = Path(inputs["population_inputs"]["path"])
    manifest_path = Path(inputs["population_rows"]["path"])
    input_before = sha256_file(input_path)
    manifest_before = sha256_file(manifest_path)
    if input_before != (inputs["population_inputs"]["sha256"], inputs["population_inputs"]["bytes"]):
        raise E4RunnerError("population input changed after pre-model verification")
    if manifest_before != (inputs["population_rows"]["sha256"], inputs["population_rows"]["bytes"]):
        raise E4RunnerError("population manifest changed after pre-model verification")
    feature_path = output_root / "V1_FINAL_POSITION.f32le"
    staging_path = output_root / "V1_FINAL_POSITION.f32le.partial"
    if feature_path.exists() or staging_path.exists():
        raise E4RunnerError("E4 feature cache output already exists; preserving prior attempt")
    row_count = 0
    with staging_path.open("xb", buffering=0) as output:
        for input_row, manifest in iter_validated_e4_rows(input_row_stream(input_path, manifest_path)):
            del manifest
            encoded, _token_count = feature_bytes(model, tokenizer, torch, np, input_row["input_text"])
            output.write(encoded)
            row_count += 1
        output.flush()
        os.fsync(output.fileno())
    if row_count != E4_ROWS or staging_path.stat().st_size != E4_CACHE_BYTES:
        raise E4RunnerError("E4 cache row count or byte length differs from the frozen support plan")
    digest, size = sha256_file(staging_path)
    cache = np.memmap(staging_path, dtype="<f4", mode="r", shape=(E4_ROWS, DIMENSION), order="C")
    finite = True
    for start in range(0, E4_ROWS, 2_048):
        if not bool(np.isfinite(cache[start : start + 2_048]).all()):
            finite = False
            break
    del cache
    if not finite:
        raise E4RunnerError("E4 feature cache contains nonfinite values; staging attempt preserved")
    os.replace(staging_path, feature_path)
    cache_sha, cache_bytes = sha256_file(feature_path)
    if cache_sha != digest or cache_bytes != size:
        raise E4RunnerError("feature cache identity changed during atomic finalization")
    row_digest, row_bytes = sha256_file(manifest_path)
    input_digest, input_bytes = sha256_file(input_path)
    if (input_digest, input_bytes) != input_before or (row_digest, row_bytes) != manifest_before:
        raise E4RunnerError("population inputs or manifest changed during feature extraction; cache attempt preserved")
    receipt = {
        "receipt_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_FEATURE_EXTRACTION_V01",
        "status": "FEATURE_CACHE_COMPLETE_GATE_PASS",
        "e4_contract_root_sha256": verified_contract_root(authorization),
        "e1_root_sha256": E1_ROOT,
        "e2_v07_root_sha256": E2_ROOT,
        "e3_v02_bundle_root_sha256": E3_BUNDLE_ROOT,
        "population_root_sha256": authorization["exact_predecessor_roots"]["e4_population_root_sha256"],
        "representation_abi_sha256": inputs["representation_abi"]["sha256"],
        "population_inputs": {"path": str(input_path.resolve()), "sha256": input_digest, "bytes": input_bytes},
        "population_row_manifest": {"path": str(manifest_path.resolve()), "sha256": row_digest, "bytes": row_bytes},
        "feature_cache": {
            "path": str(feature_path.resolve()),
            "sha256": cache_sha,
            "bytes": cache_bytes,
            "rows": row_count,
            "row_count": row_count,
            "dimension": DIMENSION,
            "feature_dim": DIMENSION,
            "dtype": "<f4",
            "layout": "C_ROW_MAJOR",
            "dtype_description": "little-endian float32",
            "row_mapping": "row i maps to manifest row_index i",
            "finite_scan_passed": finite,
        },
        "row_identity": {
            "ordered_manifest_match": True,
            "ordered_row_identity_match": True,
            "manifest_sha256": row_digest,
            "input_sha256": input_digest,
            "surface_id_values": [PRIMARY_SURFACE, HELDOUT_SURFACE],
            "truth_partition_values": [PRIMARY_CUSTODY, ESCROW_CUSTODY],
            "quartet_atomicity_and_order_verified": True,
            "row_count": row_count,
        },
        "resource": {
            "gpu_allocator_scope": "extractor-process PyTorch CUDA caching allocator only",
            "reserved_peak_limit_bytes": GPU_RESERVED_LIMIT_BYTES,
            "total_gpu_memory_claimed": False,
            "host_ram_peak_limit_bytes": HOST_RAM_LIMIT_BYTES,
            "host_ram_measurement_source": "Windows Get-Process -Id <extractor PID>.PeakWorkingSet64",
            "host_ram_measurement_scope": "extractor process only; not machine-wide RAM",
            "host_ram_process_peak_working_set_bytes": None,
            "allocator_baseline": dict(allocator_baseline),
            "no_cuda_allocator_or_device-total conflation": True,
        },
        "runtime_versions": dict(versions),
        "labels_opened": False,
        "predictions_emitted": False,
        "class_support_emitted": False,
        "heldout_template_or_joint_labels_opened": False,
        "heldout_template_or_joint_predictions_emitted": False,
        "observer_fitting_performed": False,
        "scoring_performed": False,
    }
    return receipt
