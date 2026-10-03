"""The comparison harness: best scalar policy vs vector-region policy at matched wrong-ACT harm, coverage and query cost.

Cases are data, never bound here: {case_id, envelope, context, truth}. `truth["acceptable"]` lists the dispositions that count as correct to commit (EXECUTE with its action, or NOOP);
`truth["ask_cost"]` (default 1) prices an ASK. Definitions, per case:
  committed = EXECUTE or NOOP        coverage = committed / n
  harm      = committed and not acceptable      harm rate = harm / n
  cost      = ask cost summed over ASK dispositions, / n
No credit for moving along one frontier: the vector policy is compared with the best scalar threshold that is no worse on BOTH harm and cost, so a point that merely trades harm for coverage along the scalar frontier earns nothing.
The scalar frontier is exact (every representable observed score is a candidate threshold) and is computed in O(n log n); the bootstrap resamples cases, paired, and recomputes the frontier on every resample."""
from __future__ import annotations

import bisect
import hashlib
import random
from dataclasses import dataclass

from . import authority as A
from . import scalar as S
from .authority import Authority, resolve, Unresolved
from .canon import VcsError, canonical
from .schema import Schema, check_envelope, exact, is_real

COMMIT = ("EXECUTE", "NOOP")


def check_case(schema: Schema, case: dict) -> dict:
    for f in ("case_id", "envelope", "context", "truth"):
        if f not in case:
            raise VcsError(f"case lacks {f}")
    check_envelope(schema, case["envelope"])
    acc = case["truth"].get("acceptable")
    if not isinstance(acc, list):
        raise VcsError("truth.acceptable must be a list of dispositions")
    return case


def judge(disposition: dict, truth: dict, default_cost: float = 1.0) -> tuple:
    """(committed, harm, ask, cost) as 0/1/0/1/float."""
    t = disposition["type"]
    committed = t in COMMIT
    correct = False
    if committed:
        correct = any(a.get("type") == t and (t == "NOOP" or a.get("action") == disposition.get("action")) for a in truth["acceptable"])
    ask = t == "ASK"
    return (int(committed), int(committed and not correct), int(ask), float(truth.get("ask_cost", default_cost)) if ask else 0.0)


def metrics(outs: list) -> dict:
    n = len(outs)
    if n == 0:
        raise VcsError("no cases")
    c = sum(o[0] for o in outs)
    h = sum(o[1] for o in outs)
    return {"n": n, "coverage": c / n, "harm": h / n, "harm_given_committed": (h / c) if c else None, "ask_rate": sum(o[2] for o in outs) / n, "cost": sum(o[3] for o in outs) / n}


def run_policy(decide_fn, cases: list) -> tuple:
    """decide_fn(case) -> receipt. Returns (outcomes, receipts)."""
    outs, receipts = [], []
    for c in cases:
        r = decide_fn(c)
        receipts.append(r)
        outs.append(judge(r["decision"]["disposition"], c["truth"]))
    return outs, receipts


def vector_decider(auth: Authority):
    return lambda case: A.decide(auth, case["envelope"], case["context"])


def scalar_decider(sa: S.ScalarAuthority):
    return lambda case: S.decide_scalar(sa, case["envelope"], case["context"])


# ------------------------------------------------------------------------------------------------ the exact scalar frontier
@dataclass
class ScalarSweep:
    schema: Schema
    src: dict              # {score, at_or_above, below}; `threshold` is added per point
    thresholds: list       # ascending representable observed scores
    bins: list             # per case: largest j with thresholds[j] <= score, or -1 (also for a missing score)
    above: list            # per case outcome if at_or_above
    below: list            # per case outcome if below
    n: int

    def points(self, idx=None) -> list:
        """One point per candidate threshold plus the never-above point (threshold None): (threshold, coverage, harm, cost, ask_rate)."""
        idx = range(self.n) if idx is None else idx
        m = len(self.thresholds)
        base = [0.0] * 4
        delta = [[0.0] * 4 for _ in range(m + 1)]   # index j+1 holds bin j; index 0 is the no-bin group (always below)
        n = 0
        for i in idx:
            n += 1
            b, a, bw = self.bins[i], self.above[i], self.below[i]
            bc = (bw[0], bw[1], bw[3], bw[2])
            ac = (a[0], a[1], a[3], a[2])
            for k in range(4):
                base[k] += bc[k]
                delta[b + 1][k] += ac[k] - bc[k]
        out = []
        suffix = [0.0] * 4
        rows = [None] * m
        for j in range(m - 1, -1, -1):
            for k in range(4):
                suffix[k] += delta[j + 1][k]
            rows[j] = tuple(base[k] + suffix[k] for k in range(4))
        for j in range(m):
            c, h, co, ask = rows[j]
            out.append((self.thresholds[j], c / n, h / n, co / n, ask / n))
        out.append((None, base[0] / n, base[1] / n, base[2] / n, base[3] / n))
        return out

    def authority_at(self, t) -> S.ScalarAuthority:
        if t is None:
            top = (self.thresholds[-1] if self.thresholds else 0) + 1
            return S.load_scalar({**self.src, "threshold": top}, self.schema)
        return S.load_scalar({**self.src, "threshold": t}, self.schema)


