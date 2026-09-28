from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .constants import GATES, TASKS, EXPECTED_PREDECESSORS, INHERITED_V06_SEAL
from .integrity import AuditError, Seal, read_json, read_jsonl_stream, sha256_file, verify_e4_stage_seal
from .replay import _cpu_torch_predict, load_heads


PANEL_MEMBER_IDS = frozenset({"panel_inputs", "panel_row_manifest", "selection_receipt"})
PARITY_MEMBER_IDS = frozenset({"gpu_lease_receipt", "parity_receipt", "online_feature_cache"})
FEATURE_MEMBER_IDS = frozenset({"gpu_lease_receipt", "feature_extraction_receipt", "feature_cache", "population_row_manifest"})


def _entry(seal: Seal, artifact_id: str):
    try:
        return seal.entries[artifact_id]
    except KeyError as exc:
        raise AuditError(f"stage seal is missing {artifact_id}") from exc


def _cache(path: Path, rows: int, *, dimension: int = GATES.feature_dimension) -> np.memmap:
    expected_bytes = rows * dimension * np.dtype("<f4").itemsize
    if path.stat().st_size != expected_bytes:
        raise AuditError(f"feature cache has wrong length: expected {expected_bytes} bytes")
    data = np.memmap(path, dtype="<f4", mode="r", shape=(rows, dimension), order="C")
    for start in range(0, rows, 2_048):
        if not bool(np.isfinite(data[start : start + 2_048]).all()):
            raise AuditError("feature cache contains non-finite values")
    return data


def verify_feature_stage(
    *,
    seal_path: Path,
    run_root: Path,
    contract_sha256: str,
    contract_root_sha256: str,
    panel_predecessors: Mapping[str, str],
    parity_predecessors: Mapping[str, str],
    expected_rows: int = GATES.total_rows,
) -> dict[str, Any]:
    seal = verify_e4_stage_seal(
        seal_path,
        root=run_root,
        expected_stage="FRESH_FEATURE_EXTRACTION",
        current_contract_sha256=contract_sha256,
        current_contract_root_sha256=contract_root_sha256,
        expected_predecessors=panel_predecessors,
        allowed_entry_ids=FEATURE_MEMBER_IDS,
    )
    receipt = read_json(_entry(seal, "feature_extraction_receipt").path)
    if (
        receipt.get("status") != "FEATURE_CACHE_COMPLETE_GATE_PASS"
        or receipt.get("e4_contract_root_sha256") != contract_root_sha256
    ):
        raise AuditError("feature-extraction receipt is not passing")
    cache_member = _entry(seal, "feature_cache")
    manifest_member = _entry(seal, "population_row_manifest")
    if cache_member.bytes != expected_rows * GATES.feature_dimension * 4:
        raise AuditError("sealed feature cache byte count differs from row x feature shape")
    if receipt.get("feature_cache", {}).get("sha256") != cache_member.sha256 or receipt.get("feature_cache", {}).get("bytes") != cache_member.bytes:
        raise AuditError("feature receipt cache identity differs from stage seal")
    cache_meta = receipt.get("feature_cache", {})
    if cache_meta.get("rows") != expected_rows or cache_meta.get("dimension") != GATES.feature_dimension:
        raise AuditError("feature receipt shape differs from frozen ABI")
    if cache_meta.get("dtype") != "<f4" or cache_meta.get("layout") != "C_ROW_MAJOR" or cache_meta.get("finite_scan_passed") is not True:
        raise AuditError("feature receipt dtype/layout/finiteness differs from frozen ABI")
    row_meta = receipt.get("row_identity", {})
    if row_meta.get("ordered_manifest_match") is not True or row_meta.get("ordered_row_identity_match") is not True or row_meta.get("row_count") != expected_rows:
        raise AuditError("feature receipt ordered row mapping did not pass")
    resource = receipt.get("resource", {})
    if resource.get("total_gpu_memory_claimed") is not False or resource.get("gpu_allocator_scope") != "extractor-process PyTorch CUDA caching allocator only":
        raise AuditError("feature resource receipt broadens the frozen process-scoped GPU claim")
    if receipt.get("labels_opened") is not False or receipt.get("predictions_emitted") is not False or receipt.get("heldout_template_or_joint_truth_opened") is not False:
        raise AuditError("feature extraction crossed the frozen truth/prediction boundary")
    if manifest_member.relative_path != "population/row-manifest-v01.jsonl":
        raise AuditError("feature stage does not bind the normative population row manifest")
    digest, byte_count = sha256_file(manifest_member.path)
    if row_meta.get("manifest_sha256") != digest or row_meta.get("input_sha256") != receipt.get("population_inputs", {}).get("sha256"):
        raise AuditError("feature receipt input/manifest identity does not match sealed members")
    feature_cache = _cache(cache_member.path, expected_rows)
    del feature_cache
    return {
        "status": "PASS_FEATURE_CACHE_INTEGRITY",
        "feature_root_sha256": seal.root_sha256,
        "cache_sha256": cache_member.sha256,
        "cache_bytes": cache_member.bytes,
        "row_manifest_sha256": digest,
        "row_manifest_bytes": byte_count,
        "rows": expected_rows,
        "dimension": GATES.feature_dimension,
        "finite_scan_passed": True,
    }


