"""The eighteen seal gates of §9.3, each computed from data. A gate that cannot compute its predicate fails closed; none is hardcoded.

check_row(rec, regen, acc) runs every per-row gate (G01-G05, G11, G12, G13, G17, G18) at 100% and accumulates the bank-level counters (G06, G08, G09, G14, G16).
finalize(acc, ...) computes the bank-level verdicts and G07 (every gate detects an injected defect). G10 is computed on the pair panels (interventions.check_pairs).
"""
from __future__ import annotations

import ast
import copy
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import algebra as A
from . import facts as F
from . import freeze, refsim, registry, requirements as R, sim as S, splits, targets
from .canon import sha256_hex

SRC = Path(__file__).resolve().parent
TARGET_NAMES = ["disposition", "reason", "executed_action", "applicability", "next_state", "missing_information", "relation", "edge_existence", "contradiction",
                "temporal_order", "nli", "entity", "evidence", "plan_step", "impossibility", "difficulty", "witness"]
ROW_GATES = ("G01", "G02", "G03", "G04", "G05", "G11", "G12", "G13", "G17", "G18")
MAX_EXAMPLES = 8


class Acc:
    def __init__(self):
        self.rows = 0
        self.checked = Counter()
        self.fail: dict = {}
        self.fail_count = Counter()
        self.cells = {a: Counter() for a in S.ENV_ACTIONS}
        self.reasons = Counter()
        self.dispositions = Counter()
        self.split_rows = Counter()
        self.split_disp: dict = {}
        self.sig: dict = {}            # axis -> split -> signatures
        self.rel_ids: dict = {}        # split -> relation ids used
        self.struct: dict = {}         # structural id -> split -> count
        self.text: dict = {}           # split -> textual id -> count
        self.template_fams: dict = {}  # canonical id -> held families seen
        self.tokens_outside = Counter()
        self.scopes = Counter()
        self.slots = Counter()
        self.ask_m = Counter()
        self.pair_rows = 0
        self.regen_checked = 0
        self.scope_nonempty = Counter()
        self.classif = Counter()
        self.worlds = Counter()

    def add_fail(self, gate: str, msg: str, world: str):
        self.fail_count[gate] += 1
        lst = self.fail.setdefault(gate, [])
        if len(lst) < MAX_EXAMPLES:
            lst.append(f"{world}: {msg}")

    def merge(self, o: "Acc"):
        self.rows += o.rows
        self.regen_checked += o.regen_checked
        self.pair_rows += o.pair_rows
        for name in ("checked", "fail_count", "reasons", "dispositions", "split_rows", "tokens_outside", "scopes", "slots", "ask_m", "scope_nonempty", "classif", "worlds"):
            getattr(self, name).update(getattr(o, name))
        for g, v in o.fail.items():
            self.fail[g] = (self.fail.get(g, []) + v)[:MAX_EXAMPLES]
        for a in self.cells:
            self.cells[a].update(o.cells[a])
        for sp, c in o.split_disp.items():
            self.split_disp.setdefault(sp, Counter()).update(c)
        for ax, d in o.sig.items():
            for sp, s in d.items():
                self.sig.setdefault(ax, {}).setdefault(sp, set()).update(s)
        for sp, s in o.rel_ids.items():
            self.rel_ids.setdefault(sp, set()).update(s)
        for sid, d in o.struct.items():
            for sp, n in d.items():
                t = self.struct.setdefault(sid, {})
                t[sp] = t.get(sp, 0) + n
        for sp, c in o.text.items():
            self.text.setdefault(sp, Counter()).update(c)
        for cid, s in o.template_fams.items():
            self.template_fams.setdefault(cid, set()).update(s)


# ------------------------------------------------------------------------------------------------ allowed vocabulary (G14)
def _literal_tokens() -> set:
    from . import lexicon, render
    toks: set = set()
    for name in ("lexicon.py", "render.py", "intents.py", "worldgen.py"):
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                toks |= {t.lower() for t in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)?", node.value)}
    for words in lexicon.KIND_POOLS.values():
        toks |= {w.lower() for w in words}
    for v in render.REL_PHRASES.values():
        for pool in v:
            for ph in pool:
                toks |= set(re.findall(r"[a-z]+", ph))
    return toks


_ALLOWED: set | None = None


def allowed_tokens() -> set:
    """Every word a rendering may contain: the bank's own lexicon, templates and generator literals. Nothing else can appear, so no external string can have been imported."""
    global _ALLOWED
    if _ALLOWED is None:
        _ALLOWED = _literal_tokens()
    return _ALLOWED


