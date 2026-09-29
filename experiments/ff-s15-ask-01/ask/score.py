"""HOLD scoring through the real C0 runtime, and the preregistered criteria A1-A3. Only the score stage reads HOLD."""
from __future__ import annotations

import numpy as np

from . import records
from .common import ACTIONS, C1_EVIDENCE, MATCHED_PRECISIONS, PRIMARY_ALPHA, c1fit, c1records, model, runtime

CODES = {"EXECUTE_ALLOWED": c1fit.EXECUTED, "ABSTAINED": c1fit.ABSTAINED, "ASKED": c1fit.ASKED, "ESCALATED": c1fit.ESCALATED}


def run_policy(job: dict) -> dict:
    """Worker: one policy over all HOLD rows through the C0 runtime. `job['sources']` maps each observer's bundle id to (npz path, array key)."""
    world = model.load_world(job["policy"], job["contracts"], job["bundles"])
    truth = np.load(C1_EVIDENCE / "dev-truth.npz", allow_pickle=False)
    hold = np.flatnonzero(truth["hold"])
    ids, world_hashes, families = truth["ids"], truth["world_hash"], truth["family"]
    files = {}
    arrays = {}
    for bundle_id, (path, key) in job["sources"].items():
        files.setdefault(path, np.load(path, allow_pickle=False))
        arrays[bundle_id] = files[path][key]
    needed = [b["bundle_id"] for b in world.alias_bundle.values()]
    disposition = np.empty(len(hold), dtype=np.int8)
    target = np.full(len(hold), -1, dtype=np.int16)
    repeat_identical = True
    for position, index in enumerate(hold):
        world_id = str(ids[index])
        observation = c1records.observation(world_id, str(world_hashes[index]), str(families[index]))
        vector = records.vector(world_id, {b: arrays[b][index] for b in needed}, job["name"])
        receipt, data = runtime.run(world, observation, vector)
        disposition[position] = CODES[receipt["disposition"]]
        if receipt["disposition"] == "EXECUTE_ALLOWED":
            target[position] = ACTIONS.index(receipt["disposition_target"])
        if position < 300:
            repeat_identical &= runtime.run(world, observation, vector)[1] == data
    return {"name": job["name"], "disposition": disposition, "target": target, "repeat_identical": bool(repeat_identical)}


def criteria(signal: dict, rule: dict, cost: dict) -> dict:
    """A1-A3 for one head on the primary surface.

    signal: {'dedicated': {'ap', 'recall_at': {p: recall|None}}, 'baseline': {...}}; rule: HOLD outcomes of the fitted ASK rule at the primary alpha;
    cost: {'combined': outcomes, 'c1': outcomes} for the controller with and without the ASK rule."""
    d, b = signal["dedicated"], signal["baseline"]
    wins = 0
    for p in MATCHED_PRECISIONS:
        dr, br = d["recall_at"][str(p)], b["recall_at"][str(p)]
        if dr is not None and (br is None or dr >= 1.25 * br):
            wins += 1
    a1 = bool(d["ap"] >= 1.25 * b["ap"] and wins >= 3)
    a2 = bool(rule["threshold_ppm"] is not None and rule["asks"] >= 100 and rule["precision"] is not None and rule["precision"] >= 0.45 and rule["recall"] >= 0.25)
    c, k = cost["combined"], cost["c1"]
    a3 = bool(k["correct_executed"] > 0 and c["correct_executed"] >= 0.90 * k["correct_executed"] and c["harm_rate"] is not None and k["harm_rate"] is not None
              and c["harm_rate"] <= k["harm_rate"] + 0.005)
    return {"A1_beats_existing_head": a1, "A1_matched_precision_wins": wins, "A2_usable_rule": a2, "A3_acting_tier_intact": a3, "all": bool(a1 and a2 and a3)}


def verdict(c: dict) -> str:
    if c["all"]:
        return "USEFUL ASK OBSERVER"
    if c["A1_beats_existing_head"]:
        return "SIGNAL, NOT USABLE"
    return "NO GAIN OVER THE EXISTING HEAD"
