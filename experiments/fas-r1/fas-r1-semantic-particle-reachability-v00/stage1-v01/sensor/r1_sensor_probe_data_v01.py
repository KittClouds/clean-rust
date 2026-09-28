"""Frozen feature/row construction for R1 Stage 1 probes.

This module only constructs declared probe inputs and row identities. For the
evaluation split it deliberately omits labels from returned datasets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

CONDITION_BY_VARIANT = {
    "eval_id_t0_v0": "id_seen", "eval_id_t1_v0": "id_seen",
    "eval_template_t2_v0": "template_ood",
    "eval_vocab_t0_v1": "vocabulary_ood", "eval_vocab_t1_v1": "vocabulary_ood",
    "eval_joint_t2_v1": "joint_ood",
}
KIND_ORDER = ("Same", "Different", "FixedRole", "ForbiddenRole", "ExactlyOneRole", "ImpliesNotRole")
SLOT_ORDER = ("entity_arg_0", "entity_arg_1", "role_arg_0", "role_arg_1")
ACTION_ORDER = ("improve", "neutral", "worsen")
SHUFFLE_DOMAIN = b"R1-STAGE1-SHUFFLED-FEATURE-v1\0"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def seed_for(*parts: str) -> int:
    digest = hashlib.sha256(SHUFFLE_DOMAIN + b"\0".join(p.encode("utf-8") for p in parts)).digest()
    return int.from_bytes(digest[:8], "little")


@dataclass
class Rows:
    """Rows backed by shared component arrays; batches gather only needed rows."""

    parts: list[np.ndarray]
    indexes: list[np.ndarray | None]
    labels: np.ndarray
    families: np.ndarray
    keys: np.ndarray
    conditions: np.ndarray
    extras: list[dict[str, Any]]

    @property
    def input_dim(self) -> int:
        return sum(int(part.shape[1]) for part in self.parts)

    def __len__(self) -> int:
        return int(self.labels.shape[0])

    def batch(self, indices: np.ndarray) -> np.ndarray:
        out = np.empty((len(indices), self.input_dim), dtype=np.float32)
        offset = 0
        for part, indexer in zip(self.parts, self.indexes, strict=True):
            source_indices = indices if indexer is None else indexer[indices]
            width = int(part.shape[1])
            np.copyto(out[:, offset:offset + width], part[source_indices], casting="unsafe")
            offset += width
        return out


def _onehot(index: int, width: int) -> np.ndarray:
    out = np.zeros(width, dtype=np.float32)
    if 0 <= index < width:
        out[index] = 1.0
    return out


def _variant(task: dict[str, Any]) -> str:
    return str(task["id"]).split("__", 1)[1]


def _base_task_id(task: dict[str, Any]) -> str:
    return str(task["id"]).split("__", 1)[0]


class SensorData:
    def __init__(self, data_root: Path, extraction_root: Path):
        self.data_root = data_root
        self.extraction_root = extraction_root
        self.public = read_jsonl(data_root / "public-probe-tasks.jsonl")
        self.split_by_family = {row["family_id"]: row["split"] for row in read_jsonl(data_root / "family-split.jsonl")}
        self.names = read_jsonl(data_root / "name-queries.jsonl")
        self.targets = [row for row in read_jsonl(data_root / "private-probe-targets.jsonl") if row["split"] != "evaluation"]
        self.actions = [row for row in read_jsonl(data_root / "private-action-examples.jsonl") if row["split"] != "evaluation"]
        self.eval_actions = [
            {key: row[key] for key in ("task_id", "family_id", "split", "state_index", "assignment", "edit_entity", "old_role", "new_role")}
            for row in read_jsonl(data_root / "private-action-examples.jsonl") if row["split"] == "evaluation"
        ]
        self.global_h = np.load(extraction_root / "global_h.float32.npy", mmap_mode="r")
        self.constraint_h = np.load(extraction_root / "constraint_H.float32.npy", mmap_mode="r")
        self.name_h = np.load(extraction_root / "name_H.float32.npy", mmap_mode="r")
        self.public_by_id = {row["id"]: row for row in self.public}
        self.target_by_id = {row["public_task_id"]: row for row in self.targets}
        self.name_row = {row["name_id"]: index for index, row in enumerate(self.names)}
        row_map = read_jsonl(extraction_root / "rows.jsonl")
        self.global_row: dict[str, int] = {}
        self.clause_row: dict[tuple[str, int], int] = {}
        for row in row_map:
            if row["kind"] == "global":
                self.global_row[row["task_id"]] = int(row["row"])
            elif row["kind"] == "constraint":
                self.clause_row[(row["task_id"], int(row["clause_index"]))] = int(row["row"])
        for task in self.public:
            if self._split(task) != "evaluation" and len(task["clauses"]) != len(self.target_by_id[task["id"]]["clauses"]):
                raise ValueError(f"clause target count mismatch for {task['id']}")
        self.task_meta = np.stack([self._task_meta(task) for task in self.public]).astype(np.float32)
        self.task_index = {task["id"]: i for i, task in enumerate(self.public)}
        self.clause_meta: dict[tuple[str, int], np.ndarray] = {}
        self.task_repr = np.empty((len(self.public), 4096), dtype=np.float32)
        self.action_surface = np.empty((len(self.public), 40), dtype=np.float32)
        self._build_task_features()

    def _task_meta(self, task: dict[str, Any]) -> np.ndarray:
        variant = _variant(task)
        template = "T2" if "t2" in variant else "T1" if "t1" in variant else "T0"
        vocab = "V1" if "v1" in variant else "V0"
        out = np.concatenate([
            _onehot(("T0", "T1", "T2").index(template), 3),
            _onehot(("V0", "V1").index(vocab), 2),
            _onehot(int(task["n"]) - 1, 12),
            _onehot(int(task["k"]) - 1, 4),
            np.asarray([float(bool(task["role_anonymous"])), len(task["clauses"]) / 24.0, len(task["global_text"]) / 1024.0], dtype=np.float32),
        ])
        return out

    def _build_task_features(self) -> None:
        for task_index, task in enumerate(self.public):
            task_id = task["id"]
            start = self.global_row[task_id]
            global_vec = np.asarray(self.global_h[start], dtype=np.float32)
            clause_ids = [self.clause_row[(task_id, i)] for i in range(len(task["clauses"]))]
            if clause_ids:
                clause_vectors = np.asarray(self.constraint_h[clause_ids], dtype=np.float32)
                mean_clause = clause_vectors.mean(axis=0, dtype=np.float32)
            else:
                clause_vectors = np.empty((0, 2048), dtype=np.float32)
                mean_clause = np.zeros(2048, dtype=np.float32)
            self.task_repr[task_index, :2048] = mean_clause
            self.task_repr[task_index, 2048:] = global_vec
            entity_counts = np.zeros(12, dtype=np.float32)
            role_counts = np.zeros(4, dtype=np.float32)
            for clause_index, clause in enumerate(task["clauses"]):
                entities = task["entity_mentions"][clause_index]
                roles = task["role_mentions"][clause_index]
                entity_counts[entities] += 1.0
                role_counts[roles] += 1.0
                meta = np.concatenate([
                    _onehot_mask(entities, 12), _onehot_mask(roles, 4),
                    np.asarray([len(clause) / 512.0, len(clause.split()) / 64.0,
                                clause_index / max(1, len(task["clauses"])),
                                len(set(entities)) / 4.0, len(set(roles)) / 2.0], dtype=np.float32),
                ])
                self.clause_meta[(task_id, clause_index)] = meta
            counts = np.concatenate([np.clip(entity_counts, 0, 12) / 12.0, np.clip(role_counts, 0, 6) / 6.0])
            self.action_surface[task_index] = np.concatenate([self.task_meta[task_index], counts])

    def _grouped_shuffle(self, groups: dict[str, list[int]]) -> np.ndarray:
        result = np.arange(len(self.public), dtype=np.int64)
        for group, values in groups.items():
            if len(values) > 1:
                order = np.asarray(values, dtype=np.int64)
                perm = np.random.default_rng(seed_for(group)).permutation(order)
                result[order] = perm
        return result

    def clause_shuffle(self) -> np.ndarray:
        groups: dict[str, list[int]] = {}
        for task in self.public:
            key = task["id"]
            group = f"{self._split(task)}|{_variant(task)}"
            groups.setdefault(group, []).extend(self.clause_row[(key, i)] for i in range(len(task["clauses"])) )
        result = np.arange(self.constraint_h.shape[0], dtype=np.int64)
        for group, values in groups.items():
            if len(values) > 1:
                order = np.asarray(values, dtype=np.int64)
                result[order] = np.random.default_rng(seed_for("clause", group)).permutation(order)
        return result

    def action_shuffle(self) -> np.ndarray:
        groups: dict[str, list[int]] = {}
        for index, task in enumerate(self.public):
            if self._split(task) == "evaluation":
                key = CONDITION_BY_VARIANT[_variant(task)]
            else:
                key = f"{self._split(task)}|{_variant(task)}"
            groups.setdefault(key, []).append(index)
        result = np.arange(len(self.public), dtype=np.int64)
        for group, values in groups.items():
            if len(values) > 1:
                order = np.asarray(values, dtype=np.int64)
                result[order] = np.random.default_rng(seed_for("action", group)).permutation(order)
        return result

    def splits(self) -> dict[str, list[int]]:
        output = {name: [] for name in ("train", "validation", "evaluation")}
        for index, task in enumerate(self.public):
            output[self._split(task)].append(index)
        return output

    def _condition(self, task: dict[str, Any]) -> str:
        return CONDITION_BY_VARIANT.get(_variant(task), "not_applicable")

    def _split(self, task: dict[str, Any]) -> str:
        return self.split_by_family[task["family_id"]]

    def semantic_rows(self, split: str, arm: str) -> Rows:
        clause_indices: list[int] = []
        task_indices: list[int] = []
        labels: list[int] = []
        families: list[str] = []
        keys: list[str] = []
        conditions: list[str] = []
        for ti, task in enumerate(self.public):
            if self._split(task) != split:
                continue
            target_clauses = self.target_by_id[task["id"]]["clauses"] if split != "evaluation" else [None] * len(task["clauses"])
            for ci, target_clause in enumerate(target_clauses):
                clause_indices.append(self.clause_row[(task["id"], ci)])
                task_indices.append(ti)
                labels.append(KIND_ORDER.index(target_clause["kind"]) if target_clause is not None else -1)
                families.append(task["family_id"])
                keys.append(f"{task['id']}|{ci}")
                conditions.append(self._condition(task))
        clause_ids = np.asarray(clause_indices, dtype=np.int64)
        task_ids = np.asarray(task_indices, dtype=np.int64)
        y = np.asarray(labels, dtype=np.int64)
        family = np.asarray(families, dtype=str)
        key_arr = np.asarray(keys, dtype=str)
        cond = np.asarray(conditions, dtype=str)
        if arm in ("real", "shuffled"):
            hidx = clause_ids if arm == "real" else self.clause_shuffle()[clause_ids]
            return Rows([self.constraint_h], [hidx], y, family, key_arr, cond, [{} for _ in labels])
        meta = np.stack([np.concatenate([self.task_meta[ti], self.clause_meta[(self.public[ti]["id"], ci)]])
                         for ti, ci in zip(task_ids, [int(key.rsplit("|", 1)[1]) for key in keys], strict=True)])
        if arm == "surface":
            return Rows([meta], [None], y, family, key_arr, cond, [{} for _ in labels])
        if arm == "template":
            template_meta = np.stack([np.concatenate([self.task_meta[ti], self.clause_meta[(self.public[ti]["id"], ci)][16:]])
                                      for ti, ci in zip(task_ids, [int(key.rsplit("|", 1)[1]) for key in keys], strict=True)])
            return Rows([template_meta], [None], y, family, key_arr, cond, [{} for _ in labels])
        raise ValueError(f"unknown arm {arm}")

    def binding_rows(self, split: str, arm: str) -> Rows:
        clause_ids: list[int] = []
        name_ids: list[int] = []
        slot_ids: list[int] = []
        kind_ids: list[int] = []
        task_ids: list[int] = []
        clause_numbers: list[int] = []
        candidate_numbers: list[int] = []
        labels: list[int] = []
        families: list[str] = []
        keys: list[str] = []
        conditions: list[str] = []
        for ti, task in enumerate(self.public):
            if self._split(task) != split:
                continue
            vocab = "V1" if "v1" in _variant(task) else "V0"
            target = self.target_by_id.get(task["id"])
            target_clauses = target["clauses"] if target is not None else [None] * len(task["clauses"])
            for ci, target_clause in enumerate(target_clauses):
                slots = target_clause["argument_slots"] if target_clause is not None else {}
                for slot_index, slot in enumerate(SLOT_ORDER):
                    slot_kind = "entities" if slot.startswith("entity") else "roles"
                    if split != "evaluation" and slot not in slots:
                        continue
                    candidate_count = 12 if slot_kind == "entities" else 4
                    expected = slots.get(slot) if target is not None and slot in slots else None
                    for candidate in range(candidate_count):
                        name_id = f"{vocab}_{slot_kind}_{candidate:02d}"
                        ni = self.name_row[name_id]
                        clause_ids.append(self.clause_row[(task["id"], ci)])
                        name_ids.append(ni)
                        slot_ids.append(slot_index)
                        kind_ids.append(0 if slot_kind == "entities" else 1)
                        task_ids.append(ti)
                        clause_numbers.append(ci)
                        candidate_numbers.append(candidate)
                        labels.append(int(expected == candidate) if split != "evaluation" and slot in slots else -1)
                        families.append(task["family_id"])
                        keys.append(f"{task['id']}|{ci}|{slot_index}|{candidate}")
                        conditions.append(self._condition(task))
        cidx = np.asarray(clause_ids, dtype=np.int64)
        nidx = np.asarray(name_ids, dtype=np.int64)
        sidx = np.asarray(slot_ids, dtype=np.int64)
        kidx = np.asarray(kind_ids, dtype=np.int64)
        y = np.asarray(labels, dtype=np.int64)
        fam = np.asarray(families, dtype=str)
        key_arr = np.asarray(keys, dtype=str)
        cond = np.asarray(conditions, dtype=str)
        if arm in ("real", "shuffled"):
            clause_perm = self.clause_shuffle() if arm == "shuffled" else None
            source_clause = cidx if clause_perm is None else clause_perm[cidx]
            return Rows(
                [self.constraint_h, self.name_h, _onehot_matrix(4), _onehot_matrix(2)],
                [source_clause, nidx, sidx, kidx], y, fam, key_arr, cond, [{} for _ in labels]
            )
        surface = []
        for ti, ci, si, ki, candidate in zip(task_ids, clause_numbers, slot_ids, kind_ids, candidate_numbers, strict=True):
            task = self.public[ti]
            vocab = "V1" if "v1" in _variant(task) else "V0"
            mentions = task["entity_mentions"][ci] if ki == 0 else task["role_mentions"][ci]
            max_candidates = 12
            surface.append(np.concatenate([
                self.task_meta[ti], self.clause_meta[(task["id"], ci)],
                _onehot(si, 4), _onehot(ki, 2), _onehot(candidate, max_candidates),
                np.asarray([float(candidate in mentions)], dtype=np.float32),
            ]))
        if arm == "surface":
            x = np.stack(surface).astype(np.float32)
        elif arm == "template":
            x = np.stack([np.concatenate([self.task_meta[ti], self.clause_meta[(self.public[ti]["id"], ci)][16:],
                                           _onehot(si, 4), _onehot(ki, 2)])
                          for ti, ci, si, ki in zip(task_ids, clause_numbers, slot_ids, kind_ids, strict=True)]).astype(np.float32)
        else:
            raise ValueError(f"unknown arm {arm}")
        return Rows([x], [None], y, fam, key_arr, cond, [{} for _ in labels])

    def action_rows(self, split: str, arm: str) -> Rows:
        task_indices_by_base: dict[str, list[int]] = {}
        for ti, task in enumerate(self.public):
            if self._split(task) == split:
                task_indices_by_base.setdefault(_base_task_id(task), []).append(ti)
        action_permutation = self.action_shuffle() if arm == "shuffled" else np.arange(len(self.public), dtype=np.int64)
        state_rows: list[np.ndarray] = []
        rep_indices: list[int] = []
        task_indices: list[int] = []
        labels: list[int] = []
        families: list[str] = []
        keys: list[str] = []
        conditions: list[str] = []
        extras: list[dict[str, Any]] = []
        for row in (self.eval_actions if split == "evaluation" else self.actions):
            if row["split"] != split:
                continue
            for ti in task_indices_by_base[row["task_id"]]:
                task = self.public[ti]
                variant = _variant(task)
                if split != "evaluation":
                    label = ACTION_ORDER.index(row["target_sign"])
                else:
                    label = -1
                assignment = np.zeros((12, 4), dtype=np.float32)
                for entity, role in enumerate(row["assignment"]):
                    assignment[entity, int(role)] = 1.0
                state = np.concatenate([
                    assignment.reshape(-1), _onehot_mask(range(int(task["n"])), 12),
                    _onehot_mask(range(int(task["k"])), 4), _onehot(int(row["edit_entity"]), 12),
                    _onehot(int(row["old_role"]), 4), _onehot(int(row["new_role"]), 4),
                ])
                rep_index = int(action_permutation[ti])
                rep_indices.append(rep_index)
                state_rows.append(state)
                task_indices.append(ti)
                labels.append(label)
                families.append(row["family_id"])
                keys.append(f"{variant}|{row['task_id']}|{row['state_index']}|{row['edit_entity']}|{row['new_role']}")
                conditions.append(self._condition(task))
                extras.append({} if split == "evaluation" else {
                    "nearest_solution_hamming": int(row["nearest_solution_hamming"]),
                    "violations_before": int(row["violations_before"]),
                    "role_anonymous": bool(task["role_anonymous"]),
                    "n": int(task["n"]), "edit_kind": "role_change",
                })
        states = np.stack(state_rows).astype(np.float32)
        y = np.asarray(labels, dtype=np.int64)
        family = np.asarray(families, dtype=str)
        key_arr = np.asarray(keys, dtype=str)
        cond = np.asarray(conditions, dtype=str)
        ti_arr = np.asarray(task_indices, dtype=np.int64)
        rep_idx = np.asarray(rep_indices, dtype=np.int64)
        if arm in ("real", "shuffled"):
            return Rows([self.task_repr, states], [rep_idx, None], y, family, key_arr, cond, extras)
        if arm == "surface":
            return Rows([self.action_surface, states], [ti_arr, None], y, family, key_arr, cond, extras)
        if arm == "template":
            return Rows([self.task_meta, states], [ti_arr, None], y, family, key_arr, cond, extras)
        raise ValueError(f"unknown arm {arm}")

def _onehot_matrix(width: int) -> np.ndarray:
    return np.eye(width, dtype=np.float32)


def _onehot_mask(indices: Iterable[int], width: int) -> np.ndarray:
    out = np.zeros(width, dtype=np.float32)
    for index in indices:
        if 0 <= int(index) < width:
            out[int(index)] = 1.0
    return out