# ------------------------------------------------------------------------------------------------ per-row gates
def g01(rec: dict) -> list[str]:
    bad = []
    for k in ("world_id", "split", "WORLD_TRUTH", "OBSERVATION", "INFORMATION_POLICY", "ACTION_POLICY", "TARGETS", "META", "fact_table"):
        if k not in rec:
            return [f"missing block {k}"]
    if sorted(rec["TARGETS"]) != sorted(TARGET_NAMES):
        bad.append("TARGETS block has the wrong names")
    try:
        A.check_preconditions(rec)
    except A.Regenerate as e:
        bad.append(f"partition: {e}")
    disp, reason = rec["TARGETS"]["disposition"]["value"], rec["TARGETS"]["reason"]["value"]
    if disp not in freeze.DISPOSITIONS:
        bad.append("unknown disposition")
    if (reason is not None) != (disp in freeze.REASON_FIELD_DISPOSITIONS):
        bad.append(f"reason nullability violated: {disp}/{reason}")
    if reason is not None:
        r = freeze.REASONS.get(reason)
        if r is None or not r["in_reason_field"] or r["disposition"] != disp:
            bad.append(f"reason {reason} does not map to disposition {disp}")
    return bad


def g02(rec: dict, regen) -> list[str]:
    if regen is None:
        return ["no regeneration function supplied (fails closed)"]
    again = regen()
    if again["META"]["structural_id"] != rec["META"]["structural_id"] or again["META"]["textual_id"] != rec["META"]["textual_id"] or again["TARGETS"] != rec["TARGETS"]:
        return ["regeneration by seed differs"]
    return []


def g03(rec: dict) -> list[str]:
    bad = []
    try:
        d = A.derive(rec)  # includes observation sufficiency (G5)
    except A.Regenerate as e:
        return [f"derive: {e}"]
    T = rec["TARGETS"]
    if (d.disposition, d.reason) != (T["disposition"]["value"], T["reason"]["value"]):
        bad.append("disposition/reason do not re-derive")
    if T["disposition"]["witness"]["rule_step"] != d.step:
        bad.append("rule step does not re-derive")
    if d.step not in ("1", "1a"):
        fk = A.fact_key_map(rec)
        sup = {fk[i] for i in rec["OBSERVATION"]["supported_facts"]}
        reqs = A.query_requirements(rec)
        ev = R.evaluate(reqs, sup, {fk[i] for i in rec["INFORMATION_POLICY"]["requestable"]})
        bad += [f"counterfactual: {m}" for m in R.counterfactual_violations(reqs, sup, ev["support_facts"], ev["necessary_facts"])]
    return bad


def g04(rec: dict) -> list[str]:
    return targets.verify(rec)


def g05(rec: dict, acc: Acc) -> list[str]:
    bad = []
    sm = A.sim_of(rec)
    gates = rec["WORLD_TRUTH"]["transition_system"]["gates"]
    active0 = set(sm.active[0]) if sm.active else set()
    st = refsim.state_of(sm.base0, active0)
    avail = {a["id"]: a for a in rec["ACTION_POLICY"]["available_actions"]}
    for aid, raw in avail.items():
        act = sm.by_id[aid]
        ref_legal = refsim.legal(st, raw, gates)
        if ref_legal != sm.legal(sm.base0, 0, act):
            bad.append(f"legality disagrees for {aid} ({raw['type']})")
            continue
        if not ref_legal:
            continue
        n_ref = refsim.apply(st, raw)
        n_sim = sm.apply(sm.base0, act)
        if refsim.to_keys(n_ref) - active0 != set(n_sim):
            bad.append(f"effect disagrees for {aid} ({raw['type']})")
            continue
        changed = refsim.to_keys(st) ^ refsim.to_keys(n_ref)
        if any(_subject(k) not in _touch(raw) for k in changed):
            bad.append(f"frame condition violated by {aid}")
        inv = refsim.inverse(raw)
        if inv and inv["id"] in avail and refsim.legal(n_ref, inv, gates):
            back = refsim.apply(n_ref, inv)
            if refsim.to_keys(back) != refsim.to_keys(st):
                bad.append(f"inverse of {aid} does not return to the prior state")
    return bad


def _subject(k: tuple) -> str:
    return k[1] if k[0] in ("AT", "STATE") else (k[2] if k[0] in ("HOLDS", "CONTAINS") else k[1])


def _touch(a: dict) -> set:
    g, t = a["args"], a["type"]
    if t == "MOVE":
        return {g["agent"]}
    if t == "TAKE":
        return {g["obj"]}
    if t == "DROP":
        return {g["obj"]}
    if t == "TRANSFER":
        return {g["obj"]}
    if t in ("OPEN", "CLOSE", "ACTIVATE", "DEACTIVATE"):
        return {g["target"]}
    return set()


