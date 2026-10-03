"""Flat baselines: a small CART decision tree over hand-counted features, no graph structure.

`flat`  = raw counts (fact predicates, entity types, action count, goal type).
`flat+` = flat plus three cheap booleans (goal already holds, goal entity unknown, a STATE slot with two values).
"""
from __future__ import annotations

import numpy as np

from .bank import sim

PREDS = ("AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED", "ENABLES", "BEFORE", "OWNS", "PART_OF")
ETYPES = ("LOCATION", "OBJECT", "SWITCH", "AGENT")
GOALS = ("AT", "STATE", "OWNS")
CLASSES = ("ACT", "ASK", "ABSTAIN")


def features(r: dict, plus: bool) -> list[float]:
    facts = r["initial_state"]
    ents = r["entities"]
    f = [sum(1 for x in facts if x["pred"] == p) for p in PREDS]
    f += [sum(1 for e in ents if e["type"] == t) for t in ETYPES]
    f += [len(r["available_actions"]), len(facts)]
    f += [1 if r["goal"]["pred"] == g else 0 for g in GOALS]
    if plus:
        ids = {e["id"] for e in ents}
        holds = sim.holds(facts, r["goal"]["pred"], r["goal"].get("args", []), r["goal"].get("value"))
        unknown = any(a not in ids for a in r["goal"].get("args", []))
        slots: dict = {}
        for x in facts:
            if x["pred"] == "STATE":
                slots.setdefault(x["args"][0], set()).add(x.get("value"))
        f += [int(holds), int(unknown), int(any(len(s) > 1 for s in slots.values()))]
    return f


def _gini(y, k):
    n = len(y)
    if n == 0:
        return 0.0
    p = np.bincount(y, minlength=k) / n
    return 1.0 - float((p * p).sum())


class Tree:
    def __init__(self, depth: int = 10, min_leaf: int = 20):
        self.depth, self.min_leaf = depth, min_leaf

    def fit(self, X, y, k=3):
        self.k = k
        self.root = self._grow(np.asarray(X, float), np.asarray(y, int), 0)
        return self

    def _grow(self, X, y, d):
        counts = np.bincount(y, minlength=self.k)
        if d >= self.depth or len(y) < 2 * self.min_leaf or counts.max() == len(y):
            return int(counts.argmax())
        best = (0.0, None, None)
        base = _gini(y, self.k)
        for j in range(X.shape[1]):
            for t in np.unique(X[:, j])[:-1]:
                m = X[:, j] <= t
                nl = int(m.sum())
                if nl < self.min_leaf or len(y) - nl < self.min_leaf:
                    continue
                gain = base - (nl * _gini(y[m], self.k) + (len(y) - nl) * _gini(y[~m], self.k)) / len(y)
                if gain > best[0]:
                    best = (gain, j, t)
        if best[1] is None:
            return int(counts.argmax())
        _g, j, t = best
        m = X[:, j] <= t
        return (j, float(t), self._grow(X[m], y[m], d + 1), self._grow(X[~m], y[~m], d + 1))

    def predict_one(self, x):
        n = self.root
        while isinstance(n, tuple):
            n = n[2] if x[n[0]] <= n[1] else n[3]
        return n
