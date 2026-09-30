"""VCS-0b attribution pass: which non-circular truth-only coordinates cause the G0 -> G1 loss?

Method. For each population and substrate:
  1. Fit the G0 geometry (all non-circular coords) and the G1 geometry (G0 minus UNAVAILABLE).
  2. For each non-circular UNAVAILABLE coordinate c, fit G0-minus-c and measure how much of
     the full G0->G1 drop that single removal recovers.
  3. Attribute: contribution(c) = loss(G0 minus c) - loss(G1), where loss = 1 - loo_1nn.

A coordinate that accounts for the loss is one whose removal alone restores most of the
1-NN accuracy that G1 throws away. Coordinates whose removal barely moves the loss are
incidental, and the handoff does not need to target them.

loss is reported on the SAME balanced row subset for every variant so the numbers are
directly comparable.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch

from src.vcs_abi_v02 import (COORD_ORDER, PROV, RUNTIME, ESTIMATOR, UNAVAILABLE, AVAILABLE,
                             ESTIMATABLE, MODEL_ESTIMATE, ORACLE_TRUTH, DIRECT, DERIVED,
                             circular_columns, g_filter, numeric_columns, to_vector,
                             descriptor, POPULATIONS, CIRCULARITY_SPEC)
from src import vcs_pop_v01 as P

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\vcs")
POPKEY = {"pop_solvability": "solvability", "pop_correctness": "observer_correctness"}


def loo_1nn(X, y):
    if X.shape[0] < 4 or X.shape[1] < 1:
        return float("nan")
    Xn = (X - X.mean(0)) / X.std(0).clamp(min=1e-6)
    D = torch.cdist(Xn, Xn)
    D.fill_diagonal_(float("inf"))
    return float((y[D.argmin(1)] == y).float().mean())


def knn_ratio(X, y, k=10):
    Xn = (X - X.mean(0)) / X.std(0).clamp(min=1e-6)
    D = torch.cdist(Xn, Xn)
    n = Xn.shape[0]
    eye = torch.eye(n, dtype=torch.bool)
    same = y[:, None] == y[None, :]
    Dm = D.clone(); Dm[eye] = float("inf")
    kk = min(k, max(2, n // 10))
    ins = torch.where(same & ~eye, Dm, torch.full_like(D, float("inf"))).topk(kk, largest=False).values
    ind = torch.where(~same, D, torch.full_like(D, float("inf"))).topk(kk, largest=False).values
    wi = float(ins[torch.isfinite(ins)].mean()); be = float(ind[torch.isfinite(ind)].mean())
    return round(wi / max(be, 1e-9), 4)


def matrix_for(vecs, sel, cols):
    sub = [[vecs[i][j] for j in cols] for i in sel]
    nc = numeric_columns(sub)
    if len(nc) < 2:
        return None, len(nc), len(cols)
    X = torch.tensor([[r[j] for j in nc] for r in sub], dtype=torch.float32)
    return X, len(nc), len(cols)


def balanced_sel(labels, seed=0):
    counts = {l: labels.count(l) for l in set(labels)}
    m = min(counts.values())
    if m < 12:
        return None, m, counts
    rng = random.Random(seed)
    sel = []
    for l in sorted(counts):
        sel += rng.sample([i for i, x in enumerate(labels) if x == l], m)
    rng.shuffle(sel)
    return sel, m, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-limit", type=int, default=900)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    from transformers import AutoTokenizer
    tokr = AutoTokenizer.from_pretrained(r"D:\phoenix-models\lfm2.5-230m-base-9d2be55")
    worlds = P.read_jsonl(BANK / "worlds" / "DEV.jsonl", args.dev_limit)
    wbi = {w["world_id"]: w for w in worlds}
    rows = [r for r in P.read_jsonl(BANK / "inputs" / "DEV.jsonl", args.dev_limit) if r["world_id"] in wbi]

    pops = {}
    for sub in ("causal", "encoder"):
        head = P.HeadBank(sub, "final", seed=args.seed).fit(steps=args.steps)
        pops[sub] = P.build_population(sub, "final", rows, wbi, "DEV", head, tokr)

    report = {"abi": descriptor(),
              "method": {
                  "loss": "1 - loo_1nn_accuracy on a fixed balanced subset",
                  "contribution": "loss(G0 minus c) - loss(G1); positive means removing c alone "
                                  "recovers that much of the G0->G1 loss",
                  "note": "G1 = G0 minus every UNAVAILABLE coordinate. Attribution is "
                          "single-coordinate removal from G0, not a partition of the loss.",
              },
              "populations": {}, "handoff": {}}

    for sub in ("causal", "encoder"):
        grp = pops[sub]
        vecs = [to_vector(r["state"]) for r in grp]
        for pk, name in POPKEY.items():
            labels = [r[pk] for r in grp]
            circ = circular_columns(name)
            noncirc = [c for c in COORD_ORDER if c not in circ]
            sel, m, counts = balanced_sel(labels, args.seed)
            entry = {"population_mix": counts, "per_class": m,
                     "circular_removed": sorted(circ)}
            if sel is None:
                entry["status"] = "class_too_small"
                report["populations"].setdefault(sub, {})[name] = entry
                continue
            lv = sorted(counts)
            yb = torch.tensor([lv.index(labels[i]) for i in sel])
            colidx = {c: COORD_ORDER.index(c) for c in COORD_ORDER}

            g0_cols = [colidx[c] for c in g_filter("G0", set(noncirc))]
            g1_cols = [colidx[c] for c in g_filter("G1", set(noncirc))]
            X0, n0, _ = matrix_for(vecs, sel, g0_cols)
            X1, n1, _ = matrix_for(vecs, sel, g1_cols)
            if X0 is None or X1 is None:
                entry["status"] = "insufficient_columns"
                report["populations"].setdefault(sub, {})[name] = entry
                continue
            a0, a1 = loo_1nn(X0, yb), loo_1nn(X1, yb)
            loss0, loss1 = 1 - a0, 1 - a1
            entry["G0"] = {"acc": round(a0, 4), "loss": round(loss0, 4), "n_cols": n0,
                           "knn_ratio": knn_ratio(X0, yb)}
            entry["G1"] = {"acc": round(a1, 4), "loss": round(loss1, 4), "n_cols": n1,
                           "knn_ratio": knn_ratio(X1, yb)}
            entry["G0_to_G1_loss"] = round(loss1 - loss0, 4)
            entry["majority_rate"] = round(1.0 / len(lv), 4)

            # ---- attribution: leave-one-IN from G1 ----
            # Removal from G0 cannot attribute this loss: the UNAVAILABLE coordinates are
            # mutually redundant, so dropping any single one leaves the others to carry the
            # same information and the score barely moves. What answers "which coordinates
            # account for the loss" is the reverse: start at G1 and add each coordinate
            # back, measuring how much of the lost accuracy that one coordinate recovers.
            g1_names = g_filter("G1", set(noncirc))
            contrib = []
            for c in noncirc:
                if RUNTIME[c] == AVAILABLE:
                    continue
                cols_in = [colidx[x] for x in (g1_names | {c})]
                Xi, ni_, _ = matrix_for(vecs, sel, cols_in)
                if Xi is None:
                    contrib.append({"coord": c, "acc": None, "recovery": None,
                                    "share_of_loss": None,
                                    "note": "adding this coordinate leaves <2 usable columns"})
                    continue
                ai = loo_1nn(Xi, yb)
                rec = ai - a1                      # accuracy recovered by adding it back
                contrib.append({"coord": c, "acc_G1_plus_c": round(ai, 4),
                                "recovery": round(rec, 4),
                                "share_of_loss": round(rec / max(loss1 - loss0, 1e-9), 4),
                                "knn_ratio": knn_ratio(Xi, yb)})
            contrib.sort(key=lambda d: -(d["recovery"] if d["recovery"] is not None else -9))
            entry["attribution_leave_one_in"] = contrib

            # redundancy check: is the loss spread or concentrated?
            pos = [c for c in contrib if (c["recovery"] or 0) > 0]
            entry["n_unavailable_noncircular"] = len(contrib)
            entry["n_with_positive_recovery"] = len(pos)
            entry["top_recovery_sum"] = round(sum(c["recovery"] for c in pos), 4)
            entry["total_loss"] = round(loss1 - loss0, 4)
            report["populations"].setdefault(sub, {})[name] = entry

    # ---------------- handoff target set ----------------
    for name in POPKEY.values():
        subs = [s for s in ("causal", "encoder") if name in report["populations"].get(s, {})
                and "attribution_leave_one_in" in report["populations"][s][name]]
        targets = {}
        for s in subs:
            e = report["populations"][s][name]
            for a in e["attribution_leave_one_in"]:
                if a["recovery"] is None or a["share_of_loss"] <= 0.10:
                    continue
                t = targets.setdefault(a["coord"], {"coord": a["coord"], "shares": []})
                t["shares"].append({"substrate": s, "share": a["share_of_loss"],
                                    "acc_G1_plus_c": a["acc_G1_plus_c"],
                                    "G1_acc": e["G1"]["acc"], "G0_acc": e["G0"]["acc"]})
        for coord, t in targets.items():
            shares = [x["share"] for x in t["shares"]]
            t["mean_share"] = round(sum(shares) / len(shares), 4)
            t["consensus"] = len(shares) == len(subs)
            t["circularity_status"] = "non-circular" if coord not in set(
                sum((list(CIRCULARITY_SPEC[n]) for n in POPKEY.values()), [])) else "circular"
            t["provenance_class"] = PROV[coord]
            t["runtime_availability"] = RUNTIME[coord]
            t["definition"] = descriptor()["coordinates"][coord]["description"]
            t["estimator_contract"] = ESTIMATOR[coord]
            t["valid_target_populations"] = [
                {"population": n,
                 "levels": POPULATIONS[n]["levels"],
                 "independent_of_coordinates": True,
                 "why_valid": "population is defined by simulator/head verdict, not by this coordinate"}
                for n in POPKEY.values()
                if not (coord in CIRCULARITY_SPEC.get(n, {}))]
            t["blocked_by_own_population"] = [n for n in POPKEY.values()
                                              if coord in CIRCULARITY_SPEC.get(n, {})]
        ranked = sorted(targets.values(), key=lambda d: -d["mean_share"])
        report["handoff"][name] = {
            "n_targets": len(ranked),
            "criteria": "non-circular, UNAVAILABLE at runtime, and single-coordinate removal "
                        "recovers >10% of the G0->G1 loss on at least one substrate",
            "targets": ranked,
        }

    (OUT / "vcs02-handoff.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"populations": {s: {n: {k: v for k, v in d.items() if k != "attribution"}
                                         for n, d in report["populations"].get(s, {}).items()}
                                      for s in report["populations"]},
                      "handoff_counts": {n: report["handoff"][n]["n_targets"] for n in report["handoff"]},
                      "out": str(OUT / "vcs02-handoff.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

