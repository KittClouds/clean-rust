from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np


PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s01-frozen-sensor-transfer-cartography")
RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00")
S01_RUN = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography")
BASE = S01_RUN / "read-only-cartography-v01"
OUTPUT = S01_RUN / "read-only-cartography-v01-addendum"
CORPUS = RUN / "phase1-v03" / "corpus" / "qualification-events-v03.jsonl"
FEATURE_ROWS = RUN / "phase2a-v01" / "feature-cache-v01" / "feature-rows-v01.jsonl"
FEATURES_PATH = RUN / "phase2a-v01" / "feature-cache-v01" / "features-v01.f32le"
CONTRACT = PROJECT / "contracts" / "read-only-cartography-contract-v01.json"
GROUP_FIELDS = ("world_family", "task_structure", "feedback_condition", "relation_id", "world_seed")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def nearest_rank(values: np.ndarray, quantile: float) -> float:
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    if ordered.size == 0:
        raise ValueError("No values for nearest-rank summary")
    return float(ordered[max(0, math.ceil(quantile * ordered.size) - 1)])


def distribution(values: np.ndarray) -> dict:
    vector = np.asarray(values, dtype=np.float64)
    return {"n": int(vector.size), "median": nearest_rank(vector, 0.5),
            "p25": nearest_rank(vector, 0.25), "p75": nearest_rank(vector, 0.75)}


