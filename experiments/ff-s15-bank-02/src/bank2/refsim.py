"""A second, independent implementation of the action semantics (written from the §1.6 footprint table, with different data structures from sim.py).
Used by G05 (action round trip) and G13 (certificate re-verification). It shares no code with sim.py."""
from __future__ import annotations

from . import facts as F


def state_of(keys, active=()) -> dict:
    st = {"at": {}, "holds": set(), "contains": set(), "conn": set(), "blocked": set(), "sw": {}, "rel": set()}
    for k in list(keys) + list(active):
        p = k[0]
        if p == "AT":
            st["at"][k[1]] = k[2]
        elif p == "HOLDS":
            st["holds"].add((k[1], k[2]))
        elif p == "CONTAINS":
            st["contains"].add((k[1], k[2]))
        elif p == "CONNECTED":
            st["conn"].add((k[1], k[2]))
        elif p == "BLOCKED":
            st["blocked"].add((k[1], k[2]))
        elif p == "STATE":
            st["sw"][(k[1], k[2])] = k[3]
        elif p == "REL":
            st["rel"].add(k[1:])
    return st


def to_keys(st: dict) -> set:
    out = {("AT", e, l) for e, l in st["at"].items()}
    out |= {("HOLDS", a, o) for a, o in st["holds"]} | {("CONTAINS", c, o) for c, o in st["contains"]}
    out |= {("CONNECTED", a, b) for a, b in st["conn"]} | {("BLOCKED", a, b) for a, b in st["blocked"]}
    out |= {("STATE", e, at, v) for (e, at), v in st["sw"].items()} | {("REL", *r) for r in st["rel"]}
    return out


def legal(st: dict, a: dict, gates: list) -> bool:
    t, g = a["type"], a["args"]
    if t == "MOVE":
        ag, s, d = g["agent"], g["src"], g["dst"]
        if st["at"].get(ag) != s or (s, d) not in st["conn"] or (s, d) in st["blocked"]:
            return False
        return all(st["sw"].get((x["cond"][0], x["cond"][1])) == x["cond"][2] for x in gates if x["edge"] == [s, d])
    if t == "TAKE":
        ag, o, src, at = g["agent"], g["obj"], g["source"], g["at"]
        if st["at"].get(ag) != at:
            return False
        if src == at:
            return st["at"].get(o) == at
        return (src, o) in st["contains"] and st["at"].get(src) == at and st["sw"].get((src, "openness")) == "open"
    if t == "DROP":
        ag, o, tgt, at = g["agent"], g["obj"], g["target"], g["at"]
        if (ag, o) not in st["holds"] or st["at"].get(ag) != at:
            return False
        return True if tgt == at else (st["at"].get(tgt) == at and st["sw"].get((tgt, "openness")) == "open")
    if t == "TRANSFER":
        fr, to, o, at = g["from"], g["to"], g["obj"], g["at"]
        return (fr, o) in st["holds"] and st["at"].get(fr) == at and st["at"].get(to) == at
    if t in ("OPEN", "CLOSE", "ACTIVATE", "DEACTIVATE"):
        ag, tg, at = g["agent"], g["target"], g["at"]
        attr, need = {"OPEN": ("openness", "closed"), "CLOSE": ("openness", "open"), "ACTIVATE": ("activation", "inactive"), "DEACTIVATE": ("activation", "active")}[t]
        return st["at"].get(ag) == at and st["at"].get(tg) == at and st["sw"].get((tg, attr)) == need
    return t == "WAIT"


def apply(st: dict, a: dict) -> dict:
    n = {"at": dict(st["at"]), "holds": set(st["holds"]), "contains": set(st["contains"]), "conn": set(st["conn"]), "blocked": set(st["blocked"]), "sw": dict(st["sw"]), "rel": set(st["rel"])}
    t, g = a["type"], a["args"]
    if t == "MOVE":
        n["at"][g["agent"]] = g["dst"]
    elif t == "TAKE":
        if g["source"] == g["at"]:
            del n["at"][g["obj"]]
        else:
            n["contains"].discard((g["source"], g["obj"]))
        n["holds"].add((g["agent"], g["obj"]))
    elif t == "DROP":
        n["holds"].discard((g["agent"], g["obj"]))
        if g["target"] == g["at"]:
            n["at"][g["obj"]] = g["at"]
        else:
            n["contains"].add((g["target"], g["obj"]))
    elif t == "TRANSFER":
        n["holds"].discard((g["from"], g["obj"]))
        n["holds"].add((g["to"], g["obj"]))
    elif t in ("OPEN", "CLOSE"):
        n["sw"][(g["target"], "openness")] = "open" if t == "OPEN" else "closed"
    elif t in ("ACTIVATE", "DEACTIVATE"):
        n["sw"][(g["target"], "activation")] = "active" if t == "ACTIVATE" else "inactive"
    return n


def inverse(a: dict) -> dict | None:
    """The declared inverse instance, if the action type has one."""
    t, g = a["type"], a["args"]
    from .sim import make_action
    if t == "OPEN":
        return make_action("CLOSE", **g)
    if t == "CLOSE":
        return make_action("OPEN", **g)
    if t == "ACTIVATE":
        return make_action("DEACTIVATE", **g)
    if t == "DEACTIVATE":
        return make_action("ACTIVATE", **g)
    if t == "MOVE":
        return make_action("MOVE", agent=g["agent"], src=g["dst"], dst=g["src"])
    if t == "TAKE":
        return make_action("DROP", agent=g["agent"], obj=g["obj"], target=g["source"], at=g["at"])
    if t == "DROP":
        return make_action("TAKE", agent=g["agent"], obj=g["obj"], source=g["target"], at=g["at"])
    if t == "TRANSFER":
        return make_action("TRANSFER", **{"from": g["to"], "to": g["from"], "obj": g["obj"], "at": g["at"]})
    return None


def exhaustive_space(st: dict, actions: list, gates: list, goal_key, cap: int = 60000) -> tuple[bool, int]:
    """Independent exhaustive search ignoring ticks (no scheduled facts). Returns (goal_reachable, states_explored); explored == -1 if capped."""
    def freeze_state(s):
        return (tuple(sorted(s["at"].items())), tuple(sorted(s["holds"])), tuple(sorted(s["contains"])), tuple(sorted(s["sw"].items())))
    seen = {freeze_state(st)}
    frontier = [st]
    reach = goal_key in to_keys(st)
    while frontier:
        nxt = []
        for s in frontier:
            for a in actions:
                if not legal(s, a, gates):
                    continue
                n = apply(s, a)
                k = freeze_state(n)
                if k in seen:
                    continue
                seen.add(k)
                if len(seen) > cap:
                    return reach, -1
                if goal_key is not None and goal_key in to_keys(n):
                    reach = True
                nxt.append(n)
        frontier = nxt
    return reach, len(seen)
