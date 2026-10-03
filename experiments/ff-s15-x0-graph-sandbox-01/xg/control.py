"""X2/X4: a deterministic controller that reads ACT / ABSTAIN / ASK off a typed weighted graph. No training.

Everything is derived from graph structure: delete-relaxed reachability (hmax) over REQUIRES/CAUSES/ACHIEVES edges gives ACT and the first action;
SUPPORTS/CONTRADICTS edges give support, conflict and blocked passages; the repair search (X4) gives ASK: a requirement on the goal's path that has no
support and no contradiction, where adding that one fact would make the goal reachable.
"""
from __future__ import annotations

from .build import pat_id
from .graph import Graph

INF = 99
DEPTH_CAP = 4  # BANK's oracle plans at most four steps


class View:
    """A flat read of the graph so repeated reachability runs stay cheap."""

    def __init__(self, G: Graph):
        self.G = G
        self.actions = []
        for aid in G.of_kind("ACTION"):
            reqs = [(e["dst"], e["weight"], e["source"] == "schema") for e in G.out(aid, "REQUIRES")]
            effs = [e["dst"] for e in G.out(aid, "CAUSES")]
            ach = bool(G.out(aid, "ACHIEVES"))
            self.actions.append((aid, G.nodes[aid]["action"], reqs, effs, ach))
        self.pats = {n: a for n, a in G.nodes.items() if a["kind"] == "REQUIREMENT" and a["pred"] != "SLOT"}
        self.slots = {n: (a["args"][0], a["value"], [e["weight"] for e in G.into(n, "SUPPORTS")]) for n, a in G.nodes.items() if a["kind"] == "REQUIREMENT" and a["pred"] == "SLOT"}
        self.locs = [n[4:] for n, a in G.nodes.items() if a["kind"] == "ENTITY" and a["type"] == "LOCATION"]
        self.support = {p: [e["weight"] for e in G.into(p, "SUPPORTS")] for p in self.pats}
        self.contra = {p: [e["weight"] for e in G.into(p, "CONTRADICTS")] for p in self.pats}
        self.goal = G.nodes["goal"]
        self.goal_support = [e["weight"] for e in G.into("goal", "SUPPORTS")]
        self.conflicts = [e["weight"] for e in G.edges if e["rel"] == "CONTRADICTS" and G.nodes[e["src"]]["kind"] == "STATE" and G.nodes[e["dst"]]["kind"] == "STATE"]
        self.ambiguous = any(e["rel"] == "CONTRADICTS" and G.nodes[e["src"]]["kind"] == "ENTITY" and G.nodes[e["dst"]]["kind"] == "ENTITY" for e in G.edges)
        gp = self.goal
        self.goal_pat = pat_id(gp["pred"], gp["args"], gp["value"] if gp["pred"] == "STATE" else None) if gp["in_closure"] else None


def reach(v: View, sup_th: float, con_th: float, extra_zero=frozenset()):
    """Delete-relaxed reachability. Supports count at weight >= sup_th; contradictions and gate requirements count at weight >= con_th.
    `level` is hmax (steps in parallel; decides reachability and the depth cap); `cost` is hadd (sum of steps; only used to pick which action to take first).
    Returns (goal_level, level, best) where best[pattern or 'goal'] is the index of the cheapest action that produces it."""
    level, cost = {}, {}
    for p in v.pats:
        sup = max(v.support[p], default=0.0) >= sup_th or p in extra_zero
        con = max(v.contra[p], default=0.0) >= con_th
        level[p] = 0 if (sup and not con) else INF
        cost[p] = 0 if (sup and not con) else INF
    g_ok = max(v.goal_support, default=0.0) >= sup_th or (v.goal_pat is not None and v.goal_pat in extra_zero)
    goal_level, goal_cost = (0, 0) if g_ok else (INF, INF)
    best: dict = {}
    changed = True
    rounds = 0
    while changed and rounds < 8:
        changed = False
        rounds += 1
        for idx, (_aid, _a, reqs, effs, ach) in enumerate(v.actions):
            lv, cs = 0, 0
            for (p, w, schema) in reqs:
                if schema or w >= con_th:
                    lv = max(lv, level[p])
                    cs += cost[p]
            if lv >= INF:
                continue
            alv, acs = lv + 1, cs + 1
            for p in effs:
                if max(v.contra[p], default=0.0) >= con_th:
                    continue
                if alv < level[p]:
                    level[p] = alv
                    changed = True
                if acs < cost[p]:
                    cost[p] = acs
                    best[p] = idx
                    changed = True
            if ach:
                if alv < goal_level:
                    goal_level = alv
                    changed = True
                if acs < goal_cost:
                    goal_cost = acs
                    best["goal"] = idx
                    changed = True
    v._cost = cost
    return goal_level, level, best


def first_action(v: View, level, best, con_th: float):
    """First executable action of the relaxed plan for the goal (follows the cheapest achiever, then the costliest unmet requirement, down to something executable now)."""
    idx = best["goal"]
    cost = v._cost
    for _ in range(12):
        _aid, a, reqs, _effs, _ach = v.actions[idx]
        unmet = [(cost[p], p) for (p, w, schema) in reqs if (schema or w >= con_th) and level[p] > 0 and p in best]
        if not unmet:
            return idx
        unmet.sort(key=lambda t: (-t[0], t[1]))
        idx = best[unmet[0][1]]
    return idx


