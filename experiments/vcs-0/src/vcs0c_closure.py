"""VCS-0c closure.

Two bounded repairs, no metric redesign, no normalization change, no new arms.

1. Gate 1 interval. The previous bootstrap recomputed the whole nearest-neighbour structure
   inside every resample and returned byte-identical accuracy 150 times. Repair per the
   directive: compute FIXED leave-one-out correctness per row once per arm, then bootstrap
   the PAIRED per-row difference grouped by canonical world id. No distance recomputation
   inside the resample, so no duplicate-neighbour artefact is possible.

2. O2 reversal. Diagnose with the frozen geometry by decomposing the two truth coordinates:
   G2 + truth.n_evidence_facts, G2 + truth.n_missing_facts, G2 + both. Report distinct
   counts, variance, per-coordinate distance contribution, 1-NN and ratio. Explanation only.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.vcs0c import (BANK, R2A, OUT, EXPORT, P, preflight, build_states, mat, knn_ratio,
                       TARGETS, ELIGIBLE, CHEAP_LANE, canonical_world)
from src.vcs_abi_v02 import COORD_ORDER, RUNTIME, AVAILABLE, to_vector
from src.vcs0c_run import arm_coords, G2_COLS, truth_col

EST = {t: f"estimate.{t}" for t in TARGETS}


def loo_correct(X, y):
    """FIXED leave-one-out correctness per row. Returned once; never resampled."""
    Xn = (X - X.mean(0)) / X.std(0).clamp(min=1e-6)
    D = torch.cdist(Xn, Xn)
    D.fill_diagonal_(float("inf"))
    nn = D.argmin(1)
    return (y[nn] == y).float()


def grouped_paired_bootstrap(correct_a, correct_b, groups, n_boot=2000, seed=7):
    """d_g = mean(correct_a - correct_b) within each group. Bootstrap GROUPS with
    replacement over the per-group means only. The LOO outcomes are fixed inputs, so a
    resample cannot manufacture duplicate neighbours."""
    gmap = {}
    for i, g in enumerate(groups):
        gmap.setdefault(g, []).append(i)
    keys = sorted(gmap)
    d_all = (correct_a - correct_b)
    d_g = {k: float(d_all[gmap[k]].mean()) for k in keys}
    n_rows = {k: len(gmap[k]) for k in keys}
    rng = random.Random(seed)
    deltas, mult, nrows, tots = [], [], [], []
    for _ in range(n_boot):
        pick = [keys[rng.randrange(len(keys))] for _ in keys]
        deltas.append(sum(d_g[k] for k in pick) / len(pick))
        mult.append(len(set(pick)))
        nrows.append(sum(n_rows[k] for k in pick))
        tots.append(round(sum(float(d_all[gmap[k]].sum()) for k in pick), 6))
    deltas.sort()
    lo, hi = deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas))]
    return {
        "method": "per-group mean paired LOO difference, groups bootstrapped with replacement",
        "n_groups": len(keys), "n_boot": n_boot,
        "observed_mean_diff": round(float(d_all.mean()), 4),
        "boot_mean": round(sum(deltas) / len(deltas), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "excludes_zero": bool(lo > 0 or hi < 0),
        "variation_evidence": {
            "distinct_deltas": len(set(round(x, 9) for x in deltas)),
            "distinct_group_multiplicities": len(set(mult)),
            "distinct_sampled_row_counts": len(set(nrows)),
            "distinct_paired_totals": len(set(tots)),
            "delta_min": round(deltas[0], 6), "delta_max": round(deltas[-1], 6),
        },
    }


def coord_diagnostics(vecs, sel, cols, names):
    X, nc = mat(vecs, sel, cols)
    if X is None:
        return {"status": "insufficient_columns"}
    Z = (X - X.mean(0)) / X.std(0).clamp(min=1e-6)
    D = torch.cdist(Z, Z)
    n = Z.shape[0]
    D.fill_diagonal_(0.0)
    off = D[~torch.eye(n, dtype=torch.bool)]
    per_dim = []
    for k in range(Z.shape[1]):
        j = Z[:, k:k + 1]
        d1 = torch.cdist(j, j)
        d1.fill_diagonal_(0.0)
        d1 = d1[~torch.eye(n, dtype=torch.bool)]
        per_dim.append({
            "coord": names[k] if k < len(names) else f"col{k}",
            "variance": round(float(j.var()), 6),
            "distinct": int(torch.unique(j).shape[0]),
            "mean_abs_distance": round(float(d1.abs().mean()), 6),
            "share_of_total_mean_distance": round(float(d1.abs().mean()) / max(float(off.abs().mean()), 1e-9), 4),
        })
    return {"n_cols": nc, "overall_mean_distance": round(float(off.abs().mean()), 6),
            "per_coordinate": per_dim}


def main() -> int:
    fails, checks, rows, groups = preflight()
    if fails:
        print("PREFLIGHT FAIL", fails)
        return 1
    print("PREFLIGHT: PASS")

    worlds = {json.loads(l)["world_id"]: json.loads(l)
              for l in (BANK / "worlds" / "DEV.jsonl").open(encoding="utf-8") if l.strip()}
    export_by_id = {}
    for line in EXPORT.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            export_by_id[d["world_id"]] = {
                lane: {t: d["estimates_by_lane"][lane][EST[t]]["runtime_count"] for t in TARGETS}
                for lane in d["estimates_by_lane"]}

    order = list(COORD_ORDER) + [f"{lane}.{EST[t]}"
                                 for lane in list(ELIGIBLE) + [CHEAP_LANE] for t in TARGETS]
    import src.vcs_abi_v02 as ABI
    ABI.COORD_ORDER = order

    out = {"preflight": checks, "gate1_repair": {}, "o2_diagnosis": {}, "outcome": None,
           "vcs_1b_earned": False,
           "note": "threshold, arms, metrics and normalization unchanged by the closure"}

    for sub in ("causal", "encoder"):
        head = P.HeadBank(sub, "final", seed=0).fit(steps=200)
        base = build_states(sub, head, rows, groups, worlds, export_by_id)
        vecs = []
        for r in base:
            v = to_vector(r["state"])
            extra = [float(r["estimates"][lane][t])
                     for lane in list(ELIGIBLE) + [CHEAP_LANE] for t in TARGETS]
            vecs.append(v + extra)
        gl = [r["group"] for r in base]

        for pk in ("pop_correctness", "pop_solvability"):
            labels = [r[pk] for r in base]
            cnt = {l: labels.count(l) for l in set(labels)}
            m = min(cnt.values())
            if m < 12:
                continue
            rng = random.Random(0)
            sel = []
            for l in sorted(cnt):
                sel += rng.sample([i for i, x in enumerate(labels) if x == l], m)
            rng.shuffle(sel)
            lv = sorted(cnt)
            y = torch.tensor([lv.index(labels[i]) for i in sel])
            gs = [gl[i] for i in sel]
            key = f"{sub}/{pk}"

            # ---------- gate 1: fixed LOO, grouped paired bootstrap ----------
            corr = {}
            for arm in ("G2", "G3-CHEAP", "G3-BASE", "G3-NER", "G3-HYBRID-FIXED"):
                X, nc = mat(vecs, sel, arm_coords(arm, order))
                if X is None:
                    continue
                corr[arm] = loo_correct(X, y)
            g1 = {"point_acc": {a: round(float(c.mean()), 4) for a, c in corr.items()}}
            for a in ("G3-CHEAP", "G3-BASE", "G3-NER", "G3-HYBRID-FIXED"):
                if a in corr:
                    g1[a + "_vs_G2"] = grouped_paired_bootstrap(corr[a], corr["G2"], gs)
            best = max((a for a in g1["point_acc"] if a != "G2"),
                       key=lambda a: g1["point_acc"][a])
            g1["best_arm"] = best
            g1["best_point_acc"] = g1["point_acc"].get(best)
            g1["best_supported"] = [a for a in g1["point_acc"] if a != "G2"
                                    and g1.get(a + "_vs_G2", {}).get("excludes_zero")]
            g1["PASS"] = bool(best in g1["best_supported"]
                              and g1["point_acc"][best] > g1["point_acc"]["G2"])
            out["gate1_repair"][key] = g1

            # ---------- O2 reversal diagnosis ----------
            g2 = [i for i, c in enumerate(order) if c in G2_COLS]
            d = {
                "G2": torch.tensor(g2),
                "G2+truth.n_evidence_facts": g2 + [order.index(truth_col("n_evidence_facts"))],
                "G2+truth.n_missing_facts": g2 + [order.index(truth_col("n_missing_facts"))],
                "O2_both": g2 + [order.index(truth_col(t)) for t in TARGETS],
            }
            diag = {}
            for name, cols in d.items():
                X, nc = mat(vecs, sel, cols)
                if X is None:
                    diag[name] = {"status": "insufficient_columns"}
                    continue
                e = {"n_cols": nc, "acc": round(float(loo_correct(X, y).mean()), 4),
                     "ratio": round(knn_ratio(X, y), 4),
                     "normalization": "z-score using this arm's own mean/std, clamp 1e-6",
                     "diagnostics": coord_diagnostics(vecs, sel, cols,
                                                      [order[i] for i in cols])}
                diag[name] = e
            base_acc = diag["G2"]["acc"]
            diag["reversal"] = {
                "G2": base_acc, "O2_both": diag["O2_both"]["acc"],
                "delta": round(diag["O2_both"]["acc"] - base_acc, 4),
                "which_coordinate_causes_it": (
                    "n_evidence_facts" if diag["G2+truth.n_evidence_facts"]["acc"] < base_acc - 1e-9
                    else "n_missing_facts" if diag["G2+truth.n_missing_facts"]["acc"] < base_acc - 1e-9
                    else "neither_singly"),
                "reading": "more truth does not imply better Euclidean neighbourhood geometry",
            }
            out["o2_diagnosis"][key] = diag

    # final ledger
    prim = out["gate1_repair"].get("causal/pop_correctness", {})
    if prim:
        best = prim.get("best_arm")
        cheap = prim["point_acc"].get("G3-CHEAP")
        ba = prim["point_acc"].get(best, 0)
        out["outcome"] = "C" if (ba - prim["point_acc"]["G2"]) <= 0.01 else (
            "A" if ba > cheap + 0.01 else "B")
        out["gates"] = {
            "1_beats_G2_paired_grouped_bootstrap": {"PASS": prim.get("PASS"), "arm": best},
            "3_recovers_25pct_of_G0_G2_gap": {"PASS": False,
                                              "note": "unchanged from the main run: 15.4% < 25%"},
            "5_neural_beats_cheap": {"PASS": bool(best != "G3-CHEAP" and ba > cheap + 0.005),
                                     "best_arm": best, "best": ba, "cheap": cheap},
            "2_ratio_moves_toward_oracle": {"PASS": True,
                                            "note": "unchanged from the main run; O2 caveat recorded"},
            "4_circularity_degeneracy": {"PASS": True},
        }
        out["vcs_1b_earned"] = all(v.get("PASS") for v in out["gates"].values())

    (OUT / "vcs0c-closure.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({"outcome": out["outcome"], "vcs_1b_earned": out["vcs_1b_earned"],
                      "gate1": {k: {"PASS": v.get("PASS"), "best": v.get("best_arm"),
                                    "acc": v.get("best_point_acc")}
                                for k, v in out["gate1_repair"].items()},
                      "gates": out.get("gates")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
