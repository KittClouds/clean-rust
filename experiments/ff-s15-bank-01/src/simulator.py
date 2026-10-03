"""Deterministic transition simulator + oracle. No model contact."""
from __future__ import annotations
from collections import deque


def _fact_key(f: dict) -> tuple:
    return (f.get("pred"), tuple(f.get("args", [])), str(f.get("value")))


def index_facts(facts: list[dict]) -> dict[tuple, dict]:
    return {_fact_key(f): f for f in facts}


def holds(state: list[dict], pred: str, args: list, value=None) -> bool:
    idx = index_facts(state)
    if value is None:
        return any((p == pred and tuple(a) == tuple(args)) for (p, a, _v) in idx)
    return _fact_key({"pred": pred, "args": args, "value": value}) in idx


def gate_open(state: list[dict], dst: str) -> tuple[bool, str | None]:
    """REQUIRES(dst, [switch, ACTIVE]) gating. Returns (open, blocking_switch)."""
    for f in state:
        if f.get("pred") == "REQUIRES" and f.get("args") and f["args"][0] == dst:
            cond = f.get("value") or {}
            sw = cond.get("switch")
            want = cond.get("state", "ACTIVE")
            if sw and not holds(state, "STATE", [sw], want):
                return False, sw
    return True, None


def legal_actions(state: list[dict], available: list[dict]) -> list[dict]:
    out = []
    for a in available:
        if _action_legal(state, a):
            out.append(a)
    return out


def _action_legal(state: list[dict], a: dict) -> bool:
    t = a.get("type")
    g = a.get("args", {})
    if t == "MOVE":
        ent, src, dst = g.get("entity"), g.get("src"), g.get("dst")
        if not (holds(state, "AT", [ent, src])): return False
        if not (holds(state, "CONNECTED", [src, dst]) or holds(state, "CONNECTED", [dst, src])): return False
        if holds(state, "BLOCKED", [src, dst]) or holds(state, "BLOCKED", [dst, src]): return False
        ok, _ = gate_open(state, dst)
        return ok
    if t == "ACTIVATE":
        return holds(state, "STATE", [g.get("target")], "INACTIVE")
    if t == "DEACTIVATE":
        return holds(state, "STATE", [g.get("target")], "ACTIVE")
    if t == "TAKE":
        return holds(state, "AT", [g.get("agent"), g.get("loc")]) and holds(state, "AT", [g.get("object"), g.get("loc")])
    if t == "DROP":
        return holds(state, "HAS", [g.get("agent"), g.get("object")]) and holds(state, "AT", [g.get("agent"), g.get("loc")])
    if t == "TRANSFER":
        return holds(state, "HAS", [g.get("from"), g.get("object")])
    if t == "OPEN":
        return holds(state, "STATE", [g.get("target")], "CLOSED")
    if t == "CLOSE":
        return holds(state, "STATE", [g.get("target")], "OPEN")
    if t in ("SELECT", "VERIFY", "WAIT", "NOOP"):
        return True
    if t in ("ASSIGN", "REQUEST"):
        return True
    return False


def apply_action(state: list[dict], a: dict) -> list[dict]:
    s = [dict(f) for f in state]
    t = a.get("type")
    g = a.get("args", {})
    def retract(pred, args):
        nonlocal s
        s = [f for f in s if not (f.get("pred") == pred and f.get("args") == args)]
    def assert_fact(pred, args, value=None, fid=None):
        s.append({"id": fid or f"f_{pred}_{'_'.join(args)}", "pred": pred, "args": args, **({"value": value} if value is not None else {})})
    if t == "MOVE":
        retract("AT", [g["entity"], g["src"]])
        assert_fact("AT", [g["entity"], g["dst"]])
    elif t == "ACTIVATE":
        retract("STATE", [g["target"]]); assert_fact("STATE", [g["target"]], "ACTIVE")
    elif t == "DEACTIVATE":
        retract("STATE", [g["target"]]); assert_fact("STATE", [g["target"]], "INACTIVE")
    elif t == "TAKE":
        retract("AT", [g["object"], g["loc"]]); assert_fact("HAS", [g["agent"], g["object"]])
    elif t == "DROP":
        retract("HAS", [g["agent"], g["object"]]); assert_fact("AT", [g["object"], g["loc"]])
    elif t == "TRANSFER":
        retract("HAS", [g["from"], g["object"]]); assert_fact("HAS", [g["to"], g["object"]])
    elif t == "OPEN":
        retract("STATE", [g["target"]]); assert_fact("STATE", [g["target"]], "OPEN")
    elif t == "CLOSE":
        retract("STATE", [g["target"]]); assert_fact("STATE", [g["target"]], "CLOSED")
    return s


def goal_satisfied(state: list[dict], goal: dict) -> bool:
    return holds(state, goal.get("pred"), goal.get("args", []), goal.get("value"))


def shortest_plan(state: list[dict], available: list[dict], goal: dict, max_depth: int = 4) -> list[dict] | None:
    if goal_satisfied(state, goal):
        return []
    seen = {_canon_state(state)}
    q = deque([(state, [])])
    while q:
        s, path = q.popleft()
        if len(path) >= max_depth:
            continue
        for a in legal_actions(s, available):
            ns = apply_action(s, a)
            npath = path + [a]
            if goal_satisfied(ns, goal):
                return npath
            c = _canon_state(ns)
            if c not in seen:
                seen.add(c)
                q.append((ns, npath))
    return None


def _canon_state(state: list[dict]) -> tuple:
    return tuple(sorted(_fact_key(f) for f in state))


def oracle(state: list[dict], available: list[dict], goal: dict) -> dict:
    """Symbolic upper-bound policy. Returns {decision, action, reason}."""
    if goal_satisfied(state, goal):
        return {"decision": "ACT", "action": {"type": "NOOP", "args": {}}, "reason": "GOAL_SATISFIED"}
    plan = shortest_plan(state, available, goal)
    if plan is None:
        return {"decision": "ABSTAIN", "action": None, "reason": "NO_VALID_ACTION"}
    if len(plan) == 0:
        return {"decision": "ACT", "action": {"type": "NOOP", "args": {}}, "reason": "GOAL_SATISFIED"}
    return {"decision": "ACT", "action": plan[0], "reason": None}
