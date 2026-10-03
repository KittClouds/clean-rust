from __future__ import annotations

import os
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from common import (
    AUTHORIZATION_PATH,
    BINDING_PATH,
    CONTRACT_PATH,
    PHASE_ROOT,
    PARENT_CACHE_ROOT,
    PROTOCOL_PATH,
    RESULT_ROOT,
    TASKS,
    VIEWS,
    feature_cache_paths,
    file_entry,
    fit_masks,
    load_event_metadata,
    read_json,
    save_metadata,
    sha256_file,
    snapshot_inputs,
    task_classes,
    test_condition_masks,
    tree_root,
    verify_entries,
    write_json,
)
from linear_core import configure_determinism, synthetic_self_test


def _label_array(fields: dict[str, np.ndarray], task: str) -> np.ndarray:
    return {
        "CONTEXT_IDENTITY": fields["context_id"],
        "ENTITY_IDENTITY": fields["entity_id"],
        "RELATION_IDENTITY": fields["relation"],
        "OBSERVED_STATE": fields["state"],
        "EXACT_TARGET": fields["target"],
    }[task]


def _check_parent_inputs(binding: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    result_root, _, cache_seal_path, _ = feature_cache_paths(binding)
    result_seal = read_json(result_root / "seals" / "result-tree-seal-v01.json")
    cache_seal = read_json(cache_seal_path)
    validation = read_json(result_root / "feature-cache-validation-report-v01.json")
    if result_seal.get("root_sha256") != binding["parent_roots"]["s01_2_result_root_sha256"]:
        raise RuntimeError("S01-2 result-tree seal root differs from the frozen binding")
    if result_seal.get("feature_cache_root_sha256") != binding["parent_roots"]["s01_2_feature_cache_root_sha256"]:
        raise RuntimeError("S01-2 result seal names a different feature-cache root")
    if cache_seal.get("root_sha256") != binding["parent_roots"]["s01_2_feature_cache_root_sha256"]:
        raise RuntimeError("S01-2 feature-cache seal root differs from the frozen binding")
    if cache_seal.get("probe_training_performed") is not False or cache_seal.get("geometry_analysis_performed") is not False:
        raise RuntimeError("S01-2 feature-cache seal reports an unexpected operation")
    if validation.get("status") != "FEATURE_CACHE_VALID" or validation.get("probe_training_performed") is not False:
        raise RuntimeError("S01-2 feature-cache validation report is not in the expected sealed state")
    actual_entries = verify_entries(result_root, cache_seal["entries"])
    actual_by_path = {entry["path"]: entry for entry in actual_entries}
    for file_name, expected in binding["cache_files"].items():
        path = f"feature-cache-v01/{file_name}"
        if actual_by_path.get(path) != {"path": path, **expected}:
            raise RuntimeError(f"feature view identity differs from the S01-3 input binding: {file_name}")
    actual_cache_root = tree_root(actual_entries)
    if actual_cache_root != binding["parent_roots"]["s01_2_feature_cache_root_sha256"]:
        raise RuntimeError("S01-2 feature-cache bytes do not reproduce their sealed root")
    corpus_path = Path(binding["paths"]["s01_2_corpus"])
    corpus_sha, corpus_size = sha256_file(corpus_path)
    if corpus_sha != binding["parent_roots"]["s01_2_corpus_sha256"]:
        raise RuntimeError("S01-2 corpus hash differs from the frozen binding")
    for view in VIEWS:
        record = validation["views"].get(view)
        if record is None or record["path"] != f"feature-cache-v01/{view}.f32le":
            raise RuntimeError(f"S01-2 cache validation lacks required view {view}")
        expected_dim = int(contract["views"][VIEWS.index(view)]["dimension"])
        if record["shape"] != [106496, expected_dim] or record["dtype"] != "<f4":
            raise RuntimeError(f"S01-2 view shape or dtype mismatch for {view}")
    return {
        "s01_2_result_root_sha256": result_seal["root_sha256"],
        "s01_2_feature_cache_root_sha256": actual_cache_root,
        "s01_2_feature_cache_seal_sha256": sha256_file(cache_seal_path)[0],
        "s01_2_result_tree_seal_sha256": sha256_file(result_root / "seals" / "result-tree-seal-v01.json")[0],
        "s01_2_validation_report_sha256": sha256_file(result_root / "feature-cache-validation-report-v01.json")[0],
        "s01_2_corpus_sha256": corpus_sha,
        "s01_2_corpus_bytes": corpus_size,
        "feature_cache_entries_verified": len(actual_entries),
        "feature_values_loaded": False,
        "feature_cache_bytes_rehashed": True,
        "model_weights_opened": False,
    }


def _support_audit(fields: dict[str, np.ndarray], contract: dict[str, Any]) -> dict[str, Any]:
    bucket = fields["split_bucket"]
    train_quartets = bucket != 0
    test_quartets = bucket == 0
    unique_q = np.unique(fields["quartet_id"])
    q_bucket: dict[bytes, int] = {}
    for qid, b in zip(fields["quartet_id"], bucket, strict=True):
        key = bytes(qid)
        if key in q_bucket and q_bucket[key] != int(b):
            raise RuntimeError("A/C/E/P quartet variants split across train and test")
        q_bucket[key] = int(b)
    if len(unique_q) != 26624 or len(q_bucket) != 26624:
        raise RuntimeError("sealed corpus quartet count differs from contract")
    bucket_counts = {str(i): int(len(set(fields["quartet_id"][bucket == i]))) for i in range(5)}
    expected_test = int(contract["input_boundary"]["expected_test_quartets"])
    if bucket_counts["0"] != expected_test or len(np.flatnonzero(test_quartets)) != 21272:
        raise RuntimeError("deterministic grouped split counts differ from the frozen expectation")
    rows = fields["row_index"]
    seen_templates = (fields["observation_template"] < 6) & (fields["query_template"] < 6)
    output: dict[str, Any] = {"quartets_by_bucket": bucket_counts, "tasks": {}}
    minimum = contract["prospective_support"]
    expected_condition_counts = minimum["expected_test_rows"]
    for task in TASKS:
        labels = _label_array(fields, task)
        expected_classes = task_classes(fields, task)
        train_mask, _ = fit_masks(fields, task)
        train_values, train_counts = np.unique(labels[train_mask], return_counts=True)
        minimum_train = minimum["identity_train_minimum_per_class"] if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") else minimum["other_train_minimum_per_class"]
        if not np.array_equal(train_values, expected_classes) or int(train_counts.min()) < int(minimum_train):
            raise RuntimeError(f"fit support gate failed for {task}")
        test_fields = {name: values[test_quartets] for name, values in fields.items()}
        test_labels = _label_array(test_fields, task)
        conditions = test_condition_masks(test_fields, task)
        task_audit: dict[str, Any] = {
            "class_ids": [int(value) for value in expected_classes],
            "fit_rows": int(train_mask.sum()),
            "fit_class_counts": {str(int(k)): int(v) for k, v in zip(train_values, train_counts, strict=True)},
            "test_rows_all": int(test_quartets.sum()),
            "conditions": {},
        }
        minimum_test_class = minimum["identity_test_minimum_per_class"] if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") else minimum["other_test_minimum_per_class"]
        for name, mask in conditions.items():
            count = int(mask.sum())
            if count < int(minimum["each_test_condition_minimum_total"]):
                raise RuntimeError(f"minimum total test support failed for {task}/{name}: {count}")
            present, counts = np.unique(test_labels[mask], return_counts=True)
            if len(present) == 0 or int(counts.min()) < int(minimum_test_class):
                raise RuntimeError(f"minimum per-class test support failed for {task}/{name}")
            if task not in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") and not np.array_equal(present, expected_classes):
                raise RuntimeError(f"a declared world-factor class is absent in {task}/{name}")
            if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY"):
                label_group_name = "context_id" if task == "CONTEXT_IDENTITY" else "entity_id"
                expected_present = np.unique(test_fields[label_group_name][mask])
                if not np.array_equal(present, expected_present):
                    raise RuntimeError(f"identity class support differs from corpus metadata in {task}/{name}")
            task_audit["conditions"][name] = {
                "rows": count,
                "present_classes": len(present),
                "minimum_class_rows": int(counts.min()),
                "class_counts": {str(int(k)): int(v) for k, v in zip(present, counts, strict=True)},
            }
        if task not in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY"):
            expected_names = contract["test_conditions"]["relation_state_target_tasks"]
            for name in expected_names:
                expected_count = int(expected_condition_counts[name])
                actual = task_audit["conditions"][name]["rows"]
                if actual != expected_count:
                    raise RuntimeError(f"frozen support count mismatch for {task}/{name}: {actual} != {expected_count}")
        output["tasks"][task] = task_audit
    return output


def _write_test_manifest(fields: dict[str, np.ndarray], target: Path) -> int:
    mask = fields["split_bucket"] == 0
    names = {0: "A", 1: "C", 2: "E", 3: "P"}
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        test_row = 0
        for idx in np.flatnonzero(mask):
            row = {
                "test_row": test_row,
                "feature_row_index": int(fields["row_index"][idx]),
                "event_id": bytes(fields["event_id"][idx]).decode("ascii"),
                "quartet_id": bytes(fields["quartet_id"][idx]).decode("ascii"),
                "variant_id": names[int(fields["variant"][idx])],
                "context_term_id": int(fields["context_id"][idx]),
                "context_term_split": "TRAIN_SIDE_STYLE" if fields["context_split"][idx] == 0 else "NOVEL_HELDOUT",
                "entity_term_id": int(fields["entity_id"][idx]),
                "entity_term_split": "TRAIN_SIDE_STYLE" if fields["entity_split"][idx] == 0 else "NOVEL_HELDOUT",
                "relation_id": int(fields["relation"][idx]),
                "state_id": int(fields["state"][idx]),
                "exact_target": int(fields["target"][idx]),
                "observation_template_id": int(fields["observation_template"][idx]),
                "query_template_id": int(fields["query_template"][idx]),
            }
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            test_row += 1
    return int(mask.sum())


def _seal_preflight() -> dict[str, Any]:
    exclude = {"seals/preflight-seal-v01.json", "preflight-disposition-v01.json"}
    entries = []
    for path in RESULT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(RESULT_ROOT).as_posix()
        if relative not in exclude:
            entries.append(file_entry(path, RESULT_ROOT))
    entries.sort(key=lambda item: item["path"])
    root = tree_root(entries)
    seal = {
        "seal_id": "FASS01_S01_3_PREFIT_PACKET_SEAL_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "s01-3-linear-accessibility-v01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; seal and preflight disposition excluded",
        "entries": entries,
        "root_sha256": root,
    }
    write_json(RESULT_ROOT / "seals" / "preflight-seal-v01.json", seal)
    write_json(RESULT_ROOT / "preflight-disposition-v01.json", {
        "disposition_id": "FASS01_S01_3_PREFLIGHT_DISPOSITION_V01",
        "preflight_root_sha256": root,
        "S01_3_PREFLIGHT_READY": True,
        "S01_3_PROBE_FITTING_AUTHORIZED": True,
        "S01_3_LFM_LOADED": False,
        "S01_3_FEATURE_REEXTRACTION": False,
        "S01_ADAPTIVE_MECHANISMS_AUTHORIZED": False,
        "FAS00_PHASE4_AUTHORIZED": False,
    })
    return seal


def run_preflight() -> dict[str, Any]:
    if (RESULT_ROOT / "seals" / "preflight-seal-v01.json").exists():
        raise RuntimeError("S01-3 preflight seal already exists; refusing to replace it")
    contract = read_json(CONTRACT_PATH)
    binding = read_json(BINDING_PATH)
    authorization = read_json(AUTHORIZATION_PATH)
    contract_seal = read_json(PHASE_ROOT / "seals" / "contract-freeze-seal-v01.json")
    actual_contract_entries = []
    for entry in contract_seal["entries"]:
        actual_contract_entries.append(file_entry(PHASE_ROOT / entry["path"], PHASE_ROOT))
    actual_contract_entries.sort(key=lambda item: item["path"])
    if actual_contract_entries != sorted(contract_seal["entries"], key=lambda item: item["path"]):
        raise RuntimeError("frozen S01-3 protocol/source bytes differ from the contract seal")
    if tree_root(actual_contract_entries) != contract_seal["root_sha256"]:
        raise RuntimeError("frozen S01-3 contract root does not reproduce")
    if contract["status"] != "FROZEN_PRE_FIT" or not authorization["S01_3_AUTHORIZED"]:
        raise RuntimeError("S01-3 contract is not frozen or current authorization is absent")
    if authorization["LFM_LOADING_AUTHORIZED"] or authorization["FEATURE_REEXTRACTION_AUTHORIZED"]:
        raise RuntimeError("authorization packet crossed the frozen sensor boundary")
    snapshot_inputs()
    parent_status = _check_parent_inputs(binding, contract)
    fields = load_event_metadata(binding, int(contract["input_boundary"]["expected_events"]))
    support = _support_audit(fields, contract)
    meta_path = RESULT_ROOT / "metadata" / "event-metadata-v01.npz"
    save_metadata(meta_path, fields)
    test_count = _write_test_manifest(fields, RESULT_ROOT / "metadata" / "test-events-v01.jsonl")
    if test_count != int(contract["input_boundary"]["expected_test_events"]):
        raise RuntimeError("test-event manifest count differs from frozen split contract")
    device = configure_determinism()
    self_test = synthetic_self_test()
    if device.type != "cuda":
        raise RuntimeError("frozen CUDA execution device did not initialize")
    report = {
        "report_id": "FASS01_S01_3_PREFIT_VALIDATION_V01",
        "disposition": "PREFIT_INPUTS_AND_SUPPORT_VALID",
        "contract_sha256": sha256_file(CONTRACT_PATH)[0],
        "binding_sha256": sha256_file(BINDING_PATH)[0],
        "authorization_sha256": sha256_file(AUTHORIZATION_PATH)[0],
        "protocol_sha256": sha256_file(PROTOCOL_PATH)[0],
        "contract_freeze_root_sha256": contract_seal["root_sha256"],
        "parent_inputs": parent_status,
        "metadata_rows": int(len(fields["row_index"])),
        "metadata_npz_sha256": sha256_file(meta_path)[0],
        "test_events": test_count,
        "test_event_manifest_sha256": sha256_file(RESULT_ROOT / "metadata" / "test-events-v01.jsonl")[0],
        "split_and_support": support,
        "synthetic_probe_qualification": self_test,
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "cuda_device": torch.cuda.get_device_name(0),
            "cuda_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        },
        "feature_values_loaded": False,
        "probe_fit_performed": False,
        "LFM_loaded": False,
    }
    write_json(RESULT_ROOT / "preflight-report-v01.json", report)
    seal = _seal_preflight()
    return {"status": "PREFLIGHT_READY", "preflight_root_sha256": seal["root_sha256"], "test_events": test_count}


if __name__ == "__main__":
    result = run_preflight()
    print(json.dumps(result, sort_keys=True))
