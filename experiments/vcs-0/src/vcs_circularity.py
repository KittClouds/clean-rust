"""VCS-0: is the outcome partition geometric, or is it definitional?

The atlas currently reports that `applicability.gold_action_legal` and
`semantic.n_missing_facts` separate EXECUTE from ABSTAIN/ASK with saturated effect size.
That is suspicious for a geometric claim, because BANK-v1 derives the decision label from
exactly those fields:

    decision == "EXECUTE"  <=>  selected_action is not None
    gold_action_legal      <=>  selected_action in simulator legal set
    n_missing_facts        >   0 iff the world has missing_information

If the partition is definitional rather than geometric, no atlas can discover it, and
reporting it as a discovered region would be circular.

This module quantifies circularity by removing label-defining coordinates and asking
whether the remaining evidence geometry still separates outcomes. It also fits a
nearest-neighbour manifold test to distinguish "compact region" from "thresholdable
scalar" from "nothing".
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import torch

from src.vcs_abi import new_state, set_coord, numeric_columns, to_vector, abi_descriptor
from src import vcs_build as B

EXP = Path(__file__).resolve().parents[1]
OUT = Path(r"D:\codex-runs\encoder-contrast-01\vcs")

# Coordinates that are (near-)label-defining under BANK-v1's own generator.
CIRCULAR = {
    "applicability.gold_action_legal": "decision==EXECUTE <=> selected_action is not None; "
                                       "legality is derived from that same selected_action",
    "semantic.n_missing_facts": "n_missing_facts>0 <=> ASK/INSUFFICIENT construction in the generator",
    "applicability.n_legal_alternatives": "derived from gold_action_legal by subtraction",
    "semantic.has_contradiction": "CONTRADICTION mode is the only generator path to CONFLICTING_EVIDENCE",
}

# Coordinates that are evidence-bearing and NOT label-defining by construction.
NONCIRCULAR = [
    "control.top_choice_prob", "control.margin", "control.entropy",
    "control.legal_set_support", "applicability.alt_support",
    "applicability.unlawful_top_prob", "semantic.n_evidence_facts",
    "semantic.goal_distance", "applicability.n_repair_alternatives",
]


def coords_present(rows) -> list[str]:
    order = []
    st0 = rows[0]["state"]
    for blk, cs in st0.items():
        for name in cs:
            order.append(f"{blk}.{name}")
    return order


def select(vecs: list[list[float]], order: list[str], keep: set[str]) -> list[list[float]]:
    idx = [i for i, c in enumerate(order) if c in keep]
    return [[r[i] for i in idx] for r in vecs]


def knn_manifold_test(X: torch.Tensor, y: torch.Tensor) -> dict:
    """Within-class vs between-class k-NN distance ratio. ~1.0 means no manifold;
    << 1 means compact within-class regions relative to between-class spread."""
    Xn = (X - X.mean(0)) / (X.std(0).clamp(min=1e-6))
    D = torch.cdist(Xn, Xn)
    n = Xn.shape[0]
    k = min(10, max(3, n // 20))
    same = y[:, None] == y[None, :]
    eye = torch.eye(n, dtype=torch.bool)
    Dm = D.clone()
    Dm[eye] = float("inf")
    kk = min(k, n - 1)
    idx_same = torch.where(same & ~eye, Dm, torch.full_like(D, float("inf"))).topk(kk, largest=False).values
    idx_diff = torch.where(~same, D, torch.full_like(D, float("inf"))).topk(kk, largest=False).values
    within = float(idx_same[torch.isfinite(idx_same)].mean())
    between = float(idx_diff[torch.isfinite(idx_diff)].mean())
    return {"k": kk, "within_knn": round(within, 4), "between_knn": round(between, 4),
            "ratio": round(within / max(between, 1e-9), 4),
            "interpretation": "compact_regions" if within / max(between, 1e-9) < 0.8
                              else "no_manifold"}


def per_class_1nn_accuracy(X: torch.Tensor, y: torch.Tensor) -> float:
    """Leave-one-out 1-NN accuracy in the evidence geometry."""
    Xn = (X - X.mean(0)) / (X.std(0).clamp(min=1e-6))
    D = torch.cdist(Xn, Xn)
    D.fill_diagonal_(float("inf"))
    nn = D.argmin(1)
    return float((y[nn] == y).float().mean())


def main() -> int:
    worlds = B.dev_worlds(600)
    worlds_by_id = {w["world_id"]: w for w in worlds}
    dev_rows = [r for r in B.dev_rows(600) if r["world_id"] in worlds_by_id]
    out = {"abi": abi_descriptor(),
           "circularity_audit": {
               "declared_circular": CIRCULAR,
               "noncircular_candidates": NONCIRCULAR,
               "reasoning": "BANK-v1 derives decision labels from the selected_action and from "
                            "the generator's scenario mode, so any coordinate read off those "
                            "fields is label-defining. A geometric claim built on them is circular."},
           "tests": {}}

    for sub in ("causal", "encoder"):
        surf = "final"
        head = B.HeadBank(sub, surf, seed=0).fit(steps=150)
        pop = B.build_population(sub, surf, dev_rows, worlds_by_id, "DEV", head, 0)
        order = coords_present(pop)
        vecs = [to_vector(r["state"]) for r in pop]
        labels = [r.get("outcome") or B.outcome_label(r) for r in pop]

        for tag, keep in (("all_coords", set(order)),
                          ("excluding_declared_circular", set(NONCIRCULAR)),
                          ("control_block_only", {c for c in order if c.startswith("control.")}),
                          ("semantic_block_only", {c for c in order if c.startswith("semantic.")})):
            V = select(vecs, order, keep)
            cols = numeric_columns(V)
            if len(cols) < 2 or len(set(labels)) < 2:
                out["tests"].setdefault(sub, {})[tag] = {"status": "insufficient",
                                                         "n_cols": len(cols)}
                continue
            X = torch.tensor([[r[j] for j in cols] for r in V], dtype=torch.float32)
            y = torch.tensor([sorted(set(labels)).index(l) for l in labels])
            classes = sorted(set(labels))
            counts = {c: labels.count(c) for c in classes}
            # balance by subsampling the largest class to the smallest
            m = min(counts.values())
            if m >= 15:
                by = {}
                for lab in classes:
                    idx = [i for i, l in enumerate(labels) if l == lab]
                    by[lab] = random.Random(0).sample(idx, m)
                sel = [i for lab in classes for i in by[lab]]
                Xb, yb = X[sel], torch.tensor([classes.index(labels[i]) for i in sel])
                out["tests"].setdefault(sub, {})[tag] = {
                    "n_rows": len(sel), "per_class": m,
                    "knn": knn_manifold_test(Xb, yb),
                    "loo_1nn_accuracy": round(per_class_1nn_accuracy(Xb, yb), 4),
                    "majority_rate": round(1.0 / len(classes), 4),
                    "cols": [order[j] for j in cols]}
            else:
                out["tests"].setdefault(sub, {})[tag] = {"status": "class_too_small",
                                                         "counts": counts}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "circularity.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["tests"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
