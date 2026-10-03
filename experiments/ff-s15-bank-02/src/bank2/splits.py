"""Split identities are structural (§9.1): a world belongs to a split iff a predicate over the RECORD holds, never because of how it was generated.

Each OOD split holds out ONE objective (TEST-JOINT holds out two); every other objective must be 'clean' (seen-like) in every world of every split, so a failure can be attributed.
Held sets are hash partitions of structural signatures, so they cannot be curated by hand.
"""
from __future__ import annotations

import itertools

from . import algebra as A
from . import facts as F
from . import freeze, lexicon, registry
from .canon import sha256_hex
from .worldgen import Cfg

OOD_SPLITS = ("TEST-TEMPLATE", "TEST-VOCAB", "TEST-RELATION", "TEST-GRAPH-ISO", "TEST-HOP-DEPTH", "TEST-ACTION-COMPOSITION", "TEST-TEMPORAL-COMPOSITION", "TEST-INFORMATION-POLICY", "TEST-JOINT")
TRAIN_LIKE = ("TRAIN", "DEV", "TEST-IID")
REL_DEPTH_TRAIN_MAX = 2


def _h(tag: str, sig) -> int:
    return int(sha256_hex([tag, sig])[:8], 16)


# ---------------------------------------------------------------------------------------------- signatures
def topology_class(rec: dict) -> str:
    """Isomorphism class of the location graph with edge types (none / CONNECTED / BLOCKED / both)."""
    wt = rec["WORLD_TRUTH"]
    locs = sorted(e["id"] for e in wt["entities"] if e["type"] == "LOCATION" and e["introduced"])
    idx = {l: i for i, l in enumerate(locs)}
    n = len(locs)
    m = [[0] * n for _ in range(n)]
    for f in wt["state"]:
        if f["pred"] == "CONNECTED" and f["args"][0] in idx and f["args"][1] in idx:
            m[idx[f["args"][0]]][idx[f["args"][1]]] |= 1
        if f["pred"] == "BLOCKED" and f["args"][0] in idx and f["args"][1] in idx:
            m[idx[f["args"][0]]][idx[f["args"][1]]] |= 2
    inv = [(tuple(sorted(m[i])), tuple(sorted(m[j][i] for j in range(n)))) for i in range(n)]
    for _ in range(2):  # refine with neighbour invariants
        inv = [(inv[i], tuple(sorted((m[i][j], inv[j]) for j in range(n))), tuple(sorted((m[j][i], inv[j]) for j in range(n)))) for i in range(n)]
    keyed = [sha256_hex(v)[:10] for v in inv]
    cells: dict = {}
    for i, k in enumerate(keyed):
        cells.setdefault(k, []).append(i)
    order = sorted(cells)
    count = 1
    for k in order:
        for x in range(2, len(cells[k]) + 1):
            count *= x
    if count > 720:  # too symmetric to canonize exactly: the refined colour multiset is the class
        return "wl:" + sha256_hex([n, sorted(keyed)])[:16]
    best = None
    for perms in itertools.product(*[itertools.permutations(cells[k]) for k in order]):
        seq = [i for p in perms for i in p]
        mat = tuple(m[a][b] for a in seq for b in seq)
        if best is None or mat < best:
            best = mat
    return "iso:" + sha256_hex([n, best])[:16]


def rel_depth(rec: dict) -> int:
    """Longest chain (edges) of a TRANSITIVE relation among the stored REL facts."""
    facts = [F.key(f) for f in rec["WORLD_TRUTH"]["state"] if f["pred"] == "REL"]
    depth = 0
    for rid in {k[2] for k in facts}:
        e = registry.BY_ID[rid]
        if e["transitivity"] != "TRANSITIVE":
            continue
        adj: dict = {}
        for k in facts:
            if k[2] == rid:
                adj.setdefault(k[1], []).append(k[3])
                if e["directionality"] == "SYMMETRIC":
                    adj.setdefault(k[3], []).append(k[1])

        def longest(node, seen):
            return max([1 + longest(n, seen | {n}) for n in adj.get(node, []) if n not in seen] or [0])
        for node in list(adj):
            depth = max(depth, longest(node, {node}))
    return depth


def composition_signature(rec: dict, info: dict | None = None) -> str | None:
    sm = A.sim_of(rec)
    info = info or sm.search(cap_depth=rec["META"].get("depth_cap", 8), max_states=rec["META"].get("state_cap", 60000))
    if info["status"] != "SOLVED" or len(info["canonical_plan"]) < 2:
        return None
    return ">".join(a.type for a in info["canonical_plan"])


def temporal_signature(rec: dict) -> str | None:
    ticks = sorted({s["valid_from"] for s in rec["WORLD_TRUTH"]["scheduled"] if s["valid_from"] > 0})
    return f"{len(ticks)}:" + ",".join(map(str, ticks)) if len(ticks) >= 2 else None


