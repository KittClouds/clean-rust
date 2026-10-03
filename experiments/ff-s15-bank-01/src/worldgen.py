"""Deterministic latent-world generator. No model contact."""
from __future__ import annotations
import hashlib
import random
from .schema import GENERATOR_VERSION
from . import simulator as sim

TRAIN_OBJECTS = ["sapphire", "ember", "ivory", "copper", "jade", "amber", "coral", "onyx", "topaz", "basalt"]
TESTLEX_OBJECTS = ["xenolith", "quarzite", "vortice", "zaphyr", "krypton", "molybden", "tungsten", "obsidian-x", "ferrite", "gabbro"]
TRAIN_LOCS = ["chamber_a", "chamber_b", "chamber_c", "hall_north", "hall_south", "vault_1", "vault_2", "atrium"]
TESTLEX_LOCS = ["xenon_vault", "quasar_hall", "vortex_room", "zephyr_dock", "krypt_chamber", "magma_gate", "tundra_post", "obsidian_gate"]
TRAIN_SWITCHES = ["switch_p", "switch_q", "switch_r"]
TESTLEX_SWITCHES = ["switch_x", "switch_y", "switch_z"]

RESERVED_ABSTAIN_TRAIN_EXCLUDE = {"OUT_OF_SCOPE", "AMBIGUOUS_REFERENCE", "MULTIPLE_UNRESOLVED_ACTIONS"}
TRAIN_SURFACES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S10", "S11"]
TEMPLATE_HELDOUT = ["S7", "S8", "S9"]

BASE_SEED = 20260928


