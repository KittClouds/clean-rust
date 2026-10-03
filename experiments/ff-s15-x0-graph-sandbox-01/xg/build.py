"""X2: translate a BANK symbolic record into a typed weighted graph.

Two edge producers meet here: schema rules (what each action REQUIRES, CAUSES and ACHIEVES; weight 1) and the fact producer (which facts SUPPORT or CONTRADICT which patterns; weight = confidence).
A fact producer is `producer(record, patterns) -> (fact_weights, phantoms)`; the default is the oracle (every true fact at 1.0, nothing hallucinated).
Pattern nodes are REQUIREMENT nodes named by what must hold: AT(entity, loc), CONNECTED(unordered pair) and STATE(switch, value).
"""
from __future__ import annotations

from .graph import Graph

CLOSURE_PREDS = ("AT", "STATE")  # goal predicates the action set can bring about


def pat_id(pred: str, args, value=None) -> str:
    args = list(args)
    if pred == "CONNECTED":
        args = sorted(args)
    return "pat:" + pred + ":" + ",".join(args) + (":" + str(value) if value is not None else "")


def _gates(facts: list[dict]) -> dict[str, list[tuple[str, str, str]]]:
    gates: dict[str, list[tuple[str, str, str]]] = {}
    for f in facts:
        if f["pred"] == "REQUIRES" and f.get("args"):
            cond = f.get("value") or {}
            if cond.get("switch"):
                gates.setdefault(f["args"][0], []).append((f["id"], cond["switch"], cond.get("state", "ACTIVE")))
    return gates


def action_schema(a: dict, gates: dict) -> dict:
    """Schema rules: requirements (pattern, gate-fact-id or None) and effects of one action."""
    t, g = a.get("type"), a.get("args", {})
    reqs, effs = [], []
    if t == "MOVE":
        e, s, d = g["entity"], g["src"], g["dst"]
        reqs = [(("AT", [e, s], None), None), (("CONNECTED", [s, d], None), None)]
        reqs += [(("STATE", [sw], want), fid) for fid, sw, want in gates.get(d, [])]
        effs = [("AT", [e, d], None)]
    elif t == "ACTIVATE":
        reqs, effs = [(("STATE", [g["target"]], "INACTIVE"), None)], [("STATE", [g["target"]], "ACTIVE")]
    elif t == "DEACTIVATE":
        reqs, effs = [(("STATE", [g["target"]], "ACTIVE"), None)], [("STATE", [g["target"]], "INACTIVE")]
    return {"reqs": reqs, "effs": effs}


def goal_pattern(goal: dict):
    if goal.get("pred") == "AT":
        return ("AT", goal["args"], None)
    if goal.get("pred") == "STATE":
        return ("STATE", goal["args"], goal.get("value"))
    return None


def patterns_of(record: dict) -> dict[str, tuple]:
    """Every pattern the record's actions and goal mention, keyed by node id."""
    gates = _gates(record["initial_state"])
    out = {}
    for a in record["available_actions"]:
        sc = action_schema(a, gates)
        for (p, _fid) in sc["reqs"]:
            out[pat_id(*p)] = p
        for p in sc["effs"]:
            out[pat_id(*p)] = p
    gp = goal_pattern(record["goal"])
    if gp:
        out[pat_id(*gp)] = gp
    return out


def oracle_producer(record, patterns):
    return {f["id"]: 1.0 for f in record["initial_state"]}, {}


def _fact_pattern(f: dict):
    if f["pred"] in ("AT", "CONNECTED"):
        return (f["pred"], f["args"], None)
    if f["pred"] == "STATE":
        return ("STATE", f["args"], f.get("value"))
    return None


