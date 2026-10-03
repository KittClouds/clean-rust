"""X6-A driver.

  python run_x6a.py run         # episodes for every hiding level (parallel)                         -> evidence/episodes-h*.npz, results/x6a-counts.json
  python run_x6a.py analyze     # matched-cost frontier, paired bootstrap, attribution, decision      -> results/x6a-receipt.json
  python run_x6a.py explore     # POST HOC (written after the first run): schema-only controls, paired harm  -> results/x6a-explore.json
"""
from __future__ import annotations

import itertools
import json
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from x6 import common, env, policies as P  # noqa: E402

EV, RES = ROOT / "evidence", ROOT / "results"
POLICIES = ("A_random", "B_confidence", "C_broad", "D_full", "D_no1", "D_no3", "D_only1", "D_only3", "O_oracle")
VARIANTS = {"D_full": (1, 2, 3), "D_no1": (2, 3), "D_no3": (1, 2), "D_only1": (1,), "D_only3": (3,)}
_S: dict = {}


def _init():
    common.check_x0_frozen()
    common.x1_path()
    from x1 import common as c1, producers  # noqa: F401
    _S["bundle"] = common.load_x1_bundle()
    _S["dev"] = c1.load_worlds("DEV")
    _S["mods"] = common.x0_modules()


def episode_set() -> list[int]:
    """Fold-B DEV worlds, T2 aligned, on which the oracle controller gives the correct ACT."""
    common.check_x0_frozen()
    common.x1_path()
    from x1 import common as c1
    bundle = common.load_x1_bundle()
    dev = c1.load_worlds("DEV")
    bank, build, control = common.x0_modules()
    out = []
    for i, w in enumerate(dev):
        if c1.fold(w["world_id"]) != 1 or i not in bundle.t2.pairs:
            continue
        if not w["decision"] == "ACT":
            continue
        d = control.decide(build.build_graph(w), hi=0.5, completeness=True, ambiguity=True)
        if d["decision"] == "ACT" and env.outcome(w, d, bank)[0]:
            out.append(i)
    return out


def _world(job):
    i, h = job
    w, bundle, mods = _S["dev"][i], _S["bundle"], _S["mods"]
    bank, build, control = mods
    hidden = env.hide(w, h, "hide")
    base = {"idx": i, "hidden": len(hidden)}
    ep0 = env.Episode(w, hidden, mods)
    d0, _G = ep0.decide()
    base["initial"] = d0["decision"]
    if d0["decision"] == "ACT":
        good, bad = env.outcome(w, d0, bank)
        base["klass"] = "already_correct" if good else "silent_wrong"
        return base
    base["klass"] = "needs_recovery"
    unc = P.uncertainty(w, bundle, i)
    O = env.oracle_min_sets(w, hidden, mods)
    union = set().union(*O) if O else set()
    res: dict = {}
    t = time.perf_counter()
    rs = []
    for r in range(common.RANDOM_ROLLOUTS):
        rng = random.Random(f"A|{w['world_id']}|{r}")
        rs.append(P.run(w, hidden, lambda ep, d, G, rng=rng: (P.random_next(ep, rng), "random"), modules=mods))
    res["A_random"] = (rs, time.perf_counter() - t)
    t = time.perf_counter()
    res["B_confidence"] = ([P.run(w, hidden, lambda ep, d, G: (P.confidence_next(ep, unc), "confidence"), modules=mods)], time.perf_counter() - t)
    t = time.perf_counter()
    rs = []
    for k, order in enumerate(itertools.permutations(common.FAMILIES)):
        plan = P.family_plan(w, order, random.Random(f"C|{w['world_id']}|{k}"))
        rs.append(P.run(w, hidden, lambda ep, d, G, plan=plan: (P.plan_next(ep, plan), "broad"), modules=mods))
    res["C_broad"] = (rs, time.perf_counter() - t)
    for name, sig in VARIANTS.items():
        t = time.perf_counter()
        res[name] = ([P.run(w, hidden, lambda ep, d, G, sig=sig: P.deficiency_next(ep, d, G, unc, sig), modules=mods)], time.perf_counter() - t)
    # oracle selector: cost = size of the smallest recovering set
    base["oracle_recoverable"] = bool(O)
    base["oracle_cost"] = len(O[0]) if O else None
    base["hidden_slots"] = len(hidden)
    per = {}
    for name, (rs, secs) in res.items():
        curves = np.mean([P.curve(r) for r in rs], axis=0)
        per[name] = {"curve": curves.tolist(), "cost": float(np.mean([r["cost"] for r in rs])), "recovered": float(np.mean([r["recovered"] for r in rs])),
                     "harm": float(np.mean([r["harm"] for r in rs])), "empty": float(np.mean([sum(1 for s, n in r["log"] if s not in hidden and n == 0 and s not in set().union(*[set(x) for x in [hidden]])) for r in rs])),
                     "empty_queries": float(np.mean([sum(1 for s, n in r["log"] if n == 0) for r in rs])),
                     "unnecessary": float(np.mean([sum(1 for s, n in r["log"] if s not in union) for r in rs])) if O else None,
                     "seconds": secs / len(rs), "tags": [t for r in rs for t in r["tags"]][:40]}
    per["O_oracle"] = {"curve": [1 if (O and len(O[0]) <= b) else 0 for b in range(common.BUDGET + 1)], "cost": len(O[0]) if O else common.BUDGET, "recovered": float(bool(O)), "harm": 0.0,
                       "empty_queries": 0.0, "unnecessary": 0.0, "seconds": 0.0, "tags": []}
    base["per"] = per
    return base


