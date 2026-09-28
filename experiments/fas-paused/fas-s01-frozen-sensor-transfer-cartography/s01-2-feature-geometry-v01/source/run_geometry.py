from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from common import canonical, jsonl_rows, read_json, sha256_bytes, sha256_file


MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
GEOMETRY_CONTRACT_SHA = "4f6df89b02d0b991e09ab5d8f2658627c48799a10b1dd0557795c433d61099ab"
VIEWS = (
    "V0_MEAN_FULL", "V1_FINAL_POSITION", "V2_FIRST_POSITION",
    "V3_CONTEXT_SPAN_MEAN", "V4_ENTITY_SPAN_MEAN", "V5_RELATION_SPAN_MEAN", "V6_FIXED_SPAN_CONCAT",
)
DIMS = {view: (6144 if view == "V6_FIXED_SPAN_CONCAT" else 2048) for view in VIEWS}
FACTORS = ("context", "entity", "paraphrase")
FACTOR_PAIRS = (("context", "entity"), ("context", "paraphrase"), ("entity", "paraphrase"))
SUBGROUP_FIELDS = (
    "context_term_id", "context_counterpart_term_id", "entity_term_id", "entity_counterpart_term_id",
    "context_term_split", "entity_term_split", "observation_template_id", "query_template_id",
    "relation_id", "state_id", "world_family_id", "track_id",
)
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)


