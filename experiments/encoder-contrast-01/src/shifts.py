"""Matched-shift transforms over BANK-v1 canonical worlds.

Every transform here is a truth-preserving or explicitly-declared re-rendering of a
BANK-v1 canonical world. BANK-v1 files are never written. Outputs go to this
experiment's own directory.

Two capabilities are provided:

1. `shift_world` / `render_facts` — apply an orthogonal shift (LEX, TMPL, ENT, COMP,
   DEPTH) to a fixed latent world so that constituent shifts and their interactions can
   be measured on *identical* latent truth.

2. `contrastive_pair_worlds` — build matched world pairs where the same entity pair
   appears in both orders as a positive edge, so chain index cannot substitute for role
   in the P6 binding instrument.
"""
from __future__ import annotations

import random

# ---------------------------------------------------------------- vocabulary

TRAIN_POOLS = {
    "loc": ["chamber_a", "chamber_b", "chamber_c", "hall_north", "hall_south", "vault_1", "vault_2", "atrium"],
    "obj": ["sapphire", "ember", "ivory", "copper", "jade", "amber", "coral", "onyx", "topaz", "basalt"],
    "sw": ["switch_p", "switch_q", "switch_r"],
}
HELDOUT_POOLS = {
    "loc": ["xenon_vault", "quasar_hall", "vortex_room", "zephyr_dock", "krypt_chamber", "magma_gate", "tundra_post", "obsidian_gate"],
    "obj": ["xenolith", "quarzite", "vortice", "zaphyr", "krypton", "molybden", "tungsten", "obsidian-x", "ferrite", "gabbro"],
    "sw": ["switch_x", "switch_y", "switch_z"],
}
HELD_TEMPLATES = ["S7", "S8", "S9"]

# ---------------------------------------------------------------- facts

EDGE_PREDS = ["AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED", "BEFORE", "PART_OF", "ENABLES", "OWNS", "HAS"]


def _n(eid: str) -> str:
    t = eid.split("_")[0]
    return {"loc": "L", "obj": "O", "sw": "S", "ag": "A", "cont": "C", "res": "R"}.get(t, "E") + eid.split("_")[-1]


def fact_text(f: dict, ents: dict, template: str) -> str:
    p = f.get("pred")
    a = f.get("args", [])
    g = lambda x: ents.get(x, x)
    v = f.get("value")
    if p == "AT":
        s = f"{g(a[0])} is in {g(a[1])}"
    elif p == "CONNECTED":
        s = f"{g(a[0])} connects to {g(a[1])}"
    elif p == "STATE":
        s = f"{g(a[0])} is {str(v).lower()}"
    elif p == "REQUIRES":
        sw = (v or {}).get("switch")
        s = f"{g(a[0])} requires {g(sw)} active"
    elif p == "BLOCKED":
        s = f"passage from {g(a[0])} to {g(a[1])} is blocked"
    elif p == "BEFORE":
        s = f"{g(a[0])} is before {g(a[1])}"
    elif p == "PART_OF":
        s = f"{g(a[0])} is part of {g(a[1])}"
    elif p == "ENABLES":
        s = f"{g(a[0])} enables {g(a[1])}"
    elif p == "OWNS":
        s = f"{g(a[0])} owns {g(a[1])}"
    elif p == "HAS":
        s = f"{g(a[0])} has {g(a[1])}"
    else:
        s = p
    if template == "S8":
        return f"{p} | {g(a[0])} | {g(a[1])}"
    if template == "S9":
        return f"{p}({','.join(str(x) for x in a)})"
    if template == "S7":
        return f"- {s}"
    return s


def render_facts(world: dict, names: dict, template: str, order_seed: int = 0) -> str:
    ents = {e["id"]: names[e["id"]] for e in world["entities"]}
    facts = [f for f in world["initial_state"] if f.get("pred") in EDGE_PREDS]
    lines = [fact_text(f, ents, template) for f in facts]
    if order_seed:
        rng = random.Random(order_seed)
        rng.shuffle(lines)
    g = world["goal"]
    gl = f"Goal: {g.get('pred')}({','.join(str(x) for x in g.get('args', []))})"
    body = ("\n".join(lines) if template == "S7"
            else " | ".join(lines) if template == "S8"
            else " /\\ ".join(lines) if template == "S9"
            else ". ".join(lines))
    return body + ".\n" + gl


# ---------------------------------------------------------------- shifts

def apply_lex(world: dict) -> tuple[dict, dict]:
    """Rename every entity using the held-out vocabulary pool. Truth-preserving."""
    names = {e["id"]: e["name"] for e in world["entities"]}
    rng = random.Random(abs(hash(("lex", world["world_id"]))) & 0xFFFF)
    used = {"loc": [], "obj": [], "sw": []}
    out = {}
    for e in world["entities"]:
        t = e["type"]
        k = {"LOCATION": "loc", "OBJECT": "obj", "SWITCH": "sw"}.get(t)
        if k is None:
            out[e["id"]] = e["name"]
            continue
        pool = HELDOUT_POOLS[k]
        avail = [p for p in pool if p not in used[k]]
        if not avail:
            avail = list(pool)
        pick = avail[rng.randrange(len(avail))]
        used[k].append(pick)
        out[e["id"]] = pick if t != "OBJECT" else f"{pick}_object"
    return {"shift": "LEX", "names": out}, out


def apply_tmpl(world: dict, rng: random.Random) -> tuple[dict, str]:
    t = HELD_TEMPLATES[rng.randrange(len(HELD_TEMPLATES))]
    return {"shift": "TMPL", "template": t}, t


