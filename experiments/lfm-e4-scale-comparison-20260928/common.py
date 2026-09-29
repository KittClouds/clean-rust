"""Shared five-head E4 contract and artifact helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


TASKS = {
    "context_identity": ("context_term_id", 32),
    "entity_identity": ("entity_term_id", 32),
    "relation": ("relation_id", 2),
    "observed_state": ("state_id", 3),
    "exact_target": ("exact_target", 3),
}
CONDITIONAL = frozenset(("relation", "observed_state", "exact_target"))
OPTIMIZER = {
    "learning_rate": 1.0,
    "max_iter": 300,
    "max_eval": 375,
    "tolerance_grad": 1e-7,
    "tolerance_change": 1e-9,
    "history_size": 10,
    "line_search": "strong_wolfe",
}
REGULARIZATION = 1e-4


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(8 << 20):
            h.update(data)
    return h.hexdigest()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def feature_map(path: Path, rows: int, dimension: int) -> np.memmap:
    if path.stat().st_size != rows * dimension * 4:
        raise RuntimeError(f"invalid f32 cache bytes: {path}")
    return np.memmap(path, dtype="<f4", mode="r", shape=(rows, dimension))


def task_eligible(row: dict, name: str) -> bool:
    return name not in CONDITIONAL or (
        row["context_term_id"] < 16 and row["entity_term_id"] < 16
    )