def read_json_lines(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"Refusing to overwrite addendum identity: {OUTPUT}")
    base_seal = json.loads((BASE / "seals" / "cartography-seal-v01.json").read_text(encoding="utf-8"))
    base_disposition = json.loads((BASE / "seals" / "s01-1-disposition-v01.json").read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if (base_seal["root_sha256"] != "847c0a35e7c0aa6ad7c7120ea1d4fb5b07754add0df861530cd2df5e2631d8ef" or
            base_disposition["disposition"] != "DESCRIPTIVE_MAP_COMPLETE" or
            contract["execution_authorized"] is not False or
            hash_file(CONTRACT) != "660a76946b7652206e3d823de97dd89947531ebb33f3fa13d35aeeb8dadcb69f"):
        raise RuntimeError("Base S01-1 seal or contract identity mismatch")

    worlds = list(read_json_lines(CORPUS))
    by_id = {world["event_id"]: (index, world) for index, world in enumerate(worlds)}
    selected_events: dict[str, tuple[int, dict]] = {}
    selected_rows: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in read_json_lines(BASE / "selected-feature-rows-v01.jsonl"):
        entry = by_id.get(row["event_id"])
        if entry is None:
            raise RuntimeError(f"Selected cache event is absent from corpus: {row['event_id']}")
        event_index, world = entry
        if not (world["world_seed"] in range(24, 32) and world["surface_template_id"] == 5 and world["observation_text"] is not None):
            raise RuntimeError("Base selected-row manifest contains an event outside the frozen population")
        if row["row_index"] != event_index * 2 + (0 if row["view"] == "FULL" else 1):
            raise RuntimeError("Selected cache row index no longer matches corpus order")
        if row["view"] in selected_rows[row["event_id"]]:
            raise RuntimeError("Duplicate selected cache view")
        selected_rows[row["event_id"]][row["view"]] = row
        selected_events[row["event_id"]] = entry
    if len(selected_events) != 752 or any(set(views) != {"FULL", "QUERY_ONLY"} for views in selected_rows.values()):
        raise RuntimeError("Base selected-row manifest population or view coverage mismatch")

    feature_matrix = np.memmap(FEATURES_PATH, mode="r", dtype="<f4", shape=(65536, 2048))
    grouped: dict[str, dict[str, dict[str, list]]] = {}
    for slice_name, field, term in (("test_context_term_3", "context_term_id", 3), ("test_entity_term_7", "entity_term_id", 7)):
        slice_events = [(event_index, world) for event_index, world in selected_events.values() if world[field] == term]
        if not slice_events:
            raise RuntimeError(f"Contracted slice has no rows: {slice_name}")
        buckets: dict[str, dict[str, list]] = {}
        for group_field in GROUP_FIELDS:
            by_value: dict[str, list[int]] = defaultdict(list)
            for event_index, world in slice_events:
                by_value[str(world[group_field])].append(event_index)
            bucket = {}
            for group_value, event_indexes in sorted(by_value.items()):
                row_indexes = np.asarray(event_indexes, dtype=np.int64)
                full = np.asarray(feature_matrix[row_indexes * 2], dtype=np.float64)
                query = np.asarray(feature_matrix[row_indexes * 2 + 1], dtype=np.float64)
                full_norm = np.linalg.norm(full, axis=1)
                query_norm = np.linalg.norm(query, axis=1)
                similarity = np.sum(full * query, axis=1) / (np.maximum(full_norm, 1e-12) * np.maximum(query_norm, 1e-12))
                distance = np.linalg.norm(full - query, axis=1)
                bucket[group_value] = {
                    "rows": int(len(event_indexes)),
                    "full_minus_query_only_l2_norm": distribution(distance),
                    "full_query_only_cosine_similarity": distribution(similarity),
                }
            buckets[group_field] = bucket
        grouped[slice_name] = buckets

    result = {
        "supplement_id": "FASS01_OBSERVATION_INCREMENT_SUBGROUPS_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "parent_cartography_root_sha256": base_seal["root_sha256"],
        "contract_sha256": hash_file(CONTRACT),
        "supplements": "The already-declared OBSERVATION_INCREMENT fixed subgroup summaries omitted from the base report. No new metric, view, split, or selection rule is introduced.",
        "group_fields": list(GROUP_FIELDS),
        "minimum_group_support": "none; report every represented subgroup, as specified by the contract",
        "OBSERVATION_INCREMENT_BY_FIXED_SUBGROUP": grouped,
        "scope_limit": "Paired existing FULL and QUERY_ONLY final-layer mean vectors only; no token-local or alternative representation claim.",
    }

    OUTPUT.mkdir(parents=True, exist_ok=False)
    (OUTPUT / "source").mkdir()
    (OUTPUT / "inputs").mkdir()
    (OUTPUT / "seals").mkdir()
    shutil.copy2(Path(__file__), OUTPUT / "source" / "complete-observation-subgroups-v01.py")
    shutil.copy2(PROJECT / "scripts" / "seal-addendum.ps1", OUTPUT / "source" / "seal-addendum.ps1")
    shutil.copy2(BASE / "seals" / "cartography-seal-v01.json", OUTPUT / "inputs" / "parent-cartography-seal-v01.json")
    shutil.copy2(CONTRACT, OUTPUT / "inputs" / "read-only-cartography-contract-v01.json")
    (OUTPUT / "observation-increment-subgroups-v01.json").write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")

    input_paths = {"phase1_qualification_events": CORPUS, "phase2a_feature_rows": FEATURE_ROWS,
                   "phase2a_feature_tensor": FEATURES_PATH,
                   "base_selected_feature_rows": BASE / "selected-feature-rows-v01.jsonl",
                   "base_execution_receipt": BASE / "execution-receipt-v01.json"}
    receipt = {
        "receipt_id": "FASS01_OBSERVATION_INCREMENT_SUBGROUPS_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "parent_cartography_root_sha256": base_seal["root_sha256"],
        "contract_sha256": hash_file(CONTRACT),
        "input_sha256": {name: hash_file(path) for name, path in input_paths.items()},
        "world_count": len(selected_events),
        "context_slice_count": sum(1 for _, world in selected_events.values() if world["context_term_id"] == 3),
        "entity_slice_count": sum(1 for _, world in selected_events.values() if world["entity_term_id"] == 7),
        "model_loaded": False,
        "feature_extraction": False,
        "probe_training": False,
        "new_probe_fitting": False,
        "adaptive_mechanisms": False,
    }
    (OUTPUT / "supplement-receipt-v01.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(f"FASS01_OBSERVATION_INCREMENT_SUBGROUPS_COMPLETE output={OUTPUT} slices={len(grouped)}")


if __name__ == "__main__":
    main()
