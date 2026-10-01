"""ENCODER-CONTRAST-01 readout harness.

Trains identical linear heads over cached primitives for both substrates and reports
the accessibility map per stratum. No benchmark sweep: every number is a coordinate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

EXP = Path(__file__).resolve().parents[1]
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")
SURFACES = ["first", "final", "mean", "full_mean", "layer-4", "middle"]
STRATA = ["TEST-IID", "TEST-LEXICAL", "TEST-ENTITY", "TEST-TEMPLATE", "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION", "TEST-JOINT"]
ROUTE_ACTIONS = ["MOVE", "ACTIVATE", "DEACTIVATE", "TAKE", "DROP", "TRANSFER", "OPEN", "CLOSE", "WAIT", "NOOP", "REQUEST"]
DECISIONS = ["ACT", "ASK", "ABSTAIN"]
NLI = ["ENTAILED", "CONTRADICTED", "UNKNOWN"]


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def load_split(substrate: str, split: str) -> dict:
    prim = torch.load(PRIM / substrate / f"{split}.pt", map_location="cpu", weights_only=False)
    truth = {r["world_id"]: r["labels"] for r in read_jsonl(BANK / "protected" / "test-truth" / f"{split}.jsonl")} if split.startswith("TEST-") else None
    rows = []
    for i, wid in enumerate(prim["row_ids"]):
        lab = truth.get(wid) if truth is not None else prim["labels"][i].get("labels")
        if lab is None:
            continue
        rows.append((i, wid, lab))
    return prim, rows


def targets(rows, kind: str):
    """Return (indices, labels) for an endpoint, or None if degenerate."""
    ys = []
    for _i, _w, lab in rows:
        pol = lab.get("policy", {})
        if kind == "decision":
            ys.append(DECISIONS.index(pol.get("decision")) if pol.get("decision") in DECISIONS else -1)
        elif kind == "route":
            ys.append(ROUTE_ACTIONS.index(pol.get("action")) if pol.get("action") in ROUTE_ACTIONS else -1)
        elif kind == "abstain":
            ys.append(str(lab.get("abstention", {}).get("reason") or "NONE"))
        elif kind == "nli":
            ys.append(NLI.index(lab.get("nli")) if lab.get("nli") in NLI else -1)
    if kind == "abstain":
        uniq = sorted(set(ys))
        m = {u: i for i, u in enumerate(uniq)}
        return [i for i, (_a, _b, l) in rows if l.get("abstention", {}).get("decision") == "ABSTAIN"], [m[y] for y in ys if y != "NONE"] if False else None, uniq
    keep = [(i, y) for (i, (_a, _b, l)) , y in zip([(i) for i, _w, _l in rows], ys) if y != -1]
    return [k[0] for k in keep], [k[1] for k in keep]


def build_xy(rows, kind: str):
    idx, ys = [], []
    for i, _w, lab in rows:
        pol = lab.get("policy", {})
        if kind == "decision":
            d = pol.get("decision")
            if d in DECISIONS:
                idx.append(i); ys.append(DECISIONS.index(d))
        elif kind == "route":
            a = pol.get("action")
            if a in ROUTE_ACTIONS:
                idx.append(i); ys.append(ROUTE_ACTIONS.index(a))
        elif kind == "abstain":
            if lab.get("abstention", {}).get("decision") == "ABSTAIN" and lab["abstention"].get("reason"):
                idx.append(i); ys.append(str(lab["abstention"]["reason"]))
        elif kind == "nli":
            v = lab.get("nli")
            if v in NLI:
                idx.append(i); ys.append(NLI.index(v))
    return idx, ys


def fit_linear(X: torch.Tensor, y: torch.Tensor, n_classes: int, steps: int = 300, seed: int = 0, hidden: int = 0):
    torch.manual_seed(seed)
    D = X.shape[1]
    if hidden:
        net = torch.nn.Sequential(torch.nn.Linear(D, hidden), torch.nn.ReLU(), torch.nn.Linear(hidden, n_classes))
    else:
        net = torch.nn.Linear(D, n_classes)
    opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, steps)
    for _ in range(steps):
        opt.zero_grad()
        loss = torch.nn.functional.cross_entropy(net(X), y)
        loss.backward()
        opt.step()
        sched.step()
    net.eval()
    return net


def predict(net, X: torch.Tensor) -> torch.Tensor:
    with torch.no_grad():
        return net(X).argmax(1)


def macro_f1(y_true: torch.Tensor, y_pred: torch.Tensor, n_classes: int) -> float:
    f1s = []
    for c in range(n_classes):
        tp = int(((y_pred == c) & (y_true == c)).sum())
        fp = int(((y_pred == c) & (y_true != c)).sum())
        fn = int(((y_pred != c) & (y_true == c)).sum())
        if tp + fp + fn == 0:
            continue
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def accuracy(y_true, y_pred) -> float:
    return float((y_true == y_pred).float().mean()) if len(y_true) else 0.0


def run_endpoint(prim, train_rows, eval_sets, surface: str, kind: str, seed: int, hidden: int = 0, label_map=None):
    tr_idx, tr_y = build_xy(train_rows, kind)
    if not tr_idx:
        return None
    X = prim["surfaces"][surface].float()
    if label_map is None:
        classes = sorted(set(tr_y))
        label_map = {c: i for i, c in enumerate(classes)}
    ytr = torch.tensor([label_map[v] for v in tr_y])
    Xtr = X[tr_idx]
    # standardize on train only
    mu, sd = Xtr.mean(0), Xtr.std(0).clamp(min=1e-4)
    net = fit_linear((Xtr - mu) / sd, ytr, len(label_map), seed=seed, hidden=hidden)
    out = {}
    for name, (eprim, erows) in eval_sets.items():
        ei, ey = build_xy(erows, kind)
        if not ei:
            out[name] = None
            continue
        Xt = (eprim["surfaces"][surface].float()[ei] - mu) / sd
        yp = predict(net, Xt)
        yt = torch.tensor([label_map.get(v, 0) for v in ey])
        out[name] = {"accuracy": accuracy(yt, yp), "macro_f1": macro_f1(yt, yp, len(label_map)), "n": len(ey)}
    return out, net, (mu, sd), label_map


def route_exact(train_rows, eval_rows, surface, prim_tr, prim_ev, seed, hidden=0):
    """Route exactness = action type AND all arguments correct."""
    def pack(rows, prim):
        feats, ys = [], []
        for i, w, lab in rows:
            pol = lab.get("policy", {})
            if pol.get("decision") != "ACT" or not pol.get("action"):
                continue
            feats.append(i)
            ys.append(json.dumps({"a": pol.get("action"), "g": pol.get("arguments", {})}, sort_keys=True))
        return feats, ys
    ftr, ytr_s = pack(train_rows, prim_tr)
    classes = sorted(set(ytr_s))
    lmap = {c: i for i, c in enumerate(classes)}
    if len(classes) < 2 or len(ftr) < 50:
        return None
    X = prim_tr["surfaces"][surface].float()[ftr]
    ytr = torch.tensor([lmap[v] for v in ytr_s])
    mu, sd = X.mean(0), X.std(0).clamp(min=1e-4)
    net = fit_linear((X - mu) / sd, ytr, len(classes), seed=seed, hidden=hidden)
    fe, ye_s = pack(eval_rows, prim_ev)
    if not fe:
        return None
    Xt = (prim_ev["surfaces"][surface].float()[fe] - mu) / sd
    yp = [classes[i] for i in predict(net, Xt).tolist()]
    hit = sum(1 for a, b in zip(yp, ye_s) if a == b) / len(ye_s)
    return {"route_exact": hit, "n": len(ye_s), "n_classes": len(classes)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-split", default="TRAIN")
    ap.add_argument("--strata", default=",".join(STRATA))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--substrates", default="causal,encoder")
    ap.add_argument("--nonlinear", action="store_true")
    ap.add_argument("--tag", default="v01")
    args = ap.parse_args()

    strata = [s for s in args.strata.split(",") if s]
    prim_by_sub = {}
    rows_by_sub = {}
    eval_by_sub = {}
    for sub in args.substrates.split(","):
        p, r = load_split(sub, args.train_split)
        prim_by_sub[sub] = p
        rows_by_sub[sub] = r
        eval_by_sub[sub] = {s: load_split(sub, s) for s in strata}

    results = {"tag": args.tag, "seed": args.seed, "endpoints": {}, "route": {}, "inputs": {}}
    for sub in prim_by_sub:
        results["inputs"][sub] = {}
        for name, ev in eval_by_sub[sub].items():
            base = "inputs" if name in ("TRAIN", "DEV") else "public/test-inputs"
            f = BANK / base / f"{name}.jsonl"
            results["inputs"][sub][name] = {"sha256": sha_file(f), "rows": len(ev[1])}
        results["inputs"][sub][args.train_split] = {
            "sha256": sha_file(BANK / "inputs" / f"{args.train_split}.jsonl"),
            "rows": len(rows_by_sub[sub]),
        }

    for sub in prim_by_sub:
        prim_tr, rows_tr = prim_by_sub[sub], rows_by_sub[sub]
        for surface in SURFACES:
            key = f"{sub}/{surface}"
            for kind in ("decision", "route", "abstain", "nli"):
                r = run_endpoint(prim_tr, rows_tr, eval_by_sub[sub], surface, kind, args.seed)
                if r is None:
                    continue
                scores, net, norm, lmap = r
                results["endpoints"].setdefault(f"{kind}/{surface}/{sub}", {})[sub] = scores
            re_ = route_exact(rows_tr, eval_by_sub[sub]["TEST-IID"][1], surface, prim_tr, eval_by_sub[sub]["TEST-IID"][0], args.seed)
            results["route"].setdefault(f"{surface}/{sub}", {})["TEST-IID"] = re_
            for s in strata:
                re2 = route_exact(rows_tr, eval_by_sub[sub][s][1], surface, prim_tr, eval_by_sub[sub][s][0], args.seed)
                results["route"][f"{surface}/{sub}"][s] = re2

    if args.nonlinear:
        for sub in prim_by_sub:
            prim_tr, rows_tr = prim_by_sub[sub], rows_by_sub[sub]
            best = max(SURFACES, key=lambda s: (results["route"].get(f"{s}/{sub}", {}).get("TEST-IID") or {}).get("route_exact", 0))
            for kind in ("decision", "nli"):
                r = run_endpoint(prim_tr, rows_tr, eval_by_sub[sub], best, kind, args.seed, hidden=32)
                if r is None:
                    continue
                scores, *_ = r
                results["endpoints"].setdefault(f"{kind}/{best}-mlp32/{sub}", {})[sub] = scores
            re2 = route_exact(rows_tr, eval_by_sub[sub]["TEST-IID"][1], best, prim_tr, eval_by_sub[sub]["TEST-IID"][0], args.seed, hidden=32)
            results["route"].setdefault(f"{best}-mlp32/{sub}", {})["TEST-IID"] = re2

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"contrast-{args.tag}.json"
    p.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"written": str(p), "keys": list(results["endpoints"])[:6]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
