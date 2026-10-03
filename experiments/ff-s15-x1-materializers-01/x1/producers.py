"""The four producers behind one ABI (PLAN.md). T0 schema/type prior, T1 lexical extractor, T2 cached 230M edge-existence scores, T3 synthetic noise with controlled error structure."""
from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter, defaultdict

import numpy as np

from . import common
from .abi import CandidateEdge, nodes_of, truth, universe
from .common import CG0, etype

PRONOUNS = {"it", "they", "them", "he", "she"}


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16], 16))


def _clip(x: float) -> float:
    return max(0.001, min(0.999, x))


# ================================================================================================= T0: schema / type prior
class T0:
    producer_id = "T0"
    cost = 0

    def __init__(self):
        self.rate: dict = {}

    @staticmethod
    def _cls(key: tuple, n_locs: int) -> tuple:
        return (key[0], min(max(n_locs, 2), 6))

    def fit(self, worlds: list[dict]) -> "T0":
        tot, pos = Counter(), Counter()
        for w in worlds:
            n_locs = sum(1 for e in w["entities"] if etype(str(e["id"])) == "LOCATION")
            t = truth(w)
            for k in universe(w):
                c = self._cls(k, n_locs)
                tot[c] += 1
                pos[c] += k in t
        self.rate = {c: (pos[c] + 0.5) / (tot[c] + 1.0) for c in tot}
        return self

    def emit(self, world: dict) -> list[CandidateEdge]:
        n_locs = sum(1 for e in world["entities"] if etype(str(e["id"])) == "LOCATION")
        out = []
        for k in universe(world):
            c = self._cls(k, n_locs)
            s, t = nodes_of(k)
            out.append(CandidateEdge(k, k[0], s, t, _clip(self.rate.get(c, 0.05)), "T0", f"schema:rate({c[0]},locs={c[1]})"))
        return out


# ================================================================================================= T1: lexical / surface extractor
def _split_clauses(text: str) -> list[str]:
    clauses = []
    for part in re.split(r"(?:[.;]\s+|[.;]$|\n)", text):
        part = part.strip().lstrip("-").strip()
        if part:
            clauses.append(part)
    return clauses