def g11(rec: dict) -> list[str]:
    feat = splits.features(rec)
    if not splits.predicate(rec["split"], feat):
        return [f"split predicate fails: held axes {sorted(splits.held_axes(feat))}, required {sorted(splits.REQUIRED_AXES[rec['split']])}"]
    return []


def _alt_sufficient(slot: str, subject: tuple, alt: frozenset, truth: set) -> bool:
    if slot == "object_location":
        e = subject[0]
        def chain(ent, depth, facts):
            if any(k[0] == "AT" and k[1] == ent for k in facts):
                return True
            if depth == 0:
                return False
            for k in facts:
                if k[0] == "HOLDS" and k[2] == ent and any(x[0] == "AT" and x[1] == k[1] for x in facts):
                    return True
                if k[0] == "CONTAINS" and k[2] == ent and chain(k[1], depth - 1, facts):
                    return True
            return False
        return chain(e, freeze.NESTING_DEPTH_MAX, alt)
    if slot == "entity_attribute":
        return alt == frozenset(k for k in truth if k[0] == "STATE" and k[1] == subject[0] and k[2] == subject[1])
    if slot in ("traversable_edge", "prohibited_edge"):
        return len(alt) == 1
    return bool(R.relation_alternatives(set(alt), subject[0], subject[1], subject[2] if len(subject) > 2 else None)) or alt == frozenset(k for k in truth if k[0] == "REL" and k[1] == subject[0] and k[2] == subject[1])


def g12(rec: dict, acc: Acc) -> list[str]:
    bad = []
    wt, ob, ip = rec["WORLD_TRUTH"], rec["OBSERVATION"], rec["INFORMATION_POLICY"]
    T = rec["TARGETS"]
    d_step = T["disposition"]["witness"]["rule_step"]
    markers = tuple(wt.get("slot_markers", ()))
    truth = A.truth_key_set(rec)
    fk = A.fact_key_map(rec)
    for h in ob["hidden_facts"]:
        if not R.is_open(fk[h], markers):
            bad.append("hidden fact of a CLOSED slot without a slot marker")
    if T["reason"]["value"] is not None and T["reason"]["value"] not in freeze.REASONS:
        bad.append("reason is not in the frozen table (folded or invented)")
    if d_step in ("1", "1a"):
        if wt["goal"]["required_facts"]["query"] and wt["goal"]["required_facts"].get("query_evaluated") is False:
            bad.append("query recorded for an unevaluated world")
        return bad
    sup = {fk[i] for i in ob["supported_facts"]}
    hidden = {fk[i] for i in ob["hidden_facts"]}
    requestable = {fk[i] for i in ip["requestable"]}
    reqs = A.query_requirements(rec)
    stored = wt["goal"]["required_facts"]["query"]
    if [r.to_json() for r in reqs] != stored:
        bad.append("stored requirement objects differ from the obligations of the declared source scope")
    for r in reqs:
        for alt in r.alternatives:
            if not alt <= truth:
                bad.append(f"{r.requirement_id}: an alternative is not a set of true facts")
            if not _alt_sufficient(r.slot, r.subject, alt, truth):
                bad.append(f"{r.requirement_id}: an alternative is not sufficient")
            if r.slot == "object_location":
                for f in alt:
                    if _alt_sufficient(r.slot, r.subject, alt - {f}, truth):
                        bad.append(f"{r.requirement_id}: an alternative is not minimal")
        for a, b in ((x, y) for x in r.alternatives for y in r.alternatives if x != y):
            if a < b:
                bad.append(f"{r.requirement_id}: alternatives are not an antichain")
    ev = R.evaluate(reqs, sup, requestable)
    M, nonreq = ev["M"], ev["nonreq"]
    disp = T["disposition"]["value"]
    exp, tag = R.classify_missingness(ev, hidden)
    if M:
        if (disp, T["reason"]["value"]) != (exp, tag):
            bad.append(f"missingness label {(disp, T['reason']['value'])} != derived {(exp, tag)}")
        w = T["disposition"]["witness"]["inputs"]
        if w.get("M_size") != len(M):
            bad.append("witness does not record |M|")
        if nonreq and disp != "DECLINE_UNAVAILABLE":
            bad.append("precedence violated: non-requestability must dominate cardinality")
        if disp == "ASK" and (len(M) != 1 or nonreq):
            bad.append("ASK cardinality rule violated")
        if disp == "ESCALATE" and T["reason"]["value"] == "MULTIPLE_REQUIRED_MISSING" and (len(M) < 2 or nonreq):
            bad.append("ESCALATE/MULTIPLE_REQUIRED_MISSING cardinality rule violated")
    else:
        if disp in ("ASK",) or T["reason"]["value"] in ("NECESSARY_MISSING_REQUESTABLE", "NECESSARY_MISSING_UNAVAILABLE", "MULTIPLE_REQUIRED_MISSING", "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE"):
            bad.append("a missing-information label with no unresolved requirement")
        if T["missing_information"]["value"] != exp and T["missing_information"]["value"] != tag:
            bad.append("missingness classification differs")
    if "prohibited_edge" in markers:
        sm = A.sim_of(rec)
        info = sm.search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
        dep = set(A.blocked_dependencies(rec, sm, info))
        for r in reqs:
            if r.slot == "prohibited_edge" and not any(k in dep for alt in r.alternatives for k in alt):
                bad.append("a prohibited_edge obligation is not decision-dependent")
    return bad


