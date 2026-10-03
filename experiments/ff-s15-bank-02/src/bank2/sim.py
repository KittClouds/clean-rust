"""Deterministic transition simulator for BANK-v2: nine environment actions, discrete ticks, scheduled (timed) facts, movement gates.

A state is (frozenset of fact keys, tick). Every action advances the tick by one; WAIT has no other effect. A fact scheduled in [valid_from, valid_to) holds at tick t
iff valid_from <= t < valid_to, independent of actions. Goal satisfaction is literal: the goal's fact key is present.
No model contact, no randomness.
"""
from __future__ import annotations

from collections import deque

from .canon import sha256_hex, short
from . import facts as F

ENV_ACTIONS = ("MOVE", "TAKE", "DROP", "TRANSFER", "OPEN", "CLOSE", "ACTIVATE", "DEACTIVATE", "WAIT")
ASSERTABLE = ("AT", "HOLDS", "CONTAINS", "STATE")  # predicates some environment action can assert: the action closure


def act_id(a_type: str, args: dict) -> str:
    return "a_" + short([a_type, sorted(args.items())], 10)


def make_action(a_type: str, **args) -> dict:
    return {"id": act_id(a_type, args), "type": a_type, "args": dict(args)}


class Act:
    """A grounded action compiled to fact-key preconditions and effects."""

    __slots__ = ("id", "type", "args", "pre", "neg", "rm", "add", "raw")

    def __init__(self, raw: dict, gates: dict):
        self.raw, self.id, self.type, self.args = raw, raw["id"], raw["type"], raw["args"]
        a = self.args
        pre, neg, rm, add = [], [], [], []
        t = self.type
        if t == "MOVE":
            ag, s, d = a["agent"], a["src"], a["dst"]
            pre += [("AT", ag, s), ("CONNECTED", s, d)]
            neg += [("BLOCKED", s, d)]
            for cond in gates.get((s, d), ()):
                pre.append(("STATE", *cond))
            rm += [("AT", ag, s)]
            add += [("AT", ag, d)]
        elif t == "TAKE":
            ag, o, src, at = a["agent"], a["obj"], a["source"], a["at"]
            pre.append(("AT", ag, at))
            if src == at:
                pre.append(("AT", o, at))
                rm.append(("AT", o, at))
            else:
                pre += [("CONTAINS", src, o), ("AT", src, at), ("STATE", src, "openness", "open")]
                rm.append(("CONTAINS", src, o))
            add.append(("HOLDS", ag, o))
        elif t == "DROP":
            ag, o, tgt, at = a["agent"], a["obj"], a["target"], a["at"]
            pre += [("HOLDS", ag, o), ("AT", ag, at)]
            if tgt == at:
                add.append(("AT", o, at))
            else:
                pre += [("AT", tgt, at), ("STATE", tgt, "openness", "open")]
                add.append(("CONTAINS", tgt, o))
            rm.append(("HOLDS", ag, o))
        elif t == "TRANSFER":
            fr, to, o, at = a["from"], a["to"], a["obj"], a["at"]
            pre += [("HOLDS", fr, o), ("AT", fr, at), ("AT", to, at)]
            rm.append(("HOLDS", fr, o))
            add.append(("HOLDS", to, o))
        elif t in ("OPEN", "CLOSE"):
            ag, tg, at = a["agent"], a["target"], a["at"]
            frm, to = ("closed", "open") if t == "OPEN" else ("open", "closed")
            pre += [("AT", ag, at), ("AT", tg, at), ("STATE", tg, "openness", frm)]
            rm.append(("STATE", tg, "openness", frm))
            add.append(("STATE", tg, "openness", to))
        elif t in ("ACTIVATE", "DEACTIVATE"):
            ag, tg, at = a["agent"], a["target"], a["at"]
            frm, to = ("inactive", "active") if t == "ACTIVATE" else ("active", "inactive")
            pre += [("AT", ag, at), ("AT", tg, at), ("STATE", tg, "activation", frm)]
            rm.append(("STATE", tg, "activation", frm))
            add.append(("STATE", tg, "activation", to))
        elif t == "WAIT":
            pass
        else:
            raise ValueError(t)
        self.pre, self.neg, self.rm, self.add = tuple(pre), tuple(neg), tuple(rm), tuple(add)


