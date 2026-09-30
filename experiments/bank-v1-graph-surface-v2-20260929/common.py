"""Shared immutable contracts and helpers for graph-local BANK-v1 Rung 1."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

SEED = 20260929
HIDDEN = 1024
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
WORLD_SPLITS = ("TRAIN", "DEV", "TEST-IID", "TEST-LEXICAL", "TEST-ENTITY",
                "TEST-TEMPLATE", "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION",
                "TEST-JOINT")
SURFACES = ("middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean")
ENTITY_TYPES = ("OBJECT", "AGENT", "LOCATION", "SWITCH", "CONTAINER", "RESOURCE")
PREDICATES = ("AT", "HAS", "CONNECTED", "REQUIRES", "STATE", "BLOCKED",
              "ENABLES", "BEFORE", "PART_OF", "OWNS")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@lru_cache(maxsize=8192)
def _mention_pattern(mention: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w])" + re.escape(mention) + r"(?![\w])", re.IGNORECASE)


def exact_spans(text: str, mention: str, start: int = 0, end: int | None = None) -> list[list[int]]:
    """Find case-insensitive, whole-mention spans; never fuzzy-match entity names."""
    if not mention:
        return []
    stop = len(text) if end is None else end
    return [[match.start(), match.end()] for match in _mention_pattern(mention).finditer(text, start, stop)]


def local_surface_arrays(primitives: dict[str, np.ndarray], indexes: np.ndarray,
                         surface: str) -> np.ndarray:
    if surface == "middle_plus_final":
        return np.concatenate((primitives["middle_mean"][indexes],
                               primitives["final_mean"][indexes]), axis=1)
    if surface == "final_plus_mean":
        return np.concatenate((primitives["final_last"][indexes],
                               primitives["final_mean"][indexes]), axis=1)
    if surface == "layer_m4_final":
        return np.asarray(primitives["m4_mean"][indexes])
    if surface == "full_mean":
        return np.asarray(primitives["final_mean"][indexes])
    raise KeyError(surface)


def cached_surface_arrays(primitives: dict[str, np.ndarray], indexes: np.ndarray,
                          surface: str) -> np.ndarray:
    final = np.asarray(primitives["final_token"][indexes], dtype=np.float32)
    if surface == "middle_plus_final":
        return np.concatenate((primitives["middle_final"][indexes], final), axis=1)
    if surface == "final_plus_mean":
        return np.concatenate((final, primitives["full_mean"][indexes]), axis=1)
    if surface == "layer_m4_final":
        return np.asarray(primitives["layer_m4_final"][indexes], dtype=np.float32)
    if surface == "full_mean":
        return np.asarray(primitives["full_mean"][indexes], dtype=np.float32)
    if surface == "first_token":
        return np.asarray(primitives["first_token"][indexes], dtype=np.float32)
    raise KeyError(surface)


def token_to_lexical_type(mention: str) -> str:
    """Deliberately cheap mention-string baseline; entity IDs are not inspected."""
    text = mention.casefold()
    if "switch" in text:
        return "SWITCH"
    if "agent" in text or text.strip() == "maris":
        return "AGENT"
    if "container" in text or "crate" in text:
        return "CONTAINER"
    if "resource" in text:
        return "RESOURCE"
    if "object" in text or any(x in text for x in ("ember", "onyx", "jade", "copper", "topaz")):
        return "OBJECT"
    return "LOCATION"


def identifier_type(entity_id: str) -> str:
    prefix = entity_id.split("_", 1)[0].casefold()
    return {"obj": "OBJECT", "ag": "AGENT", "loc": "LOCATION", "sw": "SWITCH",
            "cont": "CONTAINER", "res": "RESOURCE"}.get(prefix, "UNKNOWN")