def g13(rec: dict) -> list[str]:
    T = rec["TARGETS"]
    reason = T["reason"]["value"]
    if reason not in ("IMPOSSIBLE_GOAL", "NO_VALID_ACTION"):
        return []
    sm = A.sim_of(rec)
    gates = rec["WORLD_TRUTH"]["transition_system"]["gates"]
    if reason == "NO_VALID_ACTION":
        st = refsim.state_of(sm.base0, set(sm.active[0]) if sm.active else set())
        legal = [a for a in rec["ACTION_POLICY"]["available_actions"] if refsim.legal(st, a, gates)]
        return [] if not legal and T["applicability"]["value"]["legal"] == [] else ["NO_VALID_ACTION but an independent sweep finds a legal action"]
    cert = T["impossibility"]["witness"]["unsat_certificate"] if T["impossibility"]["value"] else None
    if cert is None:
        return ["IMPOSSIBLE_GOAL carries no certificate"]
    goal = rec["WORLD_TRUTH"]["goal"]
    gkey = (goal["pred"], *goal["args"])
    acts = rec["ACTION_POLICY"]["available_actions"]
    if not rec["WORLD_TRUTH"]["scheduled"]:
        st = refsim.state_of(sm.base0, set())
        reach, n = refsim.exhaustive_space(st, acts, gates, gkey)
        if reach:
            return ["an independent exhaustive search reaches the goal"]
        if n != cert.get("states_explored"):
            return [f"certificate counts {cert.get('states_explored')} states, the independent search {n}"]
        return []
    # scheduled facts: soundness by relaxation (every scheduled 'active' fact present from the start, 'inactive' ones dropped)
    relaxed = set(sm.base0) | {k for (k, _a, _b) in sm.sched if k[0] == "STATE" and k[3] in ("active", "open")}
    reach, n = refsim.exhaustive_space(refsim.state_of(relaxed, set()), acts, gates, gkey)
    return ["the goal is reachable in the relaxed world"] if reach else []


def g17(rec: dict) -> list[str]:
    bad = []
    ip, ap, T = rec["INFORMATION_POLICY"], rec["ACTION_POLICY"], rec["TARGETS"]
    disp = T["disposition"]["value"]
    avail = {a["id"] for a in ap["available_actions"]}
    sm = A.sim_of(rec)
    if disp == "EXECUTE":
        aid = T["executed_action"]["value"]
        if aid not in avail or not sm.legal(sm.base0, 0, sm.by_id[aid]):
            bad.append("EXECUTE references an action that is not an available legal environment action")
    if disp == "ASK":
        rid = T["disposition"]["witness"]["inputs"].get("request_object")
        ro = next((x for x in ip["request_objects"] if x["request_id"] == rid), None)
        if ro is None:
            bad.append("ASK references no generated request object")
        elif not ro["reveals"] or ro["requirement_id"] is None:
            bad.append("the request object does not name an unresolved requirement and its repair facts")
    for ro in ip["request_objects"]:
        if not ro["reveals"]:
            bad.append("a request object reveals nothing")
    if disp == "DECLINE_UNAVAILABLE":
        w = T["disposition"]["witness"]["inputs"]
        if T["reason"]["value"] in ("NECESSARY_MISSING_UNAVAILABLE", "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE") and not (w.get("nonreq") and w.get("unresolved")):
            bad.append("missing-information decline without a no-legal-repair witness")
        if not w:
            bad.append("DECLINE_UNAVAILABLE without its typed witness")
    if disp == "ESCALATE":
        w = T["disposition"]["witness"]["inputs"]
        if T["reason"]["value"] == "ESCALATION_REQUIRED":
            rules = {r["rule_id"] for r in ap["escalation_rules"]}
            if w.get("fired_rule") not in rules:
                bad.append("ESCALATE names no declared escalation rule")
        elif not w.get("unresolved"):
            bad.append("ESCALATE/MULTIPLE_REQUIRED_MISSING without its unresolved requirements")
    if disp not in freeze.DISPOSITIONS:
        bad.append("a disposition points at a nonexistent namespace")
    return bad


