"""Shared frozen contract for the BANK-v1 230M surface sweep."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np

DECISIONS = ("ACT", "ASK", "ABSTAIN")
ACTIONS = ("MOVE", "ACTIVATE", "DEACTIVATE", "TAKE", "DROP", "TRANSFER",
           "OPEN", "CLOSE", "SELECT", "ASSIGN", "REQUEST", "VERIFY", "WAIT", "NOOP")
ABSTAIN_REASONS = ("INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "UNKNOWN_ENTITY",
                   "UNKNOWN_TARGET", "MISSING_ARGUMENT", "NO_VALID_ACTION", "IMPOSSIBLE_GOAL",
                   "AMBIGUOUS_REFERENCE", "MULTIPLE_UNRESOLVED_ACTIONS",
                   "PRECONDITION_UNKNOWN", "OUT_OF_SCOPE")
NLI = ("ENTAILED", "CONTRADICTED", "UNKNOWN")
ENTITY_TYPES = ("OBJECT", "AGENT", "LOCATION", "SWITCH", "CONTAINER", "RESOURCE")
PREDICATES = ("AT", "HAS", "CONNECTED", "REQUIRES", "STATE", "BLOCKED", "ENABLES",
              "BEFORE", "PART_OF", "OWNS")
GOAL_VALUES = ("NONE", "ACTIVE", "INACTIVE", "TRUE", "FALSE", "OTHER")
MAX_ENTITY_SLOTS = 16
SEED = 20260929

CATEGORICAL_HEADS = {
    "decision": DECISIONS,
    "action_type": ACTIONS,
    "abstain_reason": ABSTAIN_REASONS,
    "nli": NLI,
}
MULTILABEL_HEADS = {
    "entity_types": ENTITY_TYPES,
    "relation_predicates": PREDICATES,
    "state_predicates": PREDICATES,
    "evidence_predicates": PREDICATES,
}
ALL_HEADS = tuple(CATEGORICAL_HEADS) + tuple(MULTILABEL_HEADS)

INPUT_SPECS = (
    ("TRAIN", "inputs/TRAIN.jsonl"),
    ("DEV", "inputs/DEV.jsonl"),
    ("TEST-IID", "public/test-inputs/TEST-IID.jsonl"),
    ("TEST-LEXICAL", "public/test-inputs/TEST-LEXICAL.jsonl"),
    ("TEST-ENTITY", "public/test-inputs/TEST-ENTITY.jsonl"),
    ("TEST-TEMPLATE", "public/test-inputs/TEST-TEMPLATE.jsonl"),
    ("TEST-COMPOSITION", "public/test-inputs/TEST-COMPOSITION.jsonl"),
    ("TEST-DEPTH", "public/test-inputs/TEST-DEPTH.jsonl"),
    ("TEST-ABSTENTION", "public/test-inputs/TEST-ABSTENTION.jsonl"),
    ("TEST-JOINT", "public/test-inputs/TEST-JOINT.jsonl"),
)
PRIMITIVES = ("final_token", "full_mean", "first_token", "layer_m4_final",
              "layer_m3_final", "layer_m2_final", "middle_final")
SURFACE_ORDER = (
    "final_token", "full_mean", "first_token",
    "layer_m4_final", "layer_m3_final", "layer_m2_final",
    "last4_final_mean", "final_plus_mean", "middle_plus_final",
    "random_projection_256",
)

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)

def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)

def input_paths(bank_root: Path) -> list[tuple[str, Path]]:
    return [(split, bank_root / rel) for split, rel in INPUT_SPECS]

def row_identity(row: dict) -> str:
    return str(row["world_id"])

def surface_dim(name: str, hidden: int) -> int:
    if name == "random_projection_256":
        return 256
    if name in ("final_plus_mean", "middle_plus_final"):
        return hidden * 2
    return hidden

def surface_batch(primitives: dict[str, np.ndarray], start: int, stop: int,
                  name: str, projection: np.ndarray) -> np.ndarray:
    final = np.asarray(primitives["final_token"][start:stop], dtype=np.float32)
    if name == "final_token":
        return final.copy()
    if name == "full_mean":
        return np.asarray(primitives["full_mean"][start:stop], dtype=np.float32).copy()
    if name == "first_token":
        return np.asarray(primitives["first_token"][start:stop], dtype=np.float32).copy()
    if name in ("layer_m4_final", "layer_m3_final", "layer_m2_final"):
        return np.asarray(primitives[name][start:stop], dtype=np.float32).copy()
    if name == "last4_final_mean":
        arr = (np.asarray(primitives["layer_m4_final"][start:stop], dtype=np.float32)
               + np.asarray(primitives["layer_m3_final"][start:stop], dtype=np.float32)
               + np.asarray(primitives["layer_m2_final"][start:stop], dtype=np.float32)
               + final)
        return arr * 0.25
    if name == "final_plus_mean":
        mean = np.asarray(primitives["full_mean"][start:stop], dtype=np.float32)
        return np.concatenate((final, mean), axis=1)
    if name == "middle_plus_final":
        mid = np.asarray(primitives["middle_final"][start:stop], dtype=np.float32)
        return np.concatenate((mid, final), axis=1)
    if name == "random_projection_256":
        return final @ projection
    raise KeyError(name)

def _id(index: dict[str, int], value) -> int | None:
    return index.get(str(value)) if value is not None else None

def encode_targets(row: dict) -> dict[str, int | list[int]]:
    """Encode only outputs actually present in BANK's label object."""
    out: dict[str, int | list[int]] = {}
    labels = row.get("labels") or {}
    policy = labels.get("policy")
    if policy:
        out["decision"] = _id({v: i for i, v in enumerate(DECISIONS)}, policy.get("decision"))
        if policy.get("action") is not None:
            out["action_type"] = _id({v: i for i, v in enumerate(ACTIONS)}, policy["action"])
        if policy.get("reason") is not None:
            out["abstain_reason"] = _id({v: i for i, v in enumerate(ABSTAIN_REASONS)}, policy["reason"])
    if labels.get("nli") is not None:
        out["nli"] = _id({v: i for i, v in enumerate(NLI)}, labels["nli"])

    entity_rows = labels.get("entity")
    if entity_rows is not None:
        out["entity_types"] = sorted({
            ENTITY_TYPES.index(e["type"]) for e in entity_rows if e.get("type") in ENTITY_TYPES
        })
    relation_rows = labels.get("relation")
    if relation_rows is not None:
        out["relation_predicates"] = sorted({
            PREDICATES.index(f["pred"]) for f in relation_rows if f.get("pred") in PREDICATES
        })
    transition_rows = labels.get("transition")
    if transition_rows is not None:
        out["state_predicates"] = sorted({
            PREDICATES.index(f["pred"]) for f in transition_rows if f.get("pred") in PREDICATES
        })
    evidence_ids = labels.get("evidence")
    if evidence_ids is not None and relation_rows is not None:
        id_to_pred = {str(f.get("id")): f.get("pred") for f in relation_rows if f.get("id") is not None}
        out["evidence_predicates"] = sorted({
            PREDICATES.index(id_to_pred[str(fid)]) for fid in evidence_ids
            if str(fid) in id_to_pred and id_to_pred[str(fid)] in PREDICATES
        })
    return {k: v for k, v in out.items() if v is not None}

def targets_from_rows(rows: Iterable[dict]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    rows = list(rows)
    n = len(rows)
    values: dict[str, np.ndarray] = {}
    masks: dict[str, np.ndarray] = {}
    for name, classes in CATEGORICAL_HEADS.items():
        values[name] = np.full(n, -1, dtype=np.int16)
        masks[name] = np.zeros(n, dtype=np.bool_)
    for name, classes in MULTILABEL_HEADS.items():
        values[name] = np.zeros((n, len(classes)), dtype=np.float32)
        masks[name] = np.zeros(n, dtype=np.bool_)
    for i, row in enumerate(rows):
        for name, target in encode_targets(row).items():
            if name in CATEGORICAL_HEADS:
                values[name][i] = int(target)
                masks[name][i] = True
            elif name in MULTILABEL_HEADS:
                values[name][i, np.asarray(target, dtype=np.int64)] = 1.0
                masks[name][i] = True
    return values, masks
