"""X1 driver.

  python run_x1.py prepare            # fit T0/T1 on the TRAIN sample, realign T2, calibrate T2 on fold A, fit the mergers of every setting on fold A   -> evidence/
  python run_x1.py evaluate [name..]  # fold B through the frozen X0 controller, per setting (parallel)                                              -> evidence/eval-<setting>.npz
  python run_x1.py analyze            # three levels, matched-harm comparison, bootstrap, controls, attribution, decision rules                      -> results/x1-receipt.json
  python run_x1.py explore            # EXPLORATORY, post hoc: the same comparison at coverage levels the mergers can reach (fractions of the graph's own maximum)   -> results/x1-explore.json
"""
from __future__ import annotations

import json
import multiprocessing as mp
import pickle
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from x1 import common, evalcore as E, producers as P  # noqa: E402
from x1.common import COVERAGE_LEVELS, THETAS  # noqa: E402

EV = ROOT / "evidence"
RES = ROOT / "results"
MODES_PRIMARY = ("defer", "asym", "sym")
_STATE: dict = {}


def worlds_split():
    dev = common.load_worlds("DEV")
    return dev


def prepare():
    common.check_x0_frozen()
    EV.mkdir(exist_ok=True)
    t0 = time.time()
    train = common.load_worlds("TRAIN", common.TRAIN_SAMPLE)
    dev = worlds_split()
    t0m, t1m, t2m = P.T0().fit(train), P.T1().fit(train), P.T2()
    align = t2m.load(dev)
    fold_a = [(i, w) for i, w in enumerate(dev) if common.fold(w["world_id"]) == 0 and i in t2m.pairs]
    fold_b = [(i, w) for i, w in enumerate(dev) if common.fold(w["world_id"]) == 1 and i in t2m.pairs]
    t2m.calib = E.fit_t2_calibration(t2m, fold_a)
    bundle = E.Bundle(t0m, t1m, t2m)
    fitted = {}
    for name, st in E.settings().items():
        fitted[name] = E.fit_setting(st, bundle, fold_a)
        print(f"  fitted {name} ({time.time() - t0:.0f}s)", flush=True)
    with open(EV / "bundle.pkl", "wb") as fh:
        pickle.dump({"bundle": bundle, "fitted": fitted}, fh)
    rep = {"x0_frozen": common.x0_hashes(), "t2_alignment": align, "fold_a": len(fold_a), "fold_b": len(fold_b), "t1_precision": t1m.precision, "t2_calibration": t2m.calib,
           "train_sample": len(train), "seconds": time.time() - t0}
    (EV / "prepare.json").write_text(json.dumps(rep, indent=1, sort_keys=True, default=str), encoding="ascii", newline="\n")
    print("prepared:", {k: rep[k] for k in ("fold_a", "fold_b")}, align["aligned"], "aligned")


def _init():
    _STATE["data"] = pickle.load(open(EV / "bundle.pkl", "rb"))
    _STATE["dev"] = worlds_split()


def _chunk(job):
    name, idxs, modes = job
    st = E.settings()[name]
    data, dev = _STATE["data"], _STATE["dev"]
    bundle, cfgs = data["bundle"], data["fitted"][name]
    cfg_names = list(cfgs)
    n, nc, nt, nm = len(idxs), len(cfg_names), len(THETAS), len(modes)
    arr = np.zeros((n, nc, nt, nm, 11), dtype=np.int16)   # u, h, a, dec_ok, tp, fp, fn, multi_loc, goal_no_loc, false_conflict, missed_conflict
    agree = np.zeros(n, dtype=bool)
    act_label = np.zeros(n, dtype=bool)
    score_rows = {c: [] for c in cfg_names}
    for r, i in enumerate(idxs):
        w = dev[i]
        agree[r] = E.oracle_agrees(w)
        bank, _b, _c = E.x0()
        act_label[r] = bank.label_class(w).startswith("ACT")
        out = E.eval_world(st, bundle, cfgs, i, w, modes)
        for ci, c in enumerate(cfg_names):
            for ti, th in enumerate(THETAS):
                for mi, mo in enumerate(modes):
                    u, h, a, ok, fl, (tp, fp, fn) = out["res"][(c, th, mo)]
                    arr[r, ci, ti, mi] = (u, h, a, ok, tp, fp, fn, fl["multi_loc"], fl["goal_no_loc"], fl["false_conflict"], fl["missed_conflict"])
        for c in cfg_names:
            score_rows[c] += out["scores"][c]
    scores = {}
    for c, rows in score_rows.items():
        scores[c] = (np.array([x[0] for x in rows], dtype=np.float32), np.array(["AT CONNECTED BLOCKED STATE REQUIRES".split().index(x[1]) for x in rows], dtype=np.int8), np.array([x[2] for x in rows], dtype=np.int8))
    return idxs, arr, agree, act_label, cfg_names, scores