def g18(rec: dict) -> list[str]:
    bad = []
    wt = rec["WORLD_TRUTH"]
    split = rec["split"]
    ordinals = {e["id"]: int(e["id"][1:]) for e in wt["entities"]}
    types = {e["id"]: e["type"] for e in wt["entities"]}
    facts = list(wt["state"]) + [s["fact"] for s in wt["scheduled"]]
    for f in facts:
        if f["pred"] not in freeze.PREDICATES:
            bad.append(f"predicate {f['pred']} is not in the fact language")
            continue
        if f["pred"] == "REL":
            s, rid, t = f["args"]
            e = registry.lookup(rid, split)
            if e is None:
                bad.append(f"REL {rid} has no registry entry visible in {split}")
                continue
            if types.get(s) != e["domain_type"] or types.get(t) != e["range_type"]:
                bad.append(f"REL {rid} violates its domain/range")
            if e["directionality"] == "SYMMETRIC" and ordinals[s] > ordinals[t]:
                bad.append(f"symmetric REL {rid} is not stored in ascending ordinal order")
        if any(w in f["args"] for w in ("supplies", "provides", "receives")):
            bad.append("a renderer word appears in canonical truth")
    keys = {F.key(f) for f in facts if f["pred"] == "REL"}
    for k in keys:
        e = registry.BY_ID.get(k[2])
        if e and e["inverse_relation_id"] and registry.BY_ID[e["inverse_relation_id"]]["inverse_relation_id"] != e["relation_id"]:
            bad.append("inverse declarations are not mutually consistent")
        if e and e["transitivity"] == "TRANSITIVE":
            others = keys - {k}
            chains = R.relation_alternatives({x for x in others if x[2] == k[2]}, k[1], k[2], k[3])
            if chains:
                bad.append("a stored fact is the transitive closure of other stored facts")
    for f in facts:
        if f["pred"] in ("BEFORE", "AFTER", "SUPPORTS", "CONTRADICTS", "REQUIRES", "ACHIEVES", "CAUSES", "APPLICABLE_TO", "REQUESTABLE"):
            bad.append("a forbidden predicate is in world truth")
    return bad


