"""Paired interventions P1..P12 (§4). A pair is two independently valid records whose canonical diff is confined to the intervention's declared field set
(plus fields that are formal consequences of it, declared in DEPENDENTS). Pairs are the primary product: they say WHICH interface broke.
G10 is computed by check_pairs()."""
from __future__ import annotations

import copy

from . import algebra as A
from . import facts as F
from . import freeze, pipeline, registry, render, requirements as R, splits, targets
from .canon import rng as mkrng, short
from .worldgen import Cfg, Reject, finish, _alias_map, _entity_surface, goal_dict

PAIR_INDEX_BASE = 10_000_000
AXES = [p["id"] for p in freeze.FREEZE["paired_interventions"]]
DECLARED = {p["id"]: list(p["varied"]) for p in freeze.FREEZE["paired_interventions"]}
RENDER_FIELDS = ["OBSERVATION.renderer_id", "OBSERVATION.renderer_family_id", "OBSERVATION.rendered_text", "OBSERVATION.rendered_fact_ids", "OBSERVATION.mention_spans"]
REQ_FIELDS = ["INFORMATION_POLICY.requestable", "INFORMATION_POLICY.non_requestable", "INFORMATION_POLICY.acquisition_cost", "INFORMATION_POLICY.source_constraints", "INFORMATION_POLICY.request_objects", "INFORMATION_POLICY.policy_id"]
# fields that are formal consequences of the declared variation (rendered text, the partition of hidden facts, request objects, id-dependent lists)
DEPENDENTS = {
    "P1": [],
    "P2": ["OBSERVATION.goal_mentions"],
    "P3": ["OBSERVATION.goal_mentions", "WORLD_TRUTH.goal", "INFORMATION_POLICY.request_objects"],
    "P4": ["WORLD_TRUTH.temporal_state", "OBSERVATION.visible_facts"] + REQ_FIELDS,
    "P5": ["INFORMATION_POLICY.non_requestable", "INFORMATION_POLICY.acquisition_cost", "INFORMATION_POLICY.source_constraints", "INFORMATION_POLICY.request_objects", "INFORMATION_POLICY.policy_id"],
    "P6": ["OBSERVATION.reports", "OBSERVATION.uncertain_evidence"],
    "P7": ["WORLD_TRUTH.state", "OBSERVATION.visible_facts", "OBSERVATION.supported_facts"],
    "P8": ["OBSERVATION.visible_facts", "OBSERVATION.supported_facts", "ACTION_POLICY.available_actions", "WORLD_TRUTH.temporal_state", "INFORMATION_POLICY.request_objects"],
    "P9": ["WORLD_TRUTH.scheduled", "OBSERVATION.visible_facts", "OBSERVATION.supported_facts", "INFORMATION_POLICY.request_objects"],
    "P10": ["ACTION_POLICY.conventions"],
    "P11": [],
    "P12": ["WORLD_TRUTH.temporal_state"] + REQ_FIELDS,
}
REQUIRED_FACTS = ["WORLD_TRUTH.goal.required_facts"]  # recomputed from whatever the intervention varied (a consequence, never a cause)
BASE_INTENTS = {
    "P1": ("EXECUTE", "ASK", "ESCALATE_RULE", "DECLINE_SINGLE"), "P2": ("EXECUTE", "ASK", "NOOP", "POLICY_DENIED"), "P3": ("EXECUTE", "ASK", "ESCALATE_RULE", "NOOP"),
    "P4": ("EXECUTE",), "P5": ("ASK",), "P6": ("EXECUTE", "NOOP", "POLICY_DENIED"), "P7": ("EXECUTE", "NOOP", "POLICY_DENIED"), "P8": ("EXECUTE", "NOOP", "ASK"),
    "P9": ("EXECUTE", "NOOP", "ESCALATE_RULE"), "P10": ("EXECUTE",), "P11": ("ASK", "EXECUTE", "ESCALATE_MULTI"), "P12": ("ASK", "ESCALATE_MULTI", "DECLINE_SINGLE"),
}