def apply_ent(world: dict) -> tuple[dict, list[dict]]:
    """Add an unseen entity-type combination (CONTAINER + RESOURCE) as an inert
    distractor. No edge is created or destroyed, so edge truth is unchanged."""
    ents = [dict(e) for e in world["entities"]]
    extra = [{"id": "cont_9", "type": "CONTAINER", "name": "crate_omega", "aliases": ["crate"]},
             {"id": "res_9", "type": "RESOURCE", "name": "cell_omega", "aliases": ["cell"]}]
    ents.extend(extra)
    return {"shift": "ENT", "added": [e["id"] for e in extra]}, ents


def apply_comp(world: dict) -> tuple[dict, dict]:
    """Add the REQUIRES+BLOCKED rule combination held out of TRAIN."""
    st = [dict(f) for f in world["initial_state"]]
    locs = [f["args"][0] for f in st if f["pred"] == "CONNECTED"]
    locs += [f["args"][0] for f in st if f["pred"] == "AT"]
    locs = sorted(set(locs))
    sws = [f["args"][0] for f in st if f["pred"] == "STATE"]
    if not locs or not sws:
        return {}, {}
    a, b = locs[0], locs[-1]
    added = []
    if not any(f["pred"] == "REQUIRES" for f in st):
        st.append({"id": "x_req", "pred": "REQUIRES", "args": [b], "value": {"switch": sws[0], "state": "ACTIVE"}})
        added.append("REQUIRES")
    if not any(f["pred"] == "BLOCKED" for f in st):
        st.append({"id": "x_blk", "pred": "BLOCKED", "args": [a, b]})
        added.append("BLOCKED")
    return ({"shift": "COMP", "added": added}, st) if len(added) == 2 else ({}, {})


def apply_depth(world: dict) -> tuple[dict, dict]:
    """Lengthen the relational chain by one hop at each end."""
    st = [dict(f) for f in world["initial_state"]]
    locs = sorted({f["args"][0] for f in st if f["pred"] == "CONNECTED"})
    if len(locs) < 2:
        return {}, {}
    new_id = "loc_deep"
    st.append({"id": "x_c1", "pred": "CONNECTED", "args": [locs[-1], new_id]})
    st.append({"id": "x_b1", "pred": "BEFORE", "args": [locs[0], new_id]})
    return {"shift": "DEPTH", "added_entity": new_id}, st


def build_shifted(world: dict, shifts: tuple[str, ...], rng: random.Random):
    """Return (world_dict_for_rendering, names, template). `shifts` is a subset of
    {LEX, TMPL, ENT, COMP, DEPTH}."""
    names = {e["id"]: e["name"] for e in world["entities"]}
    ents = [dict(e) for e in world["entities"]]
    st = [dict(f) for f in world["initial_state"]]
    template = "S1"
    applied = []
    if "LEX" in shifts:
        _, names = apply_lex(world)
        applied.append("LEX")
    if "TMPL" in shifts:
        _, template = apply_tmpl(world, rng)
        applied.append("TMPL")
    if "ENT" in shifts:
        _, ents = apply_ent(world)
        applied.append("ENT")
    if "COMP" in shifts:
        meta, st2 = apply_comp({"entities": ents, "initial_state": st})
        if st2:
            st = st2
            applied.append("COMP")
    if "DEPTH" in shifts:
        meta, st2 = apply_depth({"entities": ents, "initial_state": st})
        if st2:
            st = st2
            ents = ents + [{"id": "loc_deep", "type": "LOCATION", "name": names.get("loc_deep", "annex"), "aliases": []}]
            names["loc_deep"] = names.get("loc_deep", "annex")
            applied.append("DEPTH")
    w = {"world_id": world["world_id"] + "|" + "+".join(applied or ["base"]),
         "entities": ents, "initial_state": st, "goal": world["goal"],
         "policy": world.get("policy"), "abstention": world.get("abstention"),
         "applied": applied}
    return w, names, template


# ---------------------------------------------------------------- P6 contrastive

def contrastive_pair_worlds(world: dict):
    """Matched pair W_fwd / W_rev over identical latent structure: the same directed
    edge appears as (a,b) in one and (b,a) in the other, with identical entity names,
    identical predicate, identical chain length.

    This kills the chain-index shortcut that made the earlier P6 instrument score at
    0.94 with all role words removed.
    """
    st = [dict(f) for f in world["initial_state"]]
    edges = []
    for f in st:
        if f.get("pred") in EDGE_PREDS and len(f.get("args", [])) >= 2:
            a, b = f["args"][0], f["args"][1]
            if a != b:
                edges.append((a, b, f["pred"]))
    if not edges:
        return None
    rng = random.Random(abs(hash(("p6", world["world_id"]))) & 0xFFFF)
    a, b, pred = edges[rng.randrange(len(edges))]
    names = {e["id"]: e["name"] for e in world["entities"]}

    def variant(order):
        fwd = [dict(f) for f in st]
        for f in fwd:
            if f.get("pred") == pred and list(f.get("args", [])) == [a, b]:
                f["args"] = [a, b] if order == "fwd" else [b, a]
                break
        ents = {e["id"]: e["name"] for e in world["entities"]}
        lines = [fact_text(f, ents, "S1") for f in fwd if f.get("pred") in EDGE_PREDS]
        return {"world_id": f"{world['world_id']}|p6_{order}",
                "text": ". ".join(lines) + ".",
                "entities": [{"id": e["id"], "name": e["name"]} for e in world["entities"]],
                "probe_pair": [a, b] if order == "fwd" else [b, a],
                "positive_order": order}

    return {"edge": [a, b], "pred": pred, "fwd": variant("fwd"), "rev": variant("rev"),
            "names": names}
