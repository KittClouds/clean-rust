from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

PHASE_ID = "s01-3-linear-accessibility-v01"
PROJECT_ID = "fas-s01-frozen-sensor-transfer-cartography"
PHASE_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-3-linear-accessibility-v01")
CONTRACT_PATH = PHASE_ROOT / "contracts" / "linear-accessibility-contract-v01.json"
BINDING_PATH = PHASE_ROOT / "contracts" / "input-binding-v01.json"
AUTHORIZATION_PATH = PHASE_ROOT / "contracts" / "authorization-packet-v01.json"
PROTOCOL_PATH = PHASE_ROOT / "S01-3-PROTOCOL.md"
PARENT_CACHE_ROOT = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-feature-geometry-v01")
PARENT_CORPUS = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-v01-sealed\corpus\counterfactual-quartets-v01.jsonl")

VIEWS = (
    "V0_MEAN_FULL",
    "V1_FINAL_POSITION",
    "V2_FIRST_POSITION",
    "V3_CONTEXT_SPAN_MEAN",
    "V4_ENTITY_SPAN_MEAN",
    "V5_RELATION_SPAN_MEAN",
    "V6_FIXED_SPAN_CONCAT",
)
TASKS = ("CONTEXT_IDENTITY", "ENTITY_IDENTITY", "RELATION_IDENTITY", "OBSERVED_STATE", "EXACT_TARGET")
TASK_LABEL_FIELDS = {
    "CONTEXT_IDENTITY": "context_term_id",
    "ENTITY_IDENTITY": "entity_term_id",
    "RELATION_IDENTITY": "relation_id",
    "OBSERVED_STATE": "state_id",
    "EXACT_TARGET": "exact_target",
}
TERM_SPLIT = {"TRAIN_SIDE_STYLE": 0, "NOVEL_HELDOUT": 1}
VARIANT_CODE = {"A": 0, "C": 1, "E": 2, "P": 3}
TRACK_CODE = {"FACTORIAL_BALANCED": 0, "BINDING_CONTEXT": 1, "BINDING_ENTITY": 2}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_entry(path: Path, base: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": path.relative_to(base).as_posix(), "bytes": size, "sha256": digest}


def tree_root(entries: list[dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item["path"])
    payload = "".join(f"{e['path']}\t{e['bytes']}\t{e['sha256']}\n" for e in ordered)
    return sha256_bytes(payload.encode("utf-8"))


def verify_entries(base: Path, expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actual = [file_entry(base.joinpath(*item["path"].split("/")), base) for item in expected]
    actual.sort(key=lambda item: item["path"])
    wanted = sorted(expected, key=lambda item: item["path"])
    if actual != wanted:
        raise RuntimeError("sealed input file identity mismatch")
    return actual


def snapshot_inputs() -> None:
    """Copy only the phase protocol, contracts, source, and small parent seals."""
    out = RESULT_ROOT / "inputs"
    if (out / "snapshot-ready-v01.json").exists():
        raise RuntimeError("input snapshot already exists; refusing in-place replacement")
    (out / "contracts").mkdir(parents=True, exist_ok=True)
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "parents").mkdir(parents=True, exist_ok=True)
    for source in (CONTRACT_PATH, BINDING_PATH, AUTHORIZATION_PATH):
        shutil.copy2(source, out / "contracts" / source.name)
    shutil.copy2(PROTOCOL_PATH, out / PROTOCOL_PATH.name)
    shutil.copy2(PHASE_ROOT / "seals" / "contract-freeze-seal-v01.json", out / "contract-freeze-seal-v01.json")
    for source in sorted((PHASE_ROOT / "source").glob("*.py")):
        shutil.copy2(source, out / "source" / source.name)
    parent_files = {
        "s01-2-result-tree-seal-v01.json": PARENT_CACHE_ROOT / "seals" / "result-tree-seal-v01.json",
        "s01-2-feature-cache-seal-v01.json": PARENT_CACHE_ROOT / "seals" / "feature-cache-seal-v01.json",
        "s01-2-feature-cache-validation-report-v01.json": PARENT_CACHE_ROOT / "feature-cache-validation-report-v01.json",
    }
    for target_name, source in parent_files.items():
        shutil.copy2(source, out / "parents" / target_name)
    snapshot = {
        "snapshot_id": "FASS01_S01_3_INPUT_SNAPSHOT_V01",
        "s01_2_cache_root_sha256": read_json(parent_files["s01-2-feature-cache-seal-v01.json"])["root_sha256"],
        "s01_2_corpus_sha256": read_json(BINDING_PATH)["parent_roots"]["s01_2_corpus_sha256"],
        "contracts": sorted(path.name for path in (out / "contracts").glob("*.json")),
        "source_files": sorted(path.name for path in (out / "source").glob("*.py")),
        "parent_files": sorted(path.name for path in (out / "parents").glob("*.json")),
        "immutable": True,
    }
    write_json(out / "snapshot-ready-v01.json", snapshot)


def feature_cache_paths(binding: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    paths = binding["paths"]
    return (
        Path(paths["s01_2_result_root"]),
        Path(paths["s01_2_cache_root"]),
        Path(paths["s01_2_feature_cache_seal"]),
        Path(paths["s01_2_feature_rows"]),
    )


def load_event_metadata(binding: dict[str, Any], expected_events: int) -> dict[str, np.ndarray]:
    """Join the sealed corpus to the sealed feature-row index without reading vectors."""
    _, _, _, rows_path = feature_cache_paths(binding)
    event_to_row: dict[str, int] = {}
    with rows_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            event_id = row["event_id"]
            row_index = int(row["row_index"])
            if event_id in event_to_row:
                raise RuntimeError(f"duplicate event ID in feature row manifest: {event_id}")
            event_to_row[event_id] = row_index
    if len(event_to_row) != expected_events or sorted(event_to_row.values()) != list(range(expected_events)):
        raise RuntimeError("feature-row manifest row count or index coverage mismatch")

    fields: dict[str, np.ndarray] = {
        "event_id": np.full(expected_events, b"", dtype="S66"),
        "quartet_id": np.full(expected_events, b"", dtype="S64"),
        "row_index": np.arange(expected_events, dtype=np.uint32),
        "split_bucket": np.full(expected_events, 255, dtype=np.uint8),
        "variant": np.full(expected_events, 255, dtype=np.uint8),
        "context_id": np.full(expected_events, 255, dtype=np.uint8),
        "entity_id": np.full(expected_events, 255, dtype=np.uint8),
        "context_split": np.full(expected_events, 255, dtype=np.uint8),
        "entity_split": np.full(expected_events, 255, dtype=np.uint8),
        "observation_template": np.full(expected_events, 255, dtype=np.uint8),
        "query_template": np.full(expected_events, 255, dtype=np.uint8),
        "relation": np.full(expected_events, 255, dtype=np.uint8),
        "state": np.full(expected_events, 255, dtype=np.uint8),
        "target": np.full(expected_events, 255, dtype=np.uint8),
        "track": np.full(expected_events, 255, dtype=np.uint8),
        "world_family": np.full(expected_events, 255, dtype=np.uint8),
    }
    corpus_path = Path(binding["paths"]["s01_2_corpus"])
    quartet_ids: set[str] = set()
    event_seen = np.zeros(expected_events, dtype=np.bool_)
    import hashlib

    with corpus_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            quartet = json.loads(line)
            qid = quartet["quartet_id"]
            if qid in quartet_ids:
                raise RuntimeError(f"duplicate quartet ID in sealed corpus: {qid}")
            quartet_ids.add(qid)
            digest = hashlib.sha256(("FASS01-S01-3-GROUPSPLIT-V01|" + qid).encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % 5
            variants = quartet["variants"]
            if len(variants) != 4 or {v["variant_id"] for v in variants} != {"A", "C", "E", "P"}:
                raise RuntimeError(f"quartet variant identity mismatch: {qid}")
            for variant in variants:
                event_id = variant["event_id"]
                if event_id not in event_to_row:
                    raise RuntimeError(f"corpus event missing from feature manifest: {event_id}")
                idx = event_to_row[event_id]
                if event_seen[idx]:
                    raise RuntimeError(f"duplicate event row mapping: {event_id}")
                event_seen[idx] = True
                fields["event_id"][idx] = event_id.encode("ascii")
                fields["quartet_id"][idx] = qid.encode("ascii")
                fields["split_bucket"][idx] = bucket
                fields["variant"][idx] = VARIANT_CODE[variant["variant_id"]]
                fields["context_id"][idx] = int(variant["context_term_id"])
                fields["entity_id"][idx] = int(variant["entity_term_id"])
                fields["context_split"][idx] = TERM_SPLIT[variant["context_term_split"]]
                fields["entity_split"][idx] = TERM_SPLIT[variant["entity_term_split"]]
                fields["observation_template"][idx] = int(variant["observation_template_id"])
                fields["query_template"][idx] = int(variant["query_template_id"])
                fields["relation"][idx] = int(quartet["relation_id"])
                fields["state"][idx] = int(quartet["state_id"])
                fields["target"][idx] = int(quartet["exact_target"])
                fields["track"][idx] = TRACK_CODE[quartet["track_id"]]
                fields["world_family"][idx] = int(quartet["world_family_id"])
    if len(quartet_ids) != expected_events // 4 or not bool(event_seen.all()):
        raise RuntimeError("corpus to feature-row join did not cover every sealed event")
    if bool(np.any(fields["event_id"] == b"")) or bool(np.any(fields["split_bucket"] == 255)):
        raise RuntimeError("metadata arrays contain unassigned event rows")
    return fields


def task_classes(fields: dict[str, np.ndarray], task: str) -> np.ndarray:
    label_field = TASK_LABEL_FIELDS[task]
    key = {
        "CONTEXT_IDENTITY": "context_id",
        "ENTITY_IDENTITY": "entity_id",
        "RELATION_IDENTITY": "relation",
        "OBSERVED_STATE": "state",
        "EXACT_TARGET": "target",
    }[task]
    classes = np.unique(fields[key])
    if len(classes) != int(read_json(CONTRACT_PATH)["tasks"][task]["classes"]):
        raise RuntimeError(f"unexpected label support for {task} ({label_field})")
    return classes


def fit_masks(fields: dict[str, np.ndarray], task: str) -> tuple[np.ndarray, np.ndarray]:
    train_quartets = fields["split_bucket"] != 0
    seen_templates = (fields["observation_template"] < 6) & (fields["query_template"] < 6)
    if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY"):
        return train_quartets & seen_templates, fields["split_bucket"] == 0
    known_terms = (fields["context_split"] == 0) & (fields["entity_split"] == 0)
    return train_quartets & seen_templates & known_terms, fields["split_bucket"] == 0


def test_condition_masks(fields_test: dict[str, np.ndarray], task: str) -> dict[str, np.ndarray]:
    obs = fields_test["observation_template"]
    query = fields_test["query_template"]
    ctx_train = fields_test["context_split"] == 0
    ent_train = fields_test["entity_split"] == 0
    ctx_novel = fields_test["context_split"] == 1
    ent_novel = fields_test["entity_split"] == 1
    templates_seen = (obs < 6) & (query < 6)
    obs_novel_only = (obs >= 6) & (query < 6)
    query_novel_only = (query >= 6) & (obs < 6)
    both_novel_templates = (obs >= 6) & (query >= 6)
    any_novel_template = (obs >= 6) | (query >= 6)
    if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY"):
        masks = {
            "SEEN_TEMPLATES_ALL_TERMS": templates_seen,
            "OBSERVATION_TEMPLATE_HELDOUT_ONLY": obs_novel_only,
            "QUERY_TEMPLATE_HELDOUT_ONLY": query_novel_only,
            "BOTH_TEMPLATES_HELDOUT": both_novel_templates,
            "ANY_TEMPLATE_HELDOUT": any_novel_template,
        }
        term_field = "context_split" if task == "CONTEXT_IDENTITY" else "entity_split"
        train_ids = fields_test[term_field] == 0
        novel_ids = fields_test[term_field] == 1
        masks[f"SEEN_TEMPLATES_{'TRAIN_SIDE_CONTEXT' if task == 'CONTEXT_IDENTITY' else 'TRAIN_SIDE_ENTITY'}_TERMS"] = templates_seen & train_ids
        masks[f"SEEN_TEMPLATES_{'NOVEL_CONTEXT' if task == 'CONTEXT_IDENTITY' else 'NOVEL_ENTITY'}_TERMS"] = templates_seen & novel_ids
        return masks
    masks = {
        "IN_DOMAIN_TRAIN_SIDE_TERMS_SEEN_TEMPLATES": ctx_train & ent_train & templates_seen,
        "CONTEXT_NOVEL_ONLY_SEEN_TEMPLATES": ctx_novel & ent_train & templates_seen,
        "ENTITY_NOVEL_ONLY_SEEN_TEMPLATES": ctx_train & ent_novel & templates_seen,
        "BOTH_TERMS_NOVEL_SEEN_TEMPLATES": ctx_novel & ent_novel & templates_seen,
        "OBSERVATION_TEMPLATE_NOVEL_ONLY_TRAIN_SIDE_TERMS": ctx_train & ent_train & obs_novel_only,
        "QUERY_TEMPLATE_NOVEL_ONLY_TRAIN_SIDE_TERMS": ctx_train & ent_train & query_novel_only,
        "BOTH_TEMPLATES_NOVEL_TRAIN_SIDE_TERMS": ctx_train & ent_train & both_novel_templates,
        "ANY_TEMPLATE_NOVEL_TRAIN_SIDE_TERMS": ctx_train & ent_train & any_novel_template,
        "CONTEXT_NOVEL_X_ANY_TEMPLATE_NOVEL": ctx_novel & ent_train & any_novel_template,
        "ENTITY_NOVEL_X_ANY_TEMPLATE_NOVEL": ctx_train & ent_novel & any_novel_template,
        "BOTH_TERMS_NOVEL_X_ANY_TEMPLATE_NOVEL": ctx_novel & ent_novel & any_novel_template,
    }
    return masks


def save_metadata(path: Path, fields: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **fields)


def load_metadata_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as arrays:
        return {key: arrays[key] for key in arrays.files}