# ------------------------------------------------------------------------------------------------ diffing (G10)
def flatten(rec: dict) -> dict:
    out: dict = {}
    for block in ("WORLD_TRUTH", "OBSERVATION", "INFORMATION_POLICY", "ACTION_POLICY"):
        for k, v in rec[block].items():
            if block == "WORLD_TRUTH" and k == "goal":
                out["WORLD_TRUTH.goal"] = {x: y for x, y in v.items() if x != "required_facts"}
                out["WORLD_TRUTH.goal.required_facts"] = v["required_facts"]
            else:
                out[f"{block}.{k}"] = v
    return out


def diff_fields(a: dict, b: dict) -> set:
    fa, fb = flatten(a), flatten(b)
    return {k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k)}


def _covered(field: str, allowed: list) -> bool:
    return any(field == x or field.startswith(x + ".") for x in allowed)


# ------------------------------------------------------------------------------------------------ helpers
def base_row(axis: str, k: int, need=None, tries: int = 400):
    """A valid canonical row (TEST-IID distribution) of an intent suitable for the axis, satisfying `need(rec)`."""
    cfg = Cfg(split="TEST-IID", intents=BASE_INTENTS[axis])
    if axis == "P9":
        cfg.extra["timed"] = 2
    for n in range(tries):
        idx = PAIR_INDEX_BASE + AXES.index(axis) * 1_000_000 + k * 97 + n
        try:
            rows = pipeline.build_world("TEST-IID", idx, cfg)
        except RuntimeError:
            continue
        rec = rows[0]
        if need is None or need(rec):
            return rec
    raise Reject(f"no base row for {axis}")


def revalidate(rec: dict, family: str) -> dict:
    """Recompute everything derived from a mutated record: requirement objects, request objects, derivation, targets, rendering."""
    rec["META"].pop("_d", None)
    finish(rec, None)
    d = A.derive(rec)
    rec["TARGETS"] = targets.compute(rec, d)
    pipeline.apply_rendering(rec, family)
    rec["META"]["structural_id"] = pipeline.structural_id(rec)
    rec["META"]["textual_id"] = __import__("bank2.canon", fromlist=["x"]).sha256_hex(rec["OBSERVATION"]["rendered_text"])
    rec["META"]["derivation"] = {"step": d.step, "classification": d.classification}
    return rec


def _clone(rec: dict, suffix: str) -> dict:
    b = copy.deepcopy(rec)
    b["world_id"] = f"{rec['world_id']}~{suffix}"
    return b


def _fk(rec):
    return A.fact_key_map(rec)


def _hide(rec: dict, fid: str, requestable: bool, cost_seed="p") -> None:
    ob, ip = rec["OBSERVATION"], rec["INFORMATION_POLICY"]
    if fid in ob["visible_facts"]:
        ob["visible_facts"].remove(fid)
    if fid not in ob["hidden_facts"]:
        ob["hidden_facts"] = sorted(ob["hidden_facts"] + [fid])
    if fid in ob["supported_facts"] and fid not in {r["fact_id"] for r in ob["reports"]}:
        ob["supported_facts"] = sorted(set(ob["supported_facts"]) - {fid})
    _set_requestable(rec, fid, requestable)


def _reveal(rec: dict, fid: str) -> None:
    ob, ip = rec["OBSERVATION"], rec["INFORMATION_POLICY"]
    ob["hidden_facts"] = sorted(set(ob["hidden_facts"]) - {fid})
    ob["visible_facts"] = sorted(set(ob["visible_facts"]) | {fid})
    ob["supported_facts"] = sorted(set(ob["supported_facts"]) | {fid})
    for lst in ("requestable", "non_requestable"):
        ip[lst] = sorted(set(ip[lst]) - {fid})
    ip["acquisition_cost"].pop(fid, None)
    ip["source_constraints"].pop(fid, None)


def _set_requestable(rec: dict, fid: str, requestable: bool) -> None:
    ip = rec["INFORMATION_POLICY"]
    ip["requestable"] = sorted(set(ip["requestable"]) - {fid})
    ip["non_requestable"] = sorted(set(ip["non_requestable"]) - {fid})
    if requestable:
        ip["requestable"] = sorted(ip["requestable"] + [fid])
        ip["acquisition_cost"][fid] = 1 + int(short([fid, "c"], 4), 16) % 3
        ip["source_constraints"][fid] = "ORACLE" if int(short([fid, "s"], 4), 16) % 2 == 0 else "PEER"
    else:
        ip["non_requestable"] = sorted(ip["non_requestable"] + [fid])
        ip["acquisition_cost"].pop(fid, None)
        ip["source_constraints"].pop(fid, None)
    ip["policy_id"] = short([ip["requestable"], ip["non_requestable"]], 8)


