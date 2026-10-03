"""The generated relation registry (one bank-wide table, §1.6) and its schema validation.

Relation ids are opaque hash-derived tokens: no morpheme, substring or ordering reveals a rendered word or a split scope.
The table is bank-owned synthetic content, deterministic from REGISTRY_SEED.
"""
from __future__ import annotations

from .canon import sha256_hex

REGISTRY_SEED = "bank2-relation-registry-v1"
ENTITY_TYPES = ("LOCATION", "AGENT", "OBJECT", "CONTAINER", "SWITCH")

# (directionality, transitivity, domain, range, required_slot, scope, inverse_index or None)
# index order is arbitrary; ids are assigned by hashing, never by position.
_SPEC = [
    # TRAIN_VISIBLE (12)
    ("DIRECTED", "NONE", "AGENT", "OBJECT", False, "TRAIN_VISIBLE", 1),        # 0  (inverse of 1)
    ("DIRECTED", "NONE", "OBJECT", "AGENT", False, "TRAIN_VISIBLE", 0),        # 1
    ("DIRECTED", "NONE", "AGENT", "AGENT", False, "TRAIN_VISIBLE", None),      # 2
    ("SYMMETRIC", "NONE", "AGENT", "AGENT", False, "TRAIN_VISIBLE", None),     # 3
    ("DIRECTED", "TRANSITIVE", "LOCATION", "LOCATION", True, "TRAIN_VISIBLE", None),  # 4  required_slot, transitive
    ("SYMMETRIC", "NONE", "LOCATION", "LOCATION", False, "TRAIN_VISIBLE", None),      # 5
    ("DIRECTED", "NONE", "OBJECT", "LOCATION", False, "TRAIN_VISIBLE", None),  # 6
    ("DIRECTED", "NONE", "OBJECT", "OBJECT", False, "TRAIN_VISIBLE", None),    # 7
    ("DIRECTED", "TRANSITIVE", "OBJECT", "OBJECT", False, "TRAIN_VISIBLE", None),     # 8
    ("DIRECTED", "NONE", "AGENT", "LOCATION", True, "TRAIN_VISIBLE", None),    # 9  required_slot
    ("SYMMETRIC", "NONE", "OBJECT", "OBJECT", False, "TRAIN_VISIBLE", None),   # 10
    ("DIRECTED", "NONE", "LOCATION", "OBJECT", False, "TRAIN_VISIBLE", None),  # 11
    # SHARED (4)
    ("DIRECTED", "NONE", "AGENT", "OBJECT", False, "SHARED", None),            # 12
    ("DIRECTED", "TRANSITIVE", "LOCATION", "LOCATION", False, "SHARED", None), # 13
    ("SYMMETRIC", "NONE", "AGENT", "AGENT", False, "SHARED", None),            # 14
    ("DIRECTED", "NONE", "OBJECT", "LOCATION", False, "SHARED", None),         # 15
    # TEST_RELATION_ONLY (8): every property combination is absent from TRAIN_VISIBLE and SHARED
    ("DIRECTED", "TRANSITIVE", "AGENT", "AGENT", False, "TEST_RELATION_ONLY", None),       # 16
    ("SYMMETRIC", "TRANSITIVE", "LOCATION", "LOCATION", False, "TEST_RELATION_ONLY", None),  # 17
    ("DIRECTED", "NONE", "CONTAINER", "OBJECT", False, "TEST_RELATION_ONLY", 19),          # 18
    ("DIRECTED", "NONE", "OBJECT", "CONTAINER", False, "TEST_RELATION_ONLY", 18),          # 19
    ("SYMMETRIC", "NONE", "SWITCH", "SWITCH", False, "TEST_RELATION_ONLY", None),          # 20
    ("DIRECTED", "NONE", "SWITCH", "LOCATION", True, "TEST_RELATION_ONLY", None),          # 21 required_slot
    ("SYMMETRIC", "TRANSITIVE", "AGENT", "AGENT", False, "TEST_RELATION_ONLY", None),      # 22
    ("DIRECTED", "TRANSITIVE", "CONTAINER", "CONTAINER", False, "TEST_RELATION_ONLY", None),  # 23
]