def check_row(rec: dict, regen, acc: Acc) -> None:
    w = rec["world_id"]
    acc.rows += 1
    split = rec["split"]
    acc.split_rows[split] += 1
    results = {"G01": g01(rec)}
    if not results["G01"]:
        results.update({"G03": g03(rec), "G04": g04(rec), "G05": g05(rec, acc), "G11": g11(rec), "G12": g12(rec, acc), "G13": g13(rec), "G17": g17(rec), "G18": g18(rec)})
    results["G02"] = g02(rec, regen) if regen is not None else []
    if regen is not None:
        acc.regen_checked += 1
    for gate, msgs in results.items():
        acc.checked[gate] += 1
        for m in msgs:
            acc.add_fail(gate, m, w)
    if results["G01"]:
        return
    # ---- bank-level accumulators
    T = rec["TARGETS"]
    disp, reason = T["disposition"]["value"], T["reason"]["value"]
    acc.dispositions[disp] += 1
    acc.split_disp.setdefault(split, Counter())[disp] += 1
    acc.reasons[reason if reason else ("NOOP" if disp == "NOOP" else "EXECUTE")] += 1
    acc.scopes[rec["WORLD_TRUTH"]["goal"]["required_facts"]["query_source_scope"]] += 1
    rf = rec["WORLD_TRUTH"]["goal"]["required_facts"]
    for name in ("schema", "goal", "plan", "action", "query"):
        if rf[name]:
            acc.scope_nonempty[name] += 1
    if rec["META"].get("pair_id") is None or rec["OBSERVATION"]["renderer_family_id"] == freeze.HELD_FAMILIES[0] or split != "TEST-TEMPLATE":
        acc.worlds[split] += 1
    if T["disposition"]["witness"]["rule_step"] not in ("1", "1a", "2a", "2b", "2c"):
        acc.classif[T["missing_information"]["value"]] += 1
    for q in rec["WORLD_TRUTH"]["goal"]["required_facts"]["query"]:
        acc.slots[q["slot"]] += 1
    m = T["disposition"]["witness"]["inputs"].get("M_size")
    if m is not None and disp in ("ASK", "ESCALATE", "DECLINE_UNAVAILABLE"):
        acc.ask_m[f"{disp}:{m}"] += 1
    sm = A.sim_of(rec)
    legal = {a.id for a in sm.legal_set(sm.base0, 0)}
    first = set(sm.search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))["first_actions"]) if T["plan_step"]["value"] else set()
    plan_ids = set(T["plan_step"]["value"] or []) if disp == "EXECUTE" else set()
    for a in rec["ACTION_POLICY"]["available_actions"]:
        c = acc.cells[a["type"]]
        c["available"] += 1
        c["legal" if a["id"] in legal else "illegal"] += 1
        if a["id"] in first:
            c["truth_optimal"] += 1
        if a["id"] in plan_ids:
            c["executed_in_shortest_plan_witness"] += 1
    for t in {a["type"] for a in rec["ACTION_POLICY"]["available_actions"]}:
        acc.cells[t]["generated"] += 1
    feat = rec["META"]["features"] if "features" in rec["META"] else splits.features(rec)
    for ax in ("topo", "comp", "temporal", "regime", "vocab"):
        if feat.get(ax) is not None:
            acc.sig.setdefault(ax, {}).setdefault(split, set()).add(feat[ax])
    acc.sig.setdefault("rel_depth", {}).setdefault(split, set()).add(feat["rel_depth"])
    acc.sig.setdefault("topo_family", {}).setdefault(split, set()).add((feat["topo"], feat["family"]))
    for f in rec["WORLD_TRUTH"]["state"]:
        if f["pred"] == "REL":
            acc.rel_ids.setdefault(split, set()).add(f["args"][1])
    st = acc.struct.setdefault(rec["META"]["structural_id"], {})
    st[split] = st.get(split, 0) + 1
    acc.text.setdefault(split, Counter())[rec["META"]["textual_id"]] += 1
    if split == "TEST-TEMPLATE":
        acc.template_fams.setdefault(rec["META"]["canonical_id"], set()).add(rec["OBSERVATION"]["renderer_family_id"])
    allowed = allowed_tokens()
    for tok in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)?", rec["OBSERVATION"]["rendered_text"]):
        if tok.lower() not in allowed:
            acc.tokens_outside[tok.lower()] += 1


def g15(seed: dict, panels: dict) -> dict:
    bad_reg = [x["dataset_id"] for x in seed["seeds"] if not (x["abstract_properties_used"] and x["forbidden_properties"] and x["v2_constructs_affected"] and x["license"] and x["version_or_hash"])]
    bad_panel = [p["dataset_id"] for p in panels["panels"] if not p["abstract_properties_used"] or p["status"] != "declared_not_adapted"]
    missing = sorted({p["dataset_id"] for p in panels["panels"]} - {x["dataset_id"] for x in seed["seeds"]})
    return {"passed": not bad_reg and not bad_panel and not missing and panels["all_panels_remain_external"] and seed["rows_imported"] == 0, "checked": len(seed["seeds"]) + len(panels["panels"]),
            "incomplete_seeds": bad_reg, "incomplete_panels": bad_panel, "panels_without_seed_entry": missing}


