"""Supervision projections derived from canonical truth only."""
from __future__ import annotations


def project(world: dict, rendered: dict) -> dict:
    state = world["initial_state"]
    # entity task
    entity_labels = [{"id": e["id"], "type": e["type"], "mention": next((b["mention"] for b in rendered["bindings"] if b["entity_id"] == e["id"]), e["name"])} for e in world["entities"]]
    # relation task
    relation_labels = [{"id": f.get("id"), "subj": f["args"][0] if f.get("args") else None, "pred": f["pred"], "obj": f["args"][1] if len(f.get("args", [])) > 1 else None} for f in state]
    # state task
    state_labels = [{"fact_id": f.get("id"), "pred": f["pred"], "args": f.get("args"), "value": f.get("value")} for f in state]
    # NLI-style: for goal predicate -> entailed/contradicted/unknown (from oracle truth)
    goal = world["goal"]
    if world["decision"] == "ABSTAIN" and world.get("contradictions"):
        nli = "CONTRADICTED"
    elif world["decision"] == "ASK" or (world["missing_information"]):
        nli = "UNKNOWN"
    elif world["decision"] == "ACT" and world.get("selected_action", {}).get("type") == "NOOP":
        nli = "ENTAILED"
    else:
        # goal not yet true, precondition checks: if a legal action exists -> UNKNOWN (not yet), else CONTRADICTED-ish
        nli = "UNKNOWN"
    # five-head compat
    five = {"context": rendered["text"][:400], "entity": entity_labels[0] if entity_labels else None,
            "relation": relation_labels[0] if relation_labels else None,
            "state": state_labels[0] if state_labels else None,
            "target": goal}
    # policy
    if world["decision"] == "ACT":
        policy = {"decision": "ACT", "action": (world.get("selected_action") or {}).get("type"), "arguments": (world.get("selected_action") or {}).get("args", {})}
    elif world["decision"] == "ASK":
        policy = {"decision": "ASK", "action": "REQUEST", "arguments": (world.get("selected_action") or {}).get("args", {})}
    else:
        policy = {"decision": "ABSTAIN", "reason": world.get("abstain_reason")}
    return {"entity": entity_labels, "relation": relation_labels, "state": state_labels, "nli": nli,
            "five_head": five, "policy": policy,
            "evidence": world.get("evidence_facts", []),
            "transition": world.get("resulting_state", []),
            "abstention": {"decision": world["decision"], "reason": world.get("abstain_reason")}}
