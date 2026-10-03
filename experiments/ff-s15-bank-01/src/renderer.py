"""Deterministic surface renderers S0-S11. Truth-preserving by construction."""
from __future__ import annotations
from .schema import RENDERER_VERSION

def _ename(e: dict, fam: str, idx: int) -> str:
    name = e["name"]
    if fam == "S5":
        # alias/pronoun heavy: use first alias + pronoun every other
        a = (e.get("aliases") or [name])[0]
        return a if idx % 2 == 0 else ("it" if e["type"] in ("OBJECT", "SWITCH", "CONTAINER", "RESOURCE") else ("they" if e["type"] == "AGENT" else a))
    if fam == "S10":
        return f"the aforementioned {name}"
    return name


def _fact_text(f: dict, entmap: dict, fam: str) -> str:
    p, a = f.get("pred"), f.get("args", [])
    n = lambda x: entmap.get(x, x)
    v = f.get("value")
    if p == "AT": return f"{n(a[0])} is in {n(a[1])}"
    if p == "CONNECTED":
        if fam == "S10": return f"{n(a[1])} is reachable from {n(a[0])}"
        return f"{n(a[0])} connects to {n(a[1])}"
    if p == "STATE": return f"{n(a[0])} is {str(v).lower()}"
    if p == "REQUIRES": return f"{n(a[0])} requires {n(v.get('switch'))} active" if isinstance(v, dict) else f"{n(a[0])} has a requirement"
    if p == "BLOCKED": return f"passage from {n(a[0])} to {n(a[1])} is blocked"
    if p == "BEFORE": return f"{n(a[0])} is before {n(a[1])}"
    if p == "PART_OF": return f"{n(a[0])} is part of {n(a[1])}"
    if p == "OWNS": return f"{n(a[0])} owns {n(a[1])}"
    if p == "ENABLES": return f"{n(a[0])} enables {n(a[1])}"
    if p == "HAS": return f"{n(a[0])} has {n(a[1])}"
    return f"{p}({', '.join(a)})"


def _goal_text(goal: dict, entmap: dict) -> str:
    p, a = goal.get("pred"), goal.get("args", [])
    n = lambda x: entmap.get(x, x)
    if p == "AT" and len(a) >= 2: return f"Goal: place {n(a[0])} in {n(a[1])}"
    if p == "STATE": return f"Goal: {n(a[0])} must be {str(goal.get('value')).lower()}"
    return f"Goal: {p}({', '.join(a)})"


def render(world: dict, family: str | None = None) -> dict:
    fam = family or world["surface_family"]
    ents = world["entities"]
    entmap, bindings = {}, []
    for i, e in enumerate(ents):
        disp = _ename(e, fam, i)
        entmap[e["id"]] = disp
        bindings.append({"entity_id": e["id"], "mention": disp})
    state = world["initial_state"]
    facts_txt = [_fact_text(f, entmap, fam) for f in state]
    # family transforms (order/voice/noise only; never change truth)
    if fam == "S0":
        body = ". ".join(facts_txt) + "."
    elif fam == "S1":
        body = "You observe the following. " + ". ".join(facts_txt) + "."
    elif fam == "S2":
        body = "Hey, so here's the situation: " + "; ".join(facts_txt) + ". What should happen?"
    elif fam == "S3":
        body = ". ".join(reversed(facts_txt)) + "."
    elif fam == "S4":
        dist = [f"Note: record {_['id']} archived." for _ in world.get("irrelevant_facts", [])] or ["Note: no further records."]
        body = ". ".join(facts_txt) + ". " + " ".join(dist)
    elif fam == "S5":
        body = ". ".join(facts_txt) + "."
    elif fam == "S6":
        body = ". ".join(facts_txt) + ". It is not the case that the goal is already abandoned."
    elif fam == "S7":
        body = "\n".join(f"- {t}" for t in facts_txt)
    elif fam == "S8":
        body = " | ".join(facts_txt)
    elif fam == "S9":
        body = " /\\ ".join(f"{f['pred']}({','.join(f['args'])})" for f in state)
    elif fam == "S10":
        body = "It is reported that " + "; it is further reported that ".join(facts_txt) + "."
    else:  # S11 mixed
        half = len(facts_txt) // 2
        body = ". ".join(facts_txt[:half]) + ".\n- " + "\n- ".join(facts_txt[half:]) if facts_txt[half:] else ". ".join(facts_txt) + "."
    text = body + "\n" + _goal_text(world["goal"], entmap)
    # fact bindings: every referenced entity must exist in world
    return {"text": text, "family": fam, "renderer": RENDERER_VERSION, "bindings": bindings,
            "fact_ids": [f["id"] for f in state if "id" in f]}