def build_sweep(schema: Schema, src: dict, cases: list) -> ScalarSweep:
    """src: a scalar authority source without `threshold` ({score, at_or_above, below})."""
    probe = S.load_scalar({**src, "threshold": 0}, schema)
    scores, above, below = [], [], []
    for c in cases:
        s = S.score_of(probe, c["envelope"], c["context"])
        scores.append(s)
        try:
            above.append(judge(resolve(probe.spec["at_or_above"], c["context"]), c["truth"]))
            below.append(judge(resolve(probe.spec["below"], c["context"]), c["truth"]))
        except Unresolved as e:
            raise VcsError(f"case {c['case_id']}: scalar disposition needs context key {e}") from None
    cands = set()
    for s in scores:
        if s is None:
            continue
        f = float(s)
        if exact(f) == exact(s):
            cands.add(f)
    th = sorted(cands)
    ex = [exact(t) for t in th]
    bins = [(-1 if sc is None else bisect.bisect_right(ex, exact(sc)) - 1) for sc in scores]
    return ScalarSweep(schema, dict(src), th, bins, above, below, len(cases))


class SweepFamily:
    """The nasty comparator: several scalarizers (an observer confidence, single coordinates, a fitted linear combination, ...), each with its own exact frontier. The scalar frontier is the UNION of the
    members' points, so the matched comparison is against the best scalar rule of any member, at each harm and cost."""

    def __init__(self, sweeps: list):
        if not sweeps:
            raise VcsError("a scalar family needs at least one member")
        self.sweeps = sweeps
        self.n = sweeps[0].n

    def points(self, idx=None) -> list:
        return [p for sw in self.sweeps for p in sw.points(idx)]


def build_sweeps(schema: Schema, src, cases: list):
    """src: one scalar source {score, at_or_above, below}, or a list of them (a family)."""
    if isinstance(src, dict):
        return build_sweep(schema, src, cases)
    return SweepFamily([build_sweep(schema, one, cases) for one in src])


# ------------------------------------------------------------------------------------------------ matched comparison
def matched(vec: dict, points: list) -> dict:
    """vec: metrics of the vector policy. points: scalar frontier points. Inclusive ties (a scalar point equal on harm and cost is a valid match).
    `dominates` is true when NO scalar point is as safe and as cheap: the vector policy then beats the whole scalar frontier outright and the coverage margin is undefined (None), not zero."""
    feas = [p for p in points if p[2] <= vec["harm"] + 1e-12 and p[3] <= vec["cost"] + 1e-12]
    best_cov = max((p[1] for p in feas), default=None)
    safer = [p for p in points if p[1] >= vec["coverage"] - 1e-12 and p[3] <= vec["cost"] + 1e-12]
    min_harm = min((p[2] for p in safer), default=None)
    return {"dominates": not feas, "scalar_coverage_at_matched_harm_and_cost": best_cov, "coverage_margin": None if best_cov is None else vec["coverage"] - best_cov,
            "scalar_harm_at_matched_coverage_and_cost": min_harm, "harm_margin": None if min_harm is None else min_harm - vec["harm"]}


def _rng(seed: str) -> random.Random:
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))


def paired_bootstrap(vec_outs: list, sweep: ScalarSweep, *, resamples: int = 1000, seed: str = "vcs1a") -> dict:
    """Case-paired bootstrap. The scalar frontier is recomputed on every resample (the hindsight-best scalar, which favours the scalar side).
    p_credit = share of resamples in which the vector policy earns credit: it dominates the scalar frontier outright, or its coverage margin at matched harm and cost is positive. Margins summarize the resamples where they are defined."""
    n = len(vec_outs)
    rng = _rng(seed)
    cov, harm, dom, credit = [], [], 0, 0
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        vm = metrics([vec_outs[i] for i in idx])
        m = matched(vm, sweep.points(idx))
        dom += m["dominates"]
        credit += m["dominates"] or (m["coverage_margin"] or 0.0) > 1e-12
        if m["coverage_margin"] is not None:
            cov.append(m["coverage_margin"])
        if m["harm_margin"] is not None:
            harm.append(m["harm_margin"])

    def summ(v):
        if not v:
            return None
        v = sorted(v)
        q = lambda p: v[min(len(v) - 1, int(p * len(v)))]  # noqa: E731
        return {"median": q(0.5), "ci95": [q(0.025), q(0.975)], "n": len(v)}
    return {"resamples": resamples, "seed": seed, "coverage_margin": summ(cov), "harm_margin": summ(harm), "dominates_fraction": dom / resamples, "p_credit": credit / resamples}


def compare(schema: Schema, vector: Authority, scalar_src, cases: list, *, resamples: int = 1000, seed: str = "vcs1a") -> dict:
    """Vector authority vs the best scalar threshold (of one scalarizer, or of a whole family), on one set of cases."""
    v_outs, _ = run_policy(vector_decider(vector), cases)
    sweep = build_sweeps(schema, scalar_src, cases)
    vm = metrics(v_outs)
    pts = sweep.points()
    return {"vector": vm, "vector_authority_id": vector.authority_id, "scalar_frontier_points": len(pts), "scalarizers": 1 if isinstance(scalar_src, dict) else len(scalar_src), "matched": matched(vm, pts),
            "bootstrap": paired_bootstrap(v_outs, sweep, resamples=resamples, seed=seed),
            "evidence_grade": "NONE (fixture schema)" if schema.fixture else "see the preregistration of the run that produced it"}
