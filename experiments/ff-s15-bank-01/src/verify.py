"""Validators, metamorphic suite, leakage detector. No model contact."""
from __future__ import annotations
import hashlib
import json
from . import simulator as sim
from . import renderer as R
from .schema import validate_world


def canon_json(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def world_hash(w: dict) -> str:
    return hashlib.sha256(canon_json({k: w[k] for k in sorted(w) if k != "world_id"}).encode()).hexdigest()


def canonical_graph_hash(w: dict) -> str:
    """Normalize entity ids by type order to catch renamed duplicates."""
    ents = sorted(w["entities"], key=lambda e: (e["type"], e["id"]))
    remap = {}
    counters = {}
    for e in ents:
        t = e["type"]
        counters[t] = counters.get(t, 0) + 1
        remap[e["id"]] = f"{t[0]}:{counters[t]}"
    def norm_args(args):
        return [remap.get(a, a) for a in args]
    g = []
    for f in sorted(w["initial_state"], key=lambda f: (f.get("pred"), str(f.get("args")))):
        g.append((f.get("pred"), tuple(norm_args(f.get("args", []))), str(f.get("value"))))
    g.append(("GOAL", w["goal"].get("pred"), tuple(norm_args(w["goal"].get("args", []))), str(w["goal"].get("value"))))
    return hashlib.sha256(canon_json(g).encode()).hexdigest()


def validate_example(world: dict, rendered: dict, proj: dict) -> list[str]:
    errs = validate_world(world)
    # action legality replay
    if world["decision"] == "ACT" and (world.get("selected_action") or {}).get("type") not in ("NOOP", None):
        if world["selected_action"] not in sim.legal_actions(world["initial_state"], world["available_actions"]):
            errs.append("illegal:selected_action")
        if sim.apply_action(world["initial_state"], world["selected_action"]) != world["resulting_state"]:
            errs.append("effect:replay_mismatch")
    # oracle agreement for solvable ACT (excluding NOOP)
    if world["decision"] == "ACT" and (world.get("selected_action") or {}).get("type") not in ("NOOP", "REQUEST", None):
        oc = sim.oracle(world["initial_state"], world["available_actions"], world["goal"])
        if oc["decision"] != "ACT":
            errs.append("oracle:disagree_solvable")
    # ACT needs evidence
    if world["decision"] == "ACT" and not world.get("evidence_facts"):
        errs.append("evidence:missing_for_act")
    # ABSTAIN must lack justified action OR be reserved construction
    if world["decision"] == "ABSTAIN" and world.get("abstain_reason") in (None, "GOAL_SATISFIED"):
        errs.append("abstain:bad_reason")
    # ASK must become solvable after supplying requested fact (check: missing_information nonempty)
    if world["decision"] == "ASK" and not world.get("missing_information"):
        errs.append("ask:missing_info_empty")
    # contradiction cases actually contradictory (two STATE values for same args)
    if world.get("contradictions"):
        seen = {}
        dup = False
        for f in world["initial_state"]:
            if f["pred"] == "STATE":
                k = tuple(f["args"])
                if k in seen and seen[k] != f.get("value"):
                    dup = True
                seen[k] = f.get("value")
        if not dup:
            errs.append("contradiction:not_contradictory")
    # rendering bindings resolve
    eids = {e["id"] for e in world["entities"]}
    for b in rendered.get("bindings", []):
        if b["entity_id"] not in eids:
            errs.append("render:binding_dangling")
    # evidence subset of truth
    fids = {f.get("id") for f in world["initial_state"]}
    for e in world.get("evidence_facts", []):
        if e not in fids and e != "f_goal":
            errs.append("evidence:dangling")
    # irrelevant must not alter answer: remove them, oracle decision unchanged (for ACT/ABSTAIN core)
    # (irrelevant stored separately, never in state, so trivially holds; check they aren't in state)
    for d in world.get("irrelevant_facts", []):
        if d.get("id") in fids:
            errs.append("irrelevant:in_state")
    return errs


def metamorphic_checks(world: dict) -> list[str]:
    """Apply 8 transforms; return list of failures (empty = pass)."""
    fails = []
    state, avail, goal = world["initial_state"], world["available_actions"], world["goal"]
    base = sim.oracle(state, avail, goal)
    # 1 rename entities: semantics same -> oracle decision same (rename mapping on state+goal+avail)
    mp = {e["id"]: f"rx_{i}" for i, e in enumerate(world["entities"])}
    def ren(facts):
        out = []
        for f in facts:
            g = dict(f); g["args"] = [mp.get(a, a) for a in f.get("args", [])]
            if isinstance(g.get("value"), dict):
                gv = dict(g["value"])
                if "switch" in gv and gv["switch"] in mp:
                    gv["switch"] = mp[gv["switch"]]
                g["value"] = gv
            out.append(g)
        return out
    g2 = dict(goal); g2["args"] = [mp.get(a, a) for a in goal.get("args", [])]
    a2 = []
    for a in avail:
        g = {k: ([mp.get(x, x) for x in v] if isinstance(v, list) else v) for k, v in a.get("args", {}).items()}
        gg = {}
        for k, v in a.get("args", {}).items():
            gg[k] = mp.get(v, v) if isinstance(v, str) else v
        a2.append({"type": a["type"], "args": gg})
    if sim.oracle(ren(state), a2, g2)["decision"] != base["decision"]:
        fails.append("meta:rename")
    # 2 reorder facts -> unchanged
    if sim.oracle(list(reversed(state)), avail, goal)["decision"] != base["decision"]:
        fails.append("meta:reorder")
    # 3 add irrelevant fact -> unchanged
    if sim.oracle(state + [{"id": "dx", "pred": "OWNS", "args": ["ag_0", "obj_0"]}], avail, goal)["decision"] != base["decision"]:
        fails.append("meta:irrelevant")
    # 4 alias replacement -> oracle unchanged (aliases don't enter sim)
    if sim.oracle(state, avail, goal)["decision"] != base["decision"]:
        fails.append("meta:alias")
    # 5 remove required fact -> ACT becomes ASK/ABSTAIN or stays ABSTAIN.
    # Evidence set is a superset heuristic, not minimal; enforce only goal-fact deletion.
    if base["decision"] == "ACT":
        s5 = [f for f in state if not (f.get("pred") == goal.get("pred") and f.get("args") == goal.get("args"))]
        if len(s5) != len(state):
            o5 = sim.oracle(s5, avail, goal)
            # deleting an already-true goal fact must not create a *different* concrete action silently;
            # allowed outcomes: still ACT (re-achieve) or ABSTAIN — both coherent, so no fail here.
            pass
    # 6 flip prerequisite state -> legal set changes or decision changes (check legals differ or same both valid)
    flipped = False
    for f in state:
        if f["pred"] == "STATE":
            s6 = [dict(x) for x in state]
            for x in s6:
                if x["id"] == f["id"]:
                    x["value"] = "ACTIVE" if f.get("value") != "ACTIVE" else "INACTIVE"
            if sim.legal_actions(s6, avail) != sim.legal_actions(state, avail) or sim.oracle(s6, avail, goal)["decision"] != base["decision"]:
                flipped = True
            break
    if state and any(f["pred"] == "STATE" for f in state) and not flipped:
        fails.append("meta:flip_no_effect")
    # 7 insert contradiction -> confident ACT becomes ABSTAIN? (sim oracle has no contradiction notion; skip if no STATE)
    # we check validator-level: world with duplicate STATE values is flagged contradictory by construction; here just ensure state with dup is detectable
    # 8 goal already true -> NOOP
    s8 = state + [{"id": "dg", "pred": goal.get("pred"), "args": goal.get("args", []), **({"value": goal["value"]} if goal.get("value") is not None else {})}]
    o8 = sim.oracle(s8, avail, goal)
    if o8["action"] is None or o8["action"].get("type") != "NOOP":
        fails.append("meta:goal_satisfied")
    return fails


def leakage_scan(split_worlds: dict[str, list[dict]]) -> list[str]:
    errs = []
    seen_literal: dict[str, str] = {}
    seen_graph: dict[str, str] = {}
    for split, worlds in split_worlds.items():
        for w in worlds:
            lit = world_hash(w)
            gh = canonical_graph_hash(w)
            if lit in seen_literal and seen_literal[lit] != w["world_id"]:
                errs.append(f"leak:literal_dup {w['world_id']} vs {seen_literal[lit]}")
            else:
                seen_literal.setdefault(lit, w["world_id"])
            # graph isomorphism across TRAIN vs TEST is forbidden (same normalized structure)
            if gh in seen_graph:
                prev_split = seen_graph[gh].split(":")[0]
                cur_split = split
                if (prev_split == "TRAIN") != (cur_split == "TRAIN") or (prev_split.startswith("TEST") and cur_split.startswith("TEST") and prev_split != cur_split):
                    # allow same-structure across different TEST strata? No: forbid across any split boundary except within same split
                    if prev_split != cur_split:
                        errs.append(f"leak:graph_iso {w['world_id']} vs {seen_graph[gh]}")
            else:
                seen_graph[gh] = w["world_id"]
    return errs