def evaluate(names):
    common.check_x0_frozen()
    meta = json.loads((EV / "prepare.json").read_text(encoding="ascii"))
    dev = worlds_split()
    t2m = pickle.load(open(EV / "bundle.pkl", "rb"))["bundle"].t2
    fold_b = [i for i, w in enumerate(dev) if common.fold(w["world_id"]) == 1 and i in t2m.pairs]
    assert len(fold_b) == meta["fold_b"]
    todo = names or list(E.settings())
    for name in todo:
        modes = MODES_PRIMARY if name == f"real-m{common.PRIMARY_M}" else ("defer",)
        jobs = [(name, fold_b[i:i + 100], modes) for i in range(0, len(fold_b), 100)]
        t0 = time.time()
        with mp.Pool(max(1, mp.cpu_count() - 1), initializer=_init) as pool:
            parts = pool.map(_chunk, jobs, chunksize=1)
        idxs = np.concatenate([p[0] for p in parts])
        arr = np.concatenate([p[1] for p in parts])
        agree = np.concatenate([p[2] for p in parts])
        act_label = np.concatenate([p[3] for p in parts])
        cfg_names = parts[0][4]
        score_arrays = {}
        for c in cfg_names:
            score_arrays[f"score-{c}"] = np.concatenate([p[5][c][0] for p in parts])
            score_arrays[f"rtype-{c}"] = np.concatenate([p[5][c][1] for p in parts])
            score_arrays[f"label-{c}"] = np.concatenate([p[5][c][2] for p in parts])
        np.savez_compressed(EV / f"eval-{name}.npz", idx=idxs, arr=arr, agree=agree, act_label=act_label, cfgs=np.array(cfg_names), modes=np.array(modes), **score_arrays)
        print(f"  {name}: {len(idxs)} worlds, {int(agree.sum())} oracle-agree, {time.time() - t0:.0f}s", flush=True)


# ================================================================================================= analysis
def curve(arr: np.ndarray, ci: int, mi: int, mask: np.ndarray, act_denominator: int) -> tuple[np.ndarray, np.ndarray]:
    sel = arr[mask][:, ci, :, mi, :].astype(np.int64)   # worlds x theta x fields
    cov = sel[:, :, 0].sum(0) / max(act_denominator, 1)
    harm = sel[:, :, 1].sum(0) / max(len(sel), 1)
    return cov, harm


def envelope_at(cov: np.ndarray, harm: np.ndarray, c: float) -> float:
    """Lowest harm achievable at coverage >= c, linearly interpolated between operating points; inf if c is unreachable."""
    if cov.max() < c - 1e-12:
        return float("inf")
    pts = sorted(zip(cov.tolist(), harm.tolist()))
    best = float("inf")
    for (c1, h1), (c2, h2) in zip(pts, pts[1:]):
        if c1 <= c <= c2:
            t = 0.0 if c2 == c1 else (c - c1) / (c2 - c1)
            best = min(best, h1 + t * (h2 - h1))
    for cv, h in pts:
        if cv >= c:
            best = min(best, h)
    return best


