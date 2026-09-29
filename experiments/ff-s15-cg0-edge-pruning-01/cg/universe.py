"""The natural ordered-pair universe of each world, by exactly Lexi's candidate rule (see PLAN.md): typed nodes are entities with a matched span;
the universe is every ordered pair a != b of typed nodes; an edge is a pair that is the subject and object of a valid binary initial_state fact between typed nodes."""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from .common import BANK, OUT, PREDICATES, TEST_SPLITS, TYPE_CODES, pair_code, type_code

FAMILIES = tuple(f"S{i}" for i in range(12))


def load_rowmap() -> list:
    rows = [None] * 215996
    with (OUT / "rowmap.jsonl").open(encoding="utf-8") as source:
        for line in source:
            r = json.loads(line)
            rows[int(r["idx"])] = {"idx": int(r["idx"]), "world": str(r.get("paired_world") or r["world_id"]), "split": r["split"],
                                   "family": r.get("surface_family") or "", "paired": r.get("paired_world") is not None}
    if any(r is None for r in rows):
        raise RuntimeError("rowmap has gaps")
    return rows


def load_mentions() -> list:
    """row -> {entity_id: (entity_index, matched)}"""
    out = [None] * 215996
    with (OUT / "row-mentions.jsonl").open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            out[int(record["row_idx"])] = {str(m["entity_id"]): (int(m["entity_index"]), bool(m.get("matched"))) for m in record["mentions"]}
    return out


def read_worlds(split: str):
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def world_pairs(world: dict, mentions: dict) -> tuple:
    """(typed node list [(entity_index, entity_id)] sorted by index, set of positive (a_index, b_index) ordered pairs with a != b)."""
    typed = {}
    for entity in world.get("entities", []):
        eid = str(entity.get("id"))
        item = mentions.get(eid)
        if item and item[1]:
            typed[eid] = item[0]
    positives = set()
    for fact in world.get("initial_state") or []:
        args = [str(x) for x in (fact.get("args") or [])]
        if len(args) != 2 or str(fact.get("pred")) not in PREDICATES:
            continue
        if args[0] in typed and args[1] in typed and typed[args[0]] != typed[args[1]]:
            positives.add((typed[args[0]], typed[args[1]]))
    nodes = sorted((idx, eid) for eid, idx in typed.items())
    return nodes, positives


def selected_rows(rowmap: list, split: str) -> dict:
    """world_id -> row indexes to use, by Lexi's rule: canonical rows always; paired-renderer rows too for TEST partitions."""
    by_world = defaultdict(list)
    for r in rowmap:
        by_world[r["world"]].append(r)
    is_test = split.startswith("TEST")
    return {w: [r["idx"] for r in rows if (not r["paired"]) or is_test] for w, rows in by_world.items()}


def enumerate_split(split: str, rowmap: list, mentions: list) -> dict:
    """Arrays over every ordered pair of every selected row in the split."""
    chosen = selected_rows(rowmap, split)
    cols = {k: [] for k in ("row", "a", "b", "label", "pair_type", "family")}
    for world in read_worlds(split):
        for row_idx in chosen.get(str(world["world_id"]), []):
            nodes, positives = world_pairs(world, mentions[row_idx])
            if len(nodes) < 2:
                continue
            idx = np.array([n[0] for n in nodes], dtype=np.int64)
            codes = np.array([type_code(n[1]) for n in nodes], dtype=np.int64)
            n = len(nodes)
            a = np.repeat(idx, n)
            b = np.tile(idx, n)
            keep = a != b
            a, b = a[keep], b[keep]
            code = (np.repeat(codes, n) * len(TYPE_CODES) + np.tile(codes, n))[keep]
            label = np.fromiter(((x, y) in positives for x, y in zip(a.tolist(), b.tolist())), dtype=np.uint8, count=len(a))
            cols["row"].append(np.full(len(a), row_idx, dtype=np.int32))
            cols["a"].append(a.astype(np.int32))
            cols["b"].append(b.astype(np.int32))
            cols["label"].append(label)
            cols["pair_type"].append(code.astype(np.uint8))
            cols["family"].append(np.full(len(a), FAMILIES.index(rowmap[row_idx]["family"]) if rowmap[row_idx]["family"] in FAMILIES else 255, dtype=np.uint8))
    return {k: (np.concatenate(v) if v else np.array([], dtype=np.int32)) for k, v in cols.items()}


def train_pair_counts(rowmap: list, mentions: list) -> dict:
    """Natural type-pair counts over the full pair universe of canonical TRAIN worlds: pair_type -> [pairs, edges]."""
    chosen = selected_rows(rowmap, "TRAIN")
    counts = np.zeros((len(TYPE_CODES) ** 2, 2), dtype=np.int64)
    for world in read_worlds("TRAIN"):
        for row_idx in chosen.get(str(world["world_id"]), []):
            nodes, positives = world_pairs(world, mentions[row_idx])
            if len(nodes) < 2:
                continue
            codes = np.array([type_code(n[1]) for n in nodes], dtype=np.int64)
            per_type = np.bincount(codes, minlength=len(TYPE_CODES))
            for ca in range(len(TYPE_CODES)):
                for cb in range(len(TYPE_CODES)):
                    pairs = per_type[ca] * (per_type[cb] - (1 if ca == cb else 0))
                    counts[pair_code(ca, cb), 0] += pairs
            by_index = {n[0]: type_code(n[1]) for n in nodes}
            for x, y in positives:
                counts[pair_code(by_index[x], by_index[y]), 1] += 1
    return {"pairs": counts[:, 0].tolist(), "edges": counts[:, 1].tolist()}