class Sim:
    def __init__(self, base: list[tuple], scheduled: list[tuple], gates: list[dict], actions: list[dict], goal_key: tuple | None):
        self.base0 = frozenset(base)
        self.sched = [(k, vf, vt) for (k, vf, vt) in scheduled]
        bounds = [b for (_k, vf, vt) in self.sched for b in (vf, vt) if b is not None]
        self.tcap = (max(bounds) + 1) if bounds else 0
        self.active = [frozenset(k for (k, vf, vt) in self.sched if vf <= t and (vt is None or t < vt)) for t in range(self.tcap + 1)]
        gmap: dict[tuple, list] = {}
        for g in gates:
            gmap.setdefault(tuple(g["edge"]), []).append(tuple(g["cond"]))
        self.gates = gmap
        self.actions = sorted((Act(a, gmap) for a in actions), key=lambda x: x.id)
        self.goal_key = goal_key
        self.by_id = {a.id: a for a in self.actions}

    # ------------------------------------------------------------ construction from a world record
    @staticmethod
    def from_world(world: dict, keep_fact_ids: set | None = None) -> "Sim":
        def ok(f):
            return keep_fact_ids is None or f["id"] in keep_fact_ids
        base = [F.key(f) for f in world["state"] if ok(f)]
        sched = [(F.key(s["fact"]), s["valid_from"], s["valid_to"]) for s in world.get("scheduled", []) if ok(s["fact"])]
        g = world["goal"]
        goal_key = (g["pred"], *g["args"]) if g["pred"] in ASSERTABLE else None
        return Sim(base, sched, world["transition_system"].get("gates", []), world["available_actions"], goal_key)

    def without(self, key: tuple) -> "Sim":
        """The same world with one fact removed (used by decision-dependence checks)."""
        s = Sim.__new__(Sim)
        s.__dict__.update(self.__dict__)
        s.base0 = self.base0 - {key}
        return s

    # ------------------------------------------------------------ primitives
    def _tick(self, t: int) -> int:
        return t if t < self.tcap else self.tcap

    def eff_has(self, facts: frozenset, t: int, k: tuple) -> bool:
        return k in facts or k in self.active[self._tick(t)]

    def legal(self, facts: frozenset, t: int, a: Act) -> bool:
        act = self.active[self._tick(t)]
        for k in a.pre:
            if k not in facts and k not in act:
                return False
        for k in a.neg:
            if k in facts or k in act:
                return False
        return True

    def legal_trace(self, facts: frozenset, t: int, a: Act):
        """(legal, consulted): consulted positive facts that were present, and negative checks that were absent (closed-slot reads)."""
        act = self.active[self._tick(t)]
        present, absent_ok, ok = [], [], True
        for k in a.pre:
            if k in facts or k in act:
                present.append(k)
            else:
                ok = False
        for k in a.neg:
            if k in facts or k in act:
                ok = False
            else:
                absent_ok.append(k)
        return ok, present, absent_ok

    def legal_set(self, facts: frozenset, t: int) -> list[Act]:
        return [a for a in self.actions if self.legal(facts, t, a)]

    def apply(self, facts: frozenset, a: Act) -> frozenset:
        return (facts - frozenset(a.rm)) | frozenset(a.add)

    def goal_holds(self, facts: frozenset, t: int) -> bool:
        return self.goal_key is not None and self.eff_has(facts, t, self.goal_key)

    # ------------------------------------------------------------ search
    def search(self, cap_depth: int = 8, max_states: int = 60000, facts0: frozenset | None = None, t0: int = 0) -> dict:
        """Layered BFS. Returns {status, depth, canonical_plan, first_actions, n_states, certificate}.

        status: SOLVED (shortest plan found), UNSAT_EXHAUSTED (whole reachable space explored, goal absent: an exhaustive certificate),
        CAP_REACHED or STATE_LIMIT (not certifiable either way; the generator must regenerate)."""
        facts0 = self.base0 if facts0 is None else facts0
        root = (facts0, self._tick(t0))
        if self.goal_key is None:
            return {"status": "UNSAT_EXHAUSTED", "depth": None, "canonical_plan": [], "first_actions": [], "n_states": 1, "certificate": {"reason": "goal outside the action closure"}}
        if self.goal_holds(facts0, t0):
            return {"status": "SOLVED", "depth": 0, "canonical_plan": [], "first_actions": [], "n_states": 1, "certificate": None}
        depth = {root: 0}
        layers = [[root]]
        edges: dict = {}
        goal_states: list = []
        n = 1
        for d in range(cap_depth):
            nxt = []
            for st in layers[d]:
                facts, t = st
                edge_list = edges.setdefault(st, [])
                for ai, a in enumerate(self.actions):
                    if not self.legal(facts, t, a):
                        continue
                    nf = self.apply(facts, a)
                    ns = (nf, self._tick(t + 1))
                    if ns not in depth:
                        depth[ns] = d + 1
                        nxt.append(ns)
                        n += 1
                        if n > max_states:
                            return {"status": "STATE_LIMIT", "depth": None, "canonical_plan": [], "first_actions": [], "n_states": n, "certificate": None}
                    if depth[ns] == d + 1:
                        edge_list.append((ai, ns))
                        if self.goal_holds(nf, t + 1) and ns not in goal_states:
                            goal_states.append(ns)
            if goal_states:
                return self._solved(root, layers, edges, goal_states, depth, d + 1, n)
            if not nxt:
                allstates = sorted(sha256_hex([sorted(s[0]), s[1]]) for s in depth)
                return {"status": "UNSAT_EXHAUSTED", "depth": None, "canonical_plan": [], "first_actions": [], "n_states": n,
                        "certificate": {"states_explored": n, "space_digest": sha256_hex(allstates)}}
            layers.append(nxt)
        return {"status": "CAP_REACHED", "depth": None, "canonical_plan": [], "first_actions": [], "n_states": n, "certificate": None}

    def _solved(self, root, layers, edges, goal_states, depth, plan_depth, n):
        good = set(goal_states)
        for d in range(plan_depth - 1, -1, -1):
            for st in layers[d]:
                if any(ns in good for (_ai, ns) in edges.get(st, ())):
                    good.add(st)
        first, plan, cur = [], [], root
        for step in range(plan_depth):
            succ = sorted((self.actions[ai].id, ai, ns) for (ai, ns) in edges[cur] if ns in good and depth[ns] == depth[cur] + 1)
            if step == 0:
                first = sorted({aid for (aid, _ai, _ns) in succ})
            aid, ai, ns = succ[0]
            plan.append(self.actions[ai])
            cur = ns
        return {"status": "SOLVED", "depth": plan_depth, "canonical_plan": plan, "first_actions": first, "n_states": n, "certificate": None}

    def reach_depths(self, cap_depth: int = 8, max_states: int = 20000) -> tuple[dict, bool]:
        """Shortest number of actions after which each fact key first holds in some reachable state. Returns (depths, exhausted)."""
        root = (self.base0, self._tick(0))
        seen = {root}
        first: dict = {}
        for k in self.base0:
            first[k] = 0
        frontier = [root]
        for d in range(cap_depth):
            nxt = []
            for (facts, t) in frontier:
                for a in self.actions:
                    if not self.legal(facts, t, a):
                        continue
                    nf = self.apply(facts, a)
                    ns = (nf, self._tick(t + 1))
                    if ns in seen:
                        continue
                    seen.add(ns)
                    if len(seen) > max_states:
                        return first, False
                    for k in nf:
                        if k not in first:
                            first[k] = d + 1
                    nxt.append(ns)
            if not nxt:
                return first, True
            frontier = nxt
        return first, False

    # ------------------------------------------------------------ replay with consultation trace
    def replay(self, plan: list[Act], facts0: frozenset | None = None) -> dict:
        """Execute a plan step by step, recording which facts each step consulted and which initial facts (present at t=0 or scheduled) they were."""
        facts = self.base0 if facts0 is None else facts0
        initial_universe = set(self.base0) | {k for (k, _a, _b) in self.sched}
        consulted_initial: list[tuple] = []
        seen = set()
        t, steps = 0, []
        for a in plan:
            ok, present, absent_ok = self.legal_trace(facts, t, a)
            if not ok:
                raise ValueError("replayed plan step is illegal")
            for k in present:
                if k in initial_universe and k not in seen:
                    seen.add(k)
                    consulted_initial.append(k)
            steps.append({"tick": t, "action": a.id, "consulted": [list(k) for k in present], "closed_reads": [list(k) for k in absent_ok]})
            facts = self.apply(facts, a)
            t += 1
        if self.goal_key is not None and self.goal_key in initial_universe and self.eff_has(facts, t, self.goal_key) and self.goal_key not in seen:
            consulted_initial.append(self.goal_key)
        return {"final_facts": facts, "final_tick": t, "steps": steps, "consulted_initial": consulted_initial, "goal_holds": self.goal_holds(facts, t)}