def run_all():
    common.check_x0_frozen()
    eps = episode_set()
    print(f"episode worlds (oracle-correct ACT, fold B, T2 aligned): {len(eps)}", flush=True)
    EV.mkdir(exist_ok=True)
    for h in common.H_LEVELS:
        t0 = time.time()
        with mp.Pool(max(1, mp.cpu_count() - 1), initializer=_init) as pool:
            rows = pool.map(_world, [(i, h) for i in eps], chunksize=20)
        (EV / f"episodes-h{h}.json").write_text(json.dumps(rows, separators=(",", ":")), encoding="ascii")
        from collections import Counter
        c = Counter(r["klass"] for r in rows)
        print(f"  h={h}: {dict(c)} in {time.time() - t0:.0f}s", flush=True)
    (RES / "x6a-worlds.json").write_text(json.dumps({"episode_worlds": len(eps)}, indent=1), encoding="ascii")


# ================================================================================================= analysis
def boot_curves(M: dict, names: list, rng) -> dict:
    n = next(iter(M.values())).shape[0]
    idx = rng.integers(0, n, (common.BOOT, n))
    return {k: M[k][idx].mean(axis=1) for k in names}  # B x (budget+1)


def analyze():
    common.check_x0_frozen()
    rng = np.random.default_rng(common.SEED)
    receipt: dict = {"x0_frozen": common.x0_hashes(), "levels": {}}
    for h in common.H_LEVELS:
        f = EV / f"episodes-h{h}.json"
        if not f.exists():
            continue
        rows = json.loads(f.read_text(encoding="ascii"))
        from collections import Counter
        klass = Counter(r["klass"] for r in rows)
        need = [r for r in rows if r["klass"] == "needs_recovery"]
        blk: dict = {"worlds": len(rows), "classes": dict(klass), "needs_recovery": len(need), "oracle_unrecoverable": sum(1 for r in need if not r["oracle_recoverable"])}
        M = {p: np.array([r["per"][p]["curve"] for r in need]) for p in POLICIES}
        B = common.BUDGET
        mean = {p: M[p].mean(0).tolist() for p in POLICIES}
        blk["recovery_by_budget"] = mean
        auc = lambda m: m[:, : common.AUC_MAX + 1].mean(1)  # noqa: E731
        blk["auc_0_to_6"] = {p: float(auc(M[p]).mean()) for p in POLICIES}
        blk["per_policy"] = {p: {"queries_per_recovered": float(np.sum([r["per"][p]["cost"] * r["per"][p]["recovered"] for r in need]) / max(np.sum([r["per"][p]["recovered"] for r in need]), 1e-9)),
                                 "harm_rate": float(np.mean([r["per"][p]["harm"] for r in need])),
                                 "empty_queries_per_world": float(np.mean([r["per"][p]["empty_queries"] for r in need])),
                                 "unnecessary_queries_per_world": float(np.mean([r["per"][p]["unnecessary"] for r in need if r["per"][p]["unnecessary"] is not None])) if p != "O_oracle" else 0.0,
                                 "seconds_per_world": float(np.mean([r["per"][p]["seconds"] for r in need]))} for p in POLICIES}
        bs = boot_curves(M, list(POLICIES), rng)
        base_names = ["A_random", "B_confidence", "C_broad"]
        best_base = np.max(np.stack([bs[k] for k in base_names]), axis=0)   # per replicate, per budget
        gain = bs["D_full"] - best_base
        blk["D_vs_best_baseline"] = [{"budget": b, "D": float(np.median(bs["D_full"][:, b])), "best_baseline": float(np.median(best_base[:, b])), "diff": float(np.median(gain[:, b])),
                                      "ci95": [float(np.percentile(gain[:, b], 2.5)), float(np.percentile(gain[:, b], 97.5))]} for b in range(0, B + 1)]
        auc_gain = (bs["D_full"][:, : common.AUC_MAX + 1].mean(1) - best_base[:, : common.AUC_MAX + 1].mean(1))
        blk["auc_gain"] = {"median": float(np.median(auc_gain)), "ci95": [float(np.percentile(auc_gain, 2.5)), float(np.percentile(auc_gain, 97.5))]}
        # attribution: each ablation's AUC relative to the baseline frontier
        attr = {}
        base_auc = best_base[:, : common.AUC_MAX + 1].mean(1)
        for p in ("D_full", "D_no1", "D_no3", "D_only1", "D_only3", "O_oracle"):
            a = bs[p][:, : common.AUC_MAX + 1].mean(1) - base_auc
            attr[p] = {"auc_minus_best_baseline": float(np.median(a)), "ci95": [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]}
        tot = attr["D_full"]["auc_minus_best_baseline"]
        for p in ("D_no1", "D_no3"):
            attr[p]["share_of_gain_lost"] = float((tot - attr[p]["auc_minus_best_baseline"]) / tot) if tot > 1e-9 else None
        blk["attribution"] = attr
        tagc = Counter(t for r in need for t in r["per"]["D_full"]["tags"])
        blk["D_signal_firings_first40_per_world"] = dict(tagc)
        wins = sum(1 for b in (1, 2, 3) if blk["D_vs_best_baseline"][b]["ci95"][0] > 0)
        blk["decision"] = {"budgets_D_better_of_1_2_3": wins, "auc_ci_excludes_zero": bool(blk["auc_gain"]["ci95"][0] > 0),
                           "continue": bool(wins >= 2 and blk["auc_gain"]["ci95"][0] > 0)}
        receipt["levels"][str(h)] = blk
    prim = receipt["levels"].get(str(common.H_PRIMARY))
    if prim:
        named = [p for p in ("D_no1", "D_no3") if (prim["attribution"][p].get("share_of_gain_lost") or 0) >= 0.5]
        receipt["decision"] = {"primary_h": common.H_PRIMARY, **prim["decision"], "signals_carrying_at_least_half": named,
                               "outcome": ("CONTINUE" if prim["decision"]["continue"] else "STOP")}
    RES.mkdir(exist_ok=True)
    (RES / "x6a-receipt.json").write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="ascii", newline="\n")
    print(json.dumps(receipt.get("decision", {}), indent=1))


