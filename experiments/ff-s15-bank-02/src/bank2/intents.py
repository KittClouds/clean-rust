"""Scenario intents: each builds a world toward one algebra branch. The label is ALWAYS derived by algebra.derive(); an intent that does not come out as intended is rejected and the
world is regenerated with the next attempt (never relabeled, §5.2)."""
from __future__ import annotations

from . import algebra as A
from . import lexicon
from . import facts as F
from . import requirements as R
from . import sim as S
from .canon import rng as mkrng
from .worldgen import (EXPECT, MISSING_INTENTS, PLAN_FREE_INTENTS, ROOT_SEED, Cfg, Plan, Reject, Truth, action_cost, add_schema_structure,
                       assemble, build_truth, default_policy, finish, goal_dict, ground, make_sim, pick_goal, pick_intent)

MAX_ATTEMPTS = 80
SMALL = {"n_locs": 4, "n_objs": 1, "n_cont": 0, "n_sw": 0, "n_timed": 0, "other": False, "n_blocked": 0, "oneway": 0, "extra_edges": 0, "n_rel": 1}


# ------------------------------------------------------------------------------------------------ shared context
class Ctx:
    pass


def _scope_for(r, intent: str) -> str:
    if intent in MISSING_INTENTS:
        return r.choice(["PLAN"] * 5 + ["ACTION"] * 2 + ["GOAL"] * 2 + ["SCHEMA"] * 3)
    if intent in ("EXECUTE", "EXECUTE_REPORT", "POLICY_DENIED", "TIE", "ESCALATE_RULE", "ESCALATE_UNCERTAIN"):
        return r.choice(["PLAN"] * 7 + ["ACTION"] * 2 + ["GOAL"] + ["SCHEMA"])
    return r.choice(["PLAN"] * 6 + ["GOAL"] * 2 + ["SCHEMA"])


def _policy(r, t: Truth, info: dict, reqs=None):
    plan = info["canonical_plan"] if info and info["status"] == "SOLVED" else []
    first = plan[0].type if plan else None
    cost = sum(action_cost(a.type) for a in plan)
    return default_policy(r, t, len(plan), first, cost, {})


def context(r, cfg: Cfg, split: str, index: int, attempt: int, intent: str, sp: dict, goal_fn=None, kinds=None, depth_range=None, scope=None) -> Ctx:
    c = Ctx()
    c.r, c.cfg, c.split, c.index, c.attempt, c.intent = r, cfg, split, index, attempt, intent
    c.scope = scope or _scope_for(r, intent)
    c.t = build_truth(r, cfg, sp)
    if c.scope == "SCHEMA" and not add_schema_structure(r, c.t, cfg):
        raise Reject("no required_slot structure available")
    return c


def settle(c: Ctx, goal_key=None, goal_override=None, depth_range=None, kinds=None, pre=None):
    t, r, cfg = c.t, c.r, c.cfg
    if pre:
        pre(t)
    c.kind = None
    if goal_override is None:
        if goal_key is None:
            goal_key, c.kind = pick_goal(r, t, cfg, depth_range or cfg.depth_range, kinds)
        c.goal_key = goal_key
    else:
        c.goal_key = (goal_override["pred"], *goal_override["args"])
    c.goal_override = goal_override
    c.actions = ground(t)
    gk = c.goal_key if c.goal_key[0] in S.ASSERTABLE else None
    c.sm = make_sim(t, gk, c.actions)
    c.info = c.sm.search(cap_depth=cfg.depth_cap, max_states=cfg.state_cap)
    base = Plan(goal_key=c.goal_key, goal_override=goal_override, scope=c.scope, note={"goal_kind": c.kind})
    c.perms, c.rules = _policy(r, t, c.info)
    base.permissions, base.rules = dict(c.perms), list(c.rules)
    c.rec0 = assemble(t, cfg, c.split, c.index, c.attempt, c.intent, base, c.actions, c.info)
    try:
        c.reqs = A.query_requirements(c.rec0, A.sim_of(c.rec0), c.info)
    except A.Regenerate as e:
        raise Reject(str(e))
    c.ev0 = R.evaluate(c.reqs, {F.key(c.rec0["fact_table"][i]) for i in c.rec0["OBSERVATION"]["supported_facts"]}, set())
    return c