def boot_env(arr, ci, mi, mask_idx, act_mask, rng, levels):
    """Bootstrap the matched-coverage harm of one config: returns (B x len(levels)) with inf for unreachable."""
    sub = arr[mask_idx][:, ci, :, mi, :].astype(np.float64)
    act = act_mask[mask_idx]
    n = len(sub)
    out = np.empty((common.BOOT, len(levels)))
    for b in range(common.BOOT):
        s = rng.integers(0, n, n)
        cov = sub[s, :, 0].sum(0) / max(act[s].sum(), 1)
        harm = sub[s, :, 1].sum(0) / n
        for j, lv in enumerate(levels):
            out[b, j] = envelope_at(cov, harm, lv)
    return out


def analyze():
    common.check_x0_frozen()
    meta = json.loads((EV / "prepare.json").read_text(encoding="ascii"))
    receipt: dict = {"x0_frozen": common.x0_hashes(), "t2_alignment": meta["t2_alignment"], "plan": "PLAN.md", "settings": {}}
    rng = np.random.default_rng(common.SEED)
    levels = list(COVERAGE_LEVELS)
    for name in E.settings():
        f = EV / f"eval-{name}.npz"
        if not f.exists():
            continue
        z = np.load(f)
        arr, agree, act = z["arr"], z["agree"], z["act_label"]
        cfgs, modes = [str(x) for x in z["cfgs"]], [str(x) for x in z["modes"]]
        kept_idx = np.flatnonzero(agree)
        all_idx = np.arange(len(agree))
        block: dict = {"worlds": int(len(agree)), "oracle_agree_worlds": int(len(kept_idx)), "act_labelled_in_kept": int(act[kept_idx].sum()), "modes": modes}
        flat_names = [c for c in cfgs if c.startswith("flat-")]
        for mi, mode in enumerate(modes):
            per: dict = {}
            for scope, idx in (("kept", kept_idx), ("all", all_idx)):
                den = int(act[idx].sum())
                table = {}
                for c in cfgs:
                    cov, harm = curve(arr, cfgs.index(c), mi, np.isin(all_idx, idx), den)
                    table[c] = {"coverage": cov.tolist(), "harm": harm.tolist(), "envelope": [envelope_at(cov, harm, lv) for lv in levels]}
                per[scope] = table
            block[f"curves-{mode}"] = per
            # matched comparison with bootstrap (kept worlds): graph minus the best flat variant
            boots = {c: boot_env(arr, cfgs.index(c), mi, kept_idx, act, rng, levels) for c in (["graph"] + flat_names + [c for c in cfgs if c.startswith("graph-")])}
            best_flat = np.min(np.stack([boots[c] for c in flat_names]), axis=0)
            diff = boots["graph"] - best_flat
            comp = []
            for j, lv in enumerate(levels):
                d = diff[:, j]
                fin = np.isfinite(d)
                g_unreach, f_unreach = np.isinf(boots["graph"][:, j]).mean(), np.isinf(best_flat[:, j]).mean()
                comp.append({"coverage": lv, "graph_harm": float(np.nanmedian(np.where(np.isinf(boots["graph"][:, j]), np.nan, boots["graph"][:, j]))) if fin.any() or (~np.isinf(boots["graph"][:, j])).any() else None,
                             "best_flat_harm": float(np.nanmedian(np.where(np.isinf(best_flat[:, j]), np.nan, best_flat[:, j]))) if (~np.isinf(best_flat[:, j])).any() else None,
                             "diff_median": float(np.median(d[fin])) if fin.any() else None, "ci95": [float(np.percentile(d[fin], 2.5)), float(np.percentile(d[fin], 97.5))] if fin.sum() > 50 else None,
                             "graph_unreachable_share": float(g_unreach), "flat_unreachable_share": float(f_unreach),
                             "graph_better": bool((fin.sum() > 50 and np.percentile(d[fin], 97.5) < 0) or (f_unreach > 0.95 and g_unreach < 0.05)),
                             "flat_better": bool(fin.sum() > 50 and np.percentile(d[fin], 2.5) > 0)})
            block[f"matched-{mode}"] = comp
            if mode == "defer":
                ab = {}
                for c in [c for c in cfgs if c.startswith("graph-")]:
                    row = []
                    for j, lv in enumerate(levels):
                        gh, fh, ah = np.median(boots["graph"][:, j]), np.median(best_flat[:, j]), np.median(boots[c][:, j])
                        row.append({"coverage": lv, "graph": float(gh) if np.isfinite(gh) else None, "best_flat": float(fh) if np.isfinite(fh) else None, "ablated": float(ah) if np.isfinite(ah) else None})
                    ab[c] = row
                block["ablations"] = ab
        # level 1: edge quality (AP per source and relation type; precision/recall at theta=0.6 from the tp/fp/fn sums)
        rtn = "AT CONNECTED BLOCKED STATE REQUIRES".split()
        l1 = {}
        ti6 = int(np.argmin(np.abs(np.array(THETAS) - 0.6)))
        for c in cfgs:
            sc, rt, lb = z[f"score-{c}"], z[f"rtype-{c}"], z[f"label-{c}"]
            ap = {}
            for k, nm in enumerate(rtn):
                m = rt == k
                ap[nm] = E.average_precision(list(zip(sc[m].tolist(), [0] * int(m.sum()), lb[m].tolist()))) if m.any() else None
            sel = arr[:, cfgs.index(c), ti6, 0, :].astype(np.int64)
            tp, fp, fn = sel[:, 4].sum(), sel[:, 5].sum(), sel[:, 6].sum()
            l1[c] = {"average_precision": ap, "precision_at_keep_0.6": float(tp / max(tp + fp, 1)), "recall_at_keep_0.6": float(tp / max(tp + fn, 1))}
        block["level1_edge_quality"] = l1
        # level 2: graph quality at two operating points (defer controller)
        l2 = {}
        for th in (0.6, 0.8):
            ti = int(np.argmin(np.abs(np.array(THETAS) - th)))
            l2[str(th)] = {c: {k: float(arr[kept_idx][:, cfgs.index(c), ti, 0, 7 + j].mean()) for j, k in enumerate(("multi_loc", "goal_no_loc", "false_conflict", "missed_conflict"))} for c in cfgs}
        block["level2_graph_quality"] = l2
        receipt["settings"][name] = block
    # decision
    prim = receipt["settings"].get(f"real-m{common.PRIMARY_M}")
    if prim:
        comp = prim["matched-defer"]
        wins = sum(1 for c in comp if c["graph_better"])
        survives = {m: sum(1 for c in prim[f"matched-{m}"] if c["graph_better"]) for m in prim["modes"]}
        gain = [c["best_flat_harm"] - c["graph_harm"] for c in comp if c["best_flat_harm"] is not None and c["graph_harm"] is not None]
        attribution = {}
        for c, rows in prim["ablations"].items():
            lost = [(r["ablated"] - r["graph"]) for r in rows if r["ablated"] is not None and r["graph"] is not None and r["best_flat"] is not None]
            tot = [(r["best_flat"] - r["graph"]) for r in rows if r["ablated"] is not None and r["graph"] is not None and r["best_flat"] is not None]
            attribution[c] = {"gain_lost": float(np.mean(lost)) if lost else None, "gain_total": float(np.mean(tot)) if tot else None,
                              "share_lost": float(np.mean(lost) / np.mean(tot)) if lost and np.mean(tot) > 1e-9 else None}
        earns = wins >= 2 and all(v >= 2 for v in survives.values())
        named = [c for c, a in attribution.items() if a["share_lost"] is not None and a["share_lost"] >= 0.5]
        receipt["decision"] = {"levels_graph_better": wins, "levels_graph_better_by_controller": survives, "x1_earns_continuation": bool(earns), "mean_gain_over_best_flat": float(np.mean(gain)) if gain else None,
                               "attribution": attribution, "mechanisms_carrying_at_least_half": named,
                               "outcome": ("CONTINUE" if earns and named else ("CONTINUE_UNATTRIBUTED" if earns else "STOP"))}
    RES.mkdir(exist_ok=True)
    (RES / "x1-receipt.json").write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="ascii", newline="\n")
    print(json.dumps(receipt.get("decision", {}), indent=1))


