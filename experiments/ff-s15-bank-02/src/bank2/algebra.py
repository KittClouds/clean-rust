"""The §6 decision algebra as an executable, total, deterministic function of a world record. First match wins; no randomness.

`derive(record)` re-derives everything from the record alone (truth, observation, information policy, action policy). It never consults the generator.
A malformed record raises Regenerate, never a fallback branch (§5.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import facts as F
from . import freeze
from . import registry
from . import requirements as R
from . import sim as S
from .canon import sha256_hex


class Regenerate(Exception):
    """The record violates a precondition or a certificate is unavailable; the world is regenerated, never relabeled."""


@dataclass
class Derivation:
    disposition: str
    reason: str | None            # value of the reason field (null for EXECUTE and NOOP)
    step: str
    witness: dict
    classification: str | None = None   # missingness classification (NO_MISSING_REQUIRED / IRRELEVANT_MISSING) when M is empty
    action: dict | None = None
    extras: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------- record accessors
def fact_key_map(rec: dict) -> dict:
    return {fid: F.key(f) for fid, f in rec["fact_table"].items()}


def sim_of(rec: dict, keep_ids: set | None = None) -> S.Sim:
    wt = rec["WORLD_TRUTH"]
    world = {"state": wt["state"], "scheduled": wt["scheduled"], "transition_system": wt["transition_system"],
             "available_actions": rec["ACTION_POLICY"]["available_actions"], "goal": wt["goal"]}
    return S.Sim.from_world(world, keep_ids)


def truth_key_set(rec: dict) -> set:
    wt = rec["WORLD_TRUTH"]
    return {F.key(f) for f in wt["state"]} | {F.key(s["fact"]) for s in wt["scheduled"]}


def intervals(rec: dict) -> dict:
    return {F.key(s["fact"]): (s["valid_from"], s["valid_to"]) for s in rec["WORLD_TRUTH"]["scheduled"]}


# ---------------------------------------------------------------------------------------------- step 0
def check_preconditions(rec: dict) -> None:
    wt, ob, ip, ap = rec["WORLD_TRUTH"], rec["OBSERVATION"], rec["INFORMATION_POLICY"], rec["ACTION_POLICY"]
    truth_ids = {f["id"] for f in wt["state"]} | {s["fact"]["id"] for s in wt["scheduled"]}
    vis, hid, sup = set(ob["visible_facts"]), set(ob["hidden_facts"]), set(ob["supported_facts"])
    report_ids = {r["fact_id"] for r in ob["reports"]}
    if vis | hid != truth_ids or vis & hid:
        raise Regenerate("visible/hidden do not partition the truth")
    if not sup <= (vis | report_ids):
        raise Regenerate("supported facts must be visible or derived from a report")
    req, nreq = set(ip["requestable"]), set(ip["non_requestable"])
    if req & nreq or not hid <= (req | nreq):
        raise Regenerate("requestable/non_requestable violate the partition rules")
    markers = tuple(wt.get("slot_markers", ()))
    fk = fact_key_map(rec)
    for h in hid:
        k = fk[h]
        if not R.is_open(k, markers):
            raise Regenerate("a fact of a CLOSED slot is hidden without a slot marker")
    avail = {a["id"] for a in ap["available_actions"]}
    for ro in ip["request_objects"]:
        if not ro["reveals"] or not set(ro["reveals"]) <= hid:
            raise Regenerate("a request object must reveal hidden facts")
    del avail


# ---------------------------------------------------------------------------------------------- steps 1, 1a
def find_conflict(rec: dict, sup_keys: set):
    iv = intervals(rec)
    by_loc: dict = {}
    by_attr: dict = {}
    for k in sup_keys:
        if k[0] in ("AT", "HOLDS", "CONTAINS"):
            subj = k[1] if k[0] == "AT" else k[2]
            by_loc.setdefault(subj, []).append(k)
        elif k[0] == "STATE":
            by_attr.setdefault((k[1], k[2]), []).append(k)
    for subj in sorted(by_loc):
        ks = sorted(by_loc[subj])
        if len(ks) >= 2:
            return [F.fid(ks[0]), F.fid(ks[1])]
    for subj in sorted(by_attr):
        ks = sorted(by_attr[subj])
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = iv.get(ks[i], (0, None)), iv.get(ks[j], (0, None))
                overlap = a[0] < (b[1] if b[1] is not None else 10 ** 9) and b[0] < (a[1] if a[1] is not None else 10 ** 9)
                if ks[i][3] != ks[j][3] and overlap:
                    return [F.fid(ks[i]), F.fid(ks[j])]
    return None


def goal_roles(goal: dict):
    """(subject_arg, [target_args]) by predicate; literal attribute names and values are not entities."""
    p, a = goal["pred"], goal["args"]
    if p == "AT":
        return a[0], [a[1]]
    if p in ("HOLDS", "CONTAINS"):
        return a[0], [a[1]]
    if p == "STATE":
        return a[0], []
    return (a[0] if a else None), list(a[1:])


def referential(rec: dict):
    wt, ob = rec["WORLD_TRUTH"], rec["OBSERVATION"]
    goal = wt["goal"]
    intro = {e["id"] for e in wt["entities"] if e["introduced"]}
    for m in ob["goal_mentions"]:
        if len(ob["aliases"].get(m["surface"], [])) >= 2:
            return "AMBIGUOUS_REFERENCE", {"surface": m["surface"], "bound_to": sorted(ob["aliases"][m["surface"]])}
    subj, targets = goal_roles(goal)
    if subj is not None and subj not in intro:
        return "UNKNOWN_ENTITY", {"entity": subj, "role": "SUBJECT"}
    for t in targets:
        if t not in intro:
            return "UNKNOWN_TARGET", {"entity": t, "role": "TARGET"}
    if goal["pred"] not in S.ASSERTABLE:
        return "OUT_OF_SCOPE", {"goal_predicate": goal["pred"], "closure": list(S.ASSERTABLE)}
    return None, None


# ---------------------------------------------------------------------------------------------- requirements from the record
def source_scope_keys(rec: dict, scope: str, plan_info: dict | None, sm: S.Sim) -> list:
    wt = rec["WORLD_TRUTH"]
    goal = wt["goal"]
    if scope == "GOAL":
        return [(goal["pred"], *goal["args"])] if goal["pred"] in freeze.PREDICATES else []
    if scope == "SCHEMA":
        return []  # SCHEMA obligations come from the declared schema queries, see schema_requirements
    if plan_info is None or plan_info["status"] != "SOLVED" or not plan_info["canonical_plan"]:
        return [(goal["pred"], *goal["args"])] if scope == "PLAN" and goal["pred"] in freeze.PREDICATES else []
    markers = tuple(wt.get("slot_markers", ()))
    extra = blocked_dependencies(rec, sm, plan_info) if "prohibited_edge" in markers else []
    if scope == "PLAN":
        return list(sm.replay(plan_info["canonical_plan"])["consulted_initial"]) + extra
    if scope == "ACTION":
        first = plan_info["canonical_plan"][0]
        _ok, present, _abs = sm.legal_trace(sm.base0, 0, first)
        return [k for k in present] + extra
    raise Regenerate(f"unknown source scope {scope}")


def _outcome(info: dict, sm: S.Sim) -> tuple:
    return (info["status"], info["depth"], tuple(a.id for a in info["canonical_plan"]), tuple(info["first_actions"]), tuple(a.id for a in sm.legal_set(sm.base0, 0)))


def blocked_dependencies(rec: dict, sm: S.Sim, info: dict) -> list:
    """(G3) BLOCKED facts on which the decision counterfactually depends: deleting the fact changes the canonical plan, its depth, the tie set or the legal set."""
    caps = dict(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
    base = _outcome(info, sm)
    out = []
    for k in sorted(k for k in sm.base0 if k[0] == "BLOCKED"):
        sm2 = sm.without(k)
        info2 = sm2.search(**caps)
        if info2["status"] not in ("SOLVED", "UNSAT_EXHAUSTED"):
            continue
        if _outcome(info2, sm2) != base:
            out.append(k)
    return out


def schema_requirements(rec: dict) -> list[R.Requirement]:
    truth = truth_key_set(rec)
    out = []
    for q in rec["WORLD_TRUTH"].get("schema_queries", []):
        entry = registry.BY_ID[q["relation_id"]]
        subject = (q["source"], q["relation_id"], q["target"]) if entry["transitivity"] == "TRANSITIVE" else (q["source"], q["relation_id"])
        out.append(R.Requirement("general_relation", subject, R.alternatives_for(truth, "general_relation", subject), "SCHEMA"))
    return sorted(out, key=lambda r: (r.slot, r.subject))


def query_requirements(rec: dict, sm: S.Sim | None = None, plan_info: dict | None = None) -> list[R.Requirement]:
    wt = rec["WORLD_TRUTH"]
    scope = wt["goal"]["required_facts"]["query_source_scope"]
    if scope == "SCHEMA":
        return schema_requirements(rec)
    sm = sm or sim_of(rec)
    if plan_info is None and scope in ("PLAN", "ACTION"):
        plan_info = sm.search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
    keys = source_scope_keys(rec, scope, plan_info, sm)
    return R.obligations(truth_key_set(rec), keys, scope, tuple(wt.get("slot_markers", ())))


# ---------------------------------------------------------------------------------------------- the algebra
def derive(rec: dict, check_sufficiency: bool = True) -> Derivation:
    check_preconditions(rec)
    wt, ob, ip, ap = rec["WORLD_TRUTH"], rec["OBSERVATION"], rec["INFORMATION_POLICY"], rec["ACTION_POLICY"]
    fk = fact_key_map(rec)
    sup_ids = set(ob["supported_facts"])
    sup = {fk[i] for i in sup_ids}
    requestable = {fk[i] for i in ip["requestable"]}
    cost = {fk[i]: c for i, c in ip["acquisition_cost"].items()}
    hidden = {fk[i] for i in ob["hidden_facts"]}

    # 1. conflicting supported pair
    pair = find_conflict(rec, sup)
    if pair:
        return Derivation("DECLINE_UNAVAILABLE", "CONFLICTING_EVIDENCE", "1", {"conflicting_pair": pair})

    # 1a. referential checks
    reason, w = referential(rec)
    if reason:
        return Derivation("DECLINE_UNAVAILABLE", reason, "1a", w)

    sm = sim_of(rec)
    plan_info = sm.search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
    if plan_info["status"] not in ("SOLVED", "UNSAT_EXHAUSTED"):
        raise Regenerate(f"no certificate: search ended {plan_info['status']}")

    # 2. unresolved obligations
    reqs = query_requirements(rec, sm, plan_info)
    ev = R.evaluate(reqs, sup, requestable, cost)
    disp, tag = R.classify_missingness(ev, hidden)
    M, nonreq = ev["M"], ev["nonreq"]
    mwit = {"M_size": len(M), "unresolved": [_req_witness(r, sup, requestable, cost) for r in M], "nonreq": [r.requirement_id for r in nonreq],
            "support_facts": sorted(F.fid(k) for k in ev["support_facts"]), "necessary_facts": sorted(F.fid(k) for k in ev["necessary_facts"]),
            "required_requirements": [r.requirement_id for r in reqs]}
    if disp == "DECLINE_UNAVAILABLE":
        return Derivation(disp, tag, "2a", dict(mwit, chosen_unavailable=nonreq[0].requirement_id))
    if disp == "ASK":
        r = M[0]
        chosen = ev["chosen"][r.requirement_id]
        ro = next((x for x in ip["request_objects"] if x["requirement_id"] == r.requirement_id and set(x["reveals"]) == {F.fid(k) for k in chosen}), None)
        if ro is None:
            raise Regenerate("an ASK requires a generated request object naming the requirement")
        return Derivation("ASK", tag, "2b", dict(mwit, request_object=ro["request_id"], chosen_repair=sorted(F.fid(k) for k in chosen)), extras={"request_id": ro["request_id"]})
    if disp == "ESCALATE":
        return Derivation("ESCALATE", tag, "2c", mwit)
    classification = tag  # NO_MISSING_REQUIRED or IRRELEVANT_MISSING

    d = _steps_3_to_10(rec, sm, plan_info, ev, sup, classification, mwit)
    if check_sufficiency:
        obs_ids = sup_ids & ({f["id"] for f in wt["state"]} | {s["fact"]["id"] for s in wt["scheduled"]})
        sm_obs = sim_of(rec, obs_ids)
        info_obs = sm_obs.search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
        d2 = _steps_3_to_10(rec, sm_obs, info_obs, ev, sup, classification, mwit)
        if (d2.disposition, d2.reason, (d2.action or {}).get("id")) != (d.disposition, d.reason, (d.action or {}).get("id")):
            raise Regenerate("observation sufficiency: the decision differs on the observed state")
    return d


def _req_witness(r: R.Requirement, sup: set, requestable: set, cost: dict) -> dict:
    reps = R.repairs(r, sup)
    return {"requirement_id": r.requirement_id, "slot": r.slot, "subject": list(r.subject),
            "alternatives": [sorted(F.fid(k) for k in a) for a in r.alternatives],
            "repairs": [sorted(F.fid(k) for k in x) for x in reps],
            "legal": [bool(x <= requestable) for x in reps]}


def _steps_3_to_10(rec: dict, sm: S.Sim, info: dict, ev: dict, sup: set, classification: str, mwit: dict) -> Derivation:
    wt, ob, ap = rec["WORLD_TRUTH"], rec["OBSERVATION"], rec["ACTION_POLICY"]
    # 3. goal already satisfied
    if sm.goal_holds(sm.base0, 0):
        return Derivation("NOOP", None, "3", {"goal_satisfying_facts": [F.fid(sm.goal_key)]}, classification)
    # 4. no legal environment action
    legal = sm.legal_set(sm.base0, 0)
    if not legal:
        return Derivation("DECLINE_UNAVAILABLE", "NO_VALID_ACTION", "4", {"exhaustive_environment_legal_set": [], "available": len(sm.actions)}, classification)
    # 5. no plan, exhaustively
    if info["status"] == "UNSAT_EXHAUSTED":
        return Derivation("DECLINE_UNAVAILABLE", "IMPOSSIBLE_GOAL", "5", {"unsat_certificate": info["certificate"]}, classification)
    if info["status"] != "SOLVED":
        raise Regenerate(f"no certificate: search ended {info['status']}")
    plan = info["canonical_plan"]
    first = plan[0]
    rep = sm.replay(plan)
    costs = ap["action_costs"]
    total_cost = sum(costs.get(a.type, 1) for a in plan)
    # 6. escalation rules (all kinds except CONFIRM_UNCERTAIN)
    for rule in ap["escalation_rules"]:
        kind = rule["kind"]
        fired = ((kind == "MAX_PLAN_DEPTH" and len(plan) > rule["limit"]) or (kind == "COST_LIMIT" and total_cost > rule["limit"]) or (kind == "ACTION_TYPE_REQUIRES_TIER" and first.type == rule["action_type"]))
        if fired:
            return Derivation("ESCALATE", "ESCALATION_REQUIRED", "6", {"fired_rule": rule["rule_id"], "kind": kind, "plan_depth": len(plan), "plan_cost": total_cost}, classification)
    # 7. convention forbids the action
    perm = ap["permissions"].get(first.type)
    if perm and not perm["permitted"]:
        return Derivation("DECLINE_UNAVAILABLE", "POLICY_DENIED", "7", {"denying_authority": perm["authority"], "action_id": first.id, "action_type": first.type}, classification)
    # 8. a used fact is only uncertainly supported and a confirmation rule applies
    conf_rules = [r for r in ap["escalation_rules"] if r["kind"] == "CONFIRM_UNCERTAIN"]
    if conf_rules:
        vis = set(ob["visible_facts"])
        low = {}
        for r in ob["reports"]:
            low.setdefault(r["fact_id"], []).append(r["confidence_pct"])
        for k in rep["consulted_initial"]:
            fid = F.fid(k)
            if fid not in vis and fid in low and all(c < conf_rules[0]["min_confidence_pct"] for c in low[fid]):
                return Derivation("ESCALATE", "ESCALATION_REQUIRED", "8", {"fired_rule": conf_rules[0]["rule_id"], "kind": "CONFIRM_UNCERTAIN", "uncertain_fact": fid}, classification)
    # 9. tied optimal first actions
    if len(info["first_actions"]) >= 2:
        return Derivation("DECLINE_UNAVAILABLE", "MULTIPLE_UNRESOLVED_ACTIONS", "9", {"tied_optimal_actions": info["first_actions"]}, classification)
    # 10. execute
    nf = sm.apply(sm.base0, first)
    return Derivation("EXECUTE", None, "10", {"plan_prefix": [a.id for a in plan], "action_id": first.id,
                                                "legal_transition": {"pre": [F.fid(k) for k in first.pre], "rm": [F.fid(k) for k in first.rm], "add": [F.fid(k) for k in first.add]}},
                      classification, action=first.raw, extras={"plan_depth": len(plan), "next_facts_digest": sha256_hex(sorted(nf))})
