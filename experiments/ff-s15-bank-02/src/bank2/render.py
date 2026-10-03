"""Renderer families (§3.3): 8 seen (V1..V8) and 4 held (H1..H4). A family is a syntax and discourse realization, not one fixed string: seeded lexical variation is allowed inside it.

Seen and held families use DISJOINT sentence-template pools and different layouts, so TEST-TEMPLATE is a real family-level holdout.
The rendering declares the information policy, the action permissions and the escalation rules, because ASK versus DECLINE_UNAVAILABLE could not otherwise be determined from what the agent sees.
Hidden facts are never rendered, except through a report. Every visible fact is rendered exactly once.
"""
from __future__ import annotations

from . import algebra as A
from . import facts as F
from . import freeze, registry
from .canon import rng as mkrng, sha256_hex

# ------------------------------------------------------------------------------------------------ sentence template pools (disjoint per V/H)
POOLS = {
    "AT": {"V": ["{s} is at {l}", "{s} can be found at {l}", "{s} is located at {l}", "at {l} there is {s}"],
           "H": ["{s} sits in {l}", "you will find {s} in {l}", "{l} has {s}"]},
    "AT_AGENT": {"V": ["{s} is in {l}", "{s} stands at {l}", "{s} is currently at {l}"], "H": ["{s} has arrived in {l}", "{s} waits in {l}"]},
    "HOLDS": {"V": ["{a} holds {o}", "{a} carries {o}", "{a} has {o} in hand"], "H": ["{o} is in the hands of {a}", "{a} is gripping {o}"]},
    "CONTAINS": {"V": ["{c} contains {o}", "{o} is inside {c}", "inside {c} is {o}"], "H": ["{c} keeps {o} within", "{o} lies within {c}"]},
    "STATE": {"V": ["{e} is {v}", "{e} currently stands {v}"], "H": ["{e} stays {v}", "right now {e} is {v}"]},
    "CONNECTED": {"V": ["you can go from {a} to {b}", "{a} leads to {b}", "there is a path from {a} to {b}"], "H": ["one may walk from {a} into {b}", "{b} can be reached from {a}"]},
    "BLOCKED": {"V": ["going from {a} to {b} is prohibited", "the way from {a} to {b} is blocked"], "H": ["passage from {a} to {b} is forbidden", "you may not cross from {a} to {b}"]},
    "GATE": {"V": ["to go from {a} to {b}, {sw} must be {v}", "{sw} must be {v} before passing from {a} to {b}"], "H": ["crossing from {a} to {b} needs {sw} to be {v}", "from {a} to {b} only while {sw} is {v}"]},
    "SCHED": {"V": ["from tick {t}, {e} is {v}", "{e} becomes {v} at tick {t}"], "H": ["starting at tick {t}, {e} turns {v}", "by tick {t} {e} is {v}"]},
    "SCHED_UNTIL": {"V": ["until tick {u}, {e} is {v}", "{e} is {v} before tick {u}"], "H": ["up to tick {u}, {e} remains {v}", "{e} stays {v} until tick {u}"]},
    "REPORT": {"V": ["{ch} reports that {f} ({p}% sure)", "{ch} says {f} ({p}% sure)"], "H": ["according to {ch}, {f} (confidence {p}%)", "{ch} claims that {f} ({p}% confidence)"]},
    "ALIAS": {"V": ["{n} is also called {al}", "{al} is another name for {n}"], "H": ["{n} goes by {al} as well", "people say {al} for {n}"]},
}
REL_PHRASES = {  # (directionality, transitivity, domain, range) -> (forward pool, inverse pool); chosen by hash of (relation id, family), never by id order
    ("DIRECTED", "NONE", "AGENT", "OBJECT"): (["supplies", "provides material to", "hands tools to"], ["receives goods from", "gets material from"]),
    ("DIRECTED", "NONE", "OBJECT", "AGENT"): (["receives goods from", "gets material from"], ["supplies", "provides material to"]),
    ("DIRECTED", "NONE", "AGENT", "AGENT"): (["reports to", "answers to", "takes orders from"], []),
    ("SYMMETRIC", "NONE", "AGENT", "AGENT"): (["works alongside", "is allied with", "partners with"], []),
    ("DIRECTED", "TRANSITIVE", "LOCATION", "LOCATION"): (["lies within", "is part of", "sits inside the zone of"], []),
    ("SYMMETRIC", "NONE", "LOCATION", "LOCATION"): (["borders", "adjoins", "neighbors"], []),
    ("DIRECTED", "NONE", "OBJECT", "LOCATION"): (["belongs in", "is stored for", "is kept for use in"], []),
    ("DIRECTED", "NONE", "OBJECT", "OBJECT"): (["is part of", "is a component of", "fits into"], []),
    ("DIRECTED", "TRANSITIVE", "OBJECT", "OBJECT"): (["derives from", "was made from", "descends from"], []),
    ("DIRECTED", "NONE", "AGENT", "LOCATION"): (["is assigned to", "is posted at", "is responsible for"], []),
    ("SYMMETRIC", "NONE", "OBJECT", "OBJECT"): (["is paired with", "matches", "goes with"], []),
    ("DIRECTED", "NONE", "LOCATION", "OBJECT"): (["houses", "stores", "keeps"], []),
    ("DIRECTED", "TRANSITIVE", "AGENT", "AGENT"): (["is senior to", "outranks through the chain", "supervises via the chain"], []),
    ("SYMMETRIC", "TRANSITIVE", "LOCATION", "LOCATION"): (["is linked through a chain to", "is reachable from", "is joined over a chain with"], []),
    ("DIRECTED", "NONE", "CONTAINER", "OBJECT"): (["is the usual home of", "is used to keep", "is filled with"], ["is usually kept in", "is stored inside"]),
    ("DIRECTED", "NONE", "OBJECT", "CONTAINER"): (["is usually kept in", "is stored inside"], ["is the usual home of", "is used to keep"]),
    ("SYMMETRIC", "NONE", "SWITCH", "SWITCH"): (["is wired with", "is coupled to", "shares a circuit with"], []),
    ("DIRECTED", "NONE", "SWITCH", "LOCATION"): (["controls the lighting of", "is mounted in", "serves"], []),
    ("SYMMETRIC", "TRANSITIVE", "AGENT", "AGENT"): (["is connected through a chain to", "knows through a chain", "is in the same network as"], []),
    ("DIRECTED", "TRANSITIVE", "CONTAINER", "CONTAINER"): (["is nested in", "sits inside the chain of", "is stacked within"], []),
}
GENERIC_REL = (["is related to", "is tied to", "is linked with"], [])
ACTION_WORD = {"MOVE": "move", "TAKE": "take", "DROP": "drop", "TRANSFER": "transfer", "OPEN": "open", "CLOSE": "close", "ACTIVATE": "activate", "DEACTIVATE": "deactivate", "WAIT": "wait"}
VALUE_WORD = {"open": "open", "closed": "closed", "active": "active", "inactive": "inactive"}