def _requirements(rec):
    return A.query_requirements(rec)


# ------------------------------------------------------------------------------------------------ the twelve pair builders
def pair_P1(k):
    a = base_row("P1", k)
    fam = a["OBSERVATION"]["renderer_family_id"]
    other = freeze.SEEN_FAMILIES[(freeze.SEEN_FAMILIES.index(fam) + 3) % len(freeze.SEEN_FAMILIES)]
    b = _clone(a, "P1")
    pipeline.apply_rendering(b, other, seed=1)
    b["META"]["textual_id"] = __import__("bank2.canon", fromlist=["x"]).sha256_hex(b["OBSERVATION"]["rendered_text"])
    return a, b


def pair_P2(k):
    def ok(r):
        goal = r["WORLD_TRUTH"]["goal"]
        subj, targets_ = A.goal_roles(goal)
        ents = {e["id"]: e for e in r["WORLD_TRUTH"]["entities"]}
        return subj in ents and ents[subj]["type"] != "AGENT" and ents[subj]["introduced"] and any(e["id"] != subj and e["type"] == ents[subj]["type"] and e["introduced"] for e in ents.values()) and not r["OBSERVATION"]["aliases"].get("x")
    a = base_row("P2", k, ok)
    b = _clone(a, "P2")
    r = mkrng("P2", a["world_id"])
    goal = b["WORLD_TRUTH"]["goal"]
    subj = A.goal_roles(goal)[0]
    ents = {e["id"]: e for e in b["WORLD_TRUTH"]["entities"]}
    partner = r.choice(sorted(i for i, e in ents.items() if i != subj and e["type"] == ents[subj]["type"] and e["introduced"]))
    shared = f"the {r.choice(__import__('bank2.lexicon', fromlist=['x']).AMBIG_ADJ)} {ents[subj]['type'].lower()}"
    ents[subj]["aliases"], ents[partner]["aliases"] = [shared], [shared]
    b["OBSERVATION"]["aliases"] = _alias_map(_Shim(b))
    for m in b["OBSERVATION"]["goal_mentions"]:
        if m["role"] == "SUBJECT":
            m["surface"] = shared
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    return a, b


class _Shim:
    """Adapts a record's entities to worldgen._alias_map (which expects a Truth-like object)."""

    def __init__(self, rec):
        self.ents = {e["id"]: e for e in rec["WORLD_TRUTH"]["entities"]}


def pair_P3(k):
    a = base_row("P3", k)
    sm = A.sim_of(a)
    depths, _ex = sm.reach_depths(cap_depth=4, max_states=8000)
    r = mkrng("P3", a["world_id"])
    wt = a["WORLD_TRUTH"]
    truth = A.truth_key_set(a)
    cur = tuple([wt["goal"]["pred"], *wt["goal"]["args"]])
    actor = wt["actor"]
    cands = sorted(kk for kk, dd in depths.items() if 1 <= dd <= 4 and kk[0] in ("AT", "HOLDS", "CONTAINS", "STATE") and kk not in truth and kk != cur and (kk[0] != "STATE" or kk[2] in ("openness", "activation")))
    cands = [c for c in cands if all(x in {e["id"] for e in wt["entities"] if e["introduced"]} for x in (c[1:3] if c[0] != "STATE" else c[1:2]))]
    r.shuffle(cands)
    for goal_key in cands[:12]:
        b = _clone(a, "P3")
        g = goal_dict(goal_key)
        b["WORLD_TRUTH"]["goal"] = {**g, "required_facts": {"schema": [], "goal": [F.fid(goal_key)], "plan": [], "action": {}, "query": [], "query_source_scope": wt["goal"]["required_facts"]["query_source_scope"]}}
        b["fact_table"].setdefault(F.fid(goal_key), F.from_key(goal_key))
        ents = {e["id"]: e for e in b["WORLD_TRUTH"]["entities"]}
        subj, tg = A.goal_roles(g)
        b["OBSERVATION"]["goal_mentions"] = [{"surface": _entity_surface(ents[e]), "role": role, "entity": e} for role, e in [("SUBJECT", subj)] + [("TARGET", x) for x in tg] if e in ents]
        try:
            revalidate(b, a["OBSERVATION"]["renderer_family_id"])
        except (A.Regenerate, Reject):
            continue
        return a, b
    raise Reject("no alternative goal")


