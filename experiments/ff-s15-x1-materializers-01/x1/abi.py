"""The one candidate-edge ABI every producer emits. No producer decides anything; KEEP / DROP / DEFER belongs to the merger layer alone."""
from __future__ import annotations

from dataclasses import dataclass

from .common import etype

RELATION_TYPES = ("AT", "CONNECTED", "BLOCKED", "STATE", "REQUIRES", "UNTYPED_LL", "UNTYPED_EL")


@dataclass(frozen=True)
class CandidateEdge:
    candidate_edge: tuple        # (pred, args, value): the proposition this edge asserts
    relation_type: str
    source_node: str
    target_node: str
    confidence: float
    producer_id: str
    provenance: str

    def __post_init__(self):
        if self.relation_type not in RELATION_TYPES:
            raise ValueError(self.relation_type)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")


# ---------------------------------------------------------------------------------------------- the candidate universe of a world
def universe(world: dict) -> list[tuple]:
    """Every proposition a producer may assert: AT(e,l), CONNECTED(a,b), BLOCKED(a,b), STATE(sw,v), gate REQUIRES(dst,sw,ACTIVE)."""
    by: dict = {}
    for e in world["entities"]:
        by.setdefault(etype(str(e["id"])), []).append(str(e["id"]))
    locs = by.get("LOCATION", [])
    keys: list[tuple] = []
    for e in by.get("OBJECT", []) + by.get("AGENT", []):
        for l in locs:
            keys.append(("AT", (e, l), None))
    for a in locs:
        for b in locs:
            if a != b:
                keys.append(("CONNECTED", (a, b), None))
                keys.append(("BLOCKED", (a, b), None))
    for s in by.get("SWITCH", []):
        keys.append(("STATE", (s,), "ACTIVE"))
        keys.append(("STATE", (s,), "INACTIVE"))
        for d in locs:
            keys.append(("REQUIRES", (d,), (s, "ACTIVE")))
    return keys


def truth(world: dict) -> set[tuple]:
    """Membership in the world's initial_state, expressed as universe keys."""
    out = set()
    for f in world["initial_state"]:
        p, a = f["pred"], [str(x) for x in (f.get("args") or [])]
        if p in ("AT", "CONNECTED", "BLOCKED") and len(a) == 2:
            out.add((p, tuple(a), None))
        elif p == "STATE" and len(a) == 1 and isinstance(f.get("value"), str):
            out.add(("STATE", tuple(a), str(f["value"]).upper()))
        elif p == "REQUIRES" and len(a) == 1 and isinstance(f.get("value"), dict):
            v = f["value"]
            out.add(("REQUIRES", tuple(a), (str(v.get("switch")), str(v.get("state", "ACTIVE")).upper())))
    return out


def nodes_of(key: tuple) -> tuple[str, str]:
    pred, args, value = key
    if pred in ("AT", "CONNECTED", "BLOCKED"):
        return args[0], args[1]
    if pred == "STATE":
        return args[0], str(value)
    return args[0], value[0]
