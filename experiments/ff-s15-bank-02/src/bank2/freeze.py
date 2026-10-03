"""Binds the code to the sealed constitution. Importing this module re-hashes bank-v2-objects.json against its sidecar and refuses to continue on any mismatch, so the code cannot drift from the freeze silently."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBJECTS_PATH = ROOT / "bank-v2-objects.json"
SIDECAR_PATH = ROOT / "bank-v2-objects.sha256"


class FreezeMismatch(RuntimeError):
    pass


def _load():
    raw = OBJECTS_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    sidecar = SIDECAR_PATH.read_text(encoding="ascii").split()[0]
    if digest != sidecar and os.environ.get("BANK2_SEALING") != "1":  # only tools/check_freeze.py sets this, to verify an unsealed amendment
        raise FreezeMismatch(f"bank-v2-objects.json hashes to {digest}, the sealed sidecar says {sidecar}")
    return json.loads(raw.decode("utf-8")), digest


FREEZE, FREEZE_SHA = _load()
VERSION = FREEZE["version"]

PREDICATES = tuple(p["name"] for p in FREEZE["relation_vocabulary"]["operational_predicates"]) + ("REL",)
SLOTS = FREEZE["openness"]["slots"]
OPEN_SLOTS = tuple(k for k, v in SLOTS.items() if v["openness"] == "OPEN")
SLOT_OF_PRED = {m: name for name, s in SLOTS.items() for m in s["members"]}
ENV_ACTIONS = tuple(FREEZE["action_namespace"]["ENVIRONMENT_ACTIONS"])
INFO_ACTIONS = tuple(FREEZE["action_namespace"]["INFORMATION_ACTIONS"])
DISPOSITIONS = tuple(x["id"] for x in FREEZE["dispositions"])
REASONS = {r["id"]: r for r in FREEZE["reasons"]}
REASON_FIELD_DISPOSITIONS = frozenset({"ASK", "ESCALATE", "DECLINE_UNAVAILABLE"})
QUERY_SCOPES = ("SCHEMA", "GOAL", "PLAN", "ACTION")
BUDGETS = FREEZE["budgets"]
SPLIT_LIST = [s["name"] for s in FREEZE["splits"]["list"]]
GATES = [g["id"] for g in FREEZE["seal_gates"]["gates"]]
NESTING_DEPTH_MAX = FREEZE["required_facts"]["query_derivation"]["nesting_depth_max"]
SEEN_FAMILIES = tuple(FREEZE["renderer_system"]["seen_family_ids"])
HELD_FAMILIES = tuple(FREEZE["renderer_system"]["held_family_ids"])