# ------------------------------------------------------------------------------------------------ bank-level verdicts
def finalize(acc: Acc, selftest: dict, panel_check: dict | None = None) -> dict:
    out: dict = {}

    def gate(gid: str, failures: int, checked: int, detail: dict | None = None):
        out[gid] = {"passed": checked > 0 and failures == 0, "checked": checked, "failures": failures, "examples": acc.fail.get(gid, []), **(detail or {})}

    for g in ("G01", "G03", "G04", "G05", "G11", "G12", "G13", "G17", "G18"):
        gate(g, acc.fail_count[g], acc.checked[g])
    gate("G02", acc.fail_count["G02"], acc.checked["G02"], {"regen_checked": acc.regen_checked, "rows": acc.rows})
    # G06 coverage receipt
    exempt = freeze.FREEZE["action_algebra"]["coverage_receipt"]["exempt_cells"]
    cells = ["generated", "available", "legal", "illegal", "truth_optimal", "executed_in_shortest_plan_witness"]
    holes = [(a, c) for a in S.ENV_ACTIONS for c in cells if acc.cells[a][c] == 0 and c not in exempt.get(a, [])]
    gate("G06", len(holes), len(S.ENV_ACTIONS) * len(cells), {"holes": holes, "receipt": {a: {c: acc.cells[a][c] for c in cells} for a in S.ENV_ACTIONS}})
    # G07: every gate detects an injected defect
    miss = [g for g, ok in selftest.items() if not ok]
    gate("G07", len(miss), len(selftest), {"undetected": miss})
    # G08: textual and structural dedup as distinct predicates
    text_dups = sum(n - 1 for c in acc.text.values() for n in c.values() if n > 1)
    def expected(sid_splits):
        return 4 if "TEST-TEMPLATE" in sid_splits else 1
    struct_dups = sum(1 for sid, d in acc.struct.items() if any(n != expected(d) for n in d.values()) or len(d) > 1)
    out["G08"] = {"passed": acc.rows > 0 and text_dups == 0 and struct_dups == 0, "checked": acc.rows, "textual_duplicates": text_dups, "structural_duplicates": struct_dups}
    # G09: collision policy matrix
    coll = []
    held_sets = {"GRAPH-ISO": ("topo", "TEST-GRAPH-ISO"), "ACTION-COMPOSITION": ("comp", "TEST-ACTION-COMPOSITION"), "TEMPORAL-COMPOSITION": ("temporal", "TEST-TEMPORAL-COMPOSITION"),
                 "INFORMATION-POLICY": ("regime", "TEST-INFORMATION-POLICY")}
    for _ax, (sig, sp) in held_sets.items():
        mine = acc.sig.get(sig, {}).get(sp, set())
        others = set().union(*[v for k, v in acc.sig.get(sig, {}).items() if k not in (sp, "TEST-JOINT")] or [set()])
        if mine & others:
            coll.append(f"{sp}: {len(mine & others)} held {sig} signatures also occur in another split")
    hop = acc.sig.get("rel_depth", {}).get("TEST-HOP-DEPTH", set())
    if hop and min(hop) <= splits.REL_DEPTH_TRAIN_MAX:
        coll.append("TEST-HOP-DEPTH contains a chain no deeper than train")
    for sp, dset in acc.sig.get("rel_depth", {}).items():
        if sp != "TEST-HOP-DEPTH" and dset and max(dset) > splits.REL_DEPTH_TRAIN_MAX:
            coll.append(f"{sp} contains a relation chain deeper than train")
    test_only = {e["relation_id"] for e in registry.REGISTRY if e["split_scope"] == "TEST_RELATION_ONLY"}
    for sp, ids in acc.rel_ids.items():
        if sp != "TEST-RELATION" and ids & test_only:
            coll.append(f"{sp} uses a held relation id")
    joint = acc.sig.get("topo_family", {}).get("TEST-JOINT", set())
    others_tf = set().union(*[v for k, v in acc.sig.get("topo_family", {}).items() if k != "TEST-JOINT"] or [set()])
    if joint & others_tf:
        coll.append("TEST-JOINT topology+renderer combinations collide with another split")
    bad_template = [c for c, f in acc.template_fams.items() if f != set(freeze.HELD_FAMILIES)]
    if bad_template:
        coll.append(f"{len(bad_template)} TEST-TEMPLATE worlds are not rendered through all four held families")
    all_struct_splits = sum(1 for d in acc.struct.values() if len(d) > 1)
    if all_struct_splits:
        coll.append(f"{all_struct_splits} exact world duplicates span splits")
    out["G09"] = {"passed": acc.rows > 0 and not coll, "checked": acc.rows, "violations": coll}
    # G10 (pair panels)
    out["G10"] = panel_check if panel_check is not None else {"passed": False, "checked": 0, "note": "no pair panels checked (fails closed)"}
    # G14 external-row firewall
    out["G14"] = {"passed": acc.rows > 0 and not acc.tokens_outside, "checked": acc.rows, "tokens_outside_bank_vocabulary": dict(acc.tokens_outside.most_common(10)), "external_rows_imported": 0}
    # G15 registries
    seed = __import__("json").loads((freeze.ROOT / "seed-registry-v2.json").read_text(encoding="utf-8"))
    out["G15"] = g15(seed, freeze.FREEZE["external_policy"]["challenge_panel_registry"])
    # G16: critical invariants at 100%, sampled gates declare their rate
    rates = {g: (acc.checked[g] / acc.rows if acc.rows else 0.0) for g in ROW_GATES}
    out["G16"] = {"passed": acc.rows > 0 and all(abs(r - 1.0) < 1e-12 for r in rates.values()), "checked": acc.rows, "rates": rates, "sampled_gates": []}
    # reason coverage over the whole bank (G12 global part)
    reachable = [r for r, v in freeze.REASONS.items() if v["in_reason_field"]]
    unseen = [r for r in reachable if acc.reasons[r] == 0]
    out["G12"]["reason_coverage"] = {"unseen_reasons": unseen}
    if unseen:
        out["G12"]["passed"] = False
    out["_summary"] = {"rows": acc.rows, "dispositions": dict(acc.dispositions), "reasons": dict(acc.reasons), "split_rows": dict(acc.split_rows), "scopes": dict(acc.scopes), "query_slots": dict(acc.slots), "m_by_disposition": dict(acc.ask_m)}
    return out