# family layouts: V = seen, H = held
FAMILIES = {
    "V1": {"pool": "V", "layout": "prose", "order": ["setting", "facts", "reports", "rules", "goal", "policy"]},
    "V2": {"pool": "V", "layout": "bullets", "order": ["setting", "facts", "rules", "reports", "policy", "goal"]},
    "V3": {"pool": "V", "layout": "numbered", "order": ["goal", "setting", "facts", "reports", "rules", "policy"]},
    "V4": {"pool": "V", "layout": "tagged", "order": ["setting", "rules", "facts", "reports", "goal", "policy"]},
    "V5": {"pool": "V", "layout": "telegraph", "order": ["facts", "setting", "rules", "reports", "policy", "goal"]},
    "V6": {"pool": "V", "layout": "briefing", "order": ["setting", "goal", "facts", "reports", "rules", "policy"]},
    "V7": {"pool": "V", "layout": "log", "order": ["setting", "facts", "reports", "rules", "policy", "goal"]},
    "V8": {"pool": "V", "layout": "memo", "order": ["rules", "setting", "facts", "reports", "goal", "policy"]},
    "H1": {"pool": "H", "layout": "checklist", "order": ["setting", "facts", "reports", "rules", "policy", "goal"]},
    "H2": {"pool": "H", "layout": "firstperson", "order": ["setting", "facts", "reports", "goal", "rules", "policy"]},
    "H3": {"pool": "H", "layout": "table", "order": ["setting", "facts", "reports", "rules", "policy", "goal"]},
    "H4": {"pool": "H", "layout": "question", "order": ["goal", "policy", "rules", "facts", "reports", "setting"]},
}
assert tuple(k for k in FAMILIES if k.startswith("V")) == freeze.SEEN_FAMILIES and tuple(k for k in FAMILIES if k.startswith("H")) == freeze.HELD_FAMILIES


