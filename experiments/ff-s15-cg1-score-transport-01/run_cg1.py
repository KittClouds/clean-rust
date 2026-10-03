"""C-G1: score transport and calibration under shift. Reads C-G0's frozen evidence; writes results/cg1-census.json. No training, no fresh split.

  python run_cg1.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from cg1 import transforms as T

ROOT = Path(__file__).resolve().parent
CG0 = ROOT.parent / "ff-s15-cg0-edge-pruning-01" / "evidence"
RESULTS = ROOT / "results"
TEST_SPLITS = ("TEST-IID", "TEST-LEXICAL", "TEST-ENTITY", "TEST-TEMPLATE", "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION", "TEST-JOINT")
EPSILONS = (0.01, 0.02)
HELD = (7, 8, 9)
SEED = 20260929


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frozen() -> dict:
    """C-G0's scores and T0 counts, verified against the hashes C-G0 recorded when it produced them."""
    recorded = json.loads((CG0 / "prepare.json").read_text(encoding="ascii"))["evidence_sha256"]
    for name, digest in recorded.items():
        if sha256(CG0 / name) != digest:
            raise SystemExit(f"C-G0 evidence {name} does not match its recorded hash")
    counts = json.loads((CG0 / "t0-train-counts.json").read_text(encoding="ascii"))
    zero = [c for c in range(len(counts["pairs"])) if counts["pairs"][c] > 0 and counts["edges"][c] == 0]
    return {"zero_codes": np.array(zero), "evidence_sha256": recorded, "zero_type_pairs": zero}


def pool(splits) -> dict:
    parts = [np.load(CG0 / f"universe-{s}.npz") for s in splits]
    return {k: np.concatenate([p[k] for p in parts]) for k in ("row", "label", "pair_type", "family", "score")}


class Population:
    """One evaluated set of pairs: T0's share is fixed by type, and only residual pairs are transformed and thresholded."""

    def __init__(self, data: dict, zero_codes: np.ndarray):
        self.d = data
        self.t0 = np.isin(data["pair_type"], zero_codes)
        self.edges = int(data["label"].sum())
        self.non_edges = int((1 - data["label"]).sum())
        self.t0_non_edges = int((self.t0 & (data["label"] == 0)).sum())
        self.t0_edges = int((self.t0 & (data["label"] == 1)).sum())
        self.residual = ~self.t0

    def subset(self, mask: np.ndarray, zero_codes: np.ndarray) -> "Population":
        return Population({k: v[mask] for k, v in self.d.items()}, zero_codes)

    def transformed(self, method: str, score: np.ndarray | None = None) -> np.ndarray:
        r = self.residual
        s = self.d["score"] if score is None else score
        return T.transform(method, self.d["row"][r], self.d["pair_type"][r], s[r])

    def label_residual(self) -> np.ndarray:
        return self.d["label"][self.residual]


