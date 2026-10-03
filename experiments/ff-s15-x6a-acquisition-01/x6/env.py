"""The costed acquisition environment. A world's true facts are partitioned into slots; some fact-bearing slots are hidden from the working graph; QUERY(slot) reveals a slot at cost 1.
The frozen X0 controller is the only consumer; policies never see hidden facts."""
from __future__ import annotations

import hashlib
import random

from . import common
from .common import etype

Slot = tuple  # (family, id)


def slot_of_fact(f: dict) -> Slot | None:
    p, a = f["pred"], [str(x) for x in (f.get("args") or [])]
    if p == "AT" and a:
        return ("LOC", a[0])
    if p == "STATE" and a:
        return ("STATE", a[0])
    if p == "REQUIRES" and a:
        return ("GATE", a[0])
    if p in ("CONNECTED", "BLOCKED") and a:
        return ("NBR", a[0])
    return None  # distractor predicates are always visible and cannot be queried


def all_slots(world: dict) -> list[Slot]:
    out: list[Slot] = []
    for e in world["entities"]:
        eid = str(e["id"])
        t = etype(eid)
        if t in ("OBJECT", "AGENT"):
            out.append(("LOC", eid))
        elif t == "SWITCH":
            out.append(("STATE", eid))
        elif t == "LOCATION":
            out += [("GATE", eid), ("NBR", eid)]
    return sorted(set(out))


def slot_facts(world: dict) -> dict[Slot, list[dict]]:
    by: dict = {}
    for f in world["initial_state"]:
        s = slot_of_fact(f)
        if s is not None:
            by.setdefault(s, []).append(f)
    return by


def hide(world: dict, h: float, seed) -> set[Slot]:
    """Each fact-bearing slot is hidden with probability h (seeded by world)."""
    rng = random.Random(int(hashlib.sha256(f"x6a|{seed}|{world['world_id']}|{h}".encode()).hexdigest()[:16], 16))
    return {s for s in sorted(slot_facts(world)) if rng.random() < h}


class Episode:
    """One world, one hiding. The working graph is the true facts minus the hidden slots plus whatever has been queried."""

    def __init__(self, world: dict, hidden: set[Slot], oracle=None):
        self.world = world
        self.by = slot_facts(world)
        self.hidden = set(hidden)
        self.queried: set[Slot] = set()
        self.cost = 0
        self.log: list = []
        self._bank, self._build, self._control = oracle or common.x0_modules()

    # ---- the query API
    def query(self, slot: Slot) -> int:
        """Reveal a slot; cost 1 even if it was not hidden. Returns the number of facts revealed."""
        if slot in self.queried:
            raise ValueError("a slot is queried at most once")
        self.queried.add(slot)
        self.cost += 1
        revealed = len(self.by.get(slot, [])) if slot in self.hidden else 0
        self.hidden.discard(slot)
        self.log.append((slot, revealed))
        return revealed

    def unqueried(self) -> list[Slot]:
        return [s for s in all_slots(self.world) if s not in self.queried]

    # ---- the working graph
    def visible_facts(self) -> list[dict]:
        return [f for f in self.world["initial_state"] if (slot_of_fact(f) is None) or (slot_of_fact(f) not in self.hidden)]

    def empty_looking(self, slot: Slot) -> bool:
        fam, sid = slot
        for f in self.visible_facts():
            if slot_of_fact(f) == slot:
                return False
        return True

    def graph(self):
        pseudo = dict(self.world)
        pseudo["initial_state"] = self.visible_facts()
        return self._build.build_graph(pseudo)

    def decide(self, G=None):
        G = G or self.graph()
        return self._control.decide(G, hi=0.5, completeness=True, ambiguity=True), G


def outcome(world: dict, d: dict, bank) -> tuple[int, int]:
    """(correct ACT, wrong ACT) against the true world."""
    if d["decision"] != "ACT":
        return 0, 0
    lc = bank.label_class(world)
    noop = (d["action"] or {}).get("type") == "NOOP"
    if lc == "ACT/goal_already":
        good = noop
    elif lc == "ACT/plan":
        good = (not noop) and bank.first_action_ok(world, d["action"])
    else:
        good = False
    return int(good), int(not good)


def oracle_min_sets(world: dict, hidden: set[Slot], modules=None) -> list[frozenset]:
    """All minimal sets of hidden slots whose reveal yields the correct ACT (the upper-bound selector). Empty list = unrecoverable."""
    bank, build, control = modules or common.x0_modules()
    hid = sorted(hidden)
    found: list[frozenset] = []
    by = slot_facts(world)
    for size in range(0, len(hid) + 1):
        from itertools import combinations
        for sub in combinations(hid, size):
            if any(set(f_) <= set(sub) for f_ in found):
                continue
            rest = set(hid) - set(sub)
            facts = [f for f in world["initial_state"] if (slot_of_fact(f) is None) or (slot_of_fact(f) not in rest)]
            pseudo = dict(world)
            pseudo["initial_state"] = facts
            d = control.decide(build.build_graph(pseudo), hi=0.5, completeness=True, ambiguity=True)
            if outcome(world, d, bank)[0]:
                found.append(frozenset(sub))
        if found:
            return found
    return found