def build_graph(record: dict, producer=oracle_producer, source: str = "oracle") -> Graph:
    G = Graph()
    facts = record["initial_state"]
    gates = _gates(facts)
    patterns = patterns_of(record)
    fact_w, phantoms = producer(record, patterns)

    entities = {e["id"] for e in record["entities"]}
    slot_of = {"OBJECT": "AT", "AGENT": "AT", "SWITCH": "STATE", "LOCATION": "LINK"}
    for e in record["entities"]:
        G.add_node("ent:" + e["id"], "ENTITY", type=e["type"])
        if e["type"] in slot_of:
            # schema expectation: an entity of this type has a value in this slot (where is it / what state / what does it connect to)
            sid = f"slot:{slot_of[e['type']]}:{e['id']}"
            G.add_node(sid, "REQUIREMENT", pred="SLOT", args=[e["id"]], value=slot_of[e["type"]])
            G.add_edge("ent:" + e["id"], sid, "REQUIRES", 1.0, source="schema", provenance=f"{e['type']} needs a {slot_of[e['type']]} value")
    for pid, p in patterns.items():
        G.add_node(pid, "REQUIREMENT", pred=p[0], args=list(p[1]), value=p[2])
    # two entities claiming one alias cannot both be what the alias names: an ambiguous reference is an entity-entity contradiction
    owners: dict[str, list[str]] = {}
    for e in record["entities"]:
        for al in sorted(set(e.get("aliases", []))):
            owners.setdefault(al, []).append(e["id"])
    for al, ids in sorted(owners.items()):
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                G.add_edge("ent:" + ids[i], "ent:" + ids[j], "CONTRADICTS", 1.0, source="schema", provenance=f"shared alias {al!r}")
    goal = record["goal"]
    gp = goal_pattern(goal)
    ungrounded = [x for x in goal.get("args", []) if x not in entities]
    G.add_node("goal", "GOAL", pred=goal.get("pred"), args=list(goal.get("args", [])), value=goal.get("value"), in_closure=gp is not None, ungrounded=ungrounded)
    for x in goal.get("args", []):
        if x in entities:
            G.add_edge("goal", "ent:" + x, "APPLICABLE_TO", 1.0, source="schema", provenance="goal argument")

    for i, a in enumerate(record["available_actions"]):
        aid = f"act:{i}"
        G.add_node(aid, "ACTION", action=a)
        sc = action_schema(a, gates)
        for p, fid in sc["reqs"]:
            w = 1.0 if fid is None else fact_w.get(fid, 0.0)
            G.add_edge(aid, pat_id(*p), "REQUIRES", w, source="schema" if fid is None else source, provenance="gate fact " + fid if fid else "action precondition")
        for p in sc["effs"]:
            G.add_edge(aid, pat_id(*p), "CAUSES", 1.0, source="schema", provenance="action effect")
            if gp is not None and pat_id(*p) == pat_id(*gp):
                G.add_edge(aid, "goal", "ACHIEVES", 1.0, source="schema", provenance="effect matches goal")
        for x in a.get("args", {}).values():
            if x in entities:
                G.add_edge(aid, "ent:" + x, "APPLICABLE_TO", 1.0, source="schema", provenance="action argument")

    blocked = []
    for f in facts:
        w = fact_w.get(f["id"])
        if w is None:
            continue
        fid = "fact:" + f["id"]
        G.add_node(fid, "STATE", pred=f["pred"], args=list(f["args"]), value=f.get("value") if not isinstance(f.get("value"), dict) else "gate")
        for x in f["args"]:
            if x in entities:
                G.add_edge(fid, "ent:" + x, "APPLICABLE_TO", 1.0, source="schema", provenance="fact argument")
        slot_kind = {"AT": "AT", "STATE": "STATE", "CONNECTED": "LINK"}.get(f["pred"])
        if slot_kind:
            owners = f["args"] if f["pred"] == "CONNECTED" else f["args"][:1]
            for o in owners:
                sid = f"slot:{slot_kind}:{o}"
                if sid in G.nodes:
                    G.add_edge(fid, sid, "SUPPORTS", w, source=source, provenance="fact " + f["id"] + " fills slot")
        fp = _fact_pattern(f)
        if fp is not None:
            pid = pat_id(*fp)
            if pid in G.nodes:
                G.add_edge(fid, pid, "SUPPORTS", w, source=source, provenance="fact " + f["id"])
            if gp is not None and pid == pat_id(*gp):
                G.add_edge(fid, "goal", "SUPPORTS", w, source=source, provenance="fact " + f["id"])
        if f["pred"] == "BLOCKED":
            blocked.append((fid, w, f["args"]))
    for fid, w, args in blocked:
        pid = pat_id("CONNECTED", args)
        if pid in G.nodes:
            G.add_edge(fid, pid, "CONTRADICTS", w, source=source, provenance="blocked passage")
    # a functional STATE slot holding two values contradicts itself
    by_slot: dict[str, list] = {}
    for f in facts:
        if f["pred"] == "STATE" and f["id"] in fact_w:
            by_slot.setdefault(f["args"][0], []).append(f)
    for slot, fs in by_slot.items():
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                if fs[i].get("value") != fs[j].get("value"):
                    w = min(fact_w[fs[i]["id"]], fact_w[fs[j]["id"]])
                    G.add_edge("fact:" + fs[i]["id"], "fact:" + fs[j]["id"], "CONTRADICTS", w, source=source, provenance=f"two values for {slot}")
    for pid, w in phantoms.items():
        if pid in G.nodes:
            ph = "phantom:" + pid
            G.add_node(ph, "STATE", pred="PHANTOM", args=[], value=None)
            G.add_edge(ph, pid, "SUPPORTS", w, source=source, provenance="hallucinated support")
            if gp is not None and pid == pat_id(*gp):
                G.add_edge(ph, "goal", "SUPPORTS", w, source=source, provenance="hallucinated support")
    return G