def _kind_ok(p, kinds):
    return p["pred"] in kinds


def repair_set(v: View, sup_th: float, con_th: float, kinds=("AT", "STATE", "CONNECTED"), only=None):
    """Single-fact repairs: unsupported, uncontradicted patterns whose addition makes the goal reachable."""
    supported_slots = set()
    for p, a in v.pats.items():
        if max(v.support[p], default=0.0) >= sup_th and a["pred"] in ("AT", "STATE"):
            supported_slots.add((a["pred"], a["args"][0]))
    out = []
    for p, a in v.pats.items():
        if only is not None and p not in only:
            continue
        if not _kind_ok(a, kinds):
            continue
        if max(v.support[p], default=0.0) >= sup_th or max(v.contra[p], default=0.0) >= con_th:
            continue
        if a["pred"] in ("AT", "STATE") and (a["pred"], a["args"][0]) in supported_slots:
            continue  # the slot already has a value; a different value would be a conflict, not a gap
        gl, _lv, _b = reach(v, sup_th, con_th, extra_zero=frozenset([p]))
        if gl <= DEPTH_CAP:
            out.append(p)
    return sorted(out)


def slot_deficiency(v: View, th: float):
    """X4 completeness: schema slots (where is each object/agent, what state is each switch, what does each location connect to) with no support,
    plus location components that the supported CONNECTED facts leave apart. Returns (missing slot ids, bridging CONNECTED patterns)."""
    missing = sorted(s for s, (_e, _k, ws) in v.slots.items() if max(ws, default=0.0) < th)
    parent = {x: x for x in v.locs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p, a in v.pats.items():
        if a["pred"] == "CONNECTED" and max(v.support[p], default=0.0) >= th and all(x in parent for x in a["args"]):
            parent[find(a["args"][0])] = find(a["args"][1])
    split = len({find(x) for x in v.locs}) > 1
    bridges = sorted(p for p, a in v.pats.items() if a["pred"] == "CONNECTED" and split and all(x in parent for x in a["args"]) and find(a["args"][0]) != find(a["args"][1])
                     and max(v.support[p], default=0.0) < th and max(v.contra[p], default=0.0) < th)
    return missing, bridges


def decide(G: Graph, *, hi: float = 0.5, lo: float | None = None, ask_kinds=("AT", "STATE", "CONNECTED"), ask_cap: int = 99, completeness: bool = False, ambiguity: bool = False, verify: bool = True, view: View | None = None) -> dict:
    """Hard mode (lo is None): one threshold `hi`. DEFER mode: supports accepted at >= hi, contradictions and gates cautious at >= lo, supports in [lo, hi) deferred."""
    v = view or View(G)
    con_th = hi if lo is None else lo
    out = {"decision": None, "action": None, "reason": None, "candidates": [], "ask_kind": None}

    def ask_or_abstain(sup_th):
        cands = repair_set(v, sup_th, con_th, kinds=ask_kinds)
        if cands and len(cands) <= ask_cap:
            out.update(decision="ASK", candidates=cands, ask_kind="missing")
        else:
            out.update(decision="ABSTAIN", reason="INSUFFICIENT_EVIDENCE" if cands else "NO_VALID_ACTION", candidates=cands)
        return out

    if any(w >= con_th for w in v.conflicts):
        out.update(decision="ABSTAIN", reason="CONFLICTING_EVIDENCE")
        return out
    if ambiguity and v.ambiguous:
        out.update(decision="ABSTAIN", reason="AMBIGUOUS_REFERENCE")
        return out
    if v.goal["ungrounded"]:
        out.update(decision="ABSTAIN", reason="UNKNOWN_ENTITY")
        return out
    if not v.goal["in_closure"]:
        out.update(decision="ABSTAIN", reason="OUT_OF_SCOPE")
        return out
    if completeness:
        missing, bridges = slot_deficiency(v, hi)
        if missing or bridges:
            out.update(decision="ASK", ask_kind="slot", candidates=missing + bridges)
            return out
    gs = max(v.goal_support, default=0.0)
    if gs >= hi:
        out.update(decision="ACT", action={"type": "NOOP", "args": {}}, reason="GOAL_SATISFIED")
        return out
    if lo is not None and verify and gs >= lo:
        out.update(decision="ASK", ask_kind="verify", candidates=["goal"])
        return out
    gl, level, best = reach(v, hi, con_th)
    if gl <= DEPTH_CAP:
        out.update(decision="ACT", action=v.actions[first_action(v, level, best, con_th)][1])
        return out
    if lo is not None and verify:
        gl1, _l1, _b1 = reach(v, lo, con_th)
        if gl1 <= DEPTH_CAP:
            deferred = [p for p in v.pats if lo <= max(v.support[p], default=0.0) < hi]
            cands = repair_set(v, hi, con_th, kinds=("AT", "STATE", "CONNECTED"), only=set(deferred)) or sorted(deferred)
            out.update(decision="ASK", ask_kind="verify", candidates=cands)
            return out
    return ask_or_abstain(hi)
