"""Canonical row-level graph targets for the BANK-v1 cached-surface appendix.

These targets intentionally stay at whole-world granularity. The cached vectors
represent a complete rendered row, not individual entity/edge mentions, so this
module never creates node-level or candidate-edge examples.
"""
from __future__ import annotations

from collections import defaultdict, deque

ENTITY_TYPES = ("OBJECT", "AGENT", "LOCATION", "SWITCH", "CONTAINER", "RESOURCE")
RELATION_TYPES = ("AT", "HAS", "CONNECTED", "REQUIRES", "STATE", "BLOCKED",
                  "ENABLES", "BEFORE", "PART_OF", "OWNS")
STATE_VALUES = ("ACTIVE", "INACTIVE")
PATH_CLASSES = ("ALREADY_AT_GOAL", "ONE_HOP", "MULTI_HOP", "DISCONNECTED")


def shortest_goal_path(world: dict) -> int | None:
    """Return shortest undirected CONNECTED hops for an OBJECT AT goal.

    A result of -1 means the goal destination is disconnected. ``None`` means
    the graph does not define an unambiguous object-to-location AT query.
    CONNECTED facts are treated as undirected, matching BANK's movement graph.
    """
    goal = world.get("goal") or {}
    goal_args = goal.get("args") or []
    if goal.get("pred") != "AT" or len(goal_args) != 2:
        return None
    object_id, destination = goal_args
    entity_types = {str(e.get("id")): e.get("type") for e in world.get("entities", [])}
    if entity_types.get(str(object_id)) != "OBJECT":
        return None

    origins = set()
    facts = world.get("initial_state") or []
    for fact in facts:
        args = fact.get("args") or []
        if fact.get("pred") == "AT" and len(args) == 2 and args[0] == object_id:
            origins.add(str(args[1]))
    if len(origins) != 1:
        return None
    origin = next(iter(origins))
    destination = str(destination)
    if origin == destination:
        return 0

    graph: dict[str, set[str]] = defaultdict(set)
    for fact in facts:
        args = fact.get("args") or []
        if fact.get("pred") == "CONNECTED" and len(args) == 2:
            left, right = map(str, args)
            graph[left].add(right)
            graph[right].add(left)

    queue = deque([(origin, 0)])
    visited = {origin}
    while queue:
        node, distance = queue.popleft()
        for neighbor in graph[node]:
            if neighbor == destination:
                return distance + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, distance + 1))
    return -1


def path_class(distance: int | None) -> int | None:
    if distance is None:
        return None
    if distance < -1:
        raise ValueError(f"invalid path distance: {distance}")
    if distance == -1:
        return PATH_CLASSES.index("DISCONNECTED")
    if distance == 0:
        return PATH_CLASSES.index("ALREADY_AT_GOAL")
    if distance == 1:
        return PATH_CLASSES.index("ONE_HOP")
    return PATH_CLASSES.index("MULTI_HOP")


def derive_targets(world: dict) -> dict:
    """Derive row-level graph outputs solely from canonical BANK world truth."""
    entities = world.get("entities") or []
    facts = world.get("initial_state") or []
    entity_set = {str(e.get("type")) for e in entities}
    relation_set = {str(f.get("pred")) for f in facts}
    state_set = {str(f.get("value")) for f in facts if f.get("pred") == "STATE"}
    return {
        "entity_types": sorted(t for t in ENTITY_TYPES if t in entity_set),
        "relation_types": sorted(t for t in RELATION_TYPES if t in relation_set),
        "state_values": sorted(t for t in STATE_VALUES if t in state_set),
        "goal_path_distance": shortest_goal_path(world),
    }