def pair_P4(k):
    def ok(r):
        reqs = _requirements(r)
        return r["TARGETS"]["disposition"]["value"] == "EXECUTE" and len(reqs) >= 1
    a = base_row("P4", k, ok)
    r = mkrng("P4", a["world_id"])
    reqs = _requirements(a)
    q = r.choice(sorted(reqs, key=lambda x: x.requirement_id))
    alt = r.choice(q.alternatives)
    fid = F.fid(r.choice(sorted(alt)))
    b = _clone(a, "P4")
    _hide(b, fid, requestable=r.random() < 0.7)
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    if b["TARGETS"]["disposition"]["value"] == a["TARGETS"]["disposition"]["value"]:
        raise Reject("hiding did not change the missingness family")
    return a, b


def pair_P5(k):
    def ok(r):
        if r["TARGETS"]["disposition"]["value"] != "ASK" or r["TARGETS"]["reason"]["value"] != "NECESSARY_MISSING_REQUESTABLE":
            return False
        w = r["TARGETS"]["disposition"]["witness"]["inputs"]
        return len(w["chosen_repair"]) == 1 and len(w["unresolved"]) == 1 and len(w["unresolved"][0]["alternatives"]) == 1
    a = base_row("P5", k, ok)
    fid = a["TARGETS"]["disposition"]["witness"]["inputs"]["chosen_repair"][0]
    b = _clone(a, "P5")
    _set_requestable(b, fid, False)
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    return a, b


def pair_P6(k):
    a = base_row("P6", k)
    r = mkrng("P6", a["world_id"])
    fk = _fk(a)
    cands = sorted(i for i in a["OBSERVATION"]["visible_facts"] if fk[i][0] in ("AT", "STATE") and R.is_open(fk[i]))
    if not cands:
        raise Reject("nothing to contradict")
    locs = sorted(e["id"] for e in a["WORLD_TRUTH"]["entities"] if e["type"] == "LOCATION" and e["introduced"])
    truth = A.truth_key_set(a)
    claim = None
    r.shuffle(cands)
    for cid0 in cands:
        base = fk[cid0]
        if base[0] == "AT":
            opts = [("AT", base[1], l) for l in locs if l != base[2]]
        else:
            opts = [("STATE", base[1], base[2], {"open": "closed", "closed": "open", "active": "inactive", "inactive": "active"}[base[3]])]
        opts = [o for o in opts if o not in truth]
        if opts:
            claim = r.choice(opts)
            break
    if claim is None:
        raise Reject("no false claim available")
    b = _clone(a, "P6")
    cid = F.fid(claim)
    b["fact_table"][cid] = F.from_key(claim)
    b["OBSERVATION"]["reports"].append({"fact_id": cid, "channel": "rumor", "confidence_pct": r.randint(40, 90)})
    b["OBSERVATION"]["supported_facts"] = sorted(set(b["OBSERVATION"]["supported_facts"]) | {cid})
    b["OBSERVATION"]["uncertain_evidence"] = [{"fact_id": x["fact_id"], "confidence_pct": x["confidence_pct"], "channel": x["channel"]} for x in b["OBSERVATION"]["reports"] if x["confidence_pct"] < 100]
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    return a, b