def _build():
    ids = []
    for i in range(len(_SPEC)):
        n = 0
        while True:
            token = sha256_hex(f"{REGISTRY_SEED}|{i}|{n}")[:6]
            rid = "r_" + token
            if rid not in ids:
                break
            n += 1
        ids.append(rid)
    entries = []
    for i, (dirn, trans, dom, rng_, req, scope, inv) in enumerate(_SPEC):
        entries.append({
            "relation_id": ids[i], "domain_type": dom, "range_type": rng_, "directionality": dirn, "transitivity": trans,
            "inverse_relation_id": ids[inv] if inv is not None else None, "required_slot": req, "split_scope": scope,
        })
    return entries


REGISTRY = _build()
BY_ID = {e["relation_id"]: e for e in REGISTRY}


def combo(e: dict) -> tuple:
    return (e["directionality"], e["transitivity"], e["domain_type"], e["range_type"])


def train_combos() -> set:
    return {combo(e) for e in REGISTRY if e["split_scope"] in ("TRAIN_VISIBLE", "SHARED")}


def visible_in(split: str) -> list[dict]:
    """Relation entries a world in `split` may use."""
    base = [e for e in REGISTRY if e["split_scope"] in ("TRAIN_VISIBLE", "SHARED")]
    if split in ("TEST-RELATION", "TEST-JOINT-RELATION"):
        return base + [e for e in REGISTRY if e["split_scope"] == "TEST_RELATION_ONLY"]
    return base


def lookup(relation_id: str, split: str) -> dict | None:
    """G18's existence check is a lookup on (relation_id, split)."""
    e = BY_ID.get(relation_id)
    if e is None:
        return None
    if e["split_scope"] == "TEST_RELATION_ONLY" and split not in ("TEST-RELATION",):
        return None
    return e


def validate_registry(entries=None) -> list[str]:
    """Schema validation; returns a list of violations (empty means valid)."""
    entries = REGISTRY if entries is None else entries
    by_id = {e["relation_id"]: e for e in entries}
    bad = []
    if len(by_id) != len(entries):
        bad.append("duplicate relation ids")
    train = {combo(e) for e in entries if e["split_scope"] in ("TRAIN_VISIBLE", "SHARED")}
    for e in entries:
        rid = e["relation_id"]
        if e["domain_type"] not in ENTITY_TYPES or e["range_type"] not in ENTITY_TYPES:
            bad.append(f"{rid}: unknown entity type")
        if e["directionality"] == "SYMMETRIC" and e["domain_type"] != e["range_type"]:
            bad.append(f"{rid}: a symmetric relation needs domain == range")
        inv = e["inverse_relation_id"]
        if inv is not None:
            o = by_id.get(inv)
            if o is None:
                bad.append(f"{rid}: inverse {inv} is not in the registry")
                continue
            if o["inverse_relation_id"] != rid:
                bad.append(f"{rid}: inverse declaration is not mutual")
            if o["split_scope"] != e["split_scope"]:
                bad.append(f"{rid}: inverse pair spans two scopes (holdout leak)")
            if (o["domain_type"], o["range_type"]) != (e["range_type"], e["domain_type"]):
                bad.append(f"{rid}: inverse swaps domain and range incorrectly")
            if e["directionality"] != "DIRECTED":
                bad.append(f"{rid}: only DIRECTED relations carry inverses")
        if e["split_scope"] == "TEST_RELATION_ONLY" and combo(e) in train:
            bad.append(f"{rid}: TEST_RELATION_ONLY combination also occurs in train")
        if not (rid.startswith("r_") and len(rid) == 8 and all(c in "0123456789abcdef" for c in rid[2:])):
            bad.append(f"{rid}: id is not an opaque token")
        if e["split_scope"] not in ("TRAIN_VISIBLE", "TEST_RELATION_ONLY", "SHARED"):
            bad.append(f"{rid}: unknown split_scope")
    return bad