def open_irrelevant(c: Ctx) -> list:
    support = c.ev0["support_facts"]
    return sorted(k for k in c.t.facts | {k for (k, _a, _b) in c.t.sched} if R.is_open(k, c.t.slot_markers) and k not in support)


def finalize(c: Ctx, plan: Plan) -> dict:
    plan.goal_key, plan.goal_override, plan.scope = c.goal_key, c.goal_override, c.scope
    plan.note = dict(plan.note, goal_kind=c.kind)
    rec = assemble(c.t, c.cfg, c.split, c.index, c.attempt, c.intent, plan, c.actions, c.info)
    rec = finish(rec, c.t)
    try:
        d = A.derive(rec)
    except A.Regenerate as e:
        raise Reject(f"algebra: {e}")
    want = EXPECT[c.intent]
    if (d.disposition, d.reason) != want:
        raise Reject(f"intent {c.intent} derived {(d.disposition, d.reason)}")
    rec["META"]["derivation"] = {"step": d.step, "classification": d.classification}
    rec["_d"] = d
    return rec


def _hide_some_irrelevant(c: Ctx, plan: Plan, n_max=2):
    pool = open_irrelevant(c)
    n = c.r.randint(0, n_max)
    for k in c.r.sample(pool, min(n, len(pool))):
        plan.hidden.add(k)
        if c.r.random() < 0.6:
            plan.requestable.add(k)


def _requirement_hide(c: Ctx, req: R.Requirement, requestable: bool, plan: Plan, others: list):
    alt = c.r.choice(req.alternatives) if req.alternatives else None
    if not alt:
        raise Reject("requirement without alternatives")
    facts = sorted(alt)
    hide = set(c.r.sample(facts, c.r.randint(1, len(facts))))
    for o in others:
        if any(hide & a for a in o.alternatives):
            raise Reject("hidden facts shared with another requirement")
    plan.hidden |= hide
    if requestable:
        plan.requestable |= hide
    return hide


# ------------------------------------------------------------------------------------------------ handlers
def h_execute(c: Ctx, variant: str):
    r = c.r
    if c.info["status"] != "SOLVED" or not c.info["canonical_plan"]:
        raise Reject("needs a plan")
    plan = Plan(permissions=dict(c.perms), rules=list(c.rules))
    if variant == "EXECUTE":
        _hide_some_irrelevant(c, plan)
    elif variant == "EXECUTE_REPORT":
        rep = A.sim_of(c.rec0).replay(c.info["canonical_plan"])["consulted_initial"]
        opens = [k for k in rep if R.is_open(k, c.t.slot_markers)]
        if not opens:
            raise Reject("nothing consulted to recover")
        k = r.choice(sorted(opens))
        plan.hidden.add(k)
        plan.reports.append((k, r.choice(["registry", "peer", "log"]), 100))
        if r.random() < 0.5:
            plan.requestable.add(k)
    return plan


def h_noop(c: Ctx):
    plan = Plan(permissions=dict(c.perms), rules=list(c.rules))
    _hide_some_irrelevant(c, plan)
    return plan


def h_missing(c: Ctx, intent: str):
    r = c.r
    reqs = c.reqs
    need = 1 if intent in ("ASK", "DECLINE_SINGLE") else 2
    if len(reqs) < need:
        raise Reject("not enough obligations")
    plan = Plan(permissions=dict(c.perms), rules=list(c.rules))
    chosen = r.sample(sorted(reqs, key=lambda q: q.requirement_id), need)
    rest = [q for q in reqs if q not in chosen]
    flags = {"ASK": [True], "ESCALATE_MULTI": [True, True], "DECLINE_SINGLE": [False], "DECLINE_MIXED": r.choice([[True, False], [False, True], [False, False]])}[intent]
    for q, f in zip(chosen, flags):
        _requirement_hide(c, q, f, plan, rest + [x for x in chosen if x is not q])
    if r.random() < 0.4:
        _hide_some_irrelevant(c, plan, 1)
    return plan


