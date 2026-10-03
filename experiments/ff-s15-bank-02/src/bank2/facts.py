"""The fact language: seven predicates, content-derived ids, slot classification, symmetric normalization."""
from __future__ import annotations

from . import freeze
from .canon import short

# fact tuple form used by the simulator: (pred, arg0, arg1, ...)


def make_fact(pred: str, *args: str) -> dict:
    if pred not in freeze.PREDICATES:
        raise ValueError(f"predicate {pred!r} is not in the frozen fact language")
    args = [str(a) for a in args]
    return {"id": "f_" + short([pred, args], 12), "pred": pred, "args": args}


def key(f: dict) -> tuple:
    return (f["pred"], *f["args"])


def from_key(k: tuple) -> dict:
    return make_fact(k[0], *k[1:])


def fid(k: tuple) -> str:
    return "f_" + short([k[0], list(k[1:])], 12)


def slot_of(pred: str) -> str:
    return freeze.SLOT_OF_PRED[pred]


def subject_of(k: tuple):
    """The slot key of a fact: what the fact is *about*."""
    pred = k[0]
    if pred == "AT":
        return k[1]
    if pred == "HOLDS":
        return k[2]
    if pred == "CONTAINS":
        return k[2]
    if pred == "STATE":
        return (k[1], k[2])
    if pred in ("CONNECTED", "BLOCKED"):
        return (k[1], k[2])
    if pred == "REL":
        return (k[1], k[2])
    raise ValueError(pred)


def ordinal(entity_id: str) -> int:
    return int(entity_id[1:])


def normalize_symmetric(rel_key: tuple) -> tuple:
    """REL(a, r, b) for a SYMMETRIC relation is stored once, ascending entity ordinal."""
    _p, a, r, b = rel_key
    return rel_key if ordinal(a) <= ordinal(b) else ("REL", b, r, a)
