"""P4 capacity sweep: does edge existence survive with a *cheaper* readout?

Head width is swept on identical cached entity-span primitives for both substrates.
Reports TEST-IID AUC and held-renderer (S7/S8/S9) AUC so we can see whether the
bidirectional substrate buys margin at equal width, or lets a narrower head match.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch

from src.readout import fit_linear
from src.probes import ent_lookup, PRIM, EDGES, auc

OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")
BANK = Path(r"C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1")
WIDTHS = [0, 4, 16, 64, 256]


def edge_pairs(worlds, allowed):
    X, y = [], []
    for w in worlds:
        wid = w["world_id"]
        if wid not in allowed:
            continue
        eids = [e["id"] for e in w["entities"]]
        pos = set()
        for f in w["initial_state"]:
            if f.get("pred") in EDGES and len(f.get("args", [])) >= 2:
                a, b = f["args"][0], f["args"][1]
                if a in eids and b in eids:
                    pos.add((a, b))
        if not pos:
            continue
        rng = random.Random(abs(hash(wid)) & 0xFFFF)
        seen, negs, tries = set(), [], 0
        while len(negs) < len(pos) and tries < 400:
            tries += 1
            a, b = rng.choice(eids), rng.choice(eids)
            if a == b or (a, b) in pos or (b, a) in pos or (a, b) in seen:
                continue
            seen.add((a, b))
            negs.append((a, b))
        for a, b in sorted(pos):
            X.append(((a, b), wid)); y.append(1)
        for a, b in negs:
            X.append(((a, b), wid)); y.append(0)
    return X, y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrates", default="causal,encoder")
    ap.add_argument("--steps", type=int, default=600)
    args = ap.parse_args()
    out = {"widths": WIDTHS, "note": "width 0 = linear; else 1 hidden layer of that width", "results": {}}
    for sub in args.substrates.split(","):
        ptr = torch.load(PRIM / sub / "TRAIN.pt", map_location="cpu", weights_only=False)
        pev = torch.load(PRIM / sub / "TEST-IID.pt", map_location="cpu", weights_only=False)
        pte = torch.load(PRIM / sub / "TEST-TEMPLATE.pt", map_location="cpu", weights_only=False)
        lt, le, lte = ent_lookup(ptr), ent_lookup(pev), ent_lookup(pte)
        Et = ptr["entity_vectors"].float()

        def worlds(name, cap):
            return [json.loads(l) for l in open(BANK / "worlds" / f"{name}.jsonl", encoding="utf-8")][:cap]

        Xtr, ytr = edge_pairs(worlds("TRAIN", 20000), set(ptr["row_ids"]))

        def build(pairs, look, E):
            out_ = []
            for (a, b), wid in pairs:
                ia, ib = look.get((wid, a)), look.get((wid, b))
                if ia is None or ib is None:
                    continue
                out_.append(torch.cat([E[ia], E[ib]]))
            return torch.stack(out_) if out_ else torch.zeros(0, 2048)

        A = build(Xtr, lt, Et)
        ya = torch.tensor(ytr[: A.shape[0]])
        # subsample for tractability: the sweep is about width, not sample size
        if A.shape[0] > 20000:
            g = torch.Generator().manual_seed(0)
            sel = torch.randperm(A.shape[0], generator=g)[:20000]
            A, ya = A[sel], ya[sel]
        mu, sd = A.mean(0), A.std(0).clamp(min=1e-4)
        A = (A - mu) / sd
        entry = {}
        for ev_name, (pe, lk) in (("TEST-IID", (pev, le)), ("TEST-TEMPLATE", (pte, lte))):
            Xe, ye = edge_pairs(worlds(ev_name, 2000), set(pe["row_ids"]))
            B = build(Xe, lk, pe["entity_vectors"].float())
            yb = torch.tensor(ye[: B.shape[0]])
            if B.shape[0] > 8000:
                g = torch.Generator().manual_seed(0)
                sel = torch.randperm(B.shape[0], generator=g)[:8000]
                B, yb = B[sel], yb[sel]
            B = (B - mu) / sd
            for h in WIDTHS:
                net = fit_linear(A, ya, 2, steps=args.steps, hidden=h)
                with torch.no_grad():
                    p = torch.softmax(net(B), 1)[:, 1]
                entry.setdefault(str(h), {})[ev_name] = auc(yb, p)
            print(sub, ev_name, json.dumps({k: v for k, v in entry[str(WIDTHS[-1])].items()}))
        out["results"][sub] = entry
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p4-capacity.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["results"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