def pair_P7(k):
    def ok(r):
        return any(f["pred"] == "REL" and not registry.BY_ID[f["args"][1]]["inverse_relation_id"] and registry.BY_ID[f["args"][1]]["split_scope"] != "TEST_RELATION_ONLY" for f in r["WORLD_TRUTH"]["state"])
    a = base_row("P7", k, ok)
    r = mkrng("P7", a["world_id"])
    rels = sorted((f for f in a["WORLD_TRUTH"]["state"] if f["pred"] == "REL"), key=lambda f: f["id"])
    for f in rels:
        e = registry.BY_ID[f["args"][1]]
        twins = [x for x in registry.REGISTRY if x["relation_id"] != e["relation_id"] and registry.combo(x) == registry.combo(e) and x["split_scope"] != "TEST_RELATION_ONLY" and e["split_scope"] != "TEST_RELATION_ONLY"
                 and x["required_slot"] == e["required_slot"] and x["inverse_relation_id"] is None and e["inverse_relation_id"] is None]
        if not twins:
            continue
        new = r.choice(sorted(twins, key=lambda x: x["relation_id"]))
        b = _clone(a, "P7")
        old_key = F.key(f)
        new_key = ("REL", old_key[1], new["relation_id"], old_key[3])
        if new_key in A.truth_key_set(a):
            continue  # the twin fact already exists between these entities: swapping would duplicate a fact
        nf = F.from_key(new_key)
        for lst in (b["WORLD_TRUTH"]["state"],):
            lst[:] = [nf if x["id"] == f["id"] else x for x in lst]
        ob = b["OBSERVATION"]
        for key in ("visible_facts", "supported_facts", "hidden_facts"):
            ob[key] = sorted([nf["id"] if i == f["id"] else i for i in ob[key]])
        for key in ("requestable", "non_requestable"):
            b["INFORMATION_POLICY"][key] = sorted([nf["id"] if i == f["id"] else i for i in b["INFORMATION_POLICY"][key]])
        b["fact_table"][nf["id"]] = nf
        b["WORLD_TRUTH"]["relations"] = [({**x, "fact_id": nf["id"], "relation_id": new["relation_id"]} if x.get("fact_id") == f["id"] else x) for x in b["WORLD_TRUTH"]["relations"]]
        b["WORLD_TRUTH"]["schema_queries"] = [({**q, "relation_id": new["relation_id"]} if q["relation_id"] == e["relation_id"] and q["source"] == old_key[1] else q) for q in b["WORLD_TRUTH"]["schema_queries"]]
        b["META"]["pair_relation_probe"] = [old_key[1], old_key[3]]
        try:
            revalidate(b, a["OBSERVATION"]["renderer_family_id"])
        except (A.Regenerate, Reject):
            continue
        return a, b
    raise Reject("no relation with a same-property twin")


def pair_P8(k):
    a = base_row("P8", k)
    r = mkrng("P8", a["world_id"])
    locs = sorted(e["id"] for e in a["WORLD_TRUTH"]["entities"] if e["type"] == "LOCATION" and e["introduced"])
    existing = {(f["args"][0], f["args"][1]) for f in a["WORLD_TRUTH"]["state"] if f["pred"] == "CONNECTED"}
    pairs = [(x, y) for x in locs for y in locs if x != y and (x, y) not in existing and (y, x) not in existing]
    if not pairs:
        raise Reject("fully connected")
    x, y = r.choice(pairs)
    a["META"]["edge_probe"] = [x, y]
    a["TARGETS"] = targets.compute(a, A.derive(a))
    pipeline.apply_rendering(a, a["OBSERVATION"]["renderer_family_id"])
    b = _clone(a, "P8")
    from .sim import ground_actions, make_action
    for (s, d_) in ((x, y), (y, x)):
        f = F.make_fact("CONNECTED", s, d_)
        b["WORLD_TRUTH"]["state"].append(f)
        b["fact_table"][f["id"]] = f
        b["OBSERVATION"]["visible_facts"] = sorted(b["OBSERVATION"]["visible_facts"] + [f["id"]])
        b["OBSERVATION"]["supported_facts"] = sorted(b["OBSERVATION"]["supported_facts"] + [f["id"]])
        b["WORLD_TRUTH"]["relations"].append({"subj": s, "pred": "CONNECTED", "obj": d_, "fact_id": f["id"]})
        act = make_action("MOVE", agent=b["WORLD_TRUTH"]["actor"], src=s, dst=d_)
        if act["id"] not in {q["id"] for q in b["ACTION_POLICY"]["available_actions"]}:
            b["ACTION_POLICY"]["available_actions"].append(act)
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    return a, b