def main() -> int:
    frozen = load_frozen()
    zc = frozen["zero_codes"]
    dev = Population(pool(["DEV"]), zc)
    test = Population(pool(TEST_SPLITS), zc)
    assert dev.t0_edges == 0 and test.t0_edges == 0, "T0 loses an edge somewhere"
    held_mask = np.isin(test.d["family"], HELD)
    pops = {"pooled": test, "held": test.subset(held_mask, zc), **{f"S{f}": test.subset(test.d["family"] == f, zc) for f in range(12)}}
    out = {"schema": "cg1-census/v1", "epsilons": list(EPSILONS), "zero_type_pairs": frozen["zero_type_pairs"], "evidence_sha256": frozen["evidence_sha256"],
           "t0_share": {name: p.t0_non_edges / p.non_edges for name, p in pops.items()} | {"DEV": dev.t0_non_edges / dev.non_edges}, "methods": {}, "control_shuffled": {}, "geometry": {}}
    controls = {"dev": T.shuffle_within_rows(dev.d["row"][dev.residual], dev.d["score"][dev.residual], SEED), "test": T.shuffle_within_rows(test.d["row"][test.residual], test.d["score"][test.residual], SEED + 1)}

    def run(method: str, shuffled: bool) -> dict:
        def expand(pop, values):
            full = np.full(len(pop.d["label"]), np.nan)
            full[pop.residual] = values
            return full

        if shuffled:
            d_scores, t_scores = expand(dev, controls["dev"]), expand(test, controls["test"])
            dev_t = dev.transformed(method, d_scores)
            test_t_full = expand(test, test.transformed(method, t_scores))
        else:
            dev_t = dev.transformed(method)
            test_t_full = expand(test, test.transformed(method))
        results = {}
        for eps in EPSILONS:
            t = T.fit_threshold(dev_t, dev.label_residual(), dev.edges, eps)
            row = {"threshold": t, "dev": T.evaluate(dev_t, dev.label_residual(), t, dev.edges, dev.non_edges, dev.t0_non_edges)}
            for name, pop in pops.items():
                mask = np.ones(len(test.d["label"]), bool) if name == "pooled" else (held_mask if name == "held" else test.d["family"] == int(name[1:]))
                res_mask = mask[test.residual]
                sub_t = test_t_full[test.residual][res_mask]
                row[name] = T.evaluate(sub_t, test.d["label"][test.residual][res_mask], t, pop.edges, pop.non_edges, pop.t0_non_edges)
            results[str(eps)] = row
        return results

    for method in T.METHODS:
        res = run(method, shuffled=False)
        out["methods"][method] = {"by_epsilon": res, "gate": T.gate({e: {"pooled": r["pooled"], "held": r["held"]} for e, r in res.items()})}
        ctrl = run(method, shuffled=True)
        out["control_shuffled"][method] = {e: {"pooled_loss": r["pooled"]["edge_loss"], "pooled_gain": r["pooled"]["gain"]} for e, r in ctrl.items()}
        # geometry: where do TEST edge scores sit relative to DEV's, after the transform?
        dev_t = dev.transformed(method)
        dev_edge_q = float(np.quantile(dev_t[dev.label_residual() == 1], 0.01))
        test_t = test.transformed(method)
        fam = test.d["family"][test.residual]
        lab = test.label_residual()
        fam_q = {f"S{f}": float(np.quantile(test_t[(fam == f) & (lab == 1)], 0.01)) for f in range(12)}
        out["geometry"][method] = {"dev_edge_q01": dev_edge_q, "test_edge_q01_by_renderer": fam_q}
        gates = out["methods"][method]["gate"]
        r1, r2 = res["0.01"], res["0.02"]
        print(f"{method:20s} eps1%: pooled loss {r1['pooled']['edge_loss']*100:5.2f}% held {r1['held']['edge_loss']*100:5.2f}% S9 {r1['S9']['edge_loss']*100:5.2f}% gain {r1['pooled']['gain']*100:5.1f} | "
              f"eps2%: pooled {r2['pooled']['edge_loss']*100:5.2f}% held {r2['held']['edge_loss']*100:5.2f}% S9 {r2['S9']['edge_loss']*100:5.2f}% gain {r2['pooled']['gain']*100:5.1f} | advances: {gates['advances']}")
    # post hoc, NOT preregistered and chosen after the TEST-side failure was seen: what if the DEV budget is derated (fit at a smaller epsilon than the target)?
    derate = {}
    held_res = held_mask[test.residual]
    s9_res = (test.d["family"] == 9)[test.residual]
    for method in T.METHODS:
        dev_t = dev.transformed(method)
        test_t = test.transformed(method)
        rows = {}
        for eps in (0.0005, 0.001, 0.002, 0.005):
            t = T.fit_threshold(dev_t, dev.label_residual(), dev.edges, eps)
            row = {}
            for name, mask_res, pop in (("pooled", np.ones(len(test_t), bool), pops["pooled"]), ("held", held_res, pops["held"]), ("S9", s9_res, pops["S9"])):
                row[name] = T.evaluate(test_t[mask_res], test.label_residual()[mask_res], t, pop.edges, pop.non_edges, pop.t0_non_edges)
            rows[str(eps)] = row
        derate[method] = rows
    out["exploratory_derated_budget_post_hoc"] = {"note": "not preregistered; designed after the TEST-side failure was seen; a candidate for the fresh split, not a pass", "by_method": derate}
    out["decision"] = {"advancing": [m for m in T.METHODS if out["methods"][m]["gate"]["advances"]]}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "cg1-census.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")
    print("advancing:", out["decision"]["advancing"], "| wrote", path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
