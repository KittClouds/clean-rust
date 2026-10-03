"""The requirement/support engine: the single evaluator behind required_facts.query (§3.1, v0.6 ruling C).

A requirement is an obligation (slot, subject) with `support_alternatives`: an antichain of minimal fact sets, each a subset of the world's true facts and sufficient on its own.
satisfied(r) iff some alternative is contained in the supported facts; M is the set of unsatisfied requirements; requestability is evaluated over repairs (alternative minus supported).
Facts here are fact KEYS (tuples); ids are attached at the boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import facts as F
from . import freeze
from . import registry
from .canon import short

MAX_CHAIN = 4  # longest REL chain enumerated for a transitive requirement


@dataclass
class Requirement:
    slot: str
    subject: tuple
    alternatives: list  # list[frozenset[key]]
    scope: str = "PLAN"
    requirement_id: str = field(init=False)

    def __post_init__(self):
        self.requirement_id = "q_" + short([self.slot, list(self.subject), self.scope], 10)

    def to_json(self) -> dict:
        return {"requirement_id": self.requirement_id, "slot": self.slot, "subject": list(self.subject), "required": True,
                "support_alternatives": [sorted(F.fid(k) for k in alt) for alt in self.alternatives]}


# ---------------------------------------------------------------------------------------- slots
def open_slots(markers=()) -> set:
    return set(freeze.OPEN_SLOTS) | set(markers)


def is_open(k: tuple, markers=()) -> bool:
    slot = F.slot_of(k[0])
    if slot == "general_relation":
        e = registry.BY_ID.get(k[2])
        return bool(e and e["required_slot"])
    return slot in open_slots(markers)


def _antichain(alts: list) -> list:
    alts = sorted({frozenset(a) for a in alts}, key=lambda a: (len(a), sorted(a)))
    out = []
    for a in alts:
        if not any(b < a or b == a for b in out):
            out.append(a)
    return out


# ---------------------------------------------------------------------------------------- alternatives (per-slot derivation rules)
def location_alternatives(truth: set, entity: str, depth: int = freeze.NESTING_DEPTH_MAX) -> list:
    alts = []
    for k in truth:
        if k[0] == "AT" and k[1] == entity:
            alts.append(frozenset({k}))
    for k in truth:
        if k[0] == "HOLDS" and k[2] == entity:
            holder = k[1]
            for kk in truth:
                if kk[0] == "AT" and kk[1] == holder:
                    alts.append(frozenset({k, kk}))
    if depth > 0:
        for k in truth:
            if k[0] == "CONTAINS" and k[2] == entity:
                for inner in location_alternatives(truth, k[1], depth - 1):
                    alts.append(frozenset({k}) | inner)
    return _antichain(alts)


def attribute_alternatives(truth: set, entity: str, attr: str) -> list:
    fs = frozenset(k for k in truth if k[0] == "STATE" and k[1] == entity and k[2] == attr)
    return [fs] if fs else []


def edge_alternatives(truth: set, pred: str, a: str, b: str) -> list:
    k = (pred, a, b)
    return [frozenset({k})] if k in truth else []


def relation_alternatives(truth: set, source: str, rid: str, target: str | None) -> list:
    entry = registry.BY_ID[rid]
    rels = [k for k in truth if k[0] == "REL" and k[2] == rid]
    sym = entry["directionality"] == "SYMMETRIC"
    if entry["transitivity"] != "TRANSITIVE" or target is None:
        direct = frozenset(k for k in rels if k[1] == source or (sym and k[3] == source))
        return [direct] if direct else []
    adj: dict = {}
    for (_p, a, _r, b) in rels:
        adj.setdefault(a, []).append(((_p, a, _r, b), b))
        if sym:
            adj.setdefault(b, []).append(((_p, a, _r, b), a))
    alts: list = []

    def walk(node, path, seen):
        if len(path) > MAX_CHAIN:
            return
        for (fk, nxt) in adj.get(node, ()):
            if nxt in seen:
                continue
            if nxt == target:
                alts.append(frozenset(path + [fk]))
            else:
                walk(nxt, path + [fk], seen | {nxt})

    walk(source, [], {source})
    return _antichain(alts)


def alternatives_for(truth: set, slot: str, subject: tuple) -> list:
    if slot == "object_location":
        return location_alternatives(truth, subject[0] if isinstance(subject, tuple) else subject)
    if slot == "entity_attribute":
        return attribute_alternatives(truth, subject[0], subject[1])
    if slot == "traversable_edge":
        return edge_alternatives(truth, "CONNECTED", subject[0], subject[1])
    if slot == "prohibited_edge":
        return edge_alternatives(truth, "BLOCKED", subject[0], subject[1])
    if slot == "general_relation":
        return relation_alternatives(truth, subject[0], subject[1], subject[2] if len(subject) > 2 else None)
    raise ValueError(slot)


# ---------------------------------------------------------------------------------------- obligations
def subject_for(k: tuple, truth: set) -> tuple:
    slot = F.slot_of(k[0])
    if slot == "general_relation":
        entry = registry.BY_ID[k[2]]
        if entry["transitivity"] == "TRANSITIVE":
            return (k[1], k[2], k[3])
        return (k[1], k[2])
    return F.subject_of(k) if isinstance(F.subject_of(k), tuple) else (F.subject_of(k),)


def obligations(truth: set, scope_fact_keys: list, scope: str, markers=()) -> list[Requirement]:
    """Group the open-slot facts of a scope by (slot, subject): one requirement per group. Facts of CLOSED slots create no obligation."""
    groups: dict = {}
    for k in scope_fact_keys:
        if k[0] not in freeze.PREDICATES or not is_open(k, markers):
            continue
        slot = F.slot_of(k[0])
        groups.setdefault((slot, subject_for(k, truth)), None)
    reqs = []
    for (slot, subject) in sorted(groups):
        alts = alternatives_for(truth, slot, subject)
        reqs.append(Requirement(slot, subject, alts, scope))
    return reqs


# ---------------------------------------------------------------------------------------- satisfaction, repairs, requestability
def satisfied(req: Requirement, sup: set) -> bool:
    return any(alt <= sup for alt in req.alternatives)


def repairs(req: Requirement, sup: set) -> list[frozenset]:
    return [alt - sup for alt in req.alternatives]


def legal_repairs(req: Requirement, sup: set, requestable: set) -> list[frozenset]:
    return [r for r in repairs(req, sup) if r <= requestable]


def chosen_repair(req: Requirement, sup: set, requestable: set, cost: dict) -> frozenset | None:
    lr = legal_repairs(req, sup, requestable)
    if not lr:
        return None
    return min(lr, key=lambda r: (sum(cost.get(k, 1) for k in r), len(r), sorted(r)))


def evaluate(reqs: list[Requirement], sup: set, requestable: set, cost: dict | None = None) -> dict:
    """The missingness evaluation of §3.1/§3.2 over unresolved obligations."""
    cost = cost or {}
    M = [r for r in reqs if not satisfied(r, sup)]
    nonreq = [r for r in M if not legal_repairs(r, sup, requestable)]
    support_facts = set().union(*[a for r in reqs for a in r.alternatives]) if reqs else set()
    necessary: set = set()
    for r in reqs:
        complete = [a for a in r.alternatives if a <= sup]
        if complete:
            necessary |= set.intersection(*[set(a) for a in complete])
    return {"M": M, "nonreq": nonreq, "support_facts": support_facts, "necessary_facts": necessary, "requirements": reqs,
            "chosen": {r.requirement_id: chosen_repair(r, sup, requestable, cost) for r in M}}


def classify_missingness(ev: dict, hidden: set) -> tuple[str, str | None]:
    """(disposition-or-NONE, reason-or-classification) per the §3.2 table. M = empty yields a classification, never a reason."""
    M, nonreq = ev["M"], ev["nonreq"]
    if M:
        if nonreq:
            return "DECLINE_UNAVAILABLE", "NECESSARY_MISSING_UNAVAILABLE" if len(M) == 1 else "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE"
        return ("ASK", "NECESSARY_MISSING_REQUESTABLE") if len(M) == 1 else ("ESCALATE", "MULTIPLE_REQUIRED_MISSING")
    irrelevant = [h for h in hidden if h not in ev["support_facts"]]
    return "NONE", "IRRELEVANT_MISSING" if irrelevant else "NO_MISSING_REQUIRED"


# ---------------------------------------------------------------------------------------- counterfactual gate (G03/G12)
def counterfactual_violations(reqs: list[Requirement], sup: set, support_facts: set | None = None, necessary: set | None = None) -> list[str]:
    """The four-part counterfactual deletion gate, applied to the supported set. Returns violations (empty = pass)."""
    bad: list[str] = []
    sat_before = {r.requirement_id: satisfied(r, sup) for r in reqs}
    all_alt_facts = set().union(*[a for r in reqs for a in r.alternatives]) if reqs else set()
    for r in reqs:
        if not sat_before[r.requirement_id]:
            continue
        complete = [a for a in r.alternatives if a <= sup]
        union = set().union(*complete)
        if satisfied(r, sup - union):  # test 1
            bad.append(f"{r.requirement_id}: deleting every complete alternative left it satisfied")
        if len(complete) >= 2:  # test 3: one member of a redundant proof is not irrelevance
            for f in complete[0]:
                if not any(f in other for other in complete[1:]) and not satisfied(r, sup - {f}):
                    bad.append(f"{r.requirement_id}: deleting one redundant-proof fact unsatisfied the requirement")
    for f in sup - all_alt_facts:  # test 2: facts outside every alternative change nothing
        if {r.requirement_id: satisfied(r, sup - {f}) for r in reqs} != sat_before:
            bad.append(f"deleting irrelevant fact {f} changed a requirement")
    nec = necessary if necessary is not None else evaluate(reqs, sup, sup)["necessary_facts"]
    for f in nec:  # test 4: every necessary fact passes its own deletion counterfactual
        if not any(sat_before[r.requirement_id] and not satisfied(r, sup - {f}) for r in reqs):
            bad.append(f"claimed necessary fact {f} does not unsatisfy any requirement")
    for f in sup & all_alt_facts:  # the converse: a fact whose single deletion unsatisfies something must be in `necessary`
        if any(sat_before[r.requirement_id] and not satisfied(r, sup - {f}) for r in reqs) and f not in nec:
            bad.append(f"fact {f} is individually necessary but missing from necessary_facts")
    return bad
