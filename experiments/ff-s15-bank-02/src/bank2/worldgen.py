"""Canonical world generation for BANK-v2.

A world is built in four moves: (1) a true world (entities, topology, devices, timed facts, gates, relations); (2) a goal chosen by measured plan depth;
(3) an observation and policy plan that steers toward an INTENT (an algebra branch); (4) the record is assembled and the §6 algebra DERIVES the label.
If the derived branch differs from the intent, the world is regenerated, never relabeled (§5.2). Intents steer and stratify; they never label.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import algebra as A
from . import facts as F
from . import freeze, lexicon, registry
from . import requirements as R
from . import sim as S
from .canon import rng as mkrng, short, sha256_hex

ROOT_SEED = "bank2-root-seed-v0.6"


class Reject(Exception):
    """An attempt did not produce the intended branch or violated a generator constraint; try the next attempt."""


@dataclass
class Cfg:
    split: str = "TRAIN"
    held_vocab: bool = False
    depth_range: tuple = (1, 4)
    loc_range: tuple = (4, 6)
    state_cap: int = 40000
    depth_cap: int = 8
    allow_test_relations: bool = False
    require_test_relations: bool = False
    intents: tuple | None = None
    extra: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------------ intents and their mixture
INTENT_WEIGHTS = [
    ("EXECUTE", 26), ("NOOP", 5), ("ASK", 14), ("ESCALATE_MULTI", 6), ("ESCALATE_RULE", 5), ("ESCALATE_UNCERTAIN", 3),
    ("DECLINE_SINGLE", 5), ("DECLINE_MIXED", 4), ("CONFLICT", 4), ("IMPOSSIBLE", 4), ("NO_VALID", 3), ("POLICY_DENIED", 4),
    ("TIE", 4), ("AMBIGUOUS", 3), ("UNKNOWN_ENTITY", 2), ("UNKNOWN_TARGET", 2), ("OUT_OF_SCOPE", 3), ("EXECUTE_REPORT", 3),
]
PLAN_FREE_INTENTS = {"AMBIGUOUS", "UNKNOWN_ENTITY", "UNKNOWN_TARGET", "OUT_OF_SCOPE", "NO_VALID", "IMPOSSIBLE", "CONFLICT", "NOOP"}
EXPECT = {
    "EXECUTE": ("EXECUTE", None), "EXECUTE_REPORT": ("EXECUTE", None), "NOOP": ("NOOP", None),
    "ASK": ("ASK", "NECESSARY_MISSING_REQUESTABLE"), "ESCALATE_MULTI": ("ESCALATE", "MULTIPLE_REQUIRED_MISSING"),
    "ESCALATE_RULE": ("ESCALATE", "ESCALATION_REQUIRED"), "ESCALATE_UNCERTAIN": ("ESCALATE", "ESCALATION_REQUIRED"),
    "DECLINE_SINGLE": ("DECLINE_UNAVAILABLE", "NECESSARY_MISSING_UNAVAILABLE"), "DECLINE_MIXED": ("DECLINE_UNAVAILABLE", "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE"),
    "CONFLICT": ("DECLINE_UNAVAILABLE", "CONFLICTING_EVIDENCE"), "IMPOSSIBLE": ("DECLINE_UNAVAILABLE", "IMPOSSIBLE_GOAL"),
    "NO_VALID": ("DECLINE_UNAVAILABLE", "NO_VALID_ACTION"), "POLICY_DENIED": ("DECLINE_UNAVAILABLE", "POLICY_DENIED"),
    "TIE": ("DECLINE_UNAVAILABLE", "MULTIPLE_UNRESOLVED_ACTIONS"), "AMBIGUOUS": ("DECLINE_UNAVAILABLE", "AMBIGUOUS_REFERENCE"),
    "UNKNOWN_ENTITY": ("DECLINE_UNAVAILABLE", "UNKNOWN_ENTITY"), "UNKNOWN_TARGET": ("DECLINE_UNAVAILABLE", "UNKNOWN_TARGET"),
    "OUT_OF_SCOPE": ("DECLINE_UNAVAILABLE", "OUT_OF_SCOPE"),
}
MISSING_INTENTS = {"ASK", "ESCALATE_MULTI", "DECLINE_SINGLE", "DECLINE_MIXED"}


def pick_intent(r, allowed=None) -> str:
    items = [(n, w) for (n, w) in INTENT_WEIGHTS if allowed is None or n in allowed]
    tot = sum(w for _n, w in items)
    x = r.random() * tot
    for n, w in items:
        x -= w
        if x < 0:
            return n
    return items[-1][0]


# ------------------------------------------------------------------------------------------------ truth
class Truth:
    def __init__(self):
        self.ents: dict = {}          # id -> entity dict
        self.facts: set = set()       # untimed t=0 fact keys
        self.sched: list = []         # (key, valid_from, valid_to)
        self.gates: list = []         # {"edge": [a,b], "cond": [e, attr, v]}
        self.actor = None
        self.other = None
        self.timed = set()
        self.extra_actions_off: set = set()   # action types with no grounded instances (closed available set)
        self.include_wait = True
        self.schema_queries: list = []
        self.slot_markers: list = []
        self.ghosts: dict = {}

    def of(self, typ):
        return [i for i, e in self.ents.items() if e["type"] == typ]


def _distinct(r, pool, n):
    if len(pool) < n:
        raise Reject("lexicon pool too small")
    return r.sample(pool, n)


def build_truth(r, cfg: Cfg, sp: dict) -> Truth:
    t = Truth()
    n_locs = sp.get("n_locs") or r.randint(*cfg.loc_range)
    n_objs, n_cont, n_sw = sp.get("n_objs", r.randint(1, 3)), sp.get("n_cont", r.choice([0, 1, 1])), sp.get("n_sw", r.choice([0, 1, 1, 2]))
    n_timed = sp.get("n_timed", cfg.extra.get("timed") or r.choice([0, 0, 0, 1, 1, 2]))
    has_other = sp.get("other", r.random() < 0.35)
    total = n_locs + 1 + int(has_other) + n_objs + n_cont + n_sw + n_timed
    total += 1 if sp.get("ghost_type") else 0
    ordinals = list(range(total))
    r.shuffle(ordinals)  # S1: ordinals shuffled within the world, hence uncorrelated with type
    it = iter(ordinals)

    def new_entity(typ, name, introduced=True):
        eid = f"e{next(it)}"
        t.ents[eid] = {"id": eid, "name": name, "type": typ, "aliases": [], "introduced": introduced}
        return eid

    held = cfg.held_vocab
    used = set()

    def names(kind, n):
        pool = [w for w in lexicon.names_for(kind, held) if w not in used]
        got = _distinct(r, pool, n)
        used.update(got)
        return got

    locs = [new_entity("LOCATION", nm) for nm in names("LOCATION", n_locs)]
    t.actor = new_entity("AGENT", names("AGENT", 1)[0])
    if has_other:
        t.other = new_entity("AGENT", names("AGENT", 1)[0])
    objs = [new_entity("OBJECT", nm) for nm in names("OBJECT", n_objs)]
    conts = [new_entity("CONTAINER", nm) for nm in names("CONTAINER", n_cont)] if n_cont else []
    sws = [new_entity("SWITCH", nm) for nm in names("SWITCH", n_sw)] if n_sw else []
    tsws = [new_entity("SWITCH", nm) for nm in names("SWITCH", n_timed)] if n_timed else []
    if sp.get("ghost_type"):
        gpool = [w for w in lexicon.KIND_POOLS[sp["ghost_type"]] if w not in used and lexicon.is_held(w) == held]
        ghost = new_entity(sp["ghost_type"], r.choice(gpool), introduced=False)
        t.ghosts[ghost] = sp["ghost_type"]
    t.timed = set(tsws)
    # topology: random tree (bidirectional), extra edges, one-way edges, blocked edges
    edges = set()
    order = locs[:]
    r.shuffle(order)
    for i in range(1, len(order)):
        a, b = order[i], order[r.randrange(i)]
        edges |= {(a, b), (b, a)}
    if sp.get("cycle") and len(order) >= 4:
        a, b, c, d = order[:4]
        edges |= {(a, b), (b, a), (b, c), (c, b), (c, d), (d, c), (d, a), (a, d)}
    for _ in range(sp.get("extra_edges", r.choice([0, 1, 1, 2]))):
        a, b = r.sample(locs, 2)
        edges |= {(a, b), (b, a)}
    for _ in range(sp.get("oneway", r.choice([0, 0, 1]))):
        a, b = r.sample(locs, 2)
        if (a, b) not in edges:
            edges.add((a, b))
    for e in sorted(edges):
        t.facts.add(("CONNECTED", *e))
    protected = sp.get("protected_edges", set())
    cand = sorted(e for e in edges if e not in protected)
    for _ in range(sp.get("n_blocked", r.choice([0, 0, 1, 1, 2]))):
        if cand:
            e = cand.pop(r.randrange(len(cand)))
            t.facts.add(("BLOCKED", *e))
    # placement
    for c in conts:
        t.facts.add(("AT", c, r.choice(locs)))
        t.facts.add(("STATE", c, "openness", r.choice(["open", "closed"])))
    for s in sws:
        t.facts.add(("AT", s, r.choice(locs)))
        t.facts.add(("STATE", s, "activation", r.choice(["active", "inactive", "inactive"])))
    tick_pool = [2, 3, 4, 5]
    r.shuffle(tick_pool)
    for i, s in enumerate(tsws):
        t.facts.add(("AT", s, r.choice(locs)))
        k = tick_pool[i % len(tick_pool)]
        t.sched.append((("STATE", s, "activation", "inactive"), 0, k))
        t.sched.append((("STATE", s, "activation", "active"), k, None))
    t.facts.add(("AT", t.actor, r.choice(locs)))
    if t.other:
        t.facts.add(("AT", t.other, r.choice(locs)))
    for o in objs:
        x = r.random()
        if x < 0.55 or (not conts and x < 0.85):
            t.facts.add(("AT", o, r.choice(locs)))
        elif conts and x < 0.85:
            t.facts.add(("CONTAINS", r.choice(conts), o))
        elif x < 0.93 or not t.other:
            t.facts.add(("HOLDS", t.actor, o))
        else:
            t.facts.add(("HOLDS", t.other, o))
    # gates on random directed edges, each requiring a (timed or untimed) switch to be active
    gate_sws = sws + tsws
    for s in gate_sws:
        if r.random() < sp.get("gate_p", 0.8):
            cands = sorted(e for e in edges if e not in protected)
            if cands:
                e = r.choice(cands)
                t.gates.append({"edge": list(e), "cond": [s, "activation", "active"]})
    # relations (distractors), never storing a transitive closure
    _add_relations(r, t, cfg, sp)
    if cfg.extra.get("long_chain"):
        add_long_chain(r, t, cfg)
    # aliases (unique adjective forms); collisions are created only by the ambiguity intent
    adjs = lexicon.pool(lexicon.ADJECTIVES, held)
    r.shuffle(adjs)
    for i, (eid, e) in enumerate(sorted(t.ents.items())):
        if e["type"] != "AGENT":
            e["aliases"] = [f"the {adjs[i % len(adjs)]} {e['name']}"]
    return t


def _add_relations(r, t: Truth, cfg: Cfg, sp: dict):
    vis = registry.visible_in("TEST-RELATION" if cfg.allow_test_relations else "TRAIN")
    by_type = {typ: t.of(typ) for typ in registry.ENTITY_TYPES}
    n = sp.get("n_rel", r.choice([0, 1, 2, 3]))
    chosen = [e for e in vis if by_type[e["domain_type"]] and by_type[e["range_type"]] and (e["domain_type"] != e["range_type"] or len(by_type[e["domain_type"]]) >= 2)]
    if cfg.require_test_relations:
        test_only = [e for e in chosen if e["split_scope"] == "TEST_RELATION_ONLY"]
        if not test_only:
            raise Reject("no feasible test-only relation in this world")
        chosen_first = [r.choice(test_only)]
    else:
        chosen_first = []
    pool = chosen if not cfg.require_test_relations else chosen
    picks = chosen_first + [r.choice(pool) for _ in range(n)] if pool else []
    for e in picks:
        src = r.choice(by_type[e["domain_type"]])
        dstpool = [x for x in by_type[e["range_type"]] if x != src]
        if not dstpool:
            continue
        dst = r.choice(dstpool)
        if e["directionality"] == "SYMMETRIC":
            k = F.normalize_symmetric(("REL", src, e["relation_id"], dst))
        else:
            k = ("REL", src, e["relation_id"], dst)
        if k in t.facts or _implied_by_closure(t.facts, e, k):
            continue
        if not cfg.extra.get("long_chain") and _chain_depth(t.facts | {k}) > 2:
            continue
        t.facts.add(k)


def _chain_depth(facts: set) -> int:
    """Longest chain of a TRANSITIVE relation among the stored REL facts."""
    depth = 0
    rels = [x for x in facts if x[0] == "REL"]
    for rid in {x[2] for x in rels}:
        e = registry.BY_ID[rid]
        if e["transitivity"] != "TRANSITIVE":
            continue
        adj: dict = {}
        for x in rels:
            if x[2] == rid:
                adj.setdefault(x[1], []).append(x[3])
                if e["directionality"] == "SYMMETRIC":
                    adj.setdefault(x[3], []).append(x[1])

        def longest(node, seen):
            return max([1 + longest(n, seen | {n}) for n in adj.get(node, []) if n not in seen] or [0])
        for node in list(adj):
            depth = max(depth, longest(node, {node}))
    return depth


def closure_violation(facts: set) -> bool:
    """True if any stored fact of a TRANSITIVE relation is the closure of other stored facts (the gate's own predicate)."""
    rels = {x for x in facts if x[0] == "REL" and registry.BY_ID[x[2]]["transitivity"] == "TRANSITIVE"}
    for k in rels:
        same = {x for x in rels if x[2] == k[2]} - {k}
        if same and R.relation_alternatives(same, k[1], k[2], k[3]):
            return True
    return False


def _implied_by_closure(facts: set, entry: dict, k: tuple) -> bool:
    if entry["transitivity"] != "TRANSITIVE":
        return False
    rid = entry["relation_id"]
    truth = {x for x in facts if x[0] == "REL" and x[2] == rid}
    if R.relation_alternatives(truth, k[1], rid, k[3]):
        return True  # k would be a closure fact of an existing chain
    # also refuse if adding k makes an existing direct edge redundant
    for x in truth:
        if R.relation_alternatives(truth | {k}, x[1], rid, x[3]) and len(R.relation_alternatives(truth | {k}, x[1], rid, x[3])) > 1:
            return True
    return False


def add_long_chain(r, t: Truth, cfg: Cfg):
    """TEST-HOP-DEPTH: a chain of a TRANSITIVE relation deeper than train ever stores (three or four hops); its closure is never inserted."""
    vis = registry.visible_in("TEST-RELATION" if cfg.allow_test_relations else "TRAIN")
    cand = [e for e in vis if e["transitivity"] == "TRANSITIVE" and e["directionality"] == "DIRECTED" and e["domain_type"] == e["range_type"] == "LOCATION"]
    if not cand:
        raise Reject("no transitive location relation")
    e = r.choice(cand)
    locs = t.of("LOCATION")
    n = min(len(locs), r.choice([4, 4, 5]))
    chain = r.sample(locs, n)
    for x, y in zip(chain, chain[1:]):
        t.facts.add(("REL", x, e["relation_id"], y))
    if e["required_slot"]:
        t.schema_queries.append({"source": chain[0], "relation_id": e["relation_id"], "target": chain[-1]})
    if closure_violation(t.facts):
        raise Reject("the long chain would imply a stored closure fact")


def add_schema_structure(r, t: Truth, cfg: Cfg):
    """Schema-scope worlds: a required_slot relation gives obligations (non-transitive: a value; transitive: reachability over a diamond of chains)."""
    vis = registry.visible_in("TEST-RELATION" if cfg.allow_test_relations else "TRAIN")
    req = [e for e in vis if e["required_slot"]]
    r.shuffle(req)
    for e in req:
        dom, rng_ = t.of(e["domain_type"]), t.of(e["range_type"])
        if e["transitivity"] == "TRANSITIVE" and e["directionality"] == "DIRECTED" and e["domain_type"] == e["range_type"] and len(dom) >= 4:
            a, b, c, d = r.sample(dom, 4)
            for x, y in ((a, b), (b, d), (a, c), (c, d)):
                t.facts.add(("REL", x, e["relation_id"], y))
            t.schema_queries.append({"source": a, "relation_id": e["relation_id"], "target": d})
            if closure_violation(t.facts):
                raise Reject("the schema diamond would imply a stored closure fact")
            return True
        if e["transitivity"] == "NONE" and e["directionality"] == "DIRECTED" and dom and rng_:
            a, b = r.choice(dom), r.choice([x for x in rng_ if x != r.choice(dom)] or rng_)
            t.facts.add(("REL", a, e["relation_id"], b))
            t.schema_queries.append({"source": a, "relation_id": e["relation_id"], "target": None})
            return True
    return False


# ------------------------------------------------------------------------------------------------ actions, goals
def ground(t: Truth) -> list[dict]:
    locs, objs, conts = t.of("LOCATION"), t.of("OBJECT"), t.of("CONTAINER")
    sws = [s for s in t.of("SWITCH")]
    connected = [(k[1], k[2]) for k in t.facts if k[0] == "CONNECTED"]
    decoys = []
    acts = S.ground_actions(t.actor, locs, objs, conts, sws, [t.other] if t.other else [], connected, decoys, include_wait=t.include_wait, timed_switches=frozenset(t.timed))
    return [a for a in acts if a["type"] not in t.extra_actions_off]


def make_sim(t: Truth, goal_key, actions=None) -> S.Sim:
    return S.Sim(sorted(t.facts), t.sched, t.gates, actions or ground(t), goal_key)


def goal_dict(k: tuple) -> dict:
    return {"pred": k[0], "args": list(k[1:])}


def pick_goal(r, t: Truth, cfg: Cfg, depth_range: tuple, kinds=None):
    """Choose a goal fact key by measured shortest-plan depth. Returns (key, kind) or raises Reject."""
    sm = make_sim(t, None)
    depths, exhausted = sm.reach_depths(cap_depth=min(cfg.depth_cap, max(depth_range[1], 1) + 1), max_states=cfg.state_cap // 2)
    locs, objs, conts, sws = t.of("LOCATION"), t.of("OBJECT"), t.of("CONTAINER"), [s for s in t.of("SWITCH") if s not in t.timed]
    cands: dict = {"MOVE": [], "DELIVER": [], "TAKE": [], "TRANSFER": [], "PUT": [], "OPEN": [], "CLOSE": [], "ACT": [], "DEACT": []}
    for l in locs:
        cands["MOVE"].append(("AT", t.actor, l))
        for o in objs:
            cands["DELIVER"].append(("AT", o, l))
    for o in objs:
        cands["TAKE"].append(("HOLDS", t.actor, o))
        if t.other:
            cands["TRANSFER"].append(("HOLDS", t.other, o))
        for c in conts:
            cands["PUT"].append(("CONTAINS", c, o))
    for c in conts:
        cands["OPEN"].append(("STATE", c, "openness", "open"))
        cands["CLOSE"].append(("STATE", c, "openness", "closed"))
    for s in sws:
        cands["ACT"].append(("STATE", s, "activation", "active"))
        cands["DEACT"].append(("STATE", s, "activation", "inactive"))
    lo, hi = depth_range
    ok = {kind: [k for k in ks if k not in t.facts and k in depths and lo <= depths[k] <= hi] for kind, ks in cands.items()}
    kinds = [k for k in (kinds or ok) if ok.get(k)]
    if not kinds:
        raise Reject("no goal in the depth range")
    kind = r.choice(sorted(kinds))
    return r.choice(sorted(ok[kind])), kind


# ------------------------------------------------------------------------------------------------ record assembly
def _entity_surface(e: dict, alias_index: int | None = None) -> str:
    if e["type"] == "AGENT":
        return e["name"]
    if alias_index is not None and e["aliases"]:
        return e["aliases"][alias_index]
    return f"the {e['name']}"


def _alias_map(t: Truth) -> dict:
    m: dict = {}
    for e in t.ents.values():
        if not e["introduced"]:
            continue
        for s in [_entity_surface(e)] + list(e["aliases"]):
            m.setdefault(s, []).append(e["id"])
    return {k: sorted(v) for k, v in sorted(m.items())}


@dataclass
class Plan:
    """What the intent decided about observation and policy."""
    hidden: set = field(default_factory=set)
    requestable: set = field(default_factory=set)
    reports: list = field(default_factory=list)       # (key, channel, confidence_pct)
    permissions: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)
    scope: str = "PLAN"
    goal_key: tuple | None = None
    goal_override: dict | None = None
    mention_alias: dict = field(default_factory=dict)  # entity id -> alias index used in the goal mention
    note: dict = field(default_factory=dict)


def action_cost(a_type: str) -> int:
    return 1 + int(sha256_hex('cost' + a_type)[:2], 16) % 3


def default_policy(r, t: Truth, plan_len: int | None, first_type: str | None, total_cost: int, costs: dict) -> tuple[dict, list]:
    """Non-firing distractors: permissions and escalation rules that exist but do not apply."""
    perms = {a: {"permitted": True, "authority": "base-policy"} for a in S.ENV_ACTIONS}
    rules = []
    if r.random() < 0.5:
        rules.append({"rule_id": "rule_depth", "kind": "MAX_PLAN_DEPTH", "limit": (plan_len or 0) + r.randint(1, 3)})
    if r.random() < 0.4:
        rules.append({"rule_id": "rule_cost", "kind": "COST_LIMIT", "limit": total_cost + r.randint(1, 4)})
    others = [a for a in ("TRANSFER", "CLOSE", "DEACTIVATE", "OPEN", "TAKE") if a != first_type]
    if r.random() < 0.4:
        rules.append({"rule_id": "rule_tier", "kind": "ACTION_TYPE_REQUIRES_TIER", "action_type": r.choice(others)})
    if r.random() < 0.4:
        perms[r.choice(others)] = {"permitted": False, "authority": "safety-council"}
    return perms, rules


def assemble(t: Truth, cfg: Cfg, split: str, index: int, attempt: int, intent: str, plan: Plan, actions: list[dict], depth_info: dict) -> dict:
    goal = plan.goal_override or goal_dict(plan.goal_key)
    facts_table: dict = {}

    def reg(k: tuple) -> str:
        f = F.from_key(k)
        facts_table[f["id"]] = f
        return f["id"]

    state = [F.from_key(k) for k in sorted(t.facts)]
    sched = [{"fact": F.from_key(k), "valid_from": vf, "valid_to": vt} for (k, vf, vt) in t.sched]
    for f in state:
        facts_table[f["id"]] = f
    for s in sched:
        facts_table[s["fact"]["id"]] = s["fact"]
    truth_ids = {f["id"] for f in state} | {s["fact"]["id"] for s in sched}
    hidden_ids = {F.fid(k) for k in plan.hidden}
    assert hidden_ids <= truth_ids
    visible_ids = truth_ids - hidden_ids
    reports = []
    for (k, channel, conf) in plan.reports:
        reports.append({"fact_id": reg(k), "channel": channel, "confidence_pct": conf})
    supported = sorted(visible_ids | {x["fact_id"] for x in reports})
    req_ids = {F.fid(k) for k in plan.requestable} & hidden_ids
    nonreq_ids = hidden_ids - req_ids
    gkey = (goal["pred"], *goal["args"])
    goal_fact_id = reg(gkey) if goal["pred"] in freeze.PREDICATES else None

    ents = sorted(t.ents.values(), key=lambda e: int(e["id"][1:]))
    amap = _alias_map(t)
    subj, targets = A.goal_roles(goal)
    mentions = []
    for role, eid in [("SUBJECT", subj)] + [("TARGET", x) for x in targets]:
        if eid in t.ents:
            e = t.ents[eid]
            surf = _entity_surface(e, plan.mention_alias.get(eid))
            mentions.append({"surface": surf, "role": role, "entity": eid if e["introduced"] else None})
        elif eid is not None:
            mentions.append({"surface": f"the {eid}", "role": role, "entity": None})
    rec = {
        "world_id": f"W:{split}:{index:07d}:{short([ROOT_SEED, split, index, attempt], 8)}",
        "bank": "BANK-v2", "version": freeze.VERSION, "split": split,
        "fact_table": facts_table,
        "WORLD_TRUTH": {
            "entities": ents,
            "relations": [{"subj": k[1], "pred": k[0], "obj": k[-1], "fact_id": F.fid(k), **({"relation_id": k[2]} if k[0] == "REL" else {})} for k in sorted(t.facts) if k[0] in ("CONNECTED", "BLOCKED", "REL")],
            "state": state,
            "scheduled": sched,
            "temporal_state": [{"fact_id": s["fact"]["id"], "valid_from": s["valid_from"], "valid_to": s["valid_to"], "observed_at": 0 if s["fact"]["id"] in visible_ids else None} for s in sched],
            "transition_system": {"gates": t.gates, "action_types": list(S.ENV_ACTIONS), "closure": list(S.ASSERTABLE)},
            "actor": t.actor,
            "goal": {**goal, "required_facts": {"schema": [], "goal": [goal_fact_id] if goal_fact_id else [], "plan": [], "action": {}, "query": [], "query_source_scope": plan.scope}},
            "schema_queries": t.schema_queries,
            "slot_markers": list(t.slot_markers),
        },
        "OBSERVATION": {
            "visible_facts": sorted(visible_ids), "hidden_facts": sorted(hidden_ids), "supported_facts": supported,
            "reports": reports, "uncertain_evidence": [{"fact_id": x["fact_id"], "confidence_pct": x["confidence_pct"], "channel": x["channel"]} for x in reports if x["confidence_pct"] < 100],
            "aliases": amap, "goal_mentions": mentions,
            "rendered_text": None, "renderer_id": None, "renderer_family_id": None,
        },
        "INFORMATION_POLICY": {
            "requestable": sorted(req_ids), "non_requestable": sorted(nonreq_ids),
            "acquisition_cost": {i: 1 + int(sha256_hex(i)[:2], 16) % 3 for i in sorted(req_ids)},
            "source_constraints": {i: ("ORACLE" if int(sha256_hex('src' + i)[:2], 16) % 2 == 0 else "PEER") for i in sorted(req_ids)},
            "request_objects": [], "policy_id": short([sorted(req_ids), sorted(nonreq_ids)], 8),
        },
        "ACTION_POLICY": {
            "available_actions": actions, "permissions": plan.permissions, "action_costs": {a: action_cost(a) for a in S.ENV_ACTIONS},
            "escalation_rules": plan.rules, "conventions": [f"DENY:{k}" for k, v in sorted(plan.permissions.items()) if not v["permitted"]],
        },
        "META": {"intent": intent, "index": index, "attempt": attempt, "depth_cap": cfg.depth_cap, "state_cap": cfg.state_cap, "note": plan.note, "goal_kind": plan.note.get("goal_kind")},
    }
    return rec


def finish(rec: dict, t: Truth) -> dict:
    """Fill the five required_facts scopes, the requirement objects and the request objects from the record, using the single evaluator."""
    wt, ob, ip = rec["WORLD_TRUTH"], rec["OBSERVATION"], rec["INFORMATION_POLICY"]
    sm = A.sim_of(rec)
    ref, _w = A.referential(rec)
    if ref:
        # decided at step 1a: no search is needed or certifiable (the goal names an entity that does not exist for the agent)
        rf0 = rec["WORLD_TRUTH"]["goal"]["required_facts"]
        rf0.update({"query": [], "plan": [], "action": {}, "schema": [], "query_evaluated": False})
        return rec
    info = sm.search(cap_depth=rec["META"]["depth_cap"], max_states=rec["META"]["state_cap"])
    if info["status"] not in ("SOLVED", "UNSAT_EXHAUSTED"):
        raise Reject(f"search {info['status']}")
    scope = wt["goal"]["required_facts"]["query_source_scope"]
    rf = wt["goal"]["required_facts"]
    rf.pop("query_evaluated", None)
    truth = A.truth_key_set(rec)
    reqs = A.query_requirements(rec, sm, info)
    rf["query"] = [r.to_json() for r in reqs]
    plan_keys = A.source_scope_keys(rec, "PLAN", info, sm)
    rf["plan"] = sorted({F.fid(k) for k in plan_keys})
    if info["status"] == "SOLVED" and info["canonical_plan"]:
        first = info["canonical_plan"][0]
        _ok, present, _a = sm.legal_trace(sm.base0, 0, first)
        rf["action"] = {first.id: sorted(F.fid(k) for k in present)}
        plan_keys = list(plan_keys) + list(present)
    schema_keys = [k for r in A.schema_requirements(rec) for alt in r.alternatives for k in alt]
    rf["schema"] = sorted({F.fid(k) for k in schema_keys})
    for k in list(plan_keys) + schema_keys:
        rec["fact_table"].setdefault(F.fid(k), F.from_key(k))
    # request objects: one per unresolved requestable requirement (its chosen repair) plus decoys for other hidden requestable groups
    fk = A.fact_key_map(rec)
    sup = {fk[i] for i in ob["supported_facts"]}
    requestable = {fk[i] for i in ip["requestable"]}
    cost = {fk[i]: c for i, c in ip["acquisition_cost"].items()}
    ev = R.evaluate(reqs, sup, requestable, cost)
    ros, covered = [], set()
    for r in ev["M"]:
        ch = ev["chosen"][r.requirement_id]
        if ch:
            ids = sorted(F.fid(k) for k in ch)
            ros.append({"request_id": "req_" + short(ids, 8), "requirement_id": r.requirement_id, "reveals": ids})
            covered |= set(ids)
    groups: dict = {}
    for hid in ob["hidden_facts"]:
        if hid in ip["requestable"] and hid not in covered:
            k = fk[hid]
            groups.setdefault((F.slot_of(k[0]), str(F.subject_of(k))), []).append(hid)
    for _g, ids in sorted(groups.items()):
        ids = sorted(ids)
        ros.append({"request_id": "req_" + short(ids, 8), "requirement_id": None, "reveals": ids})
    ip["request_objects"] = ros
    return rec


def _key_of_id(truth: set, fid: str) -> tuple:
    for k in truth:
        if F.fid(k) == fid:
            return k
    raise KeyError(fid)
