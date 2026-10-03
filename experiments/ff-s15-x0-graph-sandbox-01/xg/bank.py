"""Read-only access to BANK-v1 open records and its symbolic simulator (used for labels and scoring only)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

BANK = Path(__file__).resolve().parents[2] / "ff-s15-bank-01"
WORLDS = BANK / "releases" / "BANK-v1" / "worlds"


def _load_sim():
    spec = importlib.util.spec_from_file_location("bank_simulator", BANK / "src" / "simulator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sim = _load_sim()


def load(split: str, limit: int | None = None) -> list[dict]:
    if split not in ("TRAIN", "DEV"):
        raise ValueError("the X-series reads TRAIN and DEV only")
    rows = []
    with open(WORLDS / f"{split}.jsonl", encoding="utf-8") as fh:
        for line in fh:
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def label_class(r: dict) -> str:
    """Label class as BANK states it (decision plus reason)."""
    if r["decision"] == "ACT":
        return "ACT/goal_already" if r["abstain_reason"] == "GOAL_SATISFIED" or (r["selected_action"] or {}).get("type") == "NOOP" else "ACT/plan"
    if r["decision"] == "ASK":
        return "ASK"
    return "ABSTAIN/" + r["abstain_reason"]


def first_action_ok(r: dict, action: dict) -> bool:
    """True if `action` is a legal first step of some shortest plan (BANK's simulator is the judge)."""
    state = r["initial_state"]
    goal = r["goal"]
    avail = r["available_actions"]
    if not any(a == action for a in avail) or not sim._action_legal(state, action):
        return False
    plan = sim.shortest_plan(state, avail, goal)
    if plan is None or len(plan) == 0:
        return False
    if len(plan) == 1:
        return sim.goal_satisfied(sim.apply_action(state, action), goal)
    nxt = sim.shortest_plan(sim.apply_action(state, action), avail, goal)
    return nxt is not None and len(nxt) == len(plan) - 1