def h_conflict(c: Ctx):
    r = c.r
    cands = sorted(k for k in c.t.facts if k[0] in ("AT", "STATE") and R.is_open(k))
    if not cands:
        raise Reject("no claim to contradict")
    k = r.choice(cands)
    locs = c.t.of("LOCATION")
    if k[0] == "AT":
        alts = [l for l in locs if l != k[2]]
        claim = ("AT", k[1], r.choice(alts))
    else:
        vals = {"openness": ["open", "closed"], "activation": ["active", "inactive"]}[k[2]]
        claim = ("STATE", k[1], k[2], [v for v in vals if v != k[3]][0])
    plan = Plan(permissions=dict(c.perms), rules=list(c.rules))
    plan.reports.append((claim, r.choice(["rumor", "note"]), r.randint(40, 90)))
    return plan


def h_policy_denied(c: Ctx):
    if c.info["status"] != "SOLVED" or not c.info["canonical_plan"]:
        raise Reject("needs a plan")
    first = c.info["canonical_plan"][0].type
    plan = Plan(permissions={a: dict(v) for a, v in c.perms.items()}, rules=[x for x in c.rules if x["kind"] != "CONFIRM_UNCERTAIN"])
    plan.permissions[first] = {"permitted": False, "authority": c.r.choice(["safety-council", "site-owner", "audit-policy"])}
    return plan


def h_escalate_rule(c: Ctx):
    r = c.r
    if c.info["status"] != "SOLVED" or not c.info["canonical_plan"]:
        raise Reject("needs a plan")
    planv = c.info["canonical_plan"]
    opts = []
    if len(planv) >= 2:
        opts.append({"rule_id": "rule_depth_fire", "kind": "MAX_PLAN_DEPTH", "limit": len(planv) - 1})
    tc = sum(action_cost(a.type) for a in planv)
    if tc >= 2:
        opts.append({"rule_id": "rule_cost_fire", "kind": "COST_LIMIT", "limit": tc - 1})
    opts.append({"rule_id": "rule_tier_fire", "kind": "ACTION_TYPE_REQUIRES_TIER", "action_type": planv[0].type})
    plan = Plan(permissions={a: {"permitted": True, "authority": "base-policy"} for a in S.ENV_ACTIONS}, rules=[x for x in c.rules if x["kind"] != "CONFIRM_UNCERTAIN"])
    plan.rules.insert(r.randint(0, len(plan.rules)), r.choice(opts))
    return plan


def h_escalate_uncertain(c: Ctx):
    r = c.r
    if c.info["status"] != "SOLVED" or not c.info["canonical_plan"]:
        raise Reject("needs a plan")
    rep = A.sim_of(c.rec0).replay(c.info["canonical_plan"])["consulted_initial"]
    opens = sorted(k for k in rep if R.is_open(k, c.t.slot_markers))
    if not opens:
        raise Reject("nothing consulted")
    k = r.choice(opens)
    plan = Plan(permissions={a: {"permitted": True, "authority": "base-policy"} for a in S.ENV_ACTIONS}, rules=[x for x in c.rules if x["kind"] not in ("CONFIRM_UNCERTAIN", "MAX_PLAN_DEPTH", "COST_LIMIT", "ACTION_TYPE_REQUIRES_TIER")])
    plan.rules.append({"rule_id": "rule_confirm", "kind": "CONFIRM_UNCERTAIN", "min_confidence_pct": 80})
    plan.hidden.add(k)
    plan.reports.append((k, r.choice(["peer", "log"]), r.randint(40, 79)))
    if r.random() < 0.5:
        plan.requestable.add(k)
    return plan


def h_ambiguous(c: Ctx):
    r = c.r
    goal = c.goal_override or goal_dict(c.goal_key)
    subj, targets = A.goal_roles(goal)
    cand = [e for e in [subj] + targets if e in c.t.ents and c.t.ents[e]["type"] != "AGENT"]
    if not cand:
        raise Reject("no non-agent goal entity")
    a = r.choice(cand)
    same = [i for i, e in c.t.ents.items() if e["type"] == c.t.ents[a]["type"] and i != a and e["introduced"]]
    others = same or [i for i, e in c.t.ents.items() if i != a and e["type"] != "AGENT" and e["introduced"]]
    if not others:
        raise Reject("no collision partner")
    b = r.choice(others)
    shared = f"the {r.choice(lexicon.pool(lexicon.AMBIG_ADJ, c.cfg.held_vocab))} {c.t.ents[a]['type'].lower()}"
    c.t.ents[a]["aliases"] = [shared]
    c.t.ents[b]["aliases"] = [shared]
    plan = Plan(permissions=dict(c.perms), rules=list(c.rules), mention_alias={a: 0})
    return plan


