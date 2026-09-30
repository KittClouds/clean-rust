"""VCS-0 atlas driver: degeneracy screen -> population map -> geometry -> shift behavior.

All on development material (BANK-v1 TRAIN for head fit + DEV worlds for evaluation).
protected/test-truth is never opened. No BANK-v2.

The atlas answers the charter's geometric questions without collapsing to a scalar:
  - does a compact region exist at all (per outcome population)?
  - is it action-specific?
  - does causal vs bidirectional reshape it?
  - does shift translate / rotate / fragment it?
  - which coordinates actually move the boundary?
  - are safe regions disconnected islands or one thresholdable blob?
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from src.vcs_abi import (abi_descriptor, coordinate_order, degeneracy_report, new_state,
                         numeric_columns, to_vector, state_hash)
from src import vcs_build as B

EXP = Path(__file__).resolve().parents[1]
OUT = Path(r"D:\codex-runs\encoder-contrast-01\vcs")
SURFACES = ["first", "final", "mean", "full_mean", "layer-4", "middle"]


def screen_degeneracy(substrate: str) -> dict:
    feats = {}
    for s in SURFACES:
        p = torch.load(B.PRIM / substrate / "DEV.pt", map_location="cpu", weights_only=False)
        feats[s] = p["surfaces"][s].float()
    return degeneracy_report(feats, p["surfaces"]["final"].shape[0])


def outcome_of(row: dict) -> str:
    """Map a BANK decision + correctness into a control-outcome population label."""
    d = row.get("decision")
    if d == "ABSTAIN":
        return "ABSTAIN"
    if d == "ASK":
        return "ASK"
    return "EXECUTE"


def pca(X: torch.Tensor, k: int = 3) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    mu = X.mean(0)
    Z = X - mu
    U, S, V = torch.linalg.svd(Z, full_matrices=False)
    V = V[:k]
    P = Z @ V.T
    ev = (S ** 2) / (len(X) - 1)
    return P, V, ev


def region_stats(P: torch.Tensor, labels: list[str], name: str) -> dict:
    groups = {}
    for lab in sorted(set(labels)):
        idx = [i for i, l in enumerate(labels) if l == lab]
        if len(idx) < 8:
            groups[lab] = {"n": len(idx), "note": "too few for geometry"}
            continue
        Q = P[idx]
        cen = Q.mean(0)
        spread = Q.std(0)
        groups[lab] = {"n": len(idx), "centroid": [round(float(x), 4) for x in cen],
                       "spread": [round(float(x), 4) for x in spread]}
    # separability of each pair by centroid distance / pooled spread
    sep = {}
    labs = [l for l in groups if "centroid" in groups[l]]
    for a in labs:
        for b in labs:
            if a >= b:
                continue
            ca = torch.tensor(groups[a]["centroid"])
            cb = torch.tensor(groups[b]["centroid"])
            sa = torch.tensor(groups[a]["spread"]) + 1e-6
            sb = torch.tensor(groups[b]["spread"]) + 1e-6
            d = float(torch.norm((ca - cb) / (sa + sb)))
            sep[f"{a}|{b}"] = round(d, 4)
    return {"population": name, "groups": groups, "centroid_separation_d": sep}


def boundary_coords(X: torch.Tensor, labels: list[str], coords: list[int], order: list[str]) -> list[dict]:
    """Which raw coordinates best separate the outcome populations? Univariate effect
    size (difference of means over pooled sd) per coordinate, computed in the measured
    coordinate basis (not the PCA basis, which would be uninterpretable)."""
    out = []
    for k in range(X.shape[1]):
        col = X[:, k]
        name = order[coords[k]] if k < len(coords) else f"col{k}"
        vals = {}
        for lab in sorted(set(labels)):
            idx = [i for i, l in enumerate(labels) if l == lab]
            vals[lab] = (float(col[idx].mean()), float(col[idx].std() + 1e-9))
        labs = sorted(vals)
        best = None
        for a in labs:
            for b in labs:
                if a >= b:
                    continue
                ma, sa = vals[a]
                mb, sb = vals[b]
                pooled = (sa + sb) / 2
                # A zero-variance population makes the ratio explode. That is a real
                # structural fact (one population is constant on this coordinate), so
                # report it as a saturated effect with an explicit flag rather than 1e9.
                if pooled <= 1e-12:
                    d = 10.0
                    flag = "SINGLE_VALUE"
                else:
                    d = min(abs(ma - mb) / pooled, 10.0)
                    flag = None
                if best is None or d > best[0]:
                    best = (d, f"{a}|{b}", flag)
        if best:
            out.append({"coord": name, "cohens_d": round(best[0], 4), "pair": best[1],
                        **({"flag": best[2]} if best[2] else {})})
    out.sort(key=lambda x: -x["cohens_d"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dev-limit", type=int, default=2000)
    ap.add_argument("--steps", type=int, default=300)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    report = {"abi": abi_descriptor(), "material": {"splits": ["TRAIN (head fit)", "DEV (atlas)"],
               "protected_truth_opened": False, "bank_v2_used": False},
               "degeneracy": {}, "surfaces_admitted": {}, "populations": {}, "boundary": {},
               "substrate_geometry": {}, "notes": []}

    worlds = B.dev_worlds(args.dev_limit)
    worlds_by_id = {w["world_id"]: w for w in worlds}
    dev_rows = [r for r in B.dev_rows(args.dev_limit) if r["world_id"] in worlds_by_id]
    order = coordinate_order()

    # ---- degeneracy screen (both substrates) ----
    for sub in ("causal", "encoder"):
        report["degeneracy"][sub] = screen_degeneracy(sub)
        admitted = [s for s in SURFACES if not report["degeneracy"][sub][s]["degenerate"]]
        report["surfaces_admitted"][sub] = admitted
        excluded = [s for s in SURFACES if report["degeneracy"][sub][s]["degenerate"]]
        if excluded:
            report["notes"].append(
                f"{sub}: excluded degenerate surfaces {excluded} (distinct-vector ratio below 1%)")

    # ---- population geometry on admitted surfaces ----
    all_rows = []
    for sub in ("causal", "encoder"):
        admitted = report["surfaces_admitted"][sub]
        if not admitted:
            continue
        for surf in admitted:
            head = B.HeadBank(sub, surf, seed=args.seed).fit(steps=args.steps)
            pop = B.build_population(sub, surf, dev_rows, worlds_by_id, "DEV", head, args.seed)
            for r in pop:
                r["substrate"] = sub
                r["surface"] = surf
                r["outcome"] = outcome_of(r)
            all_rows.extend(pop)
            key = f"{sub}/{surf}"
            report["populations"][key] = {"n": len(pop),
                                          "outcome_mix": {o: sum(1 for r in pop if r["outcome"] == o)
                                                          for o in sorted({r["outcome"] for r in pop})},
                                          "n_legal_actions": {
                                              str(k): sum(1 for r in pop if r["geometry"]["n_legal_actions"] == k)
                                              for k in sorted({r["geometry"]["n_legal_actions"] for r in pop})[:8]},
                                          "head": head.descriptor()}

    if not all_rows:
        (OUT / "atlas.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": "NO_ADMITTED_SURFACES", "report": str(OUT / "atlas.json")}, indent=2))
        return 1

    # ---- geometry per (substrate, surface) on numeric, non-degenerate coordinates ----
    for key, grp in _group(all_rows, lambda r: f"{r['substrate']}/{r['surface']}").items():
        vecs = [to_vector(r["state"]) for r in grp]
        cols = numeric_columns(vecs)
        if len(cols) < 2:
            report["populations"][key]["geometry"] = {"status": "insufficient_numeric_columns",
                                                       "n_cols": len(cols)}
            continue
        X = torch.tensor([[v[j] for j in cols] for v in vecs], dtype=torch.float32)
        k = min(3, len(cols))
        P, V, ev = pca(X, k)
        labels = [r["outcome"] for r in grp]
        ev_ratio = (ev / ev.sum()).tolist()
        report["populations"][key]["geometry"] = {
            "n_rows": len(grp),
            "n_numeric_cols": len(cols),
            "cols_used": [order[j] for j in cols],
            "pca_explained_variance_ratio": [round(float(x), 4) for x in ev_ratio],
            "region_stats": region_stats(P, labels, "outcome"),
            "boundary_coords": boundary_coords(X, labels, cols, order)[:10],
            "state_hash_sample": state_hash(grp[0]["state"]),
        }
        report["substrate_geometry"].setdefault(key.split("/")[0], {})[key] = {
            "pca_ratio": [round(float(x), 4) for x in ev_ratio],
            "region_stats": region_stats(P, labels, "outcome"),
        }

    (OUT / "atlas.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "ATLAS_COMPLETE",
                      "admitted": report["surfaces_admitted"],
                      "populations": list(report["populations"]),
                      "out": str(OUT / "atlas.json")}, indent=2))
    return 0


def _group(rows, keyfn):
    g = {}
    for r in rows:
        g.setdefault(keyfn(r), []).append(r)
    return g


if __name__ == "__main__":
    raise SystemExit(main())