class T1:
    producer_id = "T1"
    cost = 1
    PATTERNS = ("AT", "CONN", "CONN_REACH", "BLOCK", "REQ", "STATE_ACTIVE", "STATE_INACTIVE")

    def __init__(self):
        self.precision: dict = {p: 0.9 for p in self.PATTERNS}

    # ---- mention recognition
    @staticmethod
    def mentions(world: dict) -> dict:
        r = common.renderer().render(world)
        m = {}
        for b in r["bindings"]:
            s = str(b["mention"]).strip()
            if s and s.lower() not in PRONOUNS:
                m[str(b["entity_id"])] = s
        return r["text"], m

    def raw_matches(self, world: dict, miss: float = 0.0, seed="x1") -> list[tuple]:
        """[(pattern, key)] found in the text; `miss` drops each mention occurrence with that probability."""
        text, m = self.mentions(world)
        if not m:
            return []
        by_len = sorted(m.items(), key=lambda kv: -len(kv[1]))
        rx = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(s) for _e, s in by_len) + r")(?![A-Za-z0-9_])", re.I)
        back = {s.lower(): e for e, s in m.items()}
        rng = _rng(seed, world["world_id"], miss)
        found: list[tuple] = []
        for clause in _split_clauses(text):
            ms = [(x.start(), x.end(), back[x.group(1).lower()]) for x in rx.finditer(clause)]
            ms = [t for t in ms if rng.random() >= miss]
            low = clause.lower()
            ents = [e for _a, _b, e in ms]
            ty = [etype(e) for e in ents]
            if len(ents) >= 2:
                a, b = ents[0], ents[1]
                ta, tb = ty[0], ty[1]
                if " connects to " in low and ta == tb == "LOCATION":
                    found.append(("CONN", ("CONNECTED", (a, b), None)))
                elif " is reachable from " in low and ta == tb == "LOCATION":
                    found.append(("CONN_REACH", ("CONNECTED", (b, a), None)))
                elif "passage from" in low and "blocked" in low and ta == tb == "LOCATION":
                    found.append(("BLOCK", ("BLOCKED", (a, b), None)))
                elif " requires " in low and "active" in low and ta == "LOCATION" and tb == "SWITCH":
                    found.append(("REQ", ("REQUIRES", (a,), (b, "ACTIVE"))))
                elif " is in " in low and ta in ("OBJECT", "AGENT") and tb == "LOCATION":
                    found.append(("AT", ("AT", (a, b), None)))
            if len(ents) == 1 and ty[0] == "SWITCH":
                if " is inactive" in low:
                    found.append(("STATE_INACTIVE", ("STATE", (ents[0],), "INACTIVE")))
                elif " is active" in low:
                    found.append(("STATE_ACTIVE", ("STATE", (ents[0],), "ACTIVE")))
        return found

    def fit(self, worlds: list[dict]) -> "T1":
        tp, n = Counter(), Counter()
        for w in worlds:
            t = truth(w)
            uni = set(universe(w))
            for pat, key in self.raw_matches(w, 0.0):
                if key in uni:
                    n[pat] += 1
                    tp[pat] += key in t
        self.precision = {p: (tp[p] + 1.0) / (n[p] + 2.0) for p in self.PATTERNS}
        return self

    def emit(self, world: dict, miss: float = 0.0, seed="x1") -> list[CandidateEdge]:
        best: dict = {}
        uni = set(universe(world))
        for pat, key in self.raw_matches(world, miss, seed):
            if key not in uni:
                continue
            c = _clip(self.precision[pat])
            if key not in best or c > best[key][0]:
                best[key] = (c, pat)
        out = []
        for key, (c, pat) in best.items():
            s, t = nodes_of(key)
            out.append(CandidateEdge(key, key[0], s, t, c, "T1", f"lexical:{pat}"))
        return out


# ================================================================================================= T2: cached 230M edge-existence scores
class T2:
    producer_id = "T2"
    cost = 100

    def __init__(self):
        self.pairs: dict = {}      # world index -> [(a, b, score)]
        self.calib: dict = {}      # relation type -> (slope, intercept)

    def load(self, dev_worlds: list[dict]) -> dict:
        """Realign the cached scores to the DEV worlds. Verified world by world on pair count, pair-type sequence and label sequence; a world that does not align is reported and excluded."""
        z = np.load(CG0 / "evidence" / "universe-DEV.npz")
        row, label, ptype, score = z["row"], z["label"], z["pair_type"], z["score"]
        bounds = np.flatnonzero(np.diff(row)) + 1
        starts, ends = np.concatenate([[0], bounds]), np.concatenate([bounds, [len(row)]])
        if len(starts) != len(dev_worlds):
            raise RuntimeError("the cached universe and the DEV split differ in size")
        types = ("OBJECT", "AGENT", "LOCATION", "SWITCH", "CONTAINER", "RESOURCE", "UNKNOWN")
        pred = {"AT", "HAS", "CONNECTED", "REQUIRES", "STATE", "BLOCKED", "ENABLES", "BEFORE", "PART_OF", "OWNS"}
        rend = common.renderer()
        ok, bad = 0, []
        for i, (w, s, e) in enumerate(zip(dev_worlds, starts, ends)):
            r = rend.render(w)
            text = r["text"].lower()
            mention = {str(b["entity_id"]): str(b["mention"]).lower() for b in r["bindings"]}
            ents = [str(x["id"]) for x in w["entities"]]
            typed = [(j, x) for j, x in enumerate(ents) if mention.get(x) and mention[x] in text]
            idx = {x: j for j, x in typed}
            pos = set()
            for f in w["initial_state"]:
                a = [str(v) for v in (f.get("args") or [])]
                if len(a) == 2 and f["pred"] in pred and a[0] in idx and a[1] in idx and idx[a[0]] != idx[a[1]]:
                    pos.add((idx[a[0]], idx[a[1]]))
            seq, pt, lb = [], [], []
            for j, x in typed:
                for k, y in typed:
                    if j != k:
                        seq.append((x, y))
                        pt.append(types.index(etype(x)) * 7 + types.index(etype(y)))
                        lb.append(int((j, k) in pos))
            if len(seq) == e - s and (np.array(pt) == ptype[s:e]).all() and (np.array(lb) == label[s:e]).all():
                self.pairs[i] = [(a, b, float(sc)) for (a, b), sc in zip(seq, score[s:e])]
                ok += 1
            else:
                bad.append(i)
        return {"worlds": len(dev_worlds), "aligned": ok, "excluded": len(bad), "excluded_examples": bad[:10]}

    def emit(self, index: int, world: dict) -> list[CandidateEdge]:
        if index not in self.pairs:
            return []
        out = []
        for a, b, sc in self.pairs[index]:
            ta, tb = etype(a), etype(b)
            if ta in ("OBJECT", "AGENT") and tb == "LOCATION":
                rt, key = "AT", ("AT", (a, b), None)
            elif ta == tb == "LOCATION":
                rt, key = "UNTYPED_LL", ("CONNECTED", (a, b), None)   # the producer cannot say CONNECTED versus BLOCKED; the ABI says so explicitly
            else:
                continue
            slope, icpt = self.calib.get(rt, (1.0, 0.0))
            conf = _clip(1.0 / (1.0 + math.exp(-(slope * sc + icpt))))
            s, t = (a, b)
            out.append(CandidateEdge(key, rt, s, t, conf, "T2", f"230M:edge_existence(score={sc:.3f})"))
        return out


