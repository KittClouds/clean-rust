"""Acquisition policies. Each picks the next unqueried slot from what it is allowed to see: the working graph, the frozen controller's diagnostics (policy D only), and producer confidences (policy B, and D's fallback).
None sees the hidden facts. The oracle selector lives in env.oracle_min_sets and is an upper bound, not a policy."""
from __future__ import annotations

import random

from . import common
from .env import Episode, Slot, all_slots, outcome


def uncertainty(world: dict, bundle, idx: int) -> dict:
    """slot -> uncertainty in [0,1]: the largest 4p(1-p) over the slot's candidate propositions, p from X1's T2 (AT and location-to-location existence) and T0 (everything else)."""
    common.x1_path()
    from x1.abi import universe
    t0 = {e.candidate_edge: e.confidence for e in bundle.t0.emit(world)}
    t2 = {e.candidate_edge: e.confidence for e in bundle.t2.emit(idx, world)}
    unc: dict = {}
    for k in universe(world):
        p = t2.get(k, t0.get(k, 0.5))
        u = 4 * p * (1 - p)
        pred, args, val = k
        slot = {"AT": ("LOC", args[0]), "STATE": ("STATE", args[0]), "REQUIRES": ("GATE", args[0]), "CONNECTED": ("NBR", args[0]), "BLOCKED": ("NBR", args[0])}[pred]
        unc[slot] = max(unc.get(slot, 0.0), u)
    return unc


# ------------------------------------------------------------------------------------------------ A, B, C
def random_next(ep: Episode, rng: random.Random) -> Slot | None:
    left = ep.unqueried()
    return rng.choice(left) if left else None


def confidence_next(ep: Episode, unc: dict) -> Slot | None:
    left = ep.unqueried()
    if not left:
        return None
    pool = [s for s in left if ep.empty_looking(s)] or left
    return sorted(pool, key=lambda s: (-unc.get(s, 0.0), s))[0]


def family_plan(world: dict, order: tuple, rng: random.Random) -> list[Slot]:
    """Broad producer acquisition: whole families in the given order, slots within a family in a seeded random order."""
    slots = all_slots(world)
    plan: list[Slot] = []
    for fam in order:
        inside = [s for s in slots if s[0] == fam]
        rng.shuffle(inside)
        plan += inside
    return plan


def plan_next(ep: Episode, plan: list[Slot]) -> Slot | None:
    for s in plan:
        if s not in ep.queried:
            return s
    return None


# ------------------------------------------------------------------------------------------------ D: graph deficiency
def _pattern_slot(ep: Episode, pat: str) -> Slot | None:
    _p, pred, rest = pat.split(":", 2)
    if pred == "AT":
        return ("LOC", rest.split(",")[0])
    if pred == "STATE":
        return ("STATE", rest.split(":")[0])
    if pred == "CONNECTED":
        a, b = rest.split(",")
        cands = [s for s in (("NBR", a), ("NBR", b)) if s not in ep.queried]
        empty = [s for s in cands if ep.empty_looking(s)]
        return (empty or cands or [None])[0]
    return None


def deficiency_next(ep: Episode, d: dict, G, unc: dict, signals=(1, 2, 3)) -> tuple[Slot | None, str]:
    """Returns (slot, which signal supplied it). Priority: 1 goal-blocking repairs, 2 conflict, 3 missing slot; fallback is the confidence policy."""
    control = ep._control
    v = control.View(G)
    if 1 in signals:
        counts: dict = {}
        for pat in control.repair_set(v, 0.5, 0.5):
            s = _pattern_slot(ep, pat)
            if s is not None and s not in ep.queried:
                counts[s] = counts.get(s, 0) + 1
        if counts:
            return sorted(counts, key=lambda s: (-counts[s], s))[0], "repair"
    if 2 in signals and d.get("reason") == "CONFLICTING_EVIDENCE":
        seen: dict = {}
        for f in ep.visible_facts():
            if f["pred"] == "STATE":
                seen.setdefault(f["args"][0], set()).add(f.get("value"))
        for sw, vals in sorted(seen.items()):
            if len(vals) > 1 and ("STATE", sw) not in ep.queried:
                return ("STATE", sw), "conflict"
    if 3 in signals:
        missing, bridges = control.slot_deficiency(v, 0.5)
        counts = {}
        for sid in missing:
            _s, kind, ent = sid.split(":")
            slot = {"AT": ("LOC", ent), "STATE": ("STATE", ent), "LINK": ("NBR", ent)}[kind]
            if slot not in ep.queried:
                counts[slot] = counts.get(slot, 0) + 1
        for pat in bridges:
            s = _pattern_slot(ep, pat)
            if s is not None and s not in ep.queried:
                counts[s] = counts.get(s, 0) + 1
        if counts:
            return sorted(counts, key=lambda s: (-counts[s], s))[0], "missing_slot"
    return confidence_next(ep, unc), "fallback"


# ------------------------------------------------------------------------------------------------ the episode loop (shared stop rule)
def run(world: dict, hidden: set, chooser, budget: int = common.BUDGET, modules=None) -> dict:
    """chooser(ep, d, G) -> (slot or None, tag). Stops when the frozen controller decides ACT (correct -> recovered, wrong -> harm) or the budget is spent."""
    ep = Episode(world, hidden, modules)
    bank = ep._bank
    d, G = ep.decide()
    tags = []
    while d["decision"] != "ACT" and ep.cost < budget:
        slot, tag = chooser(ep, d, G)
        if slot is None:
            break
        ep.query(slot)
        tags.append(tag)
        d, G = ep.decide(G=None)
    good, bad = outcome(world, d, bank)
    return {"recovered": good, "harm": bad, "cost": ep.cost, "log": list(ep.log), "tags": tags}


def curve(res: dict, budget: int = common.BUDGET) -> list[int]:
    """recovered_at[b] for b = 0..budget."""
    return [1 if (res["recovered"] and res["cost"] <= b) else 0 for b in range(budget + 1)]