# ------------------------------------------------------------------------------------------------ dispatch
def generate_attempt(split: str, index: int, attempt: int, cfg: Cfg) -> dict:
    intent = pick_intent(mkrng(ROOT_SEED, split, index, "intent", attempt // 40), cfg.intents)  # after 40 failed attempts the next round picks another intent
    r = mkrng(ROOT_SEED, split, index, attempt)
    if intent in ("AMBIGUOUS",):
        c = context(r, cfg, split, index, attempt, intent, {"n_blocked": 0})
        settle(c, depth_range=(1, cfg.depth_range[1]))
        return finalize(c, h_ambiguous(c))
    if intent == "UNKNOWN_ENTITY":
        c = context(r, cfg, split, index, attempt, intent, {"ghost_type": "OBJECT"})
        ghost = next(g for g, ty in c.t.ghosts.items())
        loc = r.choice(c.t.of("LOCATION"))
        settle(c, goal_override={"pred": "AT", "args": [ghost, loc]})
        return finalize(c, Plan(permissions=dict(c.perms), rules=list(c.rules)))
    if intent == "UNKNOWN_TARGET":
        c = context(r, cfg, split, index, attempt, intent, {"ghost_type": "LOCATION"})
        ghost = next(g for g, ty in c.t.ghosts.items())
        obj = r.choice(c.t.of("OBJECT"))
        settle(c, goal_override={"pred": "AT", "args": [obj, ghost]})
        return finalize(c, Plan(permissions=dict(c.perms), rules=list(c.rules)))
    if intent == "OUT_OF_SCOPE":
        c = context(r, cfg, split, index, attempt, intent, {})
        a, b = r.sample(c.t.of("LOCATION"), 2)
        settle(c, goal_override={"pred": r.choice(["CONNECTED", "BLOCKED"]), "args": [a, b]})
        return finalize(c, Plan(permissions=dict(c.perms), rules=list(c.rules)))
    if intent == "NO_VALID":
        c = context(r, cfg, split, index, attempt, intent, dict(SMALL, n_objs=r.randint(1, 2)))
        t = c.t
        la = next(k[2] for k in t.facts if k[0] == "AT" and k[1] == t.actor)
        t.facts = {k for k in t.facts if not (k[0] == "CONNECTED" and la in k[1:]) and not (k[0] == "BLOCKED" and la in k[1:])}
        t.facts = {k for k in t.facts if not (k[0] == "HOLDS" and k[1] == t.actor)}
        for o in t.of("OBJECT"):
            if not any(k[0] in ("AT", "HOLDS", "CONTAINS") and o in k for k in t.facts):
                t.facts.add(("AT", o, r.choice([l for l in t.of("LOCATION") if l != la])))
        t.facts = {k for k in t.facts if not (k[0] == "AT" and k[2] == la and k[1] != t.actor)}
        t.include_wait = False
        t.gates = [g for g in t.gates if la not in g["edge"]]
        other = [l for l in t.of("LOCATION") if l != la]
        settle(c, goal_key=("AT", t.actor, r.choice(other)))
        return finalize(c, Plan(permissions=dict(c.perms), rules=list(c.rules)))
    if intent == "IMPOSSIBLE":
        c = context(r, cfg, split, index, attempt, intent, dict(SMALL, n_cont=r.choice([0, 1]), n_locs=r.choice([4, 5])), scope="PLAN")
        t = c.t
        strategy = "cut" if not t.of("CONTAINER") or r.random() < 0.7 else "sealed"
        if strategy == "cut":
            locs = t.of("LOCATION")
            la = next(k[2] for k in t.facts if k[0] == "AT" and k[1] == t.actor)
            lx = r.choice([l for l in locs if l != la])
            for k in [k for k in t.facts if k[0] == "CONNECTED" and k[2] == lx]:
                t.facts.add(("BLOCKED", k[1], k[2]))
            t.facts = {k for k in t.facts if not (k[0] in ("AT",) and k[2] == lx and k[1] != lx)}
            t.facts = {k for k in t.facts if not (k[0] == "HOLDS" and False)}
            obj = r.choice(t.of("OBJECT"))
            for k in [k for k in t.facts if k[0] in ("AT", "HOLDS", "CONTAINS") and k[-1 if k[0] != "AT" else 1] == obj and (k[0] != "AT" or True)]:
                pass
            goal = ("AT", t.actor, lx) if r.random() < 0.5 else ("AT", obj, lx)
            for k in [k for k in t.facts if k[0] in ("AT",) and k[1] == obj and k[2] == lx]:
                t.facts.discard(k)
            if goal[1] == obj and any(k == ("AT", obj, lx) for k in t.facts):
                raise Reject("goal already true")
        else:
            cont = t.of("CONTAINER")[0]
            obj = r.choice(t.of("OBJECT"))
            t.facts = {k for k in t.facts if not (k[0] in ("AT", "HOLDS", "CONTAINS") and (k[2] == obj if k[0] != "AT" else k[1] == obj))}
            t.facts = {k for k in t.facts if not (k[0] == "STATE" and k[1] == cont and k[2] == "openness")}
            t.facts |= {("CONTAINS", cont, obj), ("STATE", cont, "openness", "closed")}
            t.extra_actions_off = {"OPEN"}
            goal = ("HOLDS", t.actor, obj)
        settle(c, goal_key=goal)
        if c.info["status"] != "UNSAT_EXHAUSTED":
            raise Reject("impossible world was solvable")
        return finalize(c, Plan(permissions=dict(c.perms), rules=list(c.rules)))
    if intent == "NOOP":
        c = context(r, cfg, split, index, attempt, intent, {})
        pool = sorted(k for k in c.t.facts if k[0] in ("AT", "HOLDS", "CONTAINS", "STATE") and k[0] != "CONNECTED")
        settle(c, goal_key=r.choice(pool))
        return finalize(c, h_noop(c))
    if intent == "TIE":
        c = context(r, cfg, split, index, attempt, intent, {"cycle": True, "n_blocked": 0, "gate_p": 0.0, "n_sw": 0, "n_timed": 0, "n_cont": 0}, scope="PLAN")
        settle(c, depth_range=(2, cfg.depth_range[1]), kinds=["MOVE"])
        if len(c.info["first_actions"]) < 2:
            raise Reject("no tie")
        return finalize(c, Plan(permissions={a: {"permitted": True, "authority": "base-policy"} for a in S.ENV_ACTIONS}, rules=[]))
    # the remaining intents all need a plan of the configured depth
    sp = {}
    if intent in ("ESCALATE_RULE", "POLICY_DENIED", "EXECUTE", "EXECUTE_REPORT", "ESCALATE_UNCERTAIN") and cfg.depth_range[0] >= 2:
        sp = {}
    c = context(r, cfg, split, index, attempt, intent, sp)
    if intent in MISSING_INTENTS and r.random() < 0.3:
        c.t.slot_markers = [r.choice(["traversable_edge", "prohibited_edge"])]  # opens a CLOSED slot for this world (section 1.7)
    settle(c)
    if intent in ("EXECUTE", "EXECUTE_REPORT"):
        return finalize(c, h_execute(c, intent))
    if intent in MISSING_INTENTS:
        return finalize(c, h_missing(c, intent))
    if intent == "CONFLICT":
        return finalize(c, h_conflict(c))
    if intent == "POLICY_DENIED":
        return finalize(c, h_policy_denied(c))
    if intent == "ESCALATE_RULE":
        return finalize(c, h_escalate_rule(c))
    if intent == "ESCALATE_UNCERTAIN":
        return finalize(c, h_escalate_uncertain(c))
    raise Reject(f"unhandled intent {intent}")


def generate(split: str, index: int, cfg: Cfg | None = None) -> dict:
    cfg = cfg or Cfg(split=split)
    last = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            rec = generate_attempt(split, index, attempt, cfg)
            rec["META"]["attempts"] = attempt + 1
            return rec
        except (Reject, A.Regenerate) as e:
            last = e
    raise RuntimeError(f"world {split}:{index} not generated in {MAX_ATTEMPTS} attempts: {last}")