# ================================================================================================= post hoc
def _schema_pool(ep):
    return [s for s in ep.unqueried() if s[0] != "GATE" and ep.empty_looking(s)]


def _explore_world(job):
    i, h = job
    w, bundle, mods = _S["dev"][i], _S["bundle"], _S["mods"]
    bank = mods[0]
    hidden = env.hide(w, h, "hide")
    ep0 = env.Episode(w, hidden, mods)
    d0, _ = ep0.decide()
    if d0["decision"] == "ACT":
        return None
    unc = P.uncertainty(w, bundle, i)

    def schema_conf(ep, d, G):
        pool = _schema_pool(ep)
        return (sorted(pool, key=lambda s: (-unc.get(s, 0.0), s))[0] if pool else P.confidence_next(ep, unc)), "schema_conf"

    out = {}
    rs = []
    for r in range(common.RANDOM_ROLLOUTS):
        rng = random.Random(f"S|{w['world_id']}|{r}")
        rs.append(P.run(w, hidden, lambda ep, d, G, rng=rng: ((rng.choice(_schema_pool(ep)) if _schema_pool(ep) else P.random_next(ep, rng)), "schema_random"), modules=mods))
    out["S_schema_random"] = rs
    out["S_schema_conf"] = [P.run(w, hidden, schema_conf, modules=mods)]
    for name, rs in out.items():
        out[name] = {"curve": np.mean([P.curve(r) for r in rs], axis=0).tolist(), "harm": float(np.mean([r["harm"] for r in rs]))}
    # the base policies again, for paired comparison on the same worlds
    for name, sig in (("D_full", (1, 2, 3)), ("D_only3", (3,))):
        r = P.run(w, hidden, lambda ep, d, G, sig=sig: P.deficiency_next(ep, d, G, unc, sig), modules=mods)
        out[name] = {"curve": P.curve(r), "harm": float(r["harm"])}
    r = P.run(w, hidden, lambda ep, d, G: (P.confidence_next(ep, unc), "confidence"), modules=mods)
    out["B_confidence"] = {"curve": P.curve(r), "harm": float(r["harm"])}
    return out


