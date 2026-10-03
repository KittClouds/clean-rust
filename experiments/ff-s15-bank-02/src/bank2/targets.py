"""The TARGETS block (§5): every target is a pure function of the record, carrying a typed witness that re-derives from the record alone (G04).

compute(rec, derivation) builds the block; verify(rec) recomputes it from scratch and cross-checks the witnesses that have an independent validator.
"""
from __future__ import annotations

from . import algebra as A
from . import facts as F
from . import registry
from . import requirements as R
from . import sim as S
from .canon import rng as mkrng, sha256_hex

_FLIP = {"open": "closed", "closed": "open", "active": "inactive", "inactive": "active"}
NONTRIVIAL = ("disposition", "reason", "executed_action", "applicability", "next_state", "missing_information", "relation", "edge_existence", "contradiction",
              "temporal_order", "nli", "entity", "evidence", "plan_step", "impossibility")


def _ids(keys) -> list:
    return sorted(F.fid(k) for k in keys)


def compute(rec: dict, d: A.Derivation) -> dict:
    wt, ob, ip = rec["WORLD_TRUTH"], rec["OBSERVATION"], rec["INFORMATION_POLICY"]
    sm = A.sim_of(rec)
    truth = A.truth_key_set(rec)
    fk = A.fact_key_map(rec)
    sup = {fk[i] for i in ob["supported_facts"]}
    info = sm.search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
    r = mkrng("targets", rec["META"].get("canonical_id") or rec["world_id"])
    T: dict = {}

    T["disposition"] = {"value": d.disposition, "witness": {"rule_step": d.step, "inputs": d.witness}}
    T["reason"] = {"value": d.reason, "witness": {"step": d.step, "reason_witness": d.witness, "classification": d.classification}}
    if d.disposition == "EXECUTE":
        T["executed_action"] = {"value": d.action["id"], "witness": d.witness["legal_transition"]}
        nf = sm.apply(sm.base0, sm.by_id[d.action["id"]])
        T["next_state"] = {"value": {"add": _ids(nf - sm.base0), "rm": _ids(sm.base0 - nf), "tick": 1}, "witness": {"action_id": d.action["id"], "transition": d.witness["legal_transition"]}}
    else:
        T["executed_action"] = {"value": None, "witness": None}
        T["next_state"] = {"value": None, "witness": None}
    legal = [a.id for a in sm.legal_set(sm.base0, 0)]
    perms = rec["ACTION_POLICY"]["permissions"]
    permitted = [i for i in legal if perms.get(sm.by_id[i].type, {"permitted": True})["permitted"]]
    T["applicability"] = {"value": {"legal": legal, "permitted": permitted}, "witness": {"exhaustive_environment_legal_set": legal, "available": len(sm.actions)}}
    if d.step in ("2a", "2b", "2c"):
        T["missing_information"] = {"value": d.reason, "witness": d.witness}
    elif d.step in ("1", "1a"):
        T["missing_information"] = {"value": None, "witness": None}
    else:
        T["missing_information"] = {"value": d.classification, "witness": {"M_size": 0}}

    # relation: one REL fact, asked as "how is X related to Y"
    rels = sorted(k for k in truth if k[0] == "REL")
    if rels:
        k = r.choice(rels)
        T["relation"] = {"value": {"source": k[1], "target": k[3], "relation_id": k[2]}, "witness": {"relation_triple": list(k[1:]), "fact_id": F.fid(k)}}
    else:
        T["relation"] = {"value": None, "witness": None}

    # edge existence: a location pair, half from real edges, half not
    locs = sorted(e["id"] for e in wt["entities"] if e["type"] == "LOCATION" and e["introduced"])
    edges = sorted((k[1], k[2]) for k in truth if k[0] == "CONNECTED")
    pairs = [(a, b) for a in locs for b in locs if a != b]
    if pairs:
        pick = r.choice(edges) if (edges and r.random() < 0.5) else r.choice(pairs)
        probe = rec["META"].get("edge_probe")
        if probe and tuple(probe) in pairs:
            pick = tuple(probe)
        conn, blk = ("CONNECTED", *pick) in truth, ("BLOCKED", *pick) in truth
        T["edge_existence"] = {"value": {"pair": list(pick), "connected": conn, "blocked": blk}, "witness": {"edge_presence_or_absence": {"pair": list(pick), "connected": conn, "blocked": blk}}}
    else:
        T["edge_existence"] = {"value": None, "witness": None}

    # contradiction
    pair = A.find_conflict(rec, sup)
    T["contradiction"] = {"value": bool(pair), "witness": {"conflicting_pair": pair} if pair else {"none": True, "checked_supported_facts": len(sup)}}

    # temporal order derived from ticks
    sched = sorted(((s["valid_from"], s["fact"]["id"]) for s in wt["scheduled"] if s["valid_from"] > 0))
    T["temporal_order"] = {"value": [f for (_t, f) in sched], "witness": {"derived_event_order": [{"fact_id": f, "tick": t} for (t, f) in sched]}} if len(sched) >= 1 else {"value": None, "witness": None}

    # nli: a hypothesis fact judged against the supported facts
    pool = sorted(truth)
    h = r.choice(pool)
    if r.random() < 0.4 and h[0] in ("AT", "STATE"):
        if h[0] == "AT":
            locs2 = [l for l in locs if l != h[2]]
            h = ("AT", h[1], r.choice(locs2)) if locs2 else h
        else:
            h = ("STATE", h[1], h[2], _FLIP[h[3]])
    if h in sup:
        label, w = "ENTAILED", {"hypothesis": F.fid(h), "support": [F.fid(h)]}
    else:
        clash = None
        for k in sorted(sup):
            if (h[0] == "AT" and k[0] == "AT" and k[1] == h[1] and k != h) or (h[0] == "STATE" and k[0] == "STATE" and k[1:3] == h[1:3] and k != h):
                clash = k
                break
        label, w = ("CONTRADICTED", {"hypothesis": F.fid(h), "conflicting_fact": F.fid(clash)}) if clash else ("UNKNOWN", {"hypothesis": F.fid(h), "absent_from_supported": True})
    rec["fact_table"].setdefault(F.fid(h), F.from_key(h))
    T["nli"] = {"value": label, "witness": {"entailment_witness": w}}

    # evidence: the supporting fact set actually used by the decision's requirements
    reqs = A.query_requirements(rec, sm, info if info["status"] in ("SOLVED", "UNSAT_EXHAUSTED") else None) if d.step not in ("1", "1a") else []
    used = []
    for q in reqs:
        comp = sorted((a for a in q.alternatives if a <= sup), key=lambda a: (len(a), sorted(a)))
        if comp:
            used.append((q.requirement_id, _ids(comp[0])))
    T["evidence"] = {"value": sorted({i for (_q, ids) in used for i in ids}), "witness": {"supporting_fact_set": [{"requirement_id": q, "facts": ids} for (q, ids) in used]}}

    T["plan_step"] = {"value": [a.id for a in info["canonical_plan"]], "witness": {"plan_prefix": [a.id for a in info["canonical_plan"]], "depth": info["depth"]}} if info["status"] == "SOLVED" and info["canonical_plan"] else {"value": None, "witness": None}
    T["impossibility"] = {"value": True, "witness": {"unsat_certificate": info["certificate"]}} if info["status"] == "UNSAT_EXHAUSTED" and d.step == "5" else {"value": None, "witness": None}
    T["witness"] = {"value": {"step": d.step, "reason": d.reason}, "witness": d.witness}
    # entity: filled by the renderer (mention spans); placeholder until rendered
    T["entity"] = {"value": None, "witness": None}
    T["difficulty"] = {"value": {
        "entities": len(wt["entities"]), "locations": len(locs), "facts": len(truth), "hidden": len(ob["hidden_facts"]), "reports": len(ob["reports"]),
        "plan_depth": info["depth"], "requirements": len(reqs), "unresolved": d.witness.get("M_size") if d.step in ("2a", "2b", "2c") else 0,
        "available_actions": len(sm.actions), "legal_actions": len(legal), "scheduled_facts": len(wt["scheduled"]), "gates": len(wt["transition_system"]["gates"]),
        "search_states": info["n_states"]}, "witness": None}
    return T