def pair_P9(k):
    def ok(r):
        ticks = sorted({s["valid_from"] for s in r["WORLD_TRUTH"]["scheduled"] if s["valid_from"] > 0})
        return len(ticks) >= 2
    a = base_row("P9", k, ok)
    b = _clone(a, "P9")
    ticks = sorted({s["valid_from"] for s in b["WORLD_TRUTH"]["scheduled"] if s["valid_from"] > 0})
    t1, t2 = ticks[0], ticks[1]
    swap = {t1: t2, t2: t1}
    for s in b["WORLD_TRUTH"]["scheduled"]:
        if s["valid_from"] in swap:
            s["valid_from"] = swap[s["valid_from"]]
        if s["valid_to"] in swap:
            s["valid_to"] = swap[s["valid_to"]]
    b["WORLD_TRUTH"]["temporal_state"] = [{**ts, "valid_from": next(x["valid_from"] for x in b["WORLD_TRUTH"]["scheduled"] if x["fact"]["id"] == ts["fact_id"]),
                                           "valid_to": next(x["valid_to"] for x in b["WORLD_TRUTH"]["scheduled"] if x["fact"]["id"] == ts["fact_id"])} for ts in b["WORLD_TRUTH"]["temporal_state"]]
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    if a["TARGETS"]["temporal_order"]["value"] == b["TARGETS"]["temporal_order"]["value"]:
        raise Reject("the order did not change")
    return a, b


def pair_P10(k):
    a = base_row("P10", k, lambda r: r["TARGETS"]["disposition"]["value"] == "EXECUTE")
    first = A.sim_of(a).by_id[a["TARGETS"]["executed_action"]["value"]].type
    b = _clone(a, "P10")
    b["ACTION_POLICY"]["permissions"] = {t: dict(v) for t, v in b["ACTION_POLICY"]["permissions"].items()}
    b["ACTION_POLICY"]["permissions"][first] = {"permitted": False, "authority": "audit-policy"}
    b["ACTION_POLICY"]["conventions"] = [f"DENY:{t}" for t, v in sorted(b["ACTION_POLICY"]["permissions"].items()) if not v["permitted"]]
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    return a, b


def pair_P11(k):
    a = base_row("P11", k, lambda r: len(r["INFORMATION_POLICY"]["requestable"]) >= 1)
    b = _clone(a, "P11")
    ip = b["INFORMATION_POLICY"]
    for fid in ip["requestable"]:
        ip["acquisition_cost"][fid] = 1 + (ip["acquisition_cost"][fid] % 3)
        ip["source_constraints"][fid] = "PEER" if ip["source_constraints"][fid] == "ORACLE" else "ORACLE"
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    return a, b


def pair_P12(k):
    a = base_row("P12", k, lambda r: len(r["OBSERVATION"]["hidden_facts"]) >= 1 and r["TARGETS"]["disposition"]["value"] in ("ASK", "ESCALATE", "DECLINE_UNAVAILABLE"))
    b = _clone(a, "P12")
    for fid in list(b["OBSERVATION"]["hidden_facts"]):
        _reveal(b, fid)
    revalidate(b, a["OBSERVATION"]["renderer_family_id"])
    return a, b


BUILDERS = {f"P{i}": globals()[f"pair_P{i}"] for i in range(1, 13)}


def make_pair(axis: str, k: int):
    for attempt in range(60):
        try:
            a, b = BUILDERS[axis](k * 61 + attempt)
        except (Reject, A.Regenerate, StopIteration, KeyError, ValueError):
            continue
        pid = f"{axis}-{short([a['world_id'], b['world_id']], 10)}"
        for x, role in ((a, "A"), (b, "B")):
            x["META"].update({"pair_id": pid, "intervention": axis, "pair_role": role})
        return a, b
    raise RuntimeError(f"no pair for {axis} #{k}")


# ------------------------------------------------------------------------------------------------ G10
def _values(T: dict) -> dict:
    return {n: v["value"] for n, v in T.items()}