def explore():
    common.check_x0_frozen()
    eps = episode_set()
    rng = np.random.default_rng(common.SEED)
    res: dict = {"label": "POST HOC: written after the first X6-A run; not part of the preregistered verdict", "levels": {}}
    for h in common.H_LEVELS:
        with mp.Pool(max(1, mp.cpu_count() - 1), initializer=_init) as pool:
            rows = [r for r in pool.map(_explore_world, [(i, h) for i in eps], chunksize=20) if r is not None]
        names = ["B_confidence", "D_full", "D_only3", "S_schema_random", "S_schema_conf"]
        M = {p: np.array([r[p]["curve"] for r in rows]) for p in names}
        H = {p: np.array([r[p]["harm"] for r in rows]) for p in names}
        n = len(rows)
        idx = rng.integers(0, n, (common.BOOT, n))
        auc = {p: M[p][idx][:, :, : common.AUC_MAX + 1].mean(axis=(1, 2)) for p in names}
        ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]  # noqa: E731
        blk = {"worlds": n, "auc": {p: float(M[p][:, : common.AUC_MAX + 1].mean()) for p in names},
               "harm": {p: float(H[p].mean()) for p in names}, "auc_diff": {}, "harm_diff": {}}
        for a, b in (("D_full", "B_confidence"), ("D_only3", "B_confidence"), ("D_only3", "S_schema_conf"), ("S_schema_conf", "B_confidence"), ("D_full", "S_schema_conf")):
            d = auc[a] - auc[b]
            blk["auc_diff"][f"{a}-{b}"] = {"median": float(np.median(d)), "ci95": ci(d)}
            hd = H[a][idx].mean(1) - H[b][idx].mean(1)
            blk["harm_diff"][f"{a}-{b}"] = {"median": float(np.median(hd)), "ci95": ci(hd)}
        res["levels"][str(h)] = blk
        print(h, blk["auc"], blk["harm"], flush=True)
    (RES / "x6a-explore.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="ascii", newline="\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        run_all()
    elif cmd == "analyze":
        analyze()
    elif cmd == "explore":
        explore()
    else:
        print(__doc__)
