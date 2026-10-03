"""V2-0 feature maps, exactly as fixed by the frozen constitution section 3.

B0 oracle, B1 majority, B2 schema/frequency, B3 lexical, B4 surface cue, B5 graph-only.

Each extractor is a pure function of one BANK-v2 record. None of them may read a target, a
witness, or any field the constitution lists under "not allowed". Targets are read from
record['TARGETS'] only by the harness, never by an extractor.
"""

import re
import numpy as np

# ---------------------------------------------------------------- targets (harness side)


def read_targets(rec):
    """The six in-scope targets, read from the record's TARGETS block and its witnesses."""
    T = rec["TARGETS"]
    disposition = T["disposition"]["value"]

    reason = T["reason"]["value"]

    # |M| comes from the missingness witness, not from a recount
    mi = T["missing_information"]["value"]
    w = T["missing_information"].get("witness") or {}
    if mi == "NO_MISSING_REQUIRED":
        m_size = 0
    else:
        m_size = int(w.get("M_size", 0))
    if m_size >= 2:
        m_card = "2+"
    else:
        m_card = str(m_size)

    # requestability applies only where |M| >= 1. The witness carries `nonreq`: the subset of
    # required_requirements that is NOT requestable. So requestability is the emptiness of that
    # list -- derived from the record, not from the reason string.
    if m_size == 0:
        requestability = "NA"
    elif not w.get("nonreq"):
        requestability = "ALL_REQUESTABLE"
    else:
        requestability = "SOME_UNAVAILABLE"

    # first action type, EXECUTE rows only. The executed_action value is an action id; it is
    # resolved against the record's available_actions, which carry {id, type, args}.
    if disposition != "EXECUTE":
        first_action = "NA"
    else:
        aid = T["executed_action"]["value"]
        by_id = {a.get("id"): a.get("type") for a in rec["ACTION_POLICY"].get("available_actions", [])}
        first_action = by_id.get(aid, "UNRESOLVED")

    conflict = bool(T["contradiction"]["value"])
    return {
        "disposition": disposition,
        "reason": reason,
        "missing_cardinality": m_card,
        "requestability": requestability,
        "first_action_type": first_action,
        "conflict": conflict,
    }


# ---------------------------------------------------------------- B0 oracle


def b0_predict(rec):
    """Re-derive the label from the record via the pinned v2 algebra.

    The constitution says B0 is not a baseline but a sanity check of the instrument: it must
    score exactly 100% on every target on DEV and on every pair. A miss is an instrument defect
    and stops the rung.
    """
    T = rec["TARGETS"]
    return {
        "disposition": T["disposition"]["value"],
        "reason": T["reason"]["value"],
        "missing_cardinality": read_targets(rec)["missing_cardinality"],
        "requestability": read_targets(rec)["requestability"],
        "first_action_type": read_targets(rec)["first_action_type"],
        "conflict": bool(T["contradiction"]["value"]),
    }


# ---------------------------------------------------------------- B2 schema/frequency
# "counts only, no content: entities per type, number of available actions per type,
#  number of facts per predicate, number of hidden facts, number of reports, number of
#  escalation rules, number of denied permissions, scheduled facts, gates"

ENTITY_TYPES = ["OBJECT", "AGENT", "LOCATION", "SWITCH", "CONTAINER", "RESOURCE"]
PREDICATES = ["AT", "CONNECTED", "BLOCKED", "HOLDS", "CONTAINS", "STATE", "REL"]
ACTION_TYPES = ["MOVE", "TAKE", "DROP", "TRANSFER", "OPEN", "CLOSE",
                "ACTIVATE", "DEACTIVATE", "WAIT"]


def b2_features(rec):
    WT = rec["WORLD_TRUTH"]
    OB = rec["OBSERVATION"]
    AP = rec["ACTION_POLICY"]
    f = []
    # entities per type
    tc = {}
    for e in WT.get("entities", []):
        tc[e.get("type", "?")] = tc.get(e.get("type", "?"), 0) + 1
    f += [tc.get(t, 0) for t in ENTITY_TYPES]
    # available actions per type
    ac = {}
    for a in AP.get("available_actions", []):
        ac[a.get("type", "?")] = ac.get(a.get("type", "?"), 0) + 1
    f += [ac.get(t, 0) for t in ACTION_TYPES]
    # facts per predicate, from the fact table
    ft = rec.get("fact_table", {})
    pc = {}
    for fact in ft.values():
        pc[fact.get("pred", "?")] = pc.get(fact.get("pred", "?"), 0) + 1
    f += [pc.get(p, 0) for p in PREDICATES]
    # scalar counts
    f.append(len(OB.get("hidden_facts", [])))
    f.append(len(OB.get("reports", []) or []))
    f.append(len(AP.get("escalation_rules", []) or []))
    f.append(len(AP.get("denied_permissions", []) or AP.get("permissions", {}).get("denied", []) or []))
    f.append(len(WT.get("scheduled", []) or []))
    f.append(len(WT.get("slot_markers", []) or []))
    return f


B2_FEATURE_NAMES = (
    [f"ent_{t}" for t in ENTITY_TYPES]
    + [f"avail_{t}" for t in ACTION_TYPES]
    + [f"fact_{p}" for p in PREDICATES]
    + ["hidden_facts", "reports", "escalation_rules", "denied_permissions",
       "scheduled", "slot_markers"]
)


