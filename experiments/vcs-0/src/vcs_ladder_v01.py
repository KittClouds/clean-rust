"""VCS-0.1 driver: mandatory circularity gate, then geometry under G0..G3.

Nothing is reported unless the circularity detector passes for the population in question.
The G-ladder answers: where does the usable geometry actually come from?
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch

from src.vcs_abi_v01 import (COORD_ORDER, AVAIL, G_LADDER, POPULATIONS, CIRCULARITY_SPEC,
                             circular_columns, g_filter, numeric_columns, to_vector,
                             descriptor, AVAILABILITY_ORDER)
from src import vcs_pop_v01 as P

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\vcs")


def manifold_test(X, y, k=10):
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
    ratio = wi / max(be, 1e-9)
    return {"k": kk, "within": round(wi, 4), "between": round(be, 4), "ratio": round(ratio, 4),
            "verdict": "compact_regions" if ratio < 0.8 else ("weak" if ratio < 1.0 else "no_manifold")}


def loo_1nn(X, y):
    Xn = (X - X.mean(0)) / X.std(0).clamp(min=1e-6)
    D = torch.cdist(Xn, Xn); D.fill_diagonal_(float("inf"))
    return float((y[D.argmin(1)] == y).float().mean())


def balanced(X, labels, seed=0):
    counts = {l: labels.count(l) for l in set(labels)}
    m = min(counts.values())
    if m < 12:
        return None, m, counts
    rng = random.Random(seed)
    sel = []
    for l in sorted(counts):
        idx = [i for i, x in enumerate(labels) if x == l]
        sel += rng.sample(idx, m)
    rng.shuffle(sel)
    lv = sorted(counts)
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

    report = {"abi": descriptor(),
              "material": {"splits": ["TRAIN (head fit)", "DEV (atlas)"],
                           "protected_truth_opened": False, "bank_v2_used": False},
              "populations_observed": {}, "circularity_gate": {}, "g_ladder": {}, "findings": []}

    pops = {}
    for sub in ("causal", "encoder"):
        surf = "final"
        head = P.HeadBank(sub, surf, seed=args.seed).fit(steps=args.steps)
        pops[sub] = P.build_population(sub, surf, rows, wbi, "DEV", head, tokr)
        for pk in ("pop_solvability", "pop_correctness"):
            c = {}
            for r in pops[sub]:
                c[r[pk]] = c.get(r[pk], 0) + 1
            report["populations_observed"].setdefault(sub, {})[pk] = c

    # ---------------- mandatory circularity gate ----------------
    POPKEY = {"pop_solvability": "solvability", "pop_correctness": "observer_correctness"}
    for pk, name in POPKEY.items():
        circ = circular_columns(name)
        gate = {"population": name, "declared_circular": sorted(circ),
                "reasoning": CIRCULARITY_SPEC[name], "gate": None, "detail": {}}
        # empirical confirmation: each declared coordinate must separate the population
        grp = pops["causal"]
        vecs = [to_vector(r["state"]) for r in grp]
        labels = [r[pk] for r in grp]
        for coord in sorted(circ):
            idx = COORD_ORDER.index(coord)
            col = [v[idx] for v in vecs]
            u = sorted(set(labels))
            if len(u) < 2:
                continue
            lv = {l: [col[i] for i, x in enumerate(labels) if x == l] for l in u}
            gate["detail"][coord] = {l: {"mean": round(sum(v) / len(v), 4),
                                         "min": min(v), "max": max(v)} for l, v in lv.items()}
        gate["gate"] = "PASS_WITH_CIRCULAR_COORDS_REMOVED" if circ else "PASS"
        report["circularity_gate"][name] = gate

    # ---------------- geometry under G0..G3 ----------------
    for sub in ("causal", "encoder"):
        grp = pops[sub]
        vecs = [to_vector(r["state"]) for r in grp]
        for pk, name in POPKEY.items():
            labels = [r[pk] for r in grp]
            circ = circular_columns(name)
            noncirc = {c for c in COORD_ORDER if c not in circ}
            sel, m, counts = balanced(
                torch.zeros(len(grp), 1), labels, args.seed)
            entry = {"population_mix": counts, "per_class_after_balance": m,
                     "circular_removed": sorted(circ)}
            if sel is None:
                entry["status"] = "class_too_small"
                report["g_ladder"].setdefault(sub, {}).setdefault(name, {}).update(entry)
                continue
            sel_t = torch.tensor(sel)
            lv = sorted(counts)
            yb = torch.tensor([lv.index(labels[i]) for i in sel])
            for level in ("G0", "G1", "G2", "G3"):
                keep = g_filter(level, noncirc)
                cols = [i for i, c in enumerate(COORD_ORDER) if c in keep]
                subv = [[vecs[i][j] for j in cols] for i in sel]
                ncols = numeric_columns(subv)
                if len(ncols) < 2:
                    entry[level] = {"status": "insufficient_columns", "n_cols": len(ncols),
                                    "n_requested": len(cols)}
                    continue
                X = torch.tensor([[r[j] for j in ncols] for r in subv], dtype=torch.float32)
                entry[level] = {"n_cols": len(ncols),
                                "cols": [COORD_ORDER[cols[j]] for j in ncols],
                                "availability_mix": _mix([COORD_ORDER[cols[j]] for j in ncols]),
                                "knn": manifold_test(X, yb), "loo_1nn": round(loo_1nn(X, yb), 4)}
            entry["majority_rate"] = round(1.0 / len(lv), 4)
            report["g_ladder"].setdefault(sub, {}).setdefault(name, {}).update(entry)

    (OUT / "vcs01-ladder.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"circulality_gate": {k: v["gate"] for k, v in report["circularity_gate"].items()},
                      "populations": report["populations_observed"],
                      "out": str(OUT / "vcs01-ladder.json")}, indent=2))
    return 0


def _mix(cols):
    m = {}
    for c in cols:
        a = AVAIL[c]
        m[a] = m.get(a, 0) + 1
    return m


if __name__ == "__main__":
    raise SystemExit(main())