def policy_regime(rec: dict) -> str:
    ob, ip, ap = rec["OBSERVATION"], rec["INFORMATION_POLICY"], rec["ACTION_POLICY"]
    fk = A.fact_key_map(rec)
    hid = sorted((F.slot_of(fk[i][0]), i in set(ip["requestable"])) for i in ob["hidden_facts"])
    denied = sorted(k for k, v in ap["permissions"].items() if not v["permitted"])
    rules = sorted(r["kind"] for r in ap["escalation_rules"])
    return sha256_hex([hid, denied, rules])[:12]


def vocab_set(rec: dict) -> str:
    names = [e["name"] for e in rec["WORLD_TRUTH"]["entities"]]
    flags = {lexicon.is_held(n) for n in names}
    alias_words = {w for e in rec["WORLD_TRUTH"]["entities"] for al in e["aliases"] for w in al.split() if w in lexicon.ADJECTIVES}
    flags |= {lexicon.is_held(w) for w in alias_words}
    return "HELD" if flags == {True} else ("SEEN" if flags == {False} else "MIXED")


def uses_test_relation(rec: dict) -> bool:
    return any(registry.BY_ID[F.key(f)[2]]["split_scope"] == "TEST_RELATION_ONLY" for f in rec["WORLD_TRUTH"]["state"] if f["pred"] == "REL")


# held sets (hash partitions; the predicates below are the structural definition)
def topo_held(cls: str) -> bool:
    return _h("topo", cls) % 8 == 0


def comp_held(sig: str | None) -> bool:
    return sig is not None and _h("comp", sig) % 5 == 0


def temporal_held(sig: str | None) -> bool:
    return sig is not None and _h("temporal", sig) % 3 == 0


def regime_held(reg: str) -> bool:
    return _h("regime", reg) % 6 == 0


def features(rec: dict, info: dict | None = None) -> dict:
    fam = rec["OBSERVATION"].get("renderer_family_id")
    return {
        "topo": topology_class(rec), "rel_depth": rel_depth(rec), "comp": composition_signature(rec, info), "temporal": temporal_signature(rec),
        "regime": policy_regime(rec), "vocab": vocab_set(rec), "test_relation": uses_test_relation(rec), "family": fam,
    }


def held_axes(feat: dict) -> set:
    held = set()
    if topo_held(feat["topo"]):
        held.add("GRAPH-ISO")
    if feat["rel_depth"] > REL_DEPTH_TRAIN_MAX:
        held.add("HOP-DEPTH")
    if comp_held(feat["comp"]):
        held.add("ACTION-COMPOSITION")
    if temporal_held(feat["temporal"]):
        held.add("TEMPORAL-COMPOSITION")
    if regime_held(feat["regime"]):
        held.add("INFORMATION-POLICY")
    if feat["vocab"] == "HELD":
        held.add("VOCAB")
    if feat["test_relation"]:
        held.add("RELATION")
    if feat["family"] in freeze.HELD_FAMILIES:
        held.add("TEMPLATE")
    return held


REQUIRED_AXES = {
    "TRAIN": set(), "DEV": set(), "TEST-IID": set(),
    "TEST-TEMPLATE": {"TEMPLATE"}, "TEST-VOCAB": {"VOCAB"}, "TEST-RELATION": {"RELATION"}, "TEST-GRAPH-ISO": {"GRAPH-ISO"}, "TEST-HOP-DEPTH": {"HOP-DEPTH"},
    "TEST-ACTION-COMPOSITION": {"ACTION-COMPOSITION"}, "TEST-TEMPORAL-COMPOSITION": {"TEMPORAL-COMPOSITION"}, "TEST-INFORMATION-POLICY": {"INFORMATION-POLICY"},
    "TEST-JOINT": {"GRAPH-ISO", "TEMPLATE"},
}


def predicate(split: str, feat: dict) -> bool:
    """The structural split predicate: exactly the split's held axes are held in this world."""
    if split not in REQUIRED_AXES:
        raise ValueError(split)
    return held_axes(feat) == REQUIRED_AXES[split]


# ---------------------------------------------------------------------------------------------- generation configs
def cfg_for(split: str) -> Cfg:
    c = Cfg(split=split)
    if split == "TEST-VOCAB":
        c.held_vocab = True
    if split == "TEST-RELATION":
        c.allow_test_relations, c.require_test_relations = True, True
    if split == "TEST-HOP-DEPTH":
        c.extra["long_chain"] = True
    if split == "TEST-ACTION-COMPOSITION":
        c.depth_range = (2, 4)
        c.intents = ("EXECUTE", "EXECUTE_REPORT", "ASK", "ESCALATE_MULTI", "ESCALATE_RULE", "ESCALATE_UNCERTAIN", "DECLINE_SINGLE", "DECLINE_MIXED", "POLICY_DENIED", "CONFLICT")
    if split == "TEST-TEMPORAL-COMPOSITION":
        c.extra["timed"] = 2
        c.intents = tuple(n for n in ("EXECUTE", "EXECUTE_REPORT", "NOOP", "ASK", "ESCALATE_MULTI", "ESCALATE_RULE", "ESCALATE_UNCERTAIN", "DECLINE_SINGLE", "DECLINE_MIXED", "CONFLICT", "POLICY_DENIED", "AMBIGUOUS", "OUT_OF_SCOPE"))
    return c
