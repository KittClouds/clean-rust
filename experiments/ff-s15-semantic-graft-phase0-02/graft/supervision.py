from __future__ import annotations

import numpy as np

from .contracts import (ACTION_TYPES, ARGUMENT_ROLES, CANDIDATE_AVAILABLE,
                        GLOBAL_AVAILABLE, IDENTITY_FIELDS, OBSERVATION_FIELDS,
                        simulator)

SIM = simulator()


def observable_row(row: dict) -> dict:
    return {k: row[k] for k in OBSERVATION_FIELDS + IDENTITY_FIELDS if k in row}


def base_id(row: dict) -> str:
    return str(row.get("paired_world") or row["world_id"])


def action_key(action: dict) -> tuple:
    return (action["type"], tuple(sorted(action["args"].items())))


def candidates_from_observation(row: dict) -> list[dict]:
    """Mirror BANK-v1's registered candidate schema; never inspect goal policy labels."""
    ids = sorted({str(b["entity_id"]) for b in row["bindings"]})
    locs = sorted((i for i in ids if i.startswith("loc_")), key=lambda i: int(i[4:]))
    switches = sorted((i for i in ids if i.startswith("sw_")), key=lambda i: int(i[3:]))
    if "obj_0" not in ids:
        raise ValueError("BANK-v1 candidate schema requires observable obj_0 binding")
    out = [{"type": "MOVE", "args": {"entity": "obj_0", "src": a, "dst": b}}
           for a in locs for b in locs if a != b]
    for s in switches:
        out.extend([{"type": "ACTIVATE", "args": {"target": s}},
                    {"type": "DEACTIVATE", "args": {"target": s}}])
    return out + [{"type": "WAIT", "args": {}}, {"type": "NOOP", "args": {}}]


def candidate_encoding(row: dict, actions: list[dict], max_entities: int = 64) -> np.ndarray:
    ids = sorted({str(b["entity_id"]) for b in row["bindings"]})
    if len(ids) > max_entities:
        raise ValueError("entity capacity exceeded; no silent truncation")
    position = {eid: i + 1 for i, eid in enumerate(ids)}
    out = np.zeros((len(actions), 1 + len(ARGUMENT_ROLES)), dtype=np.int64)
    for i, a in enumerate(actions):
        if a["type"] not in ACTION_TYPES or set(a["args"]) - set(ARGUMENT_ROLES):
            raise ValueError("unregistered candidate type or argument role")
        out[i, 0] = ACTION_TYPES.index(a["type"])
        for j, role in enumerate(ARGUMENT_ROLES, 1):
            value = a["args"].get(role)
            if value is not None and value not in position:
                raise ValueError(f"unbound candidate argument: {value}")
            out[i, j] = position.get(value, 0)
    return out


def labels_from_world(world: dict, actions: list[dict]) -> tuple[np.ndarray, ...]:
    canonical = world["available_actions"]
    if [action_key(a) for a in actions] != [action_key(a) for a in canonical]:
        raise ValueError("observable candidate enumerator differs from canonical available_actions")
    state, goal = world["initial_state"], world["goal"]
    computed_legal = {action_key(a) for a in SIM.legal_actions(state, canonical)}
    if computed_legal != {action_key(a) for a in world["legal_actions"]}:
        raise ValueError("stored canonical legality differs from the canonical simulator")
    g = np.zeros(6, np.float32)
    g[1] = SIM.goal_satisfied(state, goal)
    g[2] = bool(world["missing_information"])
    g[3] = bool(world["contradictions"])
    g[5] = len(world["missing_information"])
    c = np.zeros((len(actions), 7), np.float32)
    for i, a in enumerate(actions):
        legal = action_key(a) in computed_legal
        c[i, 0] = legal
        c[i, 1] = legal and SIM.goal_satisfied(SIM.apply_action(state, a), goal)
    return (g, np.asarray(GLOBAL_AVAILABLE, dtype=np.bool_), c,
            np.broadcast_to(np.asarray(CANDIDATE_AVAILABLE, dtype=np.bool_), c.shape).copy())