class R:
    """Per-rendering state."""

    def __init__(self, rec: dict, family: str, seed):
        self.rec, self.fam = rec, FAMILIES[family]
        self.family = family
        self.r = mkrng("render", rec["world_id"], family, seed)
        self.pool = self.fam["pool"]
        wt = rec["WORLD_TRUTH"]
        self.ents = {e["id"]: e for e in wt["entities"]}
        self.rendered: list[str] = []

    def pick(self, kind: str) -> str:
        return self.r.choice(POOLS[kind][self.pool])

    def nm(self, eid: str) -> str:
        e = self.ents[eid]
        return e["name"] if e["type"] == "AGENT" else f"the {e['name']}"

    def fact_sentence(self, k: tuple) -> str:
        p = k[0]
        if p == "AT":
            e = self.ents[k[1]]
            t = self.pick("AT_AGENT" if e["type"] == "AGENT" else "AT")
            return t.format(s=self.nm(k[1]), l=self.nm(k[2]))
        if p == "HOLDS":
            return self.pick("HOLDS").format(a=self.nm(k[1]), o=self.nm(k[2]))
        if p == "CONTAINS":
            return self.pick("CONTAINS").format(c=self.nm(k[1]), o=self.nm(k[2]))
        if p == "STATE":
            return self.pick("STATE").format(e=self.nm(k[1]), v=VALUE_WORD[k[3]])
        if p == "CONNECTED":
            return self.pick("CONNECTED").format(a=self.nm(k[1]), b=self.nm(k[2]))
        if p == "BLOCKED":
            return self.pick("BLOCKED").format(a=self.nm(k[1]), b=self.nm(k[2]))
        if p == "REL":
            return f"{self.nm(k[1])} {self.rel_phrase(k[2])} {self.nm(k[3])}"
        raise ValueError(p)

    def rel_phrase(self, rid: str) -> str:
        e = registry.BY_ID[rid]
        fwd, inv = REL_PHRASES.get((e["directionality"], e["transitivity"], e["domain_type"], e["range_type"]), GENERIC_REL)
        h = int(sha256_hex(f"relword|{rid}|{self.family}")[:8], 16)
        pool = fwd
        if e["inverse_relation_id"] and inv and h % 2:
            pool = inv
        return pool[h % len(pool)]


def question_phrase(rec: dict, k: tuple, ents: dict) -> str:
    nm = lambda eid: (ents[eid]["name"] if ents[eid]["type"] == "AGENT" else f"the {ents[eid]['name']}")  # noqa: E731
    p = k[0]
    if p in ("AT", "HOLDS", "CONTAINS"):
        return f"where {nm(k[1] if p == 'AT' else k[2])} is"
    if p == "STATE":
        return f"whether {nm(k[1])} is {'open' if k[2] == 'openness' else 'active'}"
    if p == "CONNECTED":
        return f"whether one can go from {nm(k[1])} to {nm(k[2])}"
    if p == "BLOCKED":
        return f"whether going from {nm(k[1])} to {nm(k[2])} is prohibited"
    return f"how {nm(k[1])} is related to {nm(k[3])}"


