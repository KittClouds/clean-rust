"""Evaluation core: settings, fitting on fold A, per-world evaluation on fold B through the FROZEN X0 builder and controller.

The only thing that varies between runs is the materializer (producers plus merger). The controller is imported unchanged and hash-checked.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from . import common, mergers as M, producers as P
from .abi import truth, universe
from .common import DEFER_W, KEEP_W, THETAS
from .mergers import DEFER, DROP, KEEP, Flat, Graph, table

CONTROLLER_MODES = {"defer": dict(hi=0.6, lo=0.4, verify=True), "asym": dict(hi=0.6, lo=0.4, verify=False), "sym": dict(hi=0.6, lo=None, verify=True)}

_X0 = None


def x0():
    global _X0
    if _X0 is None:
        common.check_x0_frozen()
        _X0 = common._import_x0()
    return _X0


@dataclass(frozen=True)
class Setting:
    name: str
    m: float
    t3: str | None = None

    @property
    def producers(self) -> tuple:
        return ("T0", "T1", "T2") + (("T3",) if self.t3 else ())


def settings() -> dict:
    out = {}
    for m in common.M_LEVELS:
        out[f"real-m{m}"] = Setting(f"real-m{m}", m)
    for lvl in common.T3_LEVELS:
        out[f"controlled-{lvl}"] = Setting(f"controlled-{lvl}", common.PRIMARY_M, lvl)
    return out


class Bundle:
    """Fitted producers shared by every setting."""

    def __init__(self, t0: P.T0, t1: P.T1, t2: P.T2):
        self.t0, self.t1, self.t2 = t0, t1, t2

    def emit(self, setting: Setting, world: dict, idx: int) -> list:
        edges = self.t0.emit(world) + self.t1.emit(world, setting.m) + self.t2.emit(idx, world)
        if setting.t3:
            edges += P.T3(setting.t3).emit(world)
        return edges


def make_configs(setting: Setting) -> dict:
    pr = setting.producers
    cfgs = {f"{p}-alone": Flat(f"alone:{p}", pr) for p in pr if p != "T0"}
    cfgs["T0-alone"] = Flat("alone:T0", pr)
    for v in ("max", "mean", "calibrated"):
        cfgs[f"flat-{v}"] = Flat(v, pr)
    cfgs["graph"] = Graph(pr, name="graph")
    cfgs["graph-nosem"] = Graph(pr, semantics=False, name="graph-nosem")
    cfgs["graph-nocontra"] = Graph(pr, contradiction=False, name="graph-nocontra")
    cfgs["graph-nodef"] = Graph(pr, deficiency=False, name="graph-nodef")
    cfgs["graph-noagree"] = Graph(pr, agreement=False, name="graph-noagree")
    cfgs["graph-nostruct"] = Graph(pr, structural=False, name="graph-nostruct")
    return cfgs


def fit_t2_calibration(t2: P.T2, fold_a: list) -> dict:
    xs = {"AT": ([], []), "UNTYPED_LL": ([], [])}
    for idx, w in fold_a:
        t = truth(w)
        for e in t2.emit(idx, w):
            y = e.candidate_edge in t
            if e.relation_type == "UNTYPED_LL":
                a, b = e.candidate_edge[1]
                y = y or ("BLOCKED", (a, b), None) in t
            sc = float(e.provenance.split("score=")[1].rstrip(")"))
            xs[e.relation_type][0].append(sc)
            xs[e.relation_type][1].append(1.0 if y else 0.0)
    cal = {}
    for rt, (x, y) in xs.items():
        w = M.logreg(np.array([[v, 1.0] for v in x]), np.array(y), l2=0.1)
        cal[rt] = (float(w[0]), float(w[1]))
    return cal


def fit_setting(setting: Setting, bundle: Bundle, fold_a: list) -> dict:
    tables = []
    for idx, w in fold_a:
        tables.append((table(bundle.emit(setting, w, idx), setting.producers), universe(w), truth(w)))
    cfgs = make_configs(setting)
    for c in cfgs.values():
        if hasattr(c, "fit"):
            c.fit(tables)
    return cfgs


# ---------------------------------------------------------------------------------------------- materialize + controller
def facts_of(disp: dict) -> tuple[list, dict]:
    facts, weights = [], {}
    for n, (k, d) in enumerate(sorted(((k, d) for k, d in disp.items() if d != DROP), key=lambda kv: repr(kv[0]))):
        pred, args, val = k
        f = {"id": f"m{n}", "pred": pred, "args": list(args)}
        if pred == "STATE":
            f["value"] = val
        elif pred == "REQUIRES":
            f["value"] = {"switch": val[0], "state": val[1]}
        facts.append(f)
        weights[f["id"]] = KEEP_W if d == KEEP else DEFER_W
    return facts, weights


def run_controller(world: dict, disp: dict, mode: str) -> dict:
    bank, build, control = x0()
    facts, weights = facts_of(disp)
    pseudo = dict(world)
    pseudo["initial_state"] = facts
    G = build.build_graph(pseudo, lambda rec, pats: (weights, {}), "x1")
    kw = CONTROLLER_MODES[mode]
    return control.decide(G, hi=kw["hi"], lo=kw["lo"], completeness=True, ambiguity=True, verify=kw["verify"])


def outcome(world: dict, d: dict) -> tuple[int, int, int]:
    bank, _b, _c = x0()
    if d["decision"] != "ACT":
        return 0, 0, 0
    lc = bank.label_class(world)
    noop = (d["action"] or {}).get("type") == "NOOP"
    if lc == "ACT/goal_already":
        good = noop
    elif lc == "ACT/plan":
        good = (not noop) and bank.first_action_ok(world, d["action"])
    else:
        good = False
    return int(good), int(not good), 1


def oracle_agrees(world: dict) -> bool:
    bank, build, control = x0()
    d = control.decide(build.build_graph(world), hi=0.5, completeness=True, ambiguity=True)
    if d["decision"] != world["decision"]:
        return False
    return d["decision"] != "ACT" or outcome(world, d)[0] == 1


def graph_flags(world: dict, disp: dict, d: dict) -> dict:
    """Level-2 graph quality for one world."""
    at: dict = defaultdict(int)
    for k, v in disp.items():
        if k[0] == "AT" and v == KEEP:
            at[k[1][0]] += 1
    gsubj = (world["goal"].get("args") or [None])[0]
    lab = world["abstain_reason"]
    return {
        "multi_loc": int(any(n >= 2 for n in at.values())),
        "goal_no_loc": int(gsubj is not None and common.etype(str(gsubj)) in ("OBJECT", "AGENT") and not any(k[0] == "AT" and k[1][0] == gsubj and v != DROP for k, v in disp.items())),
        "false_conflict": int(d["reason"] == "CONFLICTING_EVIDENCE" and lab != "CONFLICTING_EVIDENCE"),
        "missed_conflict": int(d["reason"] != "CONFLICTING_EVIDENCE" and lab == "CONFLICTING_EVIDENCE"),
    }


def eval_world(setting: Setting, bundle: Bundle, cfgs: dict, idx: int, world: dict, modes: tuple) -> dict:
    """One world: per config, per theta, per controller mode -> (useful, harm, acted, decision_ok, flags); plus edge-quality rows."""
    tbl = table(bundle.emit(setting, world, idx), setting.producers)
    uni = universe(world)
    t = truth(world)
    lab = world["decision"]
    res: dict = {}
    scores: dict = {}
    for name, cfg in cfgs.items():
        memo: dict = {}
        for theta in THETAS:
            disp, sc = cfg.decide(tbl, uni, world, theta)
            if abs(theta - 0.6) < 1e-9:
                scores[name] = [(float(sc[k]), k[0], int(k in t)) for k in uni]
            kept = frozenset((k, d) for k, d in disp.items() if d != DROP)
            tp = sum(1 for k, d in disp.items() if d == KEEP and k in t)
            fp = sum(1 for k, d in disp.items() if d == KEEP and k not in t)
            fn = sum(1 for k in t if k in disp and disp[k] != KEEP)
            for mode in modes:
                key = (kept, mode)
                if key not in memo:
                    d = run_controller(world, disp, mode)
                    u, h, a = outcome(world, d)
                    memo[key] = (u, h, a, int(d["decision"] == lab), graph_flags(world, disp, d))
                u, h, a, ok, fl = memo[key]
                res[(name, theta, mode)] = (u, h, a, ok, fl, (tp, fp, fn))
    return {"res": res, "scores": scores}


def average_precision(rows: list) -> float:
    if not rows:
        return float("nan")
    rows = sorted(rows, key=lambda r: -r[0])
    tp = 0
    ap = 0.0
    total = sum(r[2] for r in rows)
    if total == 0:
        return float("nan")
    for i, r in enumerate(rows, 1):
        if r[2]:
            tp += 1
            ap += tp / i
    return ap / total