def expected_delta_ok(axis: str, a: dict, b: dict) -> list[str]:
    bad = []
    va, vb = _values(a["TARGETS"]), _values(b["TARGETS"])
    changed = {n for n in va if va[n] != vb[n]}
    da, db = (a["TARGETS"]["disposition"]["value"], a["TARGETS"]["reason"]["value"]), (b["TARGETS"]["disposition"]["value"], b["TARGETS"]["reason"]["value"])
    if axis == "P1":
        if changed - {"entity"}:
            bad.append(f"P1 changed targets {sorted(changed - {'entity'})}")
    elif axis == "P11":
        if changed:
            bad.append(f"P11 (negative control) changed targets {sorted(changed)}")
    elif axis == "P5":
        if not (da[0] == "ASK" and db == ("DECLINE_UNAVAILABLE", "NECESSARY_MISSING_UNAVAILABLE")):
            bad.append(f"P5 expected ASK -> DECLINE_UNAVAILABLE, got {da} -> {db}")
    elif axis == "P6":
        if db != ("DECLINE_UNAVAILABLE", "CONFLICTING_EVIDENCE") or da == db:
            bad.append("P6 did not make CONFLICTING_EVIDENCE appear")
    elif axis == "P2":
        if db != ("DECLINE_UNAVAILABLE", "AMBIGUOUS_REFERENCE") or a["TARGETS"]["entity"]["value"] == b["TARGETS"]["entity"]["value"]:
            bad.append("P2 did not change the binding target")
    elif axis == "P4":
        if da == db or da[0] != "EXECUTE" and db[0] == a["TARGETS"]["disposition"]["value"]:
            bad.append("P4 did not change the missingness family")
    elif axis == "P12":
        if "missing_information" not in changed or "evidence" not in changed:
            bad.append("P12 did not change both the missing and the evidence targets")
    elif axis == "P10":
        if a["TARGETS"]["applicability"]["value"]["permitted"] == b["TARGETS"]["applicability"]["value"]["permitted"] or db != ("DECLINE_UNAVAILABLE", "POLICY_DENIED"):
            bad.append("P10 did not flip applicability")
    elif axis == "P7":
        if not ({"relation"} <= changed or a["TARGETS"]["relation"]["value"] is None):
            pass
        other = changed - {"relation", "evidence", "difficulty", "nli", "missing_information", "witness", "disposition", "reason"}
        if other:
            bad.append(f"P7 changed unrelated targets {sorted(other)}")
    elif axis == "P8":
        if "edge_existence" not in changed:
            bad.append("P8 did not change the structure target")
    elif axis == "P9":
        if "temporal_order" not in changed:
            bad.append("P9 did not change the temporal target")
    elif axis == "P3":
        if a["WORLD_TRUTH"]["goal"]["pred"] == b["WORLD_TRUTH"]["goal"]["pred"] and a["WORLD_TRUTH"]["goal"]["args"] == b["WORLD_TRUTH"]["goal"]["args"]:
            bad.append("P3 left the goal unchanged")
    return bad


def check_pair(axis: str, a: dict, b: dict) -> list[str]:
    from . import gates
    bad = []
    for rec in (a, b):
        ids = [f["id"] for f in rec["WORLD_TRUTH"]["state"]]
        if len(ids) != len(set(ids)):
            bad.append(f"{rec['world_id']}: duplicate facts in the world state")
    d = diff_fields(a, b)
    allowed = DECLARED[axis] + DEPENDENTS[axis] + RENDER_FIELDS + REQUIRED_FACTS + ([] if axis != "P2" else ["WORLD_TRUTH.entities"])
    stray = sorted(f for f in d if not _covered(f, allowed))
    if stray:
        bad.append(f"canonical diff escapes the declared field set: {stray}")
    if not any(_covered(f, DECLARED[axis]) for f in d):
        bad.append("none of the declared fields actually varies")
    for rec in (a, b):
        for g, msgs in (("G01", gates.g01(rec)), ("G03", gates.g03(rec)), ("G04", gates.g04(rec)), ("G12", gates.g12(rec, gates.Acc())), ("G17", gates.g17(rec)), ("G18", gates.g18(rec))):
            bad += [f"{rec['world_id']} {g}: {m}" for m in msgs]
    if a["META"].get("pair_id") != b["META"].get("pair_id") or not a["META"].get("pair_id"):
        bad.append("pair identity missing or unequal")
    bad += expected_delta_ok(axis, a, b)
    return bad


def check_pairs(pairs: list[tuple[str, dict, dict]]) -> dict:
    fails, per_axis = [], {}
    for axis, a, b in pairs:
        msgs = check_pair(axis, a, b)
        per_axis.setdefault(axis, {"pairs": 0, "failures": 0})
        per_axis[axis]["pairs"] += 1
        if msgs:
            per_axis[axis]["failures"] += 1
            fails.append(f"{a['META']['pair_id']}: {msgs[0]}")
    missing = [ax for ax in AXES if ax not in per_axis]
    return {"passed": bool(pairs) and not fails and not missing, "checked": len(pairs), "failures": len(fails), "examples": fails[:8], "per_axis": per_axis, "axes_without_pairs": missing}