def gates_by_edge(gates: list[dict]) -> dict:
    out: dict = {}
    for g in gates:
        out.setdefault(tuple(g["edge"]), []).append(tuple(g["cond"]))
    return out


def ground_actions(actor: str, locations: list[str], objects: list[str], containers: list[str], switches: list[str], other_agents: list[str],
                   connected_pairs: list[tuple], decoy_pairs: list[tuple], include_wait: bool = True, timed_switches: frozenset = frozenset()) -> list[dict]:
    """The closed grounded action set for one world. MOVE instances cover connected pairs (legal, blocked, gated, wrong-place) plus a few decoys."""
    acts = []
    for (s, d) in sorted(set(connected_pairs) | set(decoy_pairs)):
        acts.append(make_action("MOVE", agent=actor, src=s, dst=d))
    for o in objects:
        for at in locations:
            acts.append(make_action("TAKE", agent=actor, obj=o, source=at, at=at))
            acts.append(make_action("DROP", agent=actor, obj=o, target=at, at=at))
            for c in containers:
                acts.append(make_action("TAKE", agent=actor, obj=o, source=c, at=at))
                acts.append(make_action("DROP", agent=actor, obj=o, target=c, at=at))
            for b in other_agents:
                acts.append(make_action("TRANSFER", **{"from": actor, "to": b, "obj": o, "at": at}))
    for c in containers:
        for at in locations:
            acts.append(make_action("OPEN", agent=actor, target=c, at=at))
            acts.append(make_action("CLOSE", agent=actor, target=c, at=at))
    for sw in switches:
        if sw in timed_switches:
            continue
        for at in locations:
            acts.append(make_action("ACTIVATE", agent=actor, target=sw, at=at))
            acts.append(make_action("DEACTIVATE", agent=actor, target=sw, at=at))
    if include_wait:
        acts.append(make_action("WAIT", agent=actor))
    # dedupe by id, keep stable order
    seen, out = set(), []
    for a in acts:
        if a["id"] not in seen:
            seen.add(a["id"])
            out.append(a)
    return out