def request_text(rec: dict, ro: dict) -> str:
    ents = {e["id"]: e for e in rec["WORLD_TRUTH"]["entities"]}
    fk = A.fact_key_map(rec)
    phrases = []
    for i in ro["reveals"]:
        q = question_phrase(rec, fk[i], ents)
        if q not in phrases:
            phrases.append(q)
    return "ask " + " and ".join(phrases)


def action_text(rec: dict, a: dict) -> str:
    ents = {e["id"]: e for e in rec["WORLD_TRUTH"]["entities"]}
    nm = lambda eid: (ents[eid]["name"] if ents[eid]["type"] == "AGENT" else f"the {ents[eid]['name']}")  # noqa: E731
    g, t = a["args"], a["type"]
    if t == "MOVE":
        return f"move from {nm(g['src'])} to {nm(g['dst'])}"
    if t == "TAKE":
        return f"take {nm(g['obj'])} from {nm(g['source'])}" + ("" if g["source"] == g["at"] else f" at {nm(g['at'])}")
    if t == "DROP":
        return f"drop {nm(g['obj'])} into {nm(g['target'])}" if g["target"] != g["at"] else f"drop {nm(g['obj'])} at {nm(g['at'])}"
    if t == "TRANSFER":
        return f"hand {nm(g['obj'])} to {nm(g['to'])} at {nm(g['at'])}"
    if t in ("OPEN", "CLOSE", "ACTIVATE", "DEACTIVATE"):
        return f"{ACTION_WORD[t]} {nm(g['target'])} at {nm(g['at'])}"
    return "wait one tick"