def json_write(path: Path, value: Any) -> None:
    path.write_bytes(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")


def nearest_rank(values: np.ndarray, q: float) -> float:
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    if ordered.size == 0:
        raise ValueError("nearest-rank summary requires a nonempty sample")
    return float(ordered[max(0, math.ceil(q * ordered.size) - 1)])


def distribution(values: Iterable[float] | np.ndarray) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0:
        raise ValueError("contracted geometry distribution is empty")
    if not np.isfinite(array).all():
        raise RuntimeError("non-finite value in geometry calculations")
    return {
        "n": int(array.size),
        "minimum": float(array.min()),
        "p10": nearest_rank(array, 0.10),
        "p25": nearest_rank(array, 0.25),
        "median": nearest_rank(array, 0.50),
        "p75": nearest_rank(array, 0.75),
        "p90": nearest_rank(array, 0.90),
        "maximum": float(array.max()),
    }


def cosine_rows(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left64 = np.asarray(left, dtype=np.float64)
    right64 = np.asarray(right, dtype=np.float64)
    numerator = np.sum(left64 * right64, axis=1, dtype=np.float64)
    left_norm = np.maximum(np.linalg.norm(left64, axis=1), 1e-12)
    right_norm = np.maximum(np.linalg.norm(right64, axis=1), 1e-12)
    return numerator / (left_norm * right_norm)


def all_pairwise_cosines(vectors: np.ndarray) -> np.ndarray:
    values = np.asarray(vectors, dtype=np.float64)
    norms = np.maximum(np.linalg.norm(values, axis=1), 1e-12)
    normalized = values / norms[:, None]
    gram = normalized @ normalized.T
    upper = np.triu_indices(values.shape[0], k=1)
    return gram[upper]


def view_path(root: Path, view: str) -> Path:
    return root / "feature-cache-v01" / f"{view}.f32le"


def verify_feature_cache(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    seal = read_json(root / "seals" / "feature-cache-seal-v01.json")
    entries = seal.get("entries", [])
    if sha256_bytes(canonical(entries)) != seal.get("root_sha256"):
        raise RuntimeError("feature-cache seal root does not reproduce")
    for item in entries:
        digest, size = sha256_file(root.joinpath(*item["path"].split("/")))
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"sealed feature-cache input changed: {item['path']}")
    report = read_json(root / "feature-cache-validation-report-v01.json")
    if report.get("status") != "FEATURE_CACHE_VALID" or report.get("events_verified") != 106496 or report.get("quartets_verified") != 26624:
        raise RuntimeError("feature-cache validation report is incomplete")
    if report.get("backbone_parameter_delta") != 0 or report.get("deterministic_repeat_pass") is not True:
        raise RuntimeError("feature-cache validation report failed a required extraction gate")
    report_sha, report_bytes = sha256_file(root / "feature-cache-validation-report-v01.json")
    if report_sha != seal.get("validation_report_sha256") or report_bytes != seal.get("validation_report_bytes"):
        raise RuntimeError("feature-cache report identity differs from its seal")
    return seal, report


def verify_inputs(root: Path, binding: dict[str, Any], feature_seal: dict[str, Any]) -> tuple[Path, Path]:
    geometry_contract_path = root / "inputs" / "contracts" / "geometry-analysis-contract-v01.json"
    if sha256_file(geometry_contract_path)[0] != GEOMETRY_CONTRACT_SHA:
        raise RuntimeError("frozen geometry contract changed")
    if binding["contract_sha256"]["geometry"] != GEOMETRY_CONTRACT_SHA:
        raise RuntimeError("run binding names a different geometry contract")
    if feature_seal.get("model_id") != MODEL_ID or feature_seal.get("model_revision") != REVISION:
        raise RuntimeError("feature-cache seal names a different model")
    corpus = Path(binding["inputs"]["corpus"])
    assignments = Path(binding["inputs"]["alignment_assignments"])
    for key, path in (("corpus", corpus), ("alignment_assignments", assignments)):
        digest, _ = sha256_file(path)
        if digest != binding["input_sha256"][key]:
            raise RuntimeError(f"sealed geometry input changed: {key}")
    return corpus, assignments


def collect_metadata(corpus_path: Path, row_manifest_path: Path) -> list[dict[str, Any]]:
    row_iter = iter(jsonl_rows(row_manifest_path))
    result = []
    event_index = 0
    for quartet in jsonl_rows(corpus_path):
        variants = quartet.get("variants", [])
        if len(variants) != 4 or [v.get("variant_id") for v in variants] != ["A", "C", "E", "P"]:
            raise RuntimeError(f"invalid quartet structure: {quartet.get('quartet_id')}")
        cached = [next(row_iter, None) for _ in range(4)]
        if any(row is None for row in cached):
            raise RuntimeError("feature row manifest ended before sealed corpus")
        for variant, row in zip(variants, cached, strict=True):
            if row.get("row_index") != event_index or row.get("quartet_id") != quartet["quartet_id"] or row.get("event_id") != variant["event_id"] or row.get("variant_id") != variant["variant_id"]:
                raise RuntimeError(f"feature/corpus row identity mismatch: {variant.get('event_id')}")
            if row.get("input_sha256") != variant.get("input_sha256") or row.get("token_ids_sha256") is None:
                raise RuntimeError(f"feature/corpus input identity mismatch: {variant['event_id']}")
            event_index += 1
        base, context_changed, entity_changed, para = variants
        if any(v.get("exact_target") != quartet.get("exact_target") for v in variants):
            raise RuntimeError(f"counterfactual target invariant changed: {quartet['quartet_id']}")
        result.append({
            "quartet_id": quartet["quartet_id"],
            "track_id": quartet["track_id"],
            "context_term_split": quartet["context_term_split"],
            "entity_term_split": quartet["entity_term_split"],
            "world_family": quartet["world_family"],
            "world_family_id": quartet["world_family_id"],
            "relation_id": quartet["relation_id"],
            "state_id": quartet["state_id"],
            "observation_template_id": quartet["observation_template_id"],
            "query_template_id": quartet["query_template_id"],
            "context_pair_id": quartet["context_pair_id"],
            "entity_pair_id": quartet["entity_pair_id"],
            "context_term_id": base["context_term_id"],
            "context_counterpart_term_id": context_changed["context_term_id"],
            "entity_term_id": base["entity_term_id"],
            "entity_counterpart_term_id": entity_changed["entity_term_id"],
            "context_term_ids": [base["context_term_id"], context_changed["context_term_id"]],
            "entity_term_ids": [base["entity_term_id"], entity_changed["entity_term_id"]],
            "variant_template_pairs": [[v["observation_template_id"], v["query_template_id"]] for v in variants],
        })
    if next(row_iter, None) is not None or event_index != 106496 or len(result) != 26624:
        raise RuntimeError("feature/corpus manifest row counts differ")
    return result


def support_cells(metadata: list[dict[str, Any]]) -> dict[str, dict[tuple[Any, ...], list[int]]]:
    factorial: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    binding_context: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    binding_entity: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    template_groups: dict[str, dict[tuple[Any, ...], list[int]]] = {factor: defaultdict(list) for factor in FACTORS}
    template_pairs: Counter[tuple[int, int]] = Counter()
    for index, meta in enumerate(metadata):
        if meta["track_id"] == "FACTORIAL_BALANCED":
            key = (meta["track_id"], meta["context_term_split"], meta["entity_term_split"], meta["world_family_id"], meta["relation_id"], meta["state_id"], meta["observation_template_id"], meta["query_template_id"])
            factorial[key].append(index)
            context_key = (meta["track_id"], meta["context_term_split"], meta["context_term_ids"][0], meta["context_term_ids"][1], meta["entity_term_split"], meta["entity_term_id"], meta["world_family_id"], meta["relation_id"], meta["state_id"])
            entity_key = (meta["track_id"], meta["entity_term_split"], meta["entity_term_ids"][0], meta["entity_term_ids"][1], meta["context_term_split"], meta["context_term_id"], meta["world_family_id"], meta["relation_id"], meta["state_id"])
            para_key = (meta["track_id"], meta["context_term_split"], meta["context_term_id"], meta["entity_term_split"], meta["entity_term_id"], meta["world_family_id"], meta["relation_id"], meta["state_id"])
            template_groups["context"][context_key].append(index)
            template_groups["entity"][entity_key].append(index)
            template_groups["paraphrase"][para_key].append(index)
            pair = (meta["observation_template_id"], meta["query_template_id"])
            template_pairs[pair] += 1
        elif meta["track_id"] == "BINDING_CONTEXT":
            binding_context[(meta["track_id"], meta["context_term_split"], meta["context_pair_id"], meta["entity_term_split"])].append(index)
        elif meta["track_id"] == "BINDING_ENTITY":
            binding_entity[(meta["track_id"], meta["entity_term_split"], meta["entity_pair_id"], meta["context_term_split"])].append(index)
        else:
            raise RuntimeError(f"unknown track: {meta['track_id']}")
    expected_templates = {(observation, query) for observation in range(8) for query in range(8)}
    if set(template_pairs) != expected_templates or any(count != 384 for count in template_pairs.values()):
        raise RuntimeError("global observation/query template-pair schedule differs from the sealed balanced 8x8 corpus")
    if len(factorial) != 1536 or any(len(indices) != 16 for indices in factorial.values()):
        raise RuntimeError("primary factorial cell support differs from 1536 cells × 16")
    if len(binding_context) != 64 or any(len(indices) != 16 for indices in binding_context.values()):
        raise RuntimeError("context binding cell support differs from 64 cells × 16")
    if len(binding_entity) != 64 or any(len(indices) != 16 for indices in binding_entity.values()):
        raise RuntimeError("entity binding cell support differs from 64 cells × 16")
    for factor, groups in template_groups.items():
        if len(groups) != 3072 or any(len(indices) != 8 for indices in groups.values()):
            raise RuntimeError(f"template invariance groups differ for {factor}")
        for indices in groups.values():
            observations = [metadata[i]["observation_template_id"] for i in indices]
            queries = [metadata[i]["query_template_id"] for i in indices]
            pairs = [(metadata[i]["observation_template_id"], metadata[i]["query_template_id"]) for i in indices]
            if sorted(observations) != list(range(8)) or sorted(queries) != list(range(8)) or len(set(pairs)) != 8:
                raise RuntimeError(f"template invariance group does not match the sealed balanced marginal schedule for {factor}")
    return {
        "factorial": factorial,
        "binding_context": binding_context,
        "binding_entity": binding_entity,
        "template": template_groups,
        "template_pair_counts": template_pairs,
    }


def validate_corpus_support(corpus_path: Path) -> dict[str, Any]:
    """Validate sealed corpus support and template schedule without feature access."""
    metadata: list[dict[str, Any]] = []
    for quartet in jsonl_rows(corpus_path):
        variants = quartet.get("variants", [])
        if len(variants) != 4 or [item.get("variant_id") for item in variants] != ["A", "C", "E", "P"]:
            raise RuntimeError(f"invalid quartet structure in preflight: {quartet.get('quartet_id')}")
        base, context_changed, entity_changed, para = variants
        if any(item.get("exact_target") != quartet.get("exact_target") for item in variants):
            raise RuntimeError(f"counterfactual target invariant changed: {quartet['quartet_id']}")
        metadata.append({
            "track_id": quartet["track_id"],
            "context_term_split": quartet["context_term_split"],
            "entity_term_split": quartet["entity_term_split"],
            "world_family_id": quartet["world_family_id"],
            "relation_id": quartet["relation_id"],
            "state_id": quartet["state_id"],
            "observation_template_id": quartet["observation_template_id"],
            "query_template_id": quartet["query_template_id"],
            "context_pair_id": quartet["context_pair_id"],
            "entity_pair_id": quartet["entity_pair_id"],
            "context_term_id": base["context_term_id"],
            "context_counterpart_term_id": context_changed["context_term_id"],
            "entity_term_id": base["entity_term_id"],
            "entity_counterpart_term_id": entity_changed["entity_term_id"],
            "context_term_ids": [base["context_term_id"], context_changed["context_term_id"]],
            "entity_term_ids": [base["entity_term_id"], entity_changed["entity_term_id"]],
            "variant_template_pairs": [[item["observation_template_id"], item["query_template_id"]] for item in variants],
        })
    if len(metadata) != 26624:
        raise RuntimeError(f"corpus support preflight found {len(metadata)} quartets, expected 26624")
    groups = support_cells(metadata)
    pair_counts = groups["template_pair_counts"]
    return {
        "quartets": len(metadata),
        "factorial_cells": len(groups["factorial"]),
        "binding_context_cells": len(groups["binding_context"]),
        "binding_entity_cells": len(groups["binding_entity"]),
        "template_groups_per_factor": {factor: len(groups["template"][factor]) for factor in FACTORS},
        "template_pair_count": len(pair_counts),
        "template_pair_support_min": min(pair_counts.values()),
        "template_pair_support_max": max(pair_counts.values()),
        "template_pair_support_each": 384,
        "per_group_observation_template_marginal": 8,
        "per_group_query_template_marginal": 8,
        "pass": True,
    }


def grouped_indices(metadata: list[dict[str, Any]], field: str) -> dict[Any, list[int]]:
    groups: dict[Any, list[int]] = defaultdict(list)
    for index, meta in enumerate(metadata):
        groups[meta[field]].append(index)
    return groups


def emit_subgroups(stream, view: str, metric: str, label: str, values: np.ndarray, metadata: list[dict[str, Any]]) -> int:
    count = 0
    for field in SUBGROUP_FIELDS:
        for value, indices in sorted(grouped_indices(metadata, field).items(), key=lambda item: str(item[0])):
            record = {"view": view, "metric": metric, "factor_or_pair": label, "group_field": field, "group_value": value, "quartet_support": len(indices), "distribution": distribution(values[indices])}
            stream.write(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def cell_key_text(key: tuple[Any, ...]) -> list[Any]:
    return list(key)


def template_key_text(key: tuple[Any, ...]) -> list[Any]:
    return list(key)


def build_deltas(feature: np.memmap, metadata: list[dict[str, Any]], dimension: int) -> dict[str, np.ndarray]:
    matrices = {factor: np.empty((len(metadata), dimension), dtype=np.float64) for factor in FACTORS}
    for index in range(len(metadata)):
        row = index * 4
        base = np.asarray(feature[row], dtype=np.float64)
        matrices["context"][index] = np.asarray(feature[row + 1], dtype=np.float64) - base
        matrices["entity"][index] = np.asarray(feature[row + 2], dtype=np.float64) - base
        matrices["paraphrase"][index] = np.asarray(feature[row + 3], dtype=np.float64) - base
    return matrices


def run(root: Path) -> None:
    binding = read_json(root / "inputs" / "input-binding-v01.json")
    feature_seal, cache_report = verify_feature_cache(root)
    corpus_path, _ = verify_inputs(root, binding, feature_seal)
    geometry_contract = read_json(root / "inputs" / "contracts" / "geometry-analysis-contract-v01.json")
    implementation_contract = read_json(root / "inputs" / "geometry-implementation-contract-v01.json")
    if geometry_contract.get("contract_id") != "FASS01_GEOMETRY_ANALYSIS_V01" or implementation_contract.get("parent_metric_contract_sha256") != GEOMETRY_CONTRACT_SHA:
        raise RuntimeError("geometry contract identity differs")
    geometry_root = root / "geometry-v01"
    if geometry_root.exists():
        raise RuntimeError("geometry output already exists; refusing reuse")
    geometry_root.mkdir()
    subgroup_path = geometry_root / "subgroup-distributions-v01.jsonl"
    cell_path = geometry_root / "cell-consistency-v01.jsonl"
    template_path = geometry_root / "template-invariance-v01.jsonl"
    metadata = collect_metadata(corpus_path, root / "feature-cache-v01" / "feature-rows-v01.jsonl")
    groups = support_cells(metadata)
    all_cells = {
        "FACTORIAL_BALANCED": groups["factorial"],
        "BINDING_CONTEXT": groups["binding_context"],
        "BINDING_ENTITY": groups["binding_entity"],
    }
    per_view = {}
    subgroup_count = cell_count = template_count = 0

    with subgroup_path.open("x", encoding="utf-8", newline="\n", buffering=8 * 1024 * 1024) as subgroup_stream, \
            cell_path.open("x", encoding="utf-8", newline="\n", buffering=8 * 1024 * 1024) as cell_stream, \
            template_path.open("x", encoding="utf-8", newline="\n", buffering=8 * 1024 * 1024) as template_stream:
        for view in VIEWS:
            feature = np.memmap(view_path(root, view), mode="r", dtype="<f4", shape=(106496, DIMS[view]))
            deltas = build_deltas(feature, metadata, DIMS[view])
            del feature
            view_result: dict[str, Any] = {"dimension": DIMS[view], "delta_l2": {}, "within_quartet_cosines": {}, "factorial_cell_consistency": {}, "matched_context_binding": {}, "matched_entity_binding": {}, "template_invariance": {}}
            norms = {factor: np.linalg.norm(deltas[factor], axis=1) for factor in FACTORS}
            for factor in FACTORS:
                view_result["delta_l2"][factor] = distribution(norms[factor])
                subgroup_count += emit_subgroups(subgroup_stream, view, "delta_l2", factor, norms[factor], metadata)
            pair_values = {}
            for left, right in FACTOR_PAIRS:
                pair_name = f"{left}_vs_{right}"
                values = cosine_rows(deltas[left], deltas[right])
                pair_values[pair_name] = values
                view_result["within_quartet_cosines"][pair_name] = distribution(values)
                subgroup_count += emit_subgroups(subgroup_stream, view, "within_quartet_cosine", pair_name, values, metadata)

            aggregate_cell_values: dict[str, list[np.ndarray]] = defaultdict(list)
            for cell_kind, mapping in all_cells.items():
                if cell_kind == "FACTORIAL_BALANCED":
                    target_factors = FACTORS
                elif cell_kind == "BINDING_CONTEXT":
                    target_factors = ("context",)
                else:
                    target_factors = ("entity",)
                for key, indices in sorted(mapping.items(), key=lambda item: tuple(str(v) for v in item[0])):
                    for factor in target_factors:
                        cosines = all_pairwise_cosines(deltas[factor][indices])
                        if cosines.size != 120:
                            raise RuntimeError(f"cell pair count differs from 120: {cell_kind} / {factor}")
                        record = {
                            "view": view,
                            "cell_kind": "factorial_consistency" if cell_kind == "FACTORIAL_BALANCED" else "matched_context_binding" if cell_kind == "BINDING_CONTEXT" else "matched_entity_binding",
                            "factor": factor,
                            "cell_key": cell_key_text(key),
                            "quartet_support": len(indices),
                            "pair_count": int(cosines.size),
                            "pairwise_cosine_distribution": distribution(cosines),
                        }
                        cell_stream.write(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
                        cell_count += 1
                        aggregate_cell_values[f"{cell_kind}:{factor}"].append(cosines)
            for kind in ("FACTORIAL_BALANCED", "BINDING_CONTEXT", "BINDING_ENTITY"):
                cell_factors = FACTORS if kind == "FACTORIAL_BALANCED" else ("context",) if kind == "BINDING_CONTEXT" else ("entity",)
                for factor in cell_factors:
                    name = f"{kind}:{factor}"
                    view_result["factorial_cell_consistency" if kind == "FACTORIAL_BALANCED" else "matched_context_binding" if kind == "BINDING_CONTEXT" else "matched_entity_binding"][factor] = {
                        "cells": len(aggregate_cell_values[name]),
                        "pairwise_cosine_distribution": distribution(np.concatenate(aggregate_cell_values[name])),
                        "pairs_per_cell": 120,
                    }

            for factor in FACTORS:
                aggregate = []
                groups_for_factor = groups["template"][factor]
                for key, indices in sorted(groups_for_factor.items(), key=lambda item: tuple(str(v) for v in item[0])):
                    cosines = all_pairwise_cosines(deltas[factor][indices])
                    if cosines.size != 28:
                        raise RuntimeError(f"template pair count differs from 28: {factor}")
                    template_stream.write(json.dumps({
                        "view": view,
                        "factor": factor,
                        "match_key": template_key_text(key),
                        "template_pairs": [metadata[i]["variant_template_pairs"][0] for i in indices],
                        "quartet_support": len(indices),
                        "pair_count": int(cosines.size),
                        "pairwise_cosine_distribution": distribution(cosines),
                    }, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
                    template_count += 1
                    aggregate.append(cosines)
                view_result["template_invariance"][factor] = {
                    "matched_groups": len(groups_for_factor),
                    "pairs_per_group": 28,
                    "pairwise_cosine_distribution": distribution(np.concatenate(aggregate)),
                }
            per_view[view] = view_result
            print(f"geometry_view_complete={view} dimension={DIMS[view]}", flush=True)
            del deltas, norms, pair_values

    subgroup_hash, subgroup_bytes = sha256_file(subgroup_path)
    cell_hash, cell_bytes = sha256_file(cell_path)
    template_hash, template_bytes = sha256_file(template_path)
    report = {
        "report_id": "FASS01_S01_2_GEOMETRY_REPORT_V01",
        "project_id": binding["project_id"],
        "phase_id": binding["phase_id"],
        "status": "FROZEN_DESCRIPTIVE_GEOMETRY_COMPLETE",
        "scientific_status": "descriptive_cartography_only",
        "input_roots": {
            "corpus_sha256": binding["corpus_sha256"],
            "S01_2_result_tree_root_sha256": binding["parent_roots"]["S01_2"]["result_tree_root_sha256"],
            "S01_2C_result_tree_root_sha256": binding["parent_roots"]["S01_2C"]["result_tree_root_sha256"],
            "feature_cache_root_sha256": feature_seal["root_sha256"],
            "feature_contract_sha256": binding["contract_sha256"]["feature"],
            "geometry_contract_sha256": GEOMETRY_CONTRACT_SHA,
            "geometry_implementation_contract_sha256": binding["contract_sha256"]["geometry_implementation"],
        },
        "population": {"quartets": len(metadata), "events": 4 * len(metadata), "tracks": {name: sum(1 for m in metadata if m["track_id"] == name) for name in ("FACTORIAL_BALANCED", "BINDING_CONTEXT", "BINDING_ENTITY")}},
        "support_validation": {
            "factorial_cells": len(groups["factorial"]),
            "binding_context_cells": len(groups["binding_context"]),
            "binding_entity_cells": len(groups["binding_entity"]),
            "quartets_per_cell": 16,
            "template_groups_per_factor": {factor: len(groups["template"][factor]) for factor in FACTORS},
            "template_pairs_per_group": 8,
            "global_template_pair_count": len(groups["template_pair_counts"]),
            "global_template_pair_support_min": min(groups["template_pair_counts"].values()),
            "global_template_pair_support_max": max(groups["template_pair_counts"].values()),
            "group_observation_marginal_unique_count": 8,
            "group_query_marginal_unique_count": 8,
            "pass": True,
        },
        "arithmetic": "all source feature rows decoded from sealed little-endian float32 and converted to float64 before any delta or metric arithmetic",
        "views": per_view,
        "metric_files": {
            "subgroup_distributions": {"path": subgroup_path.relative_to(root).as_posix(), "rows": subgroup_count, "bytes": subgroup_bytes, "sha256": subgroup_hash},
            "cell_consistency": {"path": cell_path.relative_to(root).as_posix(), "rows": cell_count, "bytes": cell_bytes, "sha256": cell_hash},
            "template_invariance": {"path": template_path.relative_to(root).as_posix(), "rows": template_count, "bytes": template_bytes, "sha256": template_hash},
        },
        "analysis_limits": {
            "probe_fitting": False,
            "nonlinear_diagnostics": False,
            "view_selection_or_ranking": False,
            "rescue_criterion": False,
            "pooling_or_layer_search": False,
            "backbone_loaded_for_geometry": False,
            "online_adaptation": False,
            "S01_3_authorized": False,
        },
    }
    json_write(geometry_root / "geometry-report-v01.json", report)
    receipt = {
        "receipt_id": "FASS01_S01_2_GEOMETRY_EXECUTION_V01",
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "geometry_contract_sha256": GEOMETRY_CONTRACT_SHA,
        "geometry_implementation_contract_sha256": binding["contract_sha256"]["geometry_implementation"],
        "report_sha256": sha256_file(geometry_root / "geometry-report-v01.json")[0],
        "complete": True,
        "model_loaded_for_geometry": False,
        "probe_training_performed": False,
        "nonlinear_diagnostics_performed": False,
        "view_selection_performed": False,
        "S01_3_authorized": False,
    }
    json_write(geometry_root / "geometry-execution-receipt-v01.json", receipt)
    print(f"geometry_complete views={len(VIEWS)} subgroup_rows={subgroup_count} cell_rows={cell_count} template_rows={template_count}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen S01-2 geometry analysis over a sealed feature cache")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    run(args.run_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
