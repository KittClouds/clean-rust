"""Shared plumbing: paths, the frozen X0 import (hash-checked), BANK-v1 access (TRAIN and DEV only), the renderer, and the fixed constants of PLAN.md."""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT.parent
X0 = EXP / "ff-s15-x0-graph-sandbox-01"
BANK1 = EXP / "ff-s15-bank-01"
CG0 = EXP / "ff-s15-cg0-edge-pruning-01"

# the frozen X0 sources (committed in 13d87e83). The run refuses to start if any differs.
X0_FILES = ("xg/__init__.py", "xg/graph.py", "xg/bank.py", "xg/build.py", "xg/control.py")
X0_SHA256 = {}  # filled from results/x0-frozen.json at import; written once by tools/freeze_x0.py


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def x0_hashes() -> dict:
    return {f: sha256_file(X0 / f) for f in X0_FILES}


def check_x0_frozen() -> dict:
    rec = json.loads((ROOT / "results" / "x0-frozen.json").read_text(encoding="ascii"))
    now = x0_hashes()
    if rec["files"] != now:
        raise RuntimeError("the frozen X0 sources changed: " + ", ".join(f for f in now if rec["files"].get(f) != now[f]))
    return now


def _import_x0():
    sys.path.insert(0, str(X0))
    from xg import bank, build, control  # noqa: E402
    return bank, build, control


def renderer():
    if "src" not in sys.modules or not hasattr(sys.modules["src"], "renderer"):
        pkg = types.ModuleType("src")
        pkg.__path__ = [str(BANK1 / "src")]
        sys.modules["src"] = pkg
    from src import renderer as r  # noqa: E402
    return r


def load_worlds(split: str, limit: int | None = None) -> list[dict]:
    if split not in ("TRAIN", "DEV"):
        raise ValueError("X1 reads BANK-v1 TRAIN and DEV only")
    out = []
    with open(BANK1 / "releases" / "BANK-v1" / "worlds" / f"{split}.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
                if limit and len(out) >= limit:
                    break
    return out


def etype(eid: str) -> str:
    return {"obj": "OBJECT", "ag": "AGENT", "loc": "LOCATION", "sw": "SWITCH", "cont": "CONTAINER", "res": "RESOURCE"}.get(eid.split("_", 1)[0].casefold(), "UNKNOWN")


def fold(world_id: str) -> int:
    return int(hashlib.sha256(("x1-fold|" + str(world_id)).encode()).hexdigest()[:8], 16) % 2


# fixed constants (PLAN.md)
THETAS = [round(0.30 + 0.05 * i, 2) for i in range(13)]
DEFER_GAP = 0.20
KEEP_W, DEFER_W = 0.9, 0.5
MARGIN = 0.25
DEFICIENCY_MIN = 0.25
M_LEVELS = (0.0, 0.2, 0.4)
PRIMARY_M = 0.2
T3_LEVELS = {"low": 0.5, "mid": 1.0, "high": 2.0}
COVERAGE_LEVELS = (0.50, 0.70, 0.85)
BOOT = 1000
SEED = 20260930
TRAIN_SAMPLE = 3000