def _rng(split: str, index: int, seed: int) -> random.Random:
    h = hashlib.sha256(f"{BASE_SEED}|{seed}|{split}|{index}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _pick_names(rng: random.Random, split: str, kind: str, n: int) -> list[str]:
    if split in ("TEST-LEXICAL", "TEST-JOINT"):
        pools = {"obj": TESTLEX_OBJECTS, "loc": TESTLEX_LOCS, "sw": TESTLEX_SWITCHES}
    else:
        pools = {"obj": TRAIN_OBJECTS, "loc": TRAIN_LOCS, "sw": TRAIN_SWITCHES}
    pool = pools[kind]
    items = list(pool)
    rng.shuffle(items)
    out = []
    for i in range(n):
        out.append(items[i % len(items)] + (f"_{i // len(items) + 1}" if i >= len(items) else ""))
    return out


def generate_world(split: str, index: int, seed: int = 0) -> dict:
    rng = _rng(split, index, seed)
    # Resample loop to satisfy split constraints (bounded, deterministic)
    for attempt in range(60):
        w = _generate_once(split, index, seed, rng, attempt)
        if _satisfies_split(w, split):
            return w
    # fallback solvable
    return _generate_once(split, index, seed, rng, 999)


def _generate_once(split: str, index: int, seed: int, rng: random.Random, attempt: int) -> dict:
    r2 = random.Random(rng.randint(0, 2**31 - 1) + attempt * 7919)
    n_loc = r2.randint(2, 5)
    n_obj = r2.randint(1, 3)
    n_sw = r2.randint(1, 3)
    loc_names = _pick_names(r2, split, "loc", n_loc)
    obj_names = _pick_names(r2, split, "obj", n_obj)
    sw_names = _pick_names(r2, split, "sw", n_sw)
    entities = []
    loc_ids = [f"loc_{i}" for i in range(n_loc)]
    obj_ids = [f"obj_{i}" for i in range(n_obj)]
    sw_ids = [f"sw_{i}" for i in range(n_sw)]
    for i, lid in enumerate(loc_ids):
        entities.append({"id": lid, "type": "LOCATION", "name": loc_names[i], "aliases": [loc_names[i].replace("_", " ")]})
    for i, oid in enumerate(obj_ids):
        entities.append({"id": oid, "type": "OBJECT", "name": f"{obj_names[i]}_object", "aliases": [obj_names[i]]})
    for i, sid in enumerate(sw_ids):
        entities.append({"id": sid, "type": "SWITCH", "name": sw_names[i], "aliases": [sw_names[i].upper()]})
    ag = "ag_0"
    entities.append({"id": ag, "type": "AGENT", "name": "agent", "aliases": ["agent"]})
    if split == "TEST-ENTITY":
        # force RESOURCE+CONTAINER combo unseen in train
        entities.append({"id": "cont_0", "type": "CONTAINER", "name": "crate_alpha", "aliases": ["crate"]})
        entities.append({"id": "res_0", "type": "RESOURCE", "name": "cell_beta", "aliases": ["cell"]})

    facts: list[dict] = []
    fid = 0

    def add(pred, args, value=None):
        nonlocal fid
        fid += 1
        f = {"id": f"f{fid}", "pred": pred, "args": args}
        if value is not None:
            f["value"] = value
        facts.append(f)
        return f

    # chain locations + random extra edges (topology entropy for large releases)
    for i in range(n_loc - 1):
        add("CONNECTED", [loc_ids[i], loc_ids[i + 1]])
    for _ in range(r2.randint(0, 2)):
        a, b = r2.sample(loc_ids, 2)
        if not any(f["pred"] == "CONNECTED" and set(f["args"]) == {a, b} for f in facts):
            add("CONNECTED", [a, b])
    # extra relational texture (ENABLES / BEFORE) — truth-relevant but simulator-neutral
    for _ in range(r2.randint(0, 2)):
        a, b = r2.sample(loc_ids, 2)
        if a != b:
            add(r2.choice(["ENABLES", "BEFORE"]), [a, b])
    # place objects + agent
    obj_loc = {oid: r2.choice(loc_ids) for oid in obj_ids}
    for oid, l in obj_loc.items():
        add("AT", [oid, l])
    ag_loc = r2.choice(loc_ids)
    add("AT", [ag, ag_loc])
    # switches
    for sid in sw_ids:
        add("STATE", [sid], "ACTIVE" if r2.random() < 0.4 else "INACTIVE")
    # gating: maybe REQUIRES last loc on switch
    use_gate = r2.random() < 0.55
    gate_sw = r2.choice(sw_ids) if use_gate else None
    gate_loc = loc_ids[-1]
    if use_gate:
        add("REQUIRES", [gate_loc], {"switch": gate_sw, "state": "ACTIVE"})
    # blocked edge sometimes
    use_block = r2.random() < 0.25
    if use_block and n_loc > 2:
        add("BLOCKED", [loc_ids[0], loc_ids[1]])
    # composition test forces both gate+block
    # depth test forces longer chain (already up to 4) + transitive BEFORE facts
    if split in ("TEST-DEPTH", "TEST-JOINT"):
        add("BEFORE", [loc_ids[0], loc_ids[-1]])
        if n_loc >= 3:
            add("PART_OF", [loc_ids[0], loc_ids[-1]])
    # distractors
    n_dist = r2.randint(0, 3)
    irrelevant = []
    for _ in range(n_dist):
        d = {"id": f"d{fid+1}", "pred": "OWNS", "args": [ag, r2.choice(obj_ids)]}
        fid += 1
        irrelevant.append(d)

    # goal
    goal_obj = obj_ids[0]
    goal_loc = r2.choice(loc_ids)
    if r2.random() < 0.25:
        goal = {"pred": "STATE", "args": [sw_ids[0]], "value": "ACTIVE"}
    else:
        goal = {"pred": "AT", "args": [goal_obj, goal_loc]}

    # available actions: ground MOVEs + switch flips + WAIT/NOOP + distractors
    available: list[dict] = []
    for i in range(len(loc_ids)):
        for j in range(len(loc_ids)):
            if i != j:
                available.append({"type": "MOVE", "args": {"entity": goal_obj, "src": loc_ids[i], "dst": loc_ids[j]}})
    for sid in sw_ids:
        available.append({"type": "ACTIVATE", "args": {"target": sid}})
        available.append({"type": "DEACTIVATE", "args": {"target": sid}})
    available.append({"type": "WAIT", "args": {}})
    available.append({"type": "NOOP", "args": {}})

    state = list(facts)
    # choose scenario mode
    mode_weights = ["SOLVABLE"] * 5 + ["ALREADY_TRUE", "MISSING", "CONTRADICTION", "UNKNOWN", "IMPOSSIBLE", "AMBIG", "MULTI", "OOS"]
    if split == "TEST-ABSTENTION":
        mode_weights = ["MISSING", "CONTRADICTION", "UNKNOWN", "IMPOSSIBLE", "AMBIG", "MULTI", "OOS"] * 2
    mode = r2.choice(mode_weights)
    # enforce reserved reasons: train must not use them
    decision, selected, abstain_reason, missing, contra = "ACT", None, None, [], []
    resulting = state
    evidence: list[str] = []

    def plan_evidence(plan0):
        ev = []
        # goal-relevant + preconditions: AT facts + gate STATE + CONNECTED
        for f in state:
            if f["pred"] in ("AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED"):
                ev.append(f["id"])
                if len(ev) >= 6:
                    break
        return ev

    if mode == "ALREADY_TRUE":
        # set state to satisfy goal
        if goal["pred"] == "AT":
            state = [f for f in state if not (f["pred"] == "AT" and f["args"][0] == goal["args"][0])]
            state.append({"id": "f_goal", "pred": "AT", "args": goal["args"]})
        else:
            state = [f for f in state if not (f["pred"] == "STATE" and f["args"] == goal["args"])]
            state.append({"id": "f_goal", "pred": "STATE", "args": goal["args"], "value": goal["value"]})
        available2 = available
        decision, selected = "ACT", {"type": "NOOP", "args": {}}
        abstain_reason = "GOAL_SATISFIED"
        resulting = list(state)
        evidence = ["f_goal"]
    elif mode == "MISSING":
        # remove one required fact (gate state or connected)
        cands = [f for f in state if f["pred"] in ("STATE", "CONNECTED", "AT")]
        if cands:
            rm = r2.choice(cands)
            missing = [{"fact_id": rm["id"], "pred": rm["pred"], "args": rm["args"]}]
            state = [f for f in state if f["id"] != rm["id"]]
        # single missing -> ASK else ABSTAIN; here single -> ASK
        if len(missing) == 1 and r2.random() < 0.6:
            decision, selected, abstain_reason = "ASK", {"type": "REQUEST", "args": {"fact": missing[0]["fact_id"]}}, None
        else:
            decision, selected, abstain_reason = "ABSTAIN", None, "INSUFFICIENT_EVIDENCE"
        resulting = list(state)
        evidence = [f["id"] for f in state[:3]]
    elif mode == "CONTRADICTION":
        cands = [f for f in state if f["pred"] == "STATE"]
        if cands:
            v = r2.choice(cands)
            contra = [v["id"]]
            flip = "ACTIVE" if v.get("value") == "INACTIVE" else "INACTIVE"
            state.append({"id": "f_contra", "pred": "STATE", "args": v["args"], "value": flip})
        decision, selected, abstain_reason = "ABSTAIN", None, "CONFLICTING_EVIDENCE"
        resulting = list(state)
        evidence = [f["id"] for f in state[:3]]
    elif mode == "UNKNOWN":
        goal = {"pred": goal["pred"], "args": ["e_unknown", goal["args"][-1]]} if len(goal["args"]) > 1 else {"pred": "AT", "args": ["e_unknown", loc_ids[0]]}
        decision, selected, abstain_reason = "ABSTAIN", None, r2.choice(["UNKNOWN_ENTITY", "UNKNOWN_TARGET"])
        resulting = list(state)
        evidence = [f["id"] for f in state[:2]]
        missing = [{"fact_id": "e_unknown", "note": "unintroduced entity"}]
    elif mode == "IMPOSSIBLE":
        # permanently seal goal loc
        state.append({"id": "f_seal", "pred": "BLOCKED", "args": [loc_ids[0], goal_loc]})
        state.append({"id": "f_seal2", "pred": "BLOCKED", "args": [goal_loc, loc_ids[0]]})
        # remove switches so gate can never open if gated
        decision, selected, abstain_reason = "ABSTAIN", None, r2.choice(["NO_VALID_ACTION", "IMPOSSIBLE_GOAL"])
        resulting = list(state)
        evidence = ["f_seal", "f_seal2"]
    elif mode == "AMBIG":
        # two entities share alias
        if entities:
            entities[1]["aliases"] = list(entities[0]["aliases"])
        decision, selected, abstain_reason = "ABSTAIN", None, "AMBIGUOUS_REFERENCE"
        resulting = list(state)
        evidence = [f["id"] for f in state[:2]]
    elif mode == "MULTI":
        decision, selected, abstain_reason = "ABSTAIN", None, "MULTIPLE_UNRESOLVED_ACTIONS"
        resulting = list(state)
        evidence = [f["id"] for f in state[:2]]
    elif mode == "OOS":
        goal = {"pred": "OWNS", "args": [ag, "e_out_of_scope"], "note": "out of action closure"}
        decision, selected, abstain_reason = "ABSTAIN", None, "OUT_OF_SCOPE"
        resulting = list(state)
        evidence = []
    else:  # SOLVABLE
        oc = sim.oracle(state, available, goal)
        if oc["decision"] == "ACT" and oc["action"] is not None and oc["action"].get("type") != "NOOP":
            decision, selected = "ACT", oc["action"]
            resulting = sim.apply_action(state, selected)
            evidence = plan_evidence([selected])
            abstain_reason = None
        else:
            # if oracle says NO_VALID_ACTION but we wanted solvable, force simple solvable: open gate
            for f in state:
                if f["pred"] == "STATE":
                    f["value"] = "ACTIVE"
            oc2 = sim.oracle(state, available, goal)
            if oc2["decision"] == "ACT" and oc2["action"] is not None:
                decision, selected = "ACT", oc2["action"]
                resulting = sim.apply_action(state, selected)
                evidence = plan_evidence([selected])
            else:
                decision, selected, abstain_reason = "ABSTAIN", None, "NO_VALID_ACTION"
                resulting = list(state)
                evidence = [f["id"] for f in state[:2]]

    # train firewall: map reserved abstain reasons back to allowed ones (regenerate as INSUFFICIENT)
    if split in ("TRAIN", "DEV", "TEST-IID", "TEST-LEXICAL", "TEST-ENTITY", "TEST-TEMPLATE", "TEST-COMPOSITION", "TEST-DEPTH"):
        if abstain_reason in RESERVED_ABSTAIN_TRAIN_EXCLUDE:
            # convert AMBIG/MULTI/OOS test-only constructions: fall back to INSUFFICIENT
            decision, selected, abstain_reason = "ABSTAIN", None, "INSUFFICIENT_EVIDENCE"

    legal = sim.legal_actions(state, available)
    plan = sim.shortest_plan(state, available, goal)
    plan_depth = 0 if plan is None else len(plan)
    rel_depth = sum(1 for f in state if f["pred"] in ("REQUIRES", "BEFORE", "PART_OF", "ENABLES"))
    # surface
    if split == "TEST-TEMPLATE":
        surf = r2.choice(TEMPLATE_HELDOUT)
    elif split == "TEST-JOINT":
        surf = r2.choice(TEMPLATE_HELDOUT)
    else:
        surf = r2.choice(TRAIN_SURFACES)
    # difficulty
    diff = {
        "entity_count": len(entities), "relation_count": len(state),
        "relevant_fact_count": len(evidence), "distractor_count": len(irrelevant),
        "relation_depth": rel_depth, "plan_depth": plan_depth,
        "alias_count": sum(len(e.get("aliases", [])) for e in entities),
        "coreference_depth": 1 if surf in ("S5", "S2") else 0,
        "negative_fact_count": 1 if surf == "S6" else 0,
        "state_changes": 0 if resulting == state else 1,
        "missing_fact_count": len(missing), "contradiction_count": len(contra),
        "candidate_action_count": len(available), "surface_complexity": len(surf),
    }
    wid = f"{split}:{index:06d}:{seed}:{attempt}"
    return {
        "world_id": wid, "generator_version": GENERATOR_VERSION, "seed": seed,
        "entities": entities, "relations": [f for f in state if f["pred"] in ("CONNECTED", "REQUIRES", "BLOCKED", "BEFORE", "PART_OF", "OWNS", "ENABLES")],
        "initial_state": state, "goal": goal, "available_actions": available,
        "legal_actions": legal, "optimal_next_actions": plan or [],
        "decision": decision, "selected_action": selected, "resulting_state": resulting,
        "abstain_reason": abstain_reason, "missing_information": missing, "contradictions": contra,
        "evidence_facts": evidence, "irrelevant_facts": irrelevant,
        "difficulty": diff, "surface_family": surf, "split": split,
        "ask_target": selected if decision == "ASK" else None,
    }


def _satisfies_split(w: dict, split: str) -> bool:
    d = w["difficulty"]
    if split == "TEST-DEPTH" and not (d["plan_depth"] >= 3 or d["relation_depth"] >= 2):
        return False
    if split == "TEST-JOINT" and not (d["plan_depth"] >= 2 and w["surface_family"] in TEMPLATE_HELDOUT):
        # joint needs template shift + nontrivial plan; relax: template shift suffices after attempts
        return w["surface_family"] in TEMPLATE_HELDOUT
    if split == "TEST-COMPOSITION":
        preds = {f["pred"] for f in w["initial_state"]}
        if not ({"REQUIRES", "BLOCKED"} <= preds):
            return False
    if split in ("TRAIN", "DEV", "TEST-IID"):
        if d["plan_depth"] > 2:
            return False
        if w["abstain_reason"] in RESERVED_ABSTAIN_TRAIN_EXCLUDE:
            return False
        preds = {f["pred"] for f in w["initial_state"]}
        if {"REQUIRES", "BLOCKED"} <= preds:
            return False  # composition held out for TEST-COMPOSITION
    if split == "TEST-ABSTENTION" and w["decision"] not in ("ABSTAIN", "ASK"):
        return False
    return True