def verify(rec: dict) -> list[str]:
    """G04: recompute every target from the record and compare, then cross-check independent validators. Returns violations."""
    bad: list[str] = []
    try:
        d = A.derive(rec)
    except A.Regenerate as e:
        return [f"derive failed: {e}"]
    fresh = compute(_copy_for_verify(rec), d)
    T = rec["TARGETS"]
    for name in NONTRIVIAL + ("difficulty",):
        if name == "entity":
            continue
        if fresh[name] != T[name]:
            bad.append(f"target {name} does not re-derive")
    # independent validators
    sm = A.sim_of(rec)
    legal_ids = {a.id for a in sm.actions if sm.legal(sm.base0, 0, a)}
    if set(T["applicability"]["value"]["legal"]) != legal_ids:
        bad.append("applicability disagrees with an independent legality sweep")
    ee = T["edge_existence"]["value"]
    if ee:
        truth = A.truth_key_set(rec)
        if (("CONNECTED", *ee["pair"]) in truth) != ee["connected"] or (("BLOCKED", *ee["pair"]) in truth) != ee["blocked"]:
            bad.append("edge_existence witness is wrong")
    rel = T["relation"]["value"]
    if rel and ("REL", rel["source"], rel["relation_id"], rel["target"]) not in A.truth_key_set(rec):
        bad.append("relation witness is not a truth fact")
    imp = T["impossibility"]
    if imp["value"]:
        info2 = A.sim_of(rec).search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
        if info2["status"] != "UNSAT_EXHAUSTED" or info2["certificate"] != imp["witness"]["unsat_certificate"]:
            bad.append("impossibility certificate does not re-verify exhaustively")
    if T["reason"]["value"] is not None and d.disposition not in ("ASK", "ESCALATE", "DECLINE_UNAVAILABLE"):
        bad.append("reason populated on a non-withholding disposition")
    return bad


def _copy_for_verify(rec: dict) -> dict:
    import copy
    return copy.deepcopy(rec)