# ================================================================================================= T3: synthetic, controlled error structure
class T3:
    producer_id = "T3"
    cost = 0

    def __init__(self, level: str):
        self.k = common.T3_LEVELS[level]
        self.level = level

    def emit(self, world: dict) -> list[CandidateEdge]:
        rng = _rng("T3", world["world_id"], self.level)
        t = truth(world)
        uni = universe(world)
        by_entity: dict = defaultdict(list)
        out: dict = {}

        def put(key, conf, prov):
            c = _clip(conf)
            if key not in out or c > out[key][0]:
                out[key] = (c, prov)

        locs = [str(e["id"]) for e in world["entities"] if etype(str(e["id"])) == "LOCATION"]
        conn = {k[1] for k in t if k[0] == "CONNECTED"}
        for key in uni:
            if key in t:
                if rng.random() < 0.90:
                    put(key, rng.gauss(0.75, 0.15), "synthetic:true")
                if key[0] == "AT" and rng.random() < 0.15 * self.k:
                    nbrs = [b for (a, b) in conn if a == key[1][1]] or [l for l in locs if l != key[1][1]]
                    if nbrs:
                        put(("AT", (key[1][0], rng.choice(sorted(nbrs))), None), rng.gauss(0.65, 0.15), "synthetic:displaced")
                if key[0] == "STATE" and rng.random() < 0.10 * self.k:
                    flip = "INACTIVE" if key[2] == "ACTIVE" else "ACTIVE"
                    put(("STATE", key[1], flip), rng.gauss(0.60, 0.15), "synthetic:flipped")
                if key[0] == "CONNECTED" and rng.random() < 0.10 * self.k:
                    put(("CONNECTED", (key[1][1], key[1][0]), None), rng.gauss(0.60, 0.15), "synthetic:inverted")
            elif rng.random() < 0.03 * self.k:
                put(key, rng.gauss(0.45, 0.15), "synthetic:hallucinated")
        edges = []
        for key, (c, prov) in out.items():
            s, tt = nodes_of(key)
            edges.append(CandidateEdge(key, key[0], s, tt, c, "T3", prov))
        return edges
