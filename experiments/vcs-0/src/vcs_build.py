"""VCS-0 control-state population builder.

Material: BANK-v1 TRAIN + DEV worlds (labels available in `inputs/`), plus development
shift strata re-rendered from fixed DEV latent worlds via `src/shifts.py`.

HARD BOUNDARY: protected/test-truth is never opened. No terminal truth, no BANK-v2.

Substrates: causal 230M and encoder 230M, both already-extracted primitives for the base
rendering. Shift cells require fresh extraction (done by the caller).
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import torch

import importlib.util

EXP = Path(__file__).resolve().parents[1]
# The readout head fitter lives in the encoder-contrast flight (read-only reuse).
_ro = EXP.parent / "encoder-contrast-01" / "src" / "readout.py"
_spec = importlib.util.spec_from_file_location("vcs_readout", _ro)
_ro_mod = importlib.util.module_from_spec(_spec)
sys.modules["vcs_readout"] = _ro_mod
_spec.loader.exec_module(_ro_mod)
fit_linear = _ro_mod.fit_linear

_sh = EXP.parent / "encoder-contrast-01" / "src" / "shifts.py"
_spec2 = importlib.util.spec_from_file_location("vcs_shifts", _sh)
SH = importlib.util.module_from_spec(_spec2)
sys.modules["vcs_shifts"] = SH
_spec2.loader.exec_module(SH)

from src.vcs_abi import new_state, set_coord

BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")
ROUTING_PRED = ("AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED", "BEFORE", "PART_OF", "ENABLES", "OWNS", "HAS")


# ------------------------------------------------------------------------ material

def read_jsonl(p: Path, limit=None):
    out = []
    with p.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            if line.strip():
                out.append(json.loads(line))
    return out


def dev_worlds(limit=None):
    return read_jsonl(BANK / "worlds" / "DEV.jsonl", limit)


def train_rows(limit=None):
    return read_jsonl(BANK / "inputs" / "TRAIN.jsonl", limit)


def dev_rows(limit=None):
    return read_jsonl(BANK / "inputs" / "DEV.jsonl", limit)


# ------------------------------------------------------------------------ shared head fit

class HeadBank:
    """One shared linear head per (substrate, surface) fit on TRAIN only, reused across
    every evaluation cell. This keeps the control-state coordinates comparable and stops
    per-cell head-fitting noise from masquerading as geometry."""

    def __init__(self, substrate: str, surface: str, seed: int = 0, hidden: int = 0):
        self.substrate, self.surface, self.seed, self.hidden = substrate, surface, seed, hidden
        self.ok = False

    def fit(self, train_limit: int = 20000, steps: int = 300):
        p = torch.load(PRIM / self.substrate / "TRAIN.pt", map_location="cpu", weights_only=False)
        rows = train_rows(train_limit)
        F = p["surfaces"][self.surface].float()
        idx, ys = [], []
        classes = []
        for i, r in enumerate(rows):
            pol = (r.get("labels") or {}).get("policy") or {}
            if pol.get("decision") == "ACT" and pol.get("action"):
                idx.append(i)
                ys.append(json.dumps({"a": pol["action"], "g": pol.get("arguments", {})}, sort_keys=True))
        classes = sorted(set(ys))
        lmap = {c: k for k, c in enumerate(classes)}
        self.classes = classes
        self.class_str = classes
        X = F[idx]
        self.mu, self.sd = X.mean(0), X.std(0).clamp(min=1e-4)
        y = torch.tensor([lmap[v] for v in ys])
        self.net = fit_linear((X - self.mu) / self.sd, y, len(classes), steps=steps,
                              seed=self.seed, hidden=self.hidden)
        self.ok = True
        return self

    def distribution(self, F: torch.Tensor) -> torch.Tensor:
        """Full class distribution for each row (softmax over train-seen route classes)."""
        with torch.no_grad():
            return torch.softmax(self.net((F - self.mu) / self.sd), 1)

    def descriptor(self) -> dict:
        return {"substrate": self.substrate, "surface": self.surface, "seed": self.seed,
                "hidden": self.hidden, "n_classes": len(self.classes),
                "calibration_family": f"trainfit:{self.substrate}:{self.surface}:s{self.seed}"}


# ------------------------------------------------------------------------ world geometry

def world_geometry(w: dict) -> dict:
    """Applicability / semantic coordinates derived from BANK canonical truth only."""
    sys_path = EXP.parent / "ff-s15-bank-01" / "src"
    import importlib.util
    spec = importlib.util.spec_from_file_location("bank_sim", sys_path / "simulator.py")
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    legal = sim.legal_actions(w["initial_state"], w["available_actions"])
    plan = sim.shortest_plan(w["initial_state"], w["available_actions"], w["goal"])
    gold = w.get("selected_action")
    gold_legal = bool(gold and gold in legal)
    n_repair = sum(1 for a in legal
                   if sim.apply_action(w["initial_state"], a) != w["initial_state"])
    key = lambda a: json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True)
    return {
        "n_legal_actions": len(legal),
        "gold_action_legal": gold_legal,
        "n_legal_alternatives": max(len(legal) - (1 if gold_legal else 0), 0),
        "n_repair_alternatives": n_repair,
        "goal_distance": 0 if plan is None else len(plan),
        "goal_reachable": plan is not None,
        "has_contradiction": bool(w.get("contradictions")),
        "n_missing_facts": len(w.get("missing_information") or []),
        "n_evidence_facts": len(w.get("evidence_facts") or []),
        "legal_route_keys": {key(a) for a in legal},
        "gold_route_key": key(gold) if gold else None,
        "decision": w.get("decision"),
    }


def outcome_label(row: dict) -> str:
    """Control-outcome population label from the canonical world decision."""
    d = row.get("geometry", {}).get("decision") or row.get("decision")
    if d == "ABSTAIN":
        return "ABSTAIN"
    if d == "ASK":
        return "ASK"
    return "EXECUTE"


# ------------------------------------------------------------------------ population build

def build_population(substrate: str, surface: str, rows: list[dict], worlds_by_id: dict,
                     cell: str, head: HeadBank, seed: int = 0) -> list[dict]:
    """One VectorControlState per row, plus flat vectors for geometry.

    Control coordinates are joined by WORLD ID, never by positional index: the primitives
    files and the BANK jsonl rows are independent artifacts and their row orders are not
    guaranteed to correspond. An earlier version indexed positionally, silently failed to
    match, and produced a substrate-independent atlas.
    """
    p = torch.load(PRIM / substrate / f"{cell}.pt", map_location="cpu", weights_only=False)
    row_of = {wid: k for k, wid in enumerate(p["row_ids"])}
    F = p["surfaces"][surface]
    out = []
    for i, r in enumerate(rows):
        wid = r["world_id"]
        w = worlds_by_id.get(wid)
        if w is None:
            continue
        geo = world_geometry(w)
        st = new_state()
        prov = head.descriptor()
        j = row_of.get(wid)
        if j is not None and j < F.shape[0]:
            probs = head.distribution(F[j].float().unsqueeze(0))[0]
            top = float(probs.max())
            srt = torch.sort(probs, descending=True).values
            margin = float(srt[0] - srt[1]) if len(srt) > 1 else 0.0
            ent = float(-(probs.clamp(min=1e-12) * probs.clamp(min=1e-12).log()).sum())
            set_coord(st, "control", "top_choice_prob", top, prov["calibration_family"])
            set_coord(st, "control", "margin", margin, prov["calibration_family"])
            set_coord(st, "control", "entropy", ent, prov["calibration_family"])
            # legal-set support: how much of the head's mass lands on simulator-legal actions
            cls = head.class_str
            probs2 = head.distribution(F[j].float().unsqueeze(0))[0]
            legal_mass = float(sum(float(probs2[c]) for c, name in enumerate(cls)
                                   if name in geo["legal_route_keys"]))
            set_coord(st, "control", "legal_set_support", legal_mass, prov["calibration_family"])
            gold_key = geo["gold_route_key"]
            if gold_key in cls:
                gi = cls.index(gold_key)
                gtop = float(probs2[gi])
                set_coord(st, "control", "top1_is_legal", bool(geo["gold_route_key"] ==
                                                              cls[int(probs2.argmax())]),
                          prov["calibration_family"])
                alt = float(probs2.sum() - gtop)
                set_coord(st, "applicability", "alt_support", alt, prov["calibration_family"])
                set_coord(st, "applicability", "unlawful_top_prob",
                          float(probs2.max() - probs2[gi].clamp(max=float(probs2.max()))),
                          prov["calibration_family"])
            set_coord(st, "control", "n_legal_actions", geo["n_legal_actions"], "bank:simulator")
        set_coord(st, "applicability", "gold_action_legal", geo["gold_action_legal"], "bank:simulator")
        set_coord(st, "applicability", "n_legal_alternatives", geo["n_legal_alternatives"], "bank:simulator")
        set_coord(st, "applicability", "n_repair_alternatives", geo["n_repair_alternatives"], "bank:simulator")
        set_coord(st, "semantic", "n_evidence_facts", geo["n_evidence_facts"], "bank:world")
        set_coord(st, "semantic", "has_contradiction", geo["has_contradiction"], "bank:world")
        set_coord(st, "semantic", "n_missing_facts", geo["n_missing_facts"], "bank:world")
        set_coord(st, "semantic", "goal_distance", geo["goal_distance"], "bank:simulator")
        set_coord(st, "representation", "substrate", substrate, "vcs:abimeta")
        set_coord(st, "representation", "surface", surface, "vcs:abimeta")
        set_coord(st, "representation", "head_seed", seed, "vcs:abimeta")
        set_coord(st, "representation", "trainable_dim", 1024, "vcs:modelcard")
        set_coord(st, "distribution", "cell", cell, "vcs:shifts")
        set_coord(st, "distribution", "renderer_family", r.get("surface_family"), "vcs:bank")
        set_coord(st, "distribution", "split", r.get("split"), "vcs:bank")
        set_coord(st, "distribution", "calibration_family", prov["calibration_family"], "vcs:abimeta")
        out.append({"world_id": wid, "state": st, "geometry": geo,
                    "decision": r.get("decision"),
                    "renderer_family": r.get("surface_family")})
    return out

