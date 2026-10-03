"""Shared plumbing for X6-A: paths, the frozen X0 import (hash-checked), X1's read-only producers for the confidence policy, constants fixed in PLAN.md."""
from __future__ import annotations

import hashlib
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT.parent
X0 = EXP / "ff-s15-x0-graph-sandbox-01"
X1 = EXP / "ff-s15-x1-materializers-01"
X0_COMMIT = "13d87e83a702209ad35f9bfc30f00fdda4551ef3"
X0_FILES = ("xg/__init__.py", "xg/graph.py", "xg/bank.py", "xg/build.py", "xg/control.py")

BUDGET = 8
H_PRIMARY = 0.3
H_LEVELS = (0.15, 0.3, 0.5)
RANDOM_ROLLOUTS = 20
AUC_MAX = 6
BOOT = 1000
SEED = 20260930
FAMILIES = ("LOC", "STATE", "GATE", "NBR")


def sha256_file(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def x0_hashes() -> dict:
    return {f: sha256_file(X0 / f) for f in X0_FILES}


def check_x0_frozen() -> dict:
    rec = json.loads((X1 / "results" / "x0-frozen.json").read_text(encoding="ascii"))  # recorded and verified against the commit by X1's tools/freeze_x0.py
    now = x0_hashes()
    if rec["files"] != now:
        raise RuntimeError("the frozen X0 sources changed")
    return now


def x1_path():
    if str(X1) not in sys.path:
        sys.path.insert(0, str(X1))


def x0_modules():
    if str(X0) not in sys.path:
        sys.path.insert(0, str(X0))
    from xg import bank, build, control  # noqa: E402
    return bank, build, control


def load_x1_bundle():
    x1_path()
    return pickle.load(open(X1 / "evidence" / "bundle.pkl", "rb"))["bundle"]


def etype(eid: str) -> str:
    return {"obj": "OBJECT", "ag": "AGENT", "loc": "LOCATION", "sw": "SWITCH"}.get(eid.split("_", 1)[0].casefold(), "OTHER")