# ------------------------------------------------------------------------------------------------ section content
def sections(st: R) -> dict:
    rec = st.rec
    wt, ob, ip, ap = rec["WORLD_TRUTH"], rec["OBSERVATION"], rec["INFORMATION_POLICY"], rec["ACTION_POLICY"]
    fk = A.fact_key_map(rec)
    ents = st.ents
    intro = [e for e in wt["entities"] if e["introduced"]]
    by_type: dict = {}
    for e in sorted(intro, key=lambda e: e["name"]):
        by_type.setdefault(e["type"], []).append(e)
    setting = []
    for typ, label in (("LOCATION", "places"), ("AGENT", "people"), ("OBJECT", "items"), ("CONTAINER", "containers"), ("SWITCH", "devices")):
        if typ in by_type:
            setting.append(f"the {label} are " + ", ".join(st.nm(e["id"]) for e in by_type[typ]))
    acting = st.ents[wt["actor"]]["name"]
    setting.append(f"you act as {acting}")
    for e in sorted(intro, key=lambda e: e["id"]):
        for al in e["aliases"]:
            setting.append(st.pick("ALIAS").format(n=st.nm(e["id"]), al=al))
    hidden = set(ob["hidden_facts"])
    sched_ids = {s["fact"]["id"]: s for s in wt["scheduled"]}
    facts = []
    order = sorted((f for f in wt["state"] if f["id"] not in hidden), key=lambda f: (f["pred"], f["args"]))
    st.r.shuffle(order)
    for f in order:
        facts.append(st.fact_sentence(F.key(f)))
        st.rendered.append(f["id"])
    for s in sorted(wt["scheduled"], key=lambda s: (s["valid_from"], s["fact"]["id"])):
        if s["fact"]["id"] in hidden:
            continue
        k = F.key(s["fact"])
        if s["valid_from"] > 0:
            facts.append(st.pick("SCHED").format(t=s["valid_from"], e=st.nm(k[1]), v=VALUE_WORD[k[3]]))
        else:
            facts.append(st.pick("SCHED_UNTIL").format(u=s["valid_to"], e=st.nm(k[1]), v=VALUE_WORD[k[3]]))
        st.rendered.append(s["fact"]["id"])
    reports = []
    for rp in ob["reports"]:
        reports.append(st.pick("REPORT").format(ch=rp["channel"], f=st.fact_sentence(fk[rp["fact_id"]]), p=rp["confidence_pct"]))
    rules = []
    for g in wt["transition_system"]["gates"]:
        rules.append(st.pick("GATE").format(a=st.nm(g["edge"][0]), b=st.nm(g["edge"][1]), sw=st.nm(g["cond"][0]), v=VALUE_WORD[g["cond"][2]]))
    rules.append("every action takes one tick and waiting changes nothing else")
    rules.append("action costs: " + ", ".join(f"{ACTION_WORD[a]} {c}" for a, c in sorted(ap["action_costs"].items())))
    policy = []
    for rid in sorted(ip["requestable"]):
        k = fk[rid]
        if all(ents[x]["introduced"] for x in _entity_args(k)):
            q = question_phrase(rec, k, ents)
            line = f"you may ask {q}"
            if line not in policy:
                policy.append(line)
    for rid in sorted(ip["non_requestable"]):
        k = fk[rid]
        if all(ents[x]["introduced"] for x in _entity_args(k)):
            q = question_phrase(rec, k, ents)
            line = f"nobody can tell you {q}"
            if line not in policy:
                policy.append(line)
    for a, v in sorted(ap["permissions"].items()):
        if not v["permitted"]:
            policy.append(f"you are not permitted to {ACTION_WORD[a]} ({v['authority']})")
    for rule in ap["escalation_rules"]:
        if rule["kind"] == "MAX_PLAN_DEPTH":
            policy.append(f"escalate if the plan needs more than {rule['limit']} steps")
        elif rule["kind"] == "COST_LIMIT":
            policy.append(f"escalate if the plan costs more than {rule['limit']}")
        elif rule["kind"] == "ACTION_TYPE_REQUIRES_TIER":
            policy.append(f"escalate before any {ACTION_WORD[rule['action_type']]} step")
        elif rule["kind"] == "CONFIRM_UNCERTAIN":
            policy.append(f"escalate if a fact you rely on is only reported with confidence below {rule['min_confidence_pct']}%")
    policy.append("ask only for what you need; decline when it cannot be obtained")
    goal = [goal_sentence(st, wt["goal"], ob["goal_mentions"])]
    return {"setting": setting, "facts": facts, "reports": reports, "rules": rules, "policy": policy, "goal": goal}


def _entity_args(k: tuple) -> list:
    if k[0] == "STATE":
        return [k[1]]
    if k[0] == "REL":
        return [k[1], k[3]]
    return list(k[1:])


def goal_sentence(st: R, goal: dict, mentions: list) -> str:
    surf = {}
    for m in mentions:
        surf.setdefault(m["role"], []).append(m["surface"])
    p, a = goal["pred"], goal["args"]
    s0 = surf.get("SUBJECT", [""])[0]
    t0 = (surf.get("TARGET") or [""])[0]
    if p == "AT":
        return f"get {s0} to {t0}" if not st.ents.get(a[0], {}).get("type") == "AGENT" else f"go to {t0}"
    if p == "HOLDS":
        return f"have {s0} hold {t0}"
    if p == "CONTAINS":
        return f"put {t0} into {s0}"
    if p == "STATE":
        return f"make {s0} {VALUE_WORD[a[2]]}"
    if p in ("CONNECTED", "BLOCKED"):
        return f"make {s0} " + ("connect to " if p == "CONNECTED" else "prohibited from ") + t0
    return f"make {s0} related to {t0}"


