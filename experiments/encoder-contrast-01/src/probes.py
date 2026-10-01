"""P3 entity-span / edge readout, and P6 role-binding contrast.

BANK-v1 is read-only here. Role-swapped inputs are re-rendered from BANK-v1 canonical
worlds into this experiment's own directory; no BANK file is written or modified.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch

from src.readout import fit_linear, predict, macro_f1, accuracy

EXP = Path(__file__).resolve().parents[1]
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")

EDGES = ["AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED", "BEFORE", "PART_OF", "ENABLES", "OWNS", "HAS"]


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def load_worlds(split: str, limit: int):
    return read_jsonl(BANK / "worlds" / f"{split}.jsonl")[:limit]


def make_pairs(worlds):
    """Directed entity-pair edge-existence dataset from canonical worlds."""
    X, y, meta = [], [], []
    for w in worlds:
        eids = [e["id"] for e in w["entities"]]
        pos = set()
        for f in w["initial_state"]:
            if f["pred"] in EDGES and len(f.get("args", [])) >= 2:
                a, b = f["args"][0], f["args"][1]
                if a in eids and b in eids:
                    pos.add((a, b))
        if not pos:
            continue
        # positives: real edges; negatives: same-type shuffled non-edges
        rng = random.Random(hash(w["world_id"]) & 0xFFFF)
        negs = set()
        tries = 0
        while len(negs) < len(pos) and tries < 200:
            tries += 1
            a, b = rng.choice(eids), rng.choice(eids)
            if a != b and (a, b) not in pos and (b, a) not in pos:
                negs.add((a, b))
        for a, b in sorted(pos):
            X.append((a, b)); y.append(1); meta.append(w["world_id"])
        for a, b in sorted(negs):
            X.append((a, b)); y.append(0); meta.append(w["world_id"])
    return X, y, meta


def ent_lookup(prim):
    """Map (world_id, entity_id) -> row index into entity_vectors."""
    lookup = {}
    running = 0
    for (bi, eids) in prim["entity_index"]:
        wid = prim["row_ids"][bi]
        for k, e in enumerate(eids):
            lookup[(wid, e)] = running + k
        running += len(eids)
    return lookup


def auc(y_true, score):
    pairs = [(s, t) for s, t in zip(score.tolist(), y_true.tolist()) if t == 1]
    negs = [s for s, t in zip(score.tolist(), y_true.tolist()) if t == 0]
    if not pairs or not negs:
        return None
    wins = 0
    for _s in negs:
        for p, _t in pairs:
            if p > _s:
                wins += 1
            elif p == _s:
                wins += 0.5
    return wins / (len(pairs) * len(negs))


def edge_pairs(worlds, allowed: set[str]):
    """Edge-existence pairs: positive = a real ordered edge between two mentioned
    entities; negative = both entities mentioned in the same row but no edge either
    direction. Negatives are therefore hard (co-mentioned, non-linked)."""
    X, y = [], []
    for w in worlds:
        wid = w["world_id"]
        if wid not in allowed:
            continue
        eids = [e["id"] for e in w["entities"]]
        pos = set()
        for f in w["initial_state"]:
            if f["pred"] in EDGES and len(f.get("args", [])) >= 2:
                a, b = f["args"][0], f["args"][1]
                if a in eids and b in eids:
                    pos.add((a, b))
        if not pos:
            continue
        rng = random.Random(abs(hash(wid)) & 0xFFFF)
        seen = set()
        negs = []
        tries = 0
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


def edge_probe(substrate: str, train_worlds, eval_worlds, feature: str):
    prim_tr = torch.load(PRIM / substrate / "TRAIN.pt", map_location="cpu", weights_only=False)
    prim_ev = torch.load(PRIM / substrate / "TEST-IID.pt", map_location="cpu", weights_only=False)
    look_tr = ent_lookup(prim_tr)
    look_ev = ent_lookup(prim_ev)
    E = prim_tr["entity_vectors"].float()
    Ev = prim_ev["entity_vectors"].float()

    def build(pairs, look, E):
        out = []
        for (a, b), wid in pairs:
            ia, ib = look.get((wid, a)), look.get((wid, b))
            if ia is None or ib is None:
                continue
            out.append(torch.cat([E[ia], E[ib]]))
        return torch.stack(out) if out else torch.zeros(0, 2048)

    Xtr, ytr = edge_pairs(train_worlds, set(prim_tr["row_ids"]))
    Xev, yev = edge_pairs(eval_worlds, set(prim_ev["row_ids"]))
    A, B = build(Xtr, look_tr, E), build(Xev, look_ev, Ev)
    if A.shape[0] < 200 or B.shape[0] < 100:
        return {"status": "insufficient_pairs", "n_train_candidates": len(Xtr), "n_eval_candidates": len(Xev),
                "n_train_usable": int(A.shape[0]), "n_eval_usable": int(B.shape[0])}
    ytr_t = torch.tensor(ytr[: A.shape[0]])
    yev_t = torch.tensor(yev[: B.shape[0]])
    mu, sd = A.mean(0), A.std(0).clamp(min=1e-4)
    net = fit_linear((A - mu) / sd, ytr_t, 2, steps=600)
    with torch.no_grad():
        prob = torch.softmax(net((B - mu) / sd), 1)[:, 1]
    return {"auc": auc(yev_t, prob), "acc": accuracy(yev_t, (prob > 0.5).long()),
            "n_train": int(A.shape[0]), "n_eval": int(B.shape[0]),
            "base_rate_eval": float(yev_t.float().mean())}


def make_pairs_with_wid(worlds):
    X, y, W = [], [], []
    for w in worlds:
        eids = [e["id"] for e in w["entities"]]
        pos = set()
        for f in w["initial_state"]:
            if f["pred"] in EDGES and len(f.get("args", [])) >= 2:
                a, b = f["args"][0], f["args"][1]
                if a in eids and b in eids:
                    pos.add((a, b))
        if not pos:
            continue
        rng = random.Random(hash(w["world_id"]) & 0xFFFF)
        negs, tries = set(), 0
        while len(negs) < len(pos) and tries < 200:
            tries += 1
            a, b = rng.choice(eids), rng.choice(eids)
            if a != b and (a, b) not in pos and (b, a) not in pos:
                negs.add((a, b))
        for a, b in sorted(pos):
            X.append((a, b)); y.append(1); W.append(w["world_id"])
        for a, b in sorted(negs):
            X.append((a, b)); y.append(0); W.append(w["world_id"])
    return list(zip(X, W)), y, W


def directed_edge_pairs(worlds, allowed: set[str]):
    """Role-binding instrument: positives are real ordered edges (a,b); negatives are
    the SAME entity pair reversed (b,a) when (b,a) is not itself an edge. A substrate
    that cannot bind role direction must sit at chance; one that can must exceed it."""
    X, y = [], []
    for w in worlds:
        wid = w["world_id"]
        if wid not in allowed:
            continue
        eids = [e["id"] for e in w["entities"]]
        edges = set()
        for f in w["initial_state"]:
            if f["pred"] in EDGES and len(f.get("args", [])) >= 2:
                a, b = f["args"][0], f["args"][1]
                if a in eids and b in eids:
                    edges.add((a, b))
        if not edges:
            continue
        for (a, b) in sorted(edges):
            if (b, a) in edges:
                continue  # symmetric: no direction to bind
            X.append(((a, b), wid)); y.append(1)
            X.append(((b, a), wid)); y.append(0)
    return X, y


def probe_from_pairs(substrate: str, split_tr: str, split_ev: str, maker, steps: int = 600):
    prim_tr = torch.load(PRIM / substrate / f"{split_tr}.pt", map_location="cpu", weights_only=False)
    prim_ev = torch.load(PRIM / substrate / f"{split_ev}.pt", map_location="cpu", weights_only=False)
    look_tr, look_ev = ent_lookup(prim_tr), ent_lookup(prim_ev)
    E, Ev = prim_tr["entity_vectors"].float(), prim_ev["entity_vectors"].float()
    BANK_W = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1" / "worlds"

    def worlds(name, cap):
        return [json.loads(l) for l in open(BANK_W / f"{name}.jsonl", encoding="utf-8")][:cap]

    Xtr, ytr = maker(worlds(split_tr, 20000), set(prim_tr["row_ids"]))
    Xev, yev = maker(worlds(split_ev, 2000), set(prim_ev["row_ids"]))

    def build(pairs, look, E):
        out = []
        for (a, b), wid in pairs:
            ia, ib = look.get((wid, a)), look.get((wid, b))
            if ia is None or ib is None:
                continue
            out.append(torch.cat([E[ia], E[ib]]))
        return torch.stack(out) if out else torch.zeros(0, 2048)

    A, B = build(Xtr, look_tr, E), build(Xev, look_ev, Ev)
    if A.shape[0] < 200 or B.shape[0] < 100:
        return {"status": "insufficient", "n_train": int(A.shape[0]), "n_eval": int(B.shape[0])}
    ya, yb = torch.tensor(ytr[: A.shape[0]]), torch.tensor(yev[: B.shape[0]])
    mu, sd = A.mean(0), A.std(0).clamp(min=1e-4)
    net = fit_linear((A - mu) / sd, ya, 2, steps=steps)
    with torch.no_grad():
        p = torch.softmax(net((B - mu) / sd), 1)[:, 1]
    return {"auc": auc(yb, p), "acc": accuracy(yb, (p > 0.5).long()),
            "n_train": int(A.shape[0]), "n_eval": int(B.shape[0]),
            "base_rate": float(yb.float().mean())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrates", default="causal,encoder")
    args = ap.parse_args()
    out = {"P3_edge_probe": {}, "P6_role_binding": {},
           "note": "P3 = unordered co-mentioned edge existence. P6 = directed edge, reversed pair as negative."}
    for sub in args.substrates.split(","):
        out["P3_edge_probe"][sub] = probe_from_pairs(sub, "TRAIN", "TEST-IID", edge_pairs)
        out["P6_role_binding"][sub] = probe_from_pairs(sub, "TRAIN", "TEST-IID", directed_edge_pairs)
    print(json.dumps(out, indent=2))
    (OUT / "p3-p6-probes.json").write_text(json.dumps(out, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