def explore():
    """Post hoc. The preregistered coverage levels (0.50/0.70/0.85) turned out to be unreachable at the primary setting, so the comparison there was undefined.
    This repeats it at fractions {0.50, 0.75, 0.90} of the graph's own maximum coverage, with the same bootstrap, and labels it exploratory."""
    common.check_x0_frozen()
    rng = np.random.default_rng(common.SEED + 1)
    out: dict = {"status": "EXPLORATORY_POST_HOC", "note": "coverage levels chosen after the preregistered ones proved unreachable; not a confirmation", "settings": {}}
    for name in E.settings():
        f = EV / f"eval-{name}.npz"
        if not f.exists():
            continue
        z = np.load(f)
        arr, agree, act = z["arr"], z["agree"], z["act_label"]
        cfgs = [str(x) for x in z["cfgs"]]
        kept = np.flatnonzero(agree)
        mask = np.isin(np.arange(len(agree)), kept)
        cov_g, _h = curve(arr, cfgs.index("graph"), 0, mask, int(act[kept].sum()))
        top = float(cov_g.max())
        levels = [round(top * f_, 3) for f_ in (0.5, 0.75, 0.9)]
        flat = [c for c in cfgs if c.startswith("flat-")]
        boots = {c: boot_env(arr, cfgs.index(c), 0, kept, act, rng, levels) for c in ["graph"] + flat + [c for c in cfgs if c.startswith("graph-")]}
        best_flat = np.min(np.stack([boots[c] for c in flat]), axis=0)
        rows = []
        for j, lv in enumerate(levels):
            d = boots["graph"][:, j] - best_flat[:, j]
            ok = np.isfinite(d)
            row = {"coverage": lv, "graph_harm": float(np.median(boots["graph"][ok, j])) if ok.any() else None, "best_flat_harm": float(np.median(best_flat[ok, j])) if ok.any() else None}
            if ok.sum() > 50:
                row.update({"diff_median": float(np.median(d[ok])), "ci95": [float(np.percentile(d[ok], 2.5)), float(np.percentile(d[ok], 97.5))]})
            ab = {}
            for c in [c for c in cfgs if c.startswith("graph-")]:
                dd = boots[c][:, j] - boots["graph"][:, j]
                okk = np.isfinite(dd)
                if okk.sum() > 50:
                    ab[c] = {"vs_graph_median": float(np.median(dd[okk])), "ci95": [float(np.percentile(dd[okk], 2.5)), float(np.percentile(dd[okk], 97.5))]}
            row["ablations_minus_graph"] = ab
            rows.append(row)
        out["settings"][name] = {"graph_max_coverage": top, "levels": rows}
    (RES / "x1-explore.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="ascii", newline="\n")
    for name, b in out["settings"].items():
        print(name, "max cov", round(b["graph_max_coverage"], 3))
        for r in b["levels"]:
            print("   cov", r["coverage"], "graph", r["graph_harm"] and round(r["graph_harm"], 4), "flat", r["best_flat_harm"] and round(r["best_flat_harm"], 4), "diff", r.get("diff_median") and round(r["diff_median"], 4), r.get("ci95") and [round(x, 4) for x in r["ci95"]])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        prepare()
    elif cmd == "evaluate":
        evaluate(sys.argv[2:])
    elif cmd == "analyze":
        analyze()
    elif cmd == "explore":
        explore()
    else:
        print(__doc__)