# ------------------------------------------------------------------------------------------------ layouts
HEAD = {"setting": "Setting", "facts": "Facts", "reports": "Reports", "rules": "Rules", "policy": "Policy", "goal": "Goal"}


def _cap(x: str) -> str:
    return x[:1].upper() + x[1:]


def compose(st: R, secs: dict) -> tuple[str, tuple]:
    lay, order = st.fam["layout"], st.fam["order"]
    out: list[str] = []
    goal_span = (0, 0)

    def emit(line: str, is_goal=False):
        nonlocal goal_span
        start = sum(len(x) + 1 for x in out)
        out.append(line)
        if is_goal:
            goal_span = (start, start + len(line))

    counter = 0
    for name in order:
        items = secs[name]
        if not items:
            continue
        g = name == "goal"
        if lay == "prose":
            emit(". ".join(_cap(i) for i in items) + ".", g)
        elif lay == "bullets":
            emit(f"{HEAD[name]}:")
            for i in items:
                emit(f"- {i}", g)
        elif lay == "numbered":
            emit(f"{HEAD[name]}")
            for n, i in enumerate(items, 1):
                emit(f"{n}. {_cap(i)}", g)
        elif lay == "tagged":
            for i in items:
                emit(f"{name.upper()}: {i}", g)
        elif lay == "telegraph":
            emit(f"{name}: " + "; ".join(items), g)
        elif lay == "briefing":
            for i in items:
                emit(f"Briefing ({name}) {i}.", g)
        elif lay == "log":
            for i in items:
                counter += 1
                emit(f"[{counter:03d}] {i}", g)
        elif lay == "memo":
            emit(f"{name.upper()} --")
            for i in items:
                emit(f"  {_cap(i)}.", g)
        elif lay == "checklist":
            emit(f"{HEAD[name]} checklist")
            for i in items:
                emit(f"[ ] {i}", g)
        elif lay == "firstperson":
            for i in items:
                emit(f"I note that {i}." if name in ("facts", "setting", "reports") else (f"I must {i}." if name == "goal" else f"I am told: {i}."), g)
        elif lay == "table":
            emit(f"| {HEAD[name]} |")
            emit("|---|")
            for i in items:
                emit(f"| {i} |", g)
        elif lay == "question":
            if name == "goal":
                emit(f"Question: what should I do next in order to {items[0]}?", True)
            else:
                emit(f"{HEAD[name]} / " + " | ".join(items))
        else:
            raise ValueError(lay)
    return "\n".join(out), goal_span


def render(rec: dict, family: str, seed=0) -> dict:
    """Returns {text, family, rendered_fact_ids, goal_mention_span}. Does not modify the record."""
    st = R(rec, family, seed)
    secs = sections(st)
    text, (gs, ge) = compose(st, secs)
    ment = rec["OBSERVATION"]["goal_mentions"]
    spans = []
    cursor = gs
    for m in ment:
        i = text.find(m["surface"], cursor, ge) if ge > gs else text.find(m["surface"])
        if i >= 0:
            spans.append({"surface": m["surface"], "role": m["role"], "span": [i, i + len(m["surface"])]})
            cursor = i + len(m["surface"])
    return {"text": text, "family": family, "rendered_fact_ids": sorted(st.rendered), "mention_spans": spans}


def entity_target(rec: dict, rendering: dict) -> dict:
    """The `entity` target: the goal subject mention resolved against the alias table (an ambiguous or unbound surface resolves to a list or to none)."""
    ob = rec["OBSERVATION"]
    subj = next((m for m in rendering["mention_spans"] if m["role"] == "SUBJECT"), None)
    if not subj:
        return {"value": None, "witness": None}
    ids = ob["aliases"].get(subj["surface"], [])
    return {"value": {"surface": subj["surface"], "entities": ids}, "witness": {"mention_span": subj["span"], "surface": subj["surface"], "alias_binding": ids}}
