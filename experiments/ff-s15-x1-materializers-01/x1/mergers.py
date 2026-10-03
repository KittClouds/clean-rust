"""Mergers. Every merger sees exactly the same emitted candidates and emits KEEP / DEFER / DROP per candidate proposition; none of them touches the frozen controller.

Flat: a scalar per proposition (max, mean, calibrated logistic), no semantics, no structure.
Graph: per-(producer, relation type) calibration and naive-Bayes agreement, then structure: undirected CONNECTED, functional AT slots, contradiction handling, requirement/link deficiency.
Each structural mechanism can be switched off for the ablations.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from . import common
from .abi import universe
from .common import DEFER_GAP, DEFICIENCY_MIN, MARGIN, etype

KEEP, DEFER, DROP = "KEEP", "DEFER", "DROP"
COVERS = {"T0": {"AT", "CONNECTED", "BLOCKED", "STATE", "REQUIRES"}, "T1": {"AT", "CONNECTED", "BLOCKED", "STATE", "REQUIRES"}, "T2": {"AT", "CONNECTED", "BLOCKED"},
          "T3": {"AT", "CONNECTED", "BLOCKED", "STATE", "REQUIRES"}}
RTYPES = ("AT", "CONNECTED", "BLOCKED", "STATE", "REQUIRES")


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(z, 30.0), -30.0)))


def logreg(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 40) -> np.ndarray:
    """Newton / IRLS with a ridge on all weights but the intercept (last column of ones)."""
    w = np.zeros(X.shape[1])
    reg = np.eye(X.shape[1]) * l2
    reg[-1, -1] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        g = X.T @ (p - y) + reg @ w
        H = (X.T * (p * (1 - p))) @ X + reg + 1e-6 * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


# ---------------------------------------------------------------------------------------------- per-world candidate table
def table(edges: list, producers: tuple) -> dict:
    """key -> {producer -> (confidence, relation_type)}; only the requested producers; the best edge per producer and key."""
    t: dict = defaultdict(dict)
    for e in edges:
        if e.producer_id in producers:
            cur = t[e.candidate_edge].get(e.producer_id)
            if cur is None or e.confidence > cur[0]:
                t[e.candidate_edge][e.producer_id] = (e.confidence, e.relation_type)
    return t


# ================================================================================================= flat
class Flat:
    def __init__(self, variant: str, producers: tuple):
        self.variant, self.producers = variant, producers
        self.w: np.ndarray | None = None
        self.name = f"flat-{variant}"

    def _x(self, per: dict) -> list[float]:
        x = []
        for p in self.producers:
            c = per.get(p, (None,))[0]
            x += [logit(c) if c is not None else 0.0, 1.0 if c is not None else 0.0]
        return x + [1.0]

    def fit(self, worlds_tables: list[tuple]) -> "Flat":
        if self.variant != "calibrated":
            return self
        X, y = [], []
        for tbl, uni, truth_set in worlds_tables:
            for k in uni:
                X.append(self._x(tbl.get(k, {})))
                y.append(1.0 if k in truth_set else 0.0)
        self.w = logreg(np.array(X), np.array(y), l2=1.0)
        return self

    def score(self, tbl: dict, uni: list) -> dict:
        out = {}
        for k in uni:
            per = tbl.get(k, {})
            if self.variant.startswith("alone:"):
                out[k] = per.get(self.variant.split(":")[1], (0.0, None))[0]
            elif self.variant == "max":
                out[k] = max((c for c, _r in per.values()), default=0.0)
            elif self.variant == "mean":
                out[k] = (sum(c for c, _r in per.values()) / len(per)) if per else 0.0
            else:
                out[k] = sigmoid(float(np.dot(self._x(per), self.w)))
        return out

    def decide(self, tbl: dict, uni: list, world: dict, theta: float) -> dict:
        s = self.score(tbl, uni)
        return {k: (KEEP if c >= theta else DEFER if c >= theta - DEFER_GAP else DROP) for k, c in s.items()}, s


# ================================================================================================= graph
class Graph:
    """Switches: semantics (relation types, undirected CONNECTED, UNTYPED_LL resolution), agreement (sum of evidence vs max), structural (functional AT slot),
    contradiction (STATE exclusivity with real contradictions kept), deficiency (slot and link completion)."""

    def __init__(self, producers: tuple, semantics=True, agreement=True, structural=True, contradiction=True, deficiency=True, name="graph"):
        self.producers = producers
        self.sem, self.agr, self.struct, self.contra, self.defi = semantics, agreement, structural, contradiction, deficiency
        self.name = name
        self.cal: dict = {}       # (producer, rtype) -> (a, b)
        self.base: dict = {}      # rtype -> base logit
        self.miss: dict = {}      # (producer, rtype) -> log likelihood ratio of an absent emission
        self.frac_c = 0.85        # P(CONNECTED | a location-to-location edge exists)

    def _rt(self, r: str) -> str:
        return r if self.sem else "ALL"

    # ---- fit on fold A
    def fit(self, worlds_tables: list[tuple]) -> "Graph":
        emitted = defaultdict(lambda: ([], []))   # (p, rt) -> (logit conf list, labels)
        cnt = defaultdict(lambda: [0, 0, 0, 0])   # (p, rt) -> [true_emit, true_miss, false_emit, false_miss]
        base = defaultdict(lambda: [0, 0])
        edge_true = edge_all = conn_true = 0
        for tbl, uni, truth_set in worlds_tables:
            for k in uni:
                rt = self._rt(k[0])
                y = k in truth_set
                base[rt][0] += y
                base[rt][1] += 1
                per = tbl.get(k, {})
                for p in self.producers:
                    if k[0] not in COVERS.get(p, ()):
                        continue
                    if p in per:
                        c, r = per[p]
                        lab = y
                        if r == "UNTYPED_LL" and self.sem:
                            lab = y or (("BLOCKED" if k[0] == "CONNECTED" else "CONNECTED", k[1], k[2]) in truth_set)
                        emitted[(p, rt if not (r == "UNTYPED_LL" and self.sem) else "LL")][0].append(logit(c))
                        emitted[(p, rt if not (r == "UNTYPED_LL" and self.sem) else "LL")][1].append(1.0 if lab else 0.0)
                        cnt[(p, rt)][0 if y else 2] += 1
                    else:
                        cnt[(p, rt)][1 if y else 3] += 1
            if self.sem:
                for k in uni:
                    if k[0] == "CONNECTED":
                        a, b = k[1]
                        ec = k in truth_set
                        eb = ("BLOCKED", k[1], None) in truth_set
                        edge_all += ec or eb
                        conn_true += ec
        self.base = {rt: logit((v[0] + 0.5) / (v[1] + 1.0)) for rt, v in base.items()}
        for (p, rt), (xs, ys) in emitted.items():
            if len(xs) >= 20:
                w = logreg(np.array([[x, 1.0] for x in xs]), np.array(ys), l2=0.1)
                self.cal[(p, rt)] = (float(w[0]), float(w[1]))
        for (p, rt), (te, tm, fe, fm) in cnt.items():
            self.miss[(p, rt)] = math.log(((tm + 0.5) / (te + tm + 1.0)) / ((fm + 0.5) / (fe + fm + 1.0)))
        if self.sem and edge_all:
            self.frac_c = max(0.5, min(0.98, conn_true / edge_all))
        return self

    def _llr(self, p: str, rt: str, c: float | None, r: str | None) -> float:
        if c is None:
            return self.miss.get((p, rt), 0.0)
        key = (p, "LL" if (r == "UNTYPED_LL" and self.sem) else rt)
        a, b = self.cal.get(key, (1.0, 0.0))
        base = self.base.get("CONNECTED" if key[1] == "LL" else rt, 0.0)
        return (a * logit(c) + b) - base

    # ---- posteriors
    def posterior(self, tbl: dict, uni: list) -> dict:
        z = {}
        for k in uni:
            rt = self._rt(k[0])
            per = tbl.get(k, {})
            llrs = []
            for p in self.producers:
                if k[0] not in COVERS.get(p, ()):
                    continue
                if p in per:
                    c, r = per[p]
                    v = self._llr(p, rt, c, r)
                    if r == "UNTYPED_LL" and self.sem:
                        v *= self.frac_c if k[0] == "CONNECTED" else (1 - self.frac_c)
                else:
                    v = self._llr(p, rt, None, None)
                llrs.append(v)
            # an untyped edge from T2 is stored under CONNECTED; give the BLOCKED twin its share
            if self.sem and k[0] == "BLOCKED":
                twin = tbl.get(("CONNECTED", k[1], None), {})
                for p, (c, r) in twin.items():
                    if r == "UNTYPED_LL":
                        llrs.append(self._llr(p, rt, c, r) * (1 - self.frac_c))
            agg = sum(llrs) if self.agr else (max(llrs) if llrs else 0.0)
            z[k] = self.base.get(rt, 0.0) + agg
        if self.sem:  # CONNECTED is undirected for the controller: the two directions share their evidence
            for k in uni:
                if k[0] == "CONNECTED":
                    a, b = k[1]
                    z[k] = max(z[k], z.get(("CONNECTED", (b, a), None), z[k]))
        return {k: sigmoid(v) for k, v in z.items()}

    # ---- dispositions
    def decide(self, tbl: dict, uni: list, world: dict, theta: float) -> tuple[dict, dict]:
        p = self.posterior(tbl, uni)
        lo = theta - DEFER_GAP
        disp = {k: (KEEP if v >= theta else DEFER if v >= lo else DROP) for k, v in p.items()}
        ents = {}
        for e in world["entities"]:
            ents.setdefault(etype(str(e["id"])), []).append(str(e["id"]))
        if self.struct:  # functional AT slot
            by_e = defaultdict(list)
            for k in uni:
                if k[0] == "AT":
                    by_e[k[1][0]].append(k)
            for e, ks in by_e.items():
                ks = sorted(ks, key=lambda k: -p[k])
                w, r = ks[0], (ks[1] if len(ks) > 1 else None)
                lead = p[w] - (p[r] if r else 0.0)
                for k in ks:
                    disp[k] = DROP
                if p[w] >= theta and lead >= MARGIN:
                    disp[w] = KEEP
                elif p[w] >= lo:
                    disp[w] = DEFER
                    if r is not None and p[r] >= lo and lead < MARGIN:
                        disp[r] = DEFER
        if self.contra:  # one switch, two values: real contradictions are kept, a weak rival is not
            for s in ents.get("SWITCH", []):
                ka, kb = ("STATE", (s,), "ACTIVE"), ("STATE", (s,), "INACTIVE")
                if ka not in p or kb not in p:
                    continue
                pa, pb = p[ka], p[kb]
                if pa >= theta and pb >= theta:
                    disp[ka] = disp[kb] = KEEP
                elif max(pa, pb) >= theta:
                    win, lose = (ka, kb) if pa >= pb else (kb, ka)
                    disp[win] = KEEP
                    disp[lose] = DROP if abs(pa - pb) >= MARGIN else DEFER
                else:
                    for k in (ka, kb):
                        disp[k] = DEFER if p[k] >= lo else DROP
        if self.defi:
            by_e = defaultdict(list)
            for k in uni:
                if k[0] == "AT":
                    by_e[k[1][0]].append(k)
            for e, ks in by_e.items():
                if any(disp[k] != DROP for k in ks):
                    continue
                ks = sorted(ks, key=lambda k: -p[k])
                lead = p[ks[0]] - (p[ks[1]] if len(ks) > 1 else 0.0)
                if p[ks[0]] >= DEFICIENCY_MIN and lead >= MARGIN:
                    disp[ks[0]] = KEEP
            locs = ents.get("LOCATION", [])
            parent = {l: l for l in locs}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x
            for k in uni:
                if k[0] == "CONNECTED" and disp[k] != DROP:
                    parent[find(k[1][0])] = find(k[1][1])
            if len({find(l) for l in locs}) > 1:
                bridges = sorted((k for k in uni if k[0] == "CONNECTED" and find(k[1][0]) != find(k[1][1])), key=lambda k: -p[k])
                if bridges and p[bridges[0]] >= DEFICIENCY_MIN:
                    disp[bridges[0]] = KEEP
        return disp, p