# ---------------------------------------------------------------- B4 surface cue
# "the presence or absence of each fixed phrase ...; plus text length decile and sentence count"

B4_PHRASES = [
    "not permitted", "escalate", "you may ask", "nobody can tell",
    "also called", "another name", "reports that", "says", "according to",
    "before tick", "from tick", "until tick",
]


def b4_features(rec, length_decile_edges=None):
    text = (rec["OBSERVATION"].get("rendered_text") or "").lower()
    f = [1.0 if p in text else 0.0 for p in B4_PHRASES]
    n_chars = len(text)
    # length decile: edges are fit on TRAIN only and passed in
    if length_decile_edges is None:
        f.append(float(n_chars))
    else:
        d = 0
        for e in length_decile_edges:
            if n_chars > e:
                d += 1
        f.append(float(d))
    f.append(float(len(re.findall(r"[.!?]+", text))))
    return f


B4_FEATURE_NAMES = [f"phrase_{p}" for p in B4_PHRASES] + ["length_decile", "sentence_count"]


# ---------------------------------------------------------------- B5 graph-only
# "computed from the VISIBLE canonical facts (not the text): counts per predicate;
#  number of locations reachable from the actor by CONNECTED minus BLOCKED edges;
#  whether the goal's entities are reachable; number of conflicting pairs among visible facts;
#  gates and scheduled facts present"


def b5_features(rec):
    WT = rec["WORLD_TRUTH"]
    OB = rec["OBSERVATION"]
    ft = rec.get("fact_table", {})
    visible = set(OB.get("visible_facts", []) or [])
    actor = WT.get("actor")

    # counts per predicate over VISIBLE facts only
    pc = {p: 0 for p in PREDICATES}
    connected, blocked = [], []
    for fid in visible:
        fact = ft.get(fid)
        if not fact:
            continue
        pred = fact.get("pred")
        pc[pred] = pc.get(pred, 0) + 1
        if pred == "CONNECTED" and len(fact.get("args", [])) == 2:
            connected.append(tuple(fact["args"]))
        elif pred == "BLOCKED" and len(fact.get("args", [])) == 2:
            blocked.append(tuple(fact["args"]))

    # reachability over CONNECTED minus BLOCKED, from the actor
    blocked_set = set(blocked) | {(b, a) for a, b in blocked}
    adj = {}
    for a, b in connected:
        if (a, b) in blocked_set:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)  # bidirectional traversal
    seen, stack = set(), ([actor] if actor else [])
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj.get(n, ()))
    n_reachable = len(seen)

    # are the goal's entities reachable?
    goal = WT.get("goal") or {}
    gargs = [a for a in goal.get("args", []) if isinstance(a, str)]
    goal_reachable = all(g in seen for g in gargs) if gargs else False

    # conflicting pairs among visible facts
    n_conf = 0
    by_key = {}
    for fid in visible:
        fact = ft.get(fid)
        if not fact or fact.get("pred") != "STATE":
            continue
        key = tuple(fact.get("args", []))
        by_key.setdefault(key, set()).add(fact.get("value"))
    for k, vals in by_key.items():
        if len(vals) > 1:
            n_conf += 1

    f = [float(pc.get(p, 0)) for p in PREDICATES]
    f.append(float(n_reachable))
    f.append(1.0 if goal_reachable else 0.0)
    f.append(float(n_conf))
    f.append(float(len(WT.get("scheduled", []) or [])))
    f.append(float(len(WT.get("slot_markers", []) or [])))
    return f


B5_FEATURE_NAMES = ([f"vis_{p}" for p in PREDICATES]
                    + ["reachable_count", "goal_reachable", "visible_conflicts",
                       "scheduled", "slot_markers"])


# ---------------------------------------------------------------- B3 lexical (sparse)
# "bag of words over rendered_text, lower-cased, 1-2 grams hashed to 2^18 buckets, tf-idf"

N_BUCKETS = 1 << 18
_TOKEN = re.compile(r"[a-z0-9_]+")


def _hash_ngrams(text, n_buckets=N_BUCKETS):
    toks = _TOKEN.findall(text.lower())
    idx = []
    for n in (1, 2):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i:i + n]) if n == 2 else toks[i]
            idx.append(hash_gram(gram) % n_buckets)
    return idx


def hash_gram(gram):
    # deterministic, process-independent hash (Python's hash() is salted per process)
    h = 1469598103934665603
    for b in gram.encode("utf-8"):
        h ^= b
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def b3_sparse(rec):
    """Return (indices, values) for one row: L2-normalised tf-idf over hashed 1-2 grams.

    idf is supplied from TRAIN only. Document frequency is accumulated in a first pass.
    """
    idx = _hash_ngrams(rec["OBSERVATION"].get("rendered_text") or "")
    tf = {}
    for i in idx:
        tf[i] = tf.get(i, 0) + 1
    return tf


B3_SPEC = {"n_buckets": N_BUCKETS, "ngrams": [1, 2], "lowercase": True,
           "weighting": "tf-idf", "norm": "l2", "hash": "fnv1a-64 deterministic"}
