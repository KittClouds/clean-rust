"""Pair construction for the two paired loss terms.

Two pair types, orthogonal by construction:

  renderer pair      (x, x~)   same latent world, different surface family.
                               Used by L_R. Taken from BANK-v1's own paired rows
                               (world_id@S_fam -> paired_world).

  truth-changing pair (x+, x-)  same latent world AND SAME renderer family, but a fact is
                               mutated so that a specific candidate's support/legality
                               genuinely flips. Used by L_CF.

The orthogonality is the point: L_CF must not be satisfiable by a renderer shortcut, and L_R
must not be satisfiable by a truth shortcut. A truth-changing pair renders both members
through the SAME surface family, and a renderer pair holds the world bit-identical.

Every truth-changing pair is VERIFIED against the executable simulator: the candidate's
legality must actually differ between x+ and x-. A mutation that does not flip anything is
discarded rather than emitted.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import random
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"

_spec = importlib.util.spec_from_file_location("p0_pair_sim", EXP.parent / "ff-s15-bank-01" / "src" / "simulator.py")
sim = importlib.util.module_from_spec(_spec)
sys.modules["p0_pair_sim"] = sim
_spec.loader.exec_module(sim)

PAIRS_ABI = "phase0-semantic-interface/pairs-v0.1"
TYPE_IDS = ["MOVE", "ACTIVATE", "DEACTIVATE", "TAKE", "DROP", "TRANSFER",
            "OPEN", "CLOSE", "SELECT", "ASSIGN", "REQUEST", "VERIFY", "WAIT", "NOOP"]


# --------------------------------------------------------------------------- renderer pairs
def renderer_pairs(split: str, limit: int = 20000) -> list[dict]:
    """(x, x~) from BANK-v1 paired rows. Same world, different surface_family."""
    base = BANK / "inputs" / f"{split}.jsonl"
    rows = [json.loads(l) for l in base.open(encoding="utf-8") if l.strip()][:limit]
    by_world: dict[str, dict[str, dict]] = {}
    for r in rows:
        pw = r.get("paired_world") or r["world_id"]
        by_world.setdefault(pw, {})[r["surface_family"]] = r
    out = []
    for pw, fams in sorted(by_world.items()):
        keys = sorted(fams)
        if len(keys) < 2:
            continue
        for i in range(len(keys) - 1):
            out.append({"group": pw, "kind": "renderer",
                        "a": {"world_id": fams[keys[i]]["world_id"], "text": fams[keys[i]]["input_text"],
                              "family": keys[i], "bindings": fams[keys[i]].get("bindings", []),
                              "surface_family": keys[i]},
                        "b": {"world_id": fams[keys[i + 1]]["world_id"], "text": fams[keys[i + 1]]["input_text"],
                              "family": keys[i + 1], "bindings": fams[keys[i + 1]].get("bindings", []),
                              "surface_family": keys[i + 1]},
                        "note": "identical latent world, different surface family"})
    return out


# --------------------------------------------------------------------------- truth-changing pairs
MUTATIONS = ("block_edge", "add_gate", "flip_switch", "remove_edge", "seal_target")


def _key(a):
    return json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True)


def _legal_keys(w):
    return {_key(a) for a in sim.legal_actions(w["initial_state"], w["available_actions"])}


def _mutate(w: dict, kind: str, rng: random.Random):
    """Return a mutated copy of w, or None if the mutation is not applicable."""
    v = copy.deepcopy(w)
    st = v["initial_state"]
    locs = sorted({f["args"][0] for f in st if f["pred"] == "CONNECTED"} |
                  {f["args"][0] for f in st if f["pred"] == "AT"})
    sws = [f["args"][0] for f in st if f["pred"] == "STATE"]
    if kind == "block_edge":
        edges = [(f["args"][0], f["args"][1]) for f in st if f["pred"] == "CONNECTED"]
        if not edges:
            return None
        a, b = edges[rng.randrange(len(edges))]
        st.append({"id": "cf_blk", "pred": "BLOCKED", "args": [a, b]})
        return v
    if kind == "add_gate":
        if not locs or not sws:
            return None
        st.append({"id": "cf_gate", "pred": "REQUIRES", "args": [locs[-1]],
                   "value": {"switch": sws[0], "state": "ACTIVE"}})
        return v
    if kind == "flip_switch":
        if not sws:
            return None
        tgt = sws[rng.randrange(len(sws))]
        for f in st:
            if f["pred"] == "STATE" and f["args"][0] == tgt:
                f["value"] = "ACTIVE" if f.get("value") != "ACTIVE" else "INACTIVE"
                return v
        return None
    if kind == "remove_edge":
        edges = [(f["args"][0], f["args"][1]) for f in st if f["pred"] == "CONNECTED"]
        if len(edges) < 2:
            return None
        a, b = edges[rng.randrange(len(edges))]
        v["initial_state"] = [f for f in st
                             if not (f["pred"] == "CONNECTED" and f["args"] == [a, b])]
        return v
    if kind == "seal_target":
        if not locs:
            return None
        st.append({"id": "cf_seal1", "pred": "BLOCKED", "args": [locs[0], locs[-1]]})
        st.append({"id": "cf_seal2", "pred": "BLOCKED", "args": [locs[-1], locs[0]]})
        return v
    return None


def _render(w: dict, family: str) -> str:
    """Deterministic surface rendering of a canonical world in a fixed family. Both members
    of a truth-changing pair use the SAME family so the renderer cannot explain the shift."""
    ents = {e["id"]: e["name"] for e in w["entities"]}
    keep = [f for f in w["initial_state"]
            if f.get("pred") in ("AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED",
                                 "BEFORE", "PART_OF", "ENABLES", "OWNS", "HAS")]
    def line(f):
        p, a, val = f["pred"], f.get("args", []), f.get("value")
        g = lambda x: ents.get(x, x)
        if p == "AT":
            return f"{g(a[0])} is in {g(a[1])}"
        if p == "CONNECTED":
            return f"{g(a[0])} connects to {g(a[1])}"
        if p == "STATE":
            return f"{g(a[0])} is {str(val).lower()}"
        if p == "REQUIRES":
            return f"{g(a[0])} requires {g((val or {}).get('switch'))} active"
        if p == "BLOCKED":
            return f"passage from {g(a[0])} to {g(a[1])} is blocked"
        if p == "BEFORE":
            return f"{g(a[0])} is before {g(a[1])}"
        if p == "PART_OF":
            return f"{g(a[0])} is part of {g(a[1])}"
        if p == "ENABLES":
            return f"{g(a[0])} enables {g(a[1])}"
        if p == "OWNS":
            return f"{g(a[0])} owns {g(a[1])}"
        if p == "HAS":
            return f"{g(a[0])} has {g(a[1])}"
        return p
    lines = [line(f) for f in keep]
    g = w["goal"]
    gl = f"Goal: {g.get('pred')}({','.join(str(x) for x in g.get('args', []))})"
    if family == "S8":
        body = " | ".join(lines)
    elif family == "S9":
        body = " /\\ ".join(f"{f['pred']}({','.join(str(x) for x in f.get('args', []))})" for f in keep)
    elif family == "S7":
        body = "\n".join("- " + t for t in lines)
    else:
        body = ". ".join(lines)
    return body + ".\n" + gl


def truth_changing_pairs(split: str, family: str = "S1", limit: int = 4000,
                         per_world: int = 1, seed: int = 0) -> tuple[list[dict], dict]:
    """(x+, x-) pairs where a candidate's support genuinely flips. Both members render in the
    SAME surface family. Every emitted pair is simulator-verified."""
    worlds = []
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            if line.strip():
                worlds.append(json.loads(line))
    rng = random.Random(seed)
    out = []
    stats = {"attempted": 0, "emitted": 0, "discarded_no_flip": 0,
             "mutation_hist": {}}
    for w in worlds:
        cands = w.get("available_actions") or []
        if not cands:
            continue
        base_legal = _legal_keys(w)
        made = 0
        kinds = list(MUTATIONS)
        rng.shuffle(kinds)
        for kind in kinds:
            if made >= per_world:
                break
            v = _mutate(w, kind, rng)
            if v is None:
                continue
            stats["attempted"] += 1
            mut_legal = _legal_keys(v)
            # find a candidate index j whose legality genuinely differs
            flipped = [i for i, a in enumerate(cands)
                       if (_key(a) in base_legal) != (_key(a) in mut_legal)]
            if not flipped:
                stats["discarded_no_flip"] += 1
                continue
            j = flipped[rng.randrange(len(flipped))]
            a = cands[j]
            y = 1.0 if (_key(a) in base_legal and _key(a) not in mut_legal) else -1.0
            if y > 0:
                yv, yn = 1.0, 0.0      # support should DROP in the mutant
                y = -1.0
            else:
                yv, yn = 0.0, 1.0      # support should RISE in the mutant
                y = 1.0
            out.append({
                "group": w["world_id"], "kind": "truth_change", "mutation": kind,
                "candidate_index": j, "candidate": a, "sign": y,
                "a": {"world_id": w["world_id"] + "+", "text": _render(w, family),
                      "family": family, "world": w, "legality": _key(a) in base_legal},
                "b": {"world_id": w["world_id"] + "-", "text": _render(v, family),
                      "family": family, "world": v, "legality": _key(a) in mut_legal},
                "note": "same renderer family, verified legality flip on candidate j",
            })
            stats["mutation_hist"][kind] = stats["mutation_hist"].get(kind, 0) + 1
            stats["emitted"] += 1
            made += 1
    return out, stats


def pairs_descriptor(render: list[dict], truth: list[dict], truth_stats: dict) -> dict:
    return {
        "abi": PAIRS_ABI,
        "renderer_pairs": {
            "count": len(render),
            "source": "BANK-v1 paired rows (world_id@S_fam -> paired_world)",
            "families_observed": sorted({p["a"]["family"] for p in render} |
                                        {p["b"]["family"] for p in render}),
            "held": "same latent world, different surface family",
            "used_by": "L_R",
        },
        "truth_changing_pairs": {
            "count": len(truth),
            "source": "constructed by canonical-state mutation, simulator-verified",
            "mutations": truth_stats.get("mutation_hist", {}),
            "rendering": "both members rendered in the SAME surface family",
            "verification": "candidate legality must differ between x+ and x-; "
                            "mutations that flip nothing are discarded",
            "stats": truth_stats,
            "used_by": "L_CF",
        },
        "orthogonality": {
            "L_CF": "truth changes, renderer held constant -> cannot be satisfied by a "
                    "renderer shortcut",
            "L_R": "renderer changes, world held constant -> cannot be satisfied by a "
                   "truth shortcut",
        },
    }