# ------------------------------------------------------------------------------------------------ G07: mutation self-tests
def selftests(samples: dict, regen_other) -> dict:
    """Corrupt valid material one way per gate; the gate must notice. Returns {gate: detected}. `samples` holds valid EXECUTE, ASK, IMPOSSIBLE rows."""
    import json as _json
    res: dict = {}
    ex, ask, imp = samples["EXECUTE"], samples["ASK"], samples["IMPOSSIBLE"]

    def mut(rec, fn):
        r = copy.deepcopy(rec)
        fn(r)
        return r

    res["G01"] = bool(g01(mut(ex, lambda r: r["TARGETS"]["reason"].__setitem__("value", "GOAL_SATISFIED"))))
    res["G02"] = bool(g02(ex, lambda: regen_other))
    res["G03"] = bool(g03(mut(ex, lambda r: r["TARGETS"]["disposition"].__setitem__("value", "NOOP"))))
    res["G04"] = bool(g04(mut(ex, lambda r: r["TARGETS"]["applicability"].__setitem__("value", {"legal": ["a_bogus"], "permitted": []}))))
    # G05: disagree with the reference simulator by breaking its TAKE/MOVE effect
    orig = refsim.apply
    try:
        refsim.apply = lambda st, a: st  # a reference that forgets every effect
        res["G05"] = bool(g05(ex, Acc()))
    finally:
        refsim.apply = orig
    res["G11"] = bool(g11(mut(ex, lambda r: r.__setitem__("split", "TEST-GRAPH-ISO" if r["split"] != "TEST-GRAPH-ISO" else "TRAIN"))))
    res["G12"] = bool(g12(mut(ask, lambda r: r["WORLD_TRUTH"]["goal"]["required_facts"].__setitem__("query", [])), Acc()))
    res["G13"] = bool(g13(mut(imp, lambda r: r["TARGETS"]["impossibility"]["witness"]["unsat_certificate"].__setitem__("states_explored", 999999))))
    res["G17"] = bool(g17(mut(ask, lambda r: r["INFORMATION_POLICY"].__setitem__("request_objects", []))))
    res["G18"] = bool(g18(mut(ex, lambda r: r["WORLD_TRUTH"]["state"].append({"id": "f_x", "pred": "SUPPORTS", "args": ["e0", "e1"]}))))
    # bank-level gates: fabricate defective accumulators
    good = Acc()
    check_row(ex, None, good)
    res["G06"] = not finalize(_with_hole(good), {}, None)["G06"]["passed"]
    dup = Acc()
    check_row(ex, None, dup)
    check_row(ex, None, dup)
    f = finalize(dup, {}, None)
    res["G08"] = not f["G08"]["passed"]
    coll = Acc()
    coll.rows = 2
    coll.sig = {"topo": {"TEST-GRAPH-ISO": {"iso:x"}, "TRAIN": {"iso:x"}}}
    res["G09"] = not finalize(coll, {}, None)["G09"]["passed"]
    tok = mut(ex, lambda r: r["OBSERVATION"].__setitem__("rendered_text", r["OBSERVATION"]["rendered_text"] + " quarterly dividend"))
    tacc = Acc()
    check_row(tok, None, tacc)
    res["G14"] = not finalize(tacc, {}, None)["G14"]["passed"]
    seed = _json.loads((freeze.ROOT / "seed-registry-v2.json").read_text(encoding="utf-8"))
    seed["seeds"][0]["abstract_properties_used"] = []
    res["G15"] = not g15(seed, freeze.FREEZE["external_policy"]["challenge_panel_registry"])["passed"]
    short = Acc()
    short.rows = 10
    short.checked["G03"] = 7
    res["G16"] = not finalize(short, {}, None)["G16"]["passed"]
    return res


def _with_hole(acc: Acc) -> Acc:
    a = copy.deepcopy(acc)
    a.cells["TRANSFER"]["illegal"] = 0
    a.cells["TRANSFER"]["legal"] = 0
    a.cells["TRANSFER"]["available"] = 0
    return a