def _read_panel(e1_inputs: Path, e1_manifest: Path, panel_inputs: Path, panel_manifest: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    source_inputs = list(read_jsonl_stream(e1_inputs))
    source_rows = list(read_jsonl_stream(e1_manifest))
    if len(source_inputs) != 106_496 or len(source_rows) != len(source_inputs):
        raise AuditError("parity source E1 row population has an unexpected size")
    panel_text = list(read_jsonl_stream(panel_inputs))
    panel_rows = list(read_jsonl_stream(panel_manifest))
    if len(panel_text) != 1_024 or len(panel_rows) != 1_024:
        raise AuditError("parity panel does not contain 256 complete quartets")
    indices: list[int] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    cell_counts: dict[tuple[int, int], int] = {}
    quartet_first_indices: list[int] = []
    for index, (item, row) in enumerate(zip(panel_text, panel_rows, strict=True)):
        if set(item) != {"row_id", "quartet_id", "variant_id", "input_text"}:
            raise AuditError("parity input row has unexpected fields")
        required = {
            "panel_row_index", "cache_row_index", "row_id", "quartet_id", "variant_id",
            "query_template_id", "quartile_id", "quartet_max_token_count", "source_partition",
        }
        if set(row) != required or row.get("panel_row_index") != index or row.get("source_partition") != "E1_FIT":
            raise AuditError("parity panel manifest differs from the frozen selector schema")
        query_id, quartile = row.get("query_template_id"), row.get("quartile_id")
        if type(query_id) is not int or not 0 <= query_id < 8 or type(quartile) is not int or not 0 <= quartile < 4:
            raise AuditError("parity panel template/quartile assignment is malformed")
        cell = (query_id, quartile)
        cell_counts[cell] = cell_counts.get(cell, 0) + (1 if row["variant_id"] == "A" else 0)
        cache_index = row.get("cache_row_index")
        if type(cache_index) is not int or not 0 <= cache_index < len(source_rows):
            raise AuditError("parity panel source cache index is invalid")
        original, original_manifest = source_inputs[cache_index], source_rows[cache_index]
        for key in ("row_id", "quartet_id", "variant_id"):
            if item.get(key) != row.get(key) or item.get(key) != original.get(key) or item.get(key) != original_manifest.get(key):
                raise AuditError(f"parity panel source row identity mismatch: {key}")
        if item.get("input_text") != original.get("input_text"):
            raise AuditError("parity panel text differs from its E1 source row")
        indices.append(cache_index)
        qid = str(row["quartet_id"])
        if qid not in grouped:
            quartet_first_indices.append(cache_index)
            grouped[qid] = []
        grouped[qid].append(row)
    if len(grouped) != 256 or any(tuple(row["variant_id"] for row in rows) != ("A", "C", "E", "P") for rows in grouped.values()):
        raise AuditError("parity panel does not preserve whole A/C/E/P quartets")
    if set(cell_counts.values()) != {8} or quartet_first_indices != sorted(quartet_first_indices):
        raise AuditError("parity panel cell counts or original-cache ordering differ from the frozen selector")
    return panel_text, panel_rows, indices


def verify_parity_stage(
    *,
    panel_seal_path: Path,
    parity_seal_path: Path,
    run_root: Path,
    contract_sha256: str,
    contract_root_sha256: str,
    panel_predecessors: Mapping[str, str],
    parity_predecessors: Mapping[str, str],
    e1_inputs: Path,
    e1_manifest: Path,
    e1_feature_cache: Path,
    e1_feature_cache_sha256: str,
    e3_seal_path: Path,
    e3_root_sha256: str = EXPECTED_PREDECESSORS["e3_v02_bundle_root_sha256"],
) -> dict[str, Any]:
    panel_seal = verify_e4_stage_seal(
        panel_seal_path,
        root=run_root,
        expected_stage="PARITY_PANEL_MATERIALIZATION",
        current_contract_sha256=contract_sha256,
        current_contract_root_sha256=contract_root_sha256,
        expected_predecessors=panel_predecessors,
        allowed_entry_ids=PANEL_MEMBER_IDS,
    )
    panel_receipt = read_json(_entry(panel_seal, "selection_receipt").path)
    if (
        panel_receipt.get("status") != "PARITY_PANEL_SEALED"
        or panel_receipt.get("e4_contract_root_sha256") != INHERITED_V06_SEAL["root_sha256"]
        or panel_receipt.get("predictions_emitted") is not False
        or panel_receipt.get("labels_opened") is not False
    ):
        raise AuditError("parity panel receipt does not preserve label-free pre-model boundary")
    panel_inputs, panel_rows, source_indices = _read_panel(
        e1_inputs, e1_manifest, _entry(panel_seal, "panel_inputs").path,
        _entry(panel_seal, "panel_row_manifest").path,
    )
    e1_cache_sha, e1_cache_bytes = sha256_file(e1_feature_cache)
    if e1_cache_sha != e1_feature_cache_sha256 or e1_cache_bytes != 872_415_232:
        raise AuditError("E1 feature cache differs from the frozen E2 v07 reference identity")
    base = np.memmap(e1_feature_cache, dtype="<f4", mode="r", shape=(106_496, GATES.feature_dimension), order="C")
    parity_seal = verify_e4_stage_seal(
        parity_seal_path,
        root=run_root,
        expected_stage="ONLINE_CACHE_PARITY",
        current_contract_sha256=contract_sha256,
        current_contract_root_sha256=contract_root_sha256,
        expected_predecessors=parity_predecessors,
        allowed_entry_ids=PARITY_MEMBER_IDS,
    )
    receipt = read_json(_entry(parity_seal, "parity_receipt").path)
    if (
        receipt.get("status") != "ONLINE_CACHE_PARITY_PASS"
        or receipt.get("e4_contract_root_sha256") != contract_root_sha256
        or receipt.get("feature_byte_identical") is not True
        or receipt.get("total_gpu_memory_claimed") is not False
        or receipt.get("labels_opened") is not False
        or receipt.get("fresh_e4_predictions_emitted") is not False
        or receipt.get("heldout_template_or_joint_truth_opened") is not False
    ):
        raise AuditError("online/cache parity receipt failed frozen exact-byte or resource semantics")
    online_member = _entry(parity_seal, "online_feature_cache")
    online = _cache(online_member.path, 1_024)
    for position, source_index in enumerate(source_indices):
        if online[position].tobytes(order="C") != base[source_index].tobytes(order="C"):
            raise AuditError(f"online parity feature bytes differ from E1 cache at panel row {position}")
    heads = load_heads(e3_seal_path, e3_root_sha256)
    online_predictions: dict[str, np.ndarray] = {}
    cached_predictions: dict[str, np.ndarray] = {}
    selected_cached = np.asarray(base[source_indices], dtype=np.float32, order="C")
    for task in TASKS:
        online_predictions[task] = _cpu_torch_predict(np.asarray(online), heads[task])
        cached_predictions[task] = _cpu_torch_predict(selected_cached, heads[task])
    computed_agreement = {
        task: float(np.mean(online_predictions[task] == cached_predictions[task]))
        for task in TASKS
    }
    agreements = receipt.get("prediction_agreement_by_head")
    if (
        not isinstance(agreements, dict)
        or set(agreements) != set(TASKS)
        or any(value != 1.0 for value in agreements.values())
        or computed_agreement != {task: 1.0 for task in TASKS}
    ):
        raise AuditError("parity receipt does not report 100% agreement for each of the five heads")
    del online, base
    return {
        "status": "PASS_ONLINE_CACHE_PARITY",
        "panel_root_sha256": panel_seal.root_sha256,
        "parity_root_sha256": parity_seal.root_sha256,
        "panel_quartets": 256,
        "panel_rows": len(panel_inputs),
        "feature_bytes_identical": True,
        "prediction_agreement_by_head": computed_agreement,
        "e1_feature_cache_bytes": e1_cache_bytes,
    }
