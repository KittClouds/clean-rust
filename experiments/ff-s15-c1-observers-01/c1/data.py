"""BANK-v1 DEV rows: truth, and a leak-free calibration/holdout split. Nothing beyond DEV is read."""
from __future__ import annotations

import hashlib
import json

import numpy as np

from .common import ACTIONS, BANK, DECISIONS, DEV_ROWS, DEV_START, SWEEP


def load_dev() -> dict:
    """Returns row metadata and truth for the 24,000 DEV rows, in cache order."""
    rowmap = []
    with (SWEEP / "rowmap.jsonl").open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            if index < DEV_START:
                continue
            if index >= DEV_START + DEV_ROWS:
                break
            rowmap.append(json.loads(line))
    ids, worlds, graphs, families = [], [], [], []
    decision = np.full(DEV_ROWS, -1, dtype=np.int8)
    action = np.full(DEV_ROWS, -1, dtype=np.int8)
    with (BANK / "inputs" / "DEV.jsonl").open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            row = json.loads(line)
            if row["split"] != "DEV" or row["world_id"] != rowmap[index]["row_id"] or rowmap[index]["idx"] != DEV_START + index:
                raise RuntimeError(f"DEV row {index} does not line up with the cache rowmap")
            policy = row["labels"]["policy"]
            ids.append(row["world_id"])
            worlds.append(row["world_hash"])
            graphs.append(row["graph_hash"])
            families.append(row["surface_family"])
            decision[index] = DECISIONS.index(policy["decision"])
            if policy.get("action") is not None:
                action[index] = ACTIONS.index(policy["action"])
    if len(ids) != DEV_ROWS:
        raise RuntimeError("DEV row count mismatch")
    return {"ids": ids, "world_hash": worlds, "graph_hash": graphs, "family": families, "truth_decision": decision, "truth_action": action}


def hold_mask(ids: list, worlds: list, graphs: list) -> np.ndarray:
    """True for HOLD rows. Groups are connected components over world_hash and graph_hash, so neither ever straddles the split."""
    parent = list(range(len(ids)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict = {}
    for i in range(len(ids)):
        for key in (("w", worlds[i]), ("g", graphs[i])):
            if key in seen:
                a, b = find(i), find(seen[key])
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                seen[key] = i
    smallest: dict = {}
    for i in range(len(ids)):
        root = find(i)
        if root not in smallest or ids[i] < smallest[root]:
            smallest[root] = ids[i]
    mask = np.zeros(len(ids), dtype=bool)
    for i in range(len(ids)):
        digest = hashlib.sha256(("s15-c1-split-v1:" + smallest[find(i)]).encode("ascii")).hexdigest()
        mask[i] = int(digest[:8], 16) % 2 == 1
    return mask
