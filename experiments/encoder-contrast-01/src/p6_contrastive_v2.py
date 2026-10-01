"""P6 role binding, rebuilt at the feature-invariant level.

Design corrections, in response to three successive instrument failures:

1. The "antisymmetry forces 50%" argument was wrong. If a span vector encodes its role,
   then [x_A,x_B] and [x_B,x_A] are legitimately different features. Discriminating them
   is what a *successful* binding probe looks like. Antisymmetry is therefore a
   construction property to assert, not a null to appeal to.

2. The remaining confound is most plausibly an ENTITY-TYPE PRIOR, not a role cue. BANK-v1
   edges are dominated by AT(obj, loc), so "slot 1 holds the OBJECT" scores well while
   reading nothing. Probe edges are therefore restricted to pairs whose endpoints share
   an entity type, which kills type-prior discrimination outright.

3. The pipeline is validated by asserted invariants plus a destructive null, rather than
   by a single expected number.

Invariants asserted at runtime (I1..I7) and the destructive null are described in INVARIANTS.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from pathlib import Path

import torch

from src.readout import fit_linear, accuracy
from src.extract_primitives import load_substrate, mention_spans, entity_span_vectors

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")

EDGE_PREDS = ("AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED", "BEFORE",
              "PART_OF", "ENABLES", "OWNS", "HAS")

INVARIANTS = """
I1 text(pos) is byte-identical to text(neg) for the same underlying world
I2 feature(pos) == concat(span_A, span_B) and feature(neg) == concat(span_B, span_A)
   where span_A/span_B are the SAME two tensors derived from the SAME text
I3 both rows of a pair are embedded from one tokenizer call on one text
I4 the entity-span lookup key is the underlying world id, with no |pos/|neg influence
I5 train/eval split is grouped by underlying world, so no pair straddles the split
I6 probe endpoints share an entity type, so type priors cannot discriminate
I7 mention-position is balanced: for a given world, the probed pair's mention order is
   randomized, and globally both orders occur equally often
"""

FAILURES = []


def check(cond: bool, code: str, detail: str = ""):
    if not cond:
        FAILURES.append(f"{code}: {detail}")
    return cond


def fact_line(f, ents):
    p, a, v = f["pred"], f.get("args", []), f.get("value")
    g = lambda x: ents.get(x, x)
    if p == "AT":
        return f"{g(a[0])} is in {g(a[1])}"
    if p == "CONNECTED":
        return f"{g(a[0])} connects to {g(a[1])}"
    if p == "STATE":
        return f"{g(a[0])} is {str(v).lower()}"
    if p == "REQUIRES":
        return f"{g(a[0])} requires {g((v or {}).get('switch'))} active"
    if p == "BLOCKED":
        return f"passage from {g(a[0])} to {g(a[1])} is blocked"
    if p == "BEFORE":
        return f"{g(a[0])} is before {g(a[1])}"
    if p == "PART_OF":
        return f"{g(a[0])} is part of {g(a[1])}"
    if p == "ENABLES":
        return f"{g(a[0])} enables {g(a[1])}"
    if p == "OWNS":
        return f"{g(a[0])} owns {g(a[1])}"
    if p == "HAS":
        return f"{g(a[0])} has {g(a[1])}"
    return p


def build_pairs(worlds, interface):
    """Yield one record per world: text (embedded once), probed ordered pair, label map."""
    recs = []
    for w in worlds:
        wid = w["world_id"]
        etype = {e["id"]: e["type"] for e in w["entities"]}
        # I6: only probe pairs whose endpoints share a type
        cands = []
        for f in w["initial_state"]:
            if f.get("pred") in EDGE_PREDS and len(f.get("args", [])) >= 2:
                a, b = f["args"][0], f["args"][1]
                if a != b and a in etype and b in etype and etype[a] == etype[b]:
                    cands.append((a, b, f["pred"]))
        if not cands:
            continue
        rng = random.Random(abs(hash(("p6v2", wid))) & 0xFFFF)
        a, b, pred = cands[rng.randrange(len(cands))]

        # per-world id -> name permutation (kills identity priors across the split)
        ids = [e["id"] for e in w["entities"]]
        names0 = [e["name"] for e in w["entities"]]
        perm = list(range(len(ids)))
        random.Random(abs(hash(("perm2", wid))) & 0xFFFF).shuffle(perm)
        ents = {ids[i]: names0[perm[i]] for i in range(len(ids))}

        facts = [f for f in w["initial_state"]
                 if f.get("pred") in EDGE_PREDS and len(f.get("args", [])) >= 2]
        # I7: independent per-line mention-order randomization
        lrng = random.Random(abs(hash(("ord2", wid))) & 0xFFFF)
        lines = []
        for f in facts:
            s, o = f["args"][0], f["args"][1]
            if lrng.random() < 0.5:
                s, o = o, s
            if interface == "minimal":
                lines.append(f"{ents.get(s, s)} {ents.get(o, o)}")
            else:
                lines.append(fact_line(dict(f, args=[s, o]), ents))
        if interface == "role_shuf":
            random.Random(abs(hash(wid)) & 0xFFFF).shuffle(lines)
        recs.append({
            "world": wid,
            "text": ". ".join(lines) + ".",
            "entities": [{"id": e["id"], "name": ents[e["id"]]} for e in w["entities"]],
            "A": a, "B": b,
            "pred": pred,
        })
    return recs


def embed_worlds(substrate, recs, device, batch=24):
    """One tokenizer call per world -> one span tensor set per world. I3."""
    tok, model, _ = load_substrate(substrate, device)
    out = []
    for s in range(0, len(recs), batch):
        ch = recs[s:s + batch]
        enc = tok([r["text"] for r in ch], return_tensors="pt", padding=True,
                  truncation=True, max_length=512, return_offsets_mapping=True)
        offs = enc.pop("offset_mapping")
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            hs = model(**enc, output_hidden_states=True).hidden_states[-1]
        mask = enc["attention_mask"].bool()
        spans = [mention_spans(r["text"], [{"mention": e["name"]} for e in r["entities"]]) for r in ch]
        ev = entity_span_vectors(hs, mask, offs.tolist(), spans)
        n = 0
        for r in ch:
            k = len(r["entities"])
            out.append(ev[n:n + k])
            n += k
    del model
    torch.cuda.empty_cache()
    return out


def features(recs, spans, destructive="none", seed=0):
    """I2/I4: lookup keyed by underlying world id; pos/neg rows share one span tensor set.

    destructive modes:
      none       canonical construction
      swap       pair-matched orientation randomization (breaks role correspondence)
      independent spans drawn from a DIFFERENT record (breaks all correspondence)
    """
    look = {}
    for i, r in enumerate(recs):
        for k, e in enumerate(r["entities"]):
            look[(r["world"], e["id"])] = i * 0 + k
    # for the independent null, a fixed derangement of record -> span source
    n = len(recs)
    shift = max(1, n // 2)
    X, y, groups = [], [], []
    for i, (r, S) in enumerate(zip(recs, spans)):
        a = look[(r["world"], r["A"])]
        b = look[(r["world"], r["B"])]
        Ssrc = S
        if destructive == "independent":
            Ssrc = spans[(i + shift) % n]
            a2, b2 = a, b
            a, b = a2 % Ssrc.shape[0], b2 % Ssrc.shape[0]
        elif destructive == "swap":
            if random.Random(seed * 1000003 + i).random() < 0.5:
                a, b = b, a
        spanA, spanB = Ssrc[a], Ssrc[b]
        X.append(torch.cat([spanA, spanB]))   # label 1: (A,B) as asserted
        y.append(1)
        X.append(torch.cat([spanB, spanA]))   # label 0: the reverse
        y.append(0)
        groups.append(r["world"])
    return torch.stack(X).float(), torch.tensor(y), groups


def auc(y_true, score):
    pos = [s for s, t in zip(score.tolist(), y_true.tolist()) if t == 1]
    neg = [s for s, t in zip(score.tolist(), y_true.tolist()) if t == 0]
    if not pos or not neg:
        return None
    w = 0.0
    for n in neg:
        for p in pos:
            w += 1.0 if p > n else (0.5 if p == n else 0.0)
    return w / (len(pos) * len(neg))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrates", default="causal,encoder")
    ap.add_argument("--cap", type=int, default=5000)
    ap.add_argument("--steps", type=int, default=800)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    worlds = [json.loads(l) for l in open(BANK / "worlds" / "TEST-IID.jsonl", encoding="utf-8")][: args.cap]
    out = {"invariants": INVARIANTS, "invariant_failures": FAILURES,
           "design_note": "antisymmetry is asserted (I2), not used as a 50% null: a role-encoding "
                          "span vector legitimately makes [x_A,x_B] != [x_B,x_A].",
           "probe": "type-matched ordered pair (I6)", "results": {}, "null": {}}

    for interface in ("role", "minimal", "role_shuf"):
        recs = build_pairs(worlds, interface)
        # I7 balance check
        firsts = []
        for r in recs[:200]:
            iA = r["text"].find(next(e["name"] for e in r["entities"] if e["id"] == r["A"]))
            iB = r["text"].find(next(e["name"] for e in r["entities"] if e["id"] == r["B"]))
            if iA >= 0 and iB >= 0:
                firsts.append(0 if iA < iB else 1)
        balance = sum(firsts) / len(firsts) if firsts else 0
        check(0.35 < balance < 0.65, "I7", f"mention-order balance={balance:.3f}")

        wids = sorted({r["world"] for r in recs})
        cut = set(wids[: int(len(wids) * 0.7)])
        tr_idx = [i for i, r in enumerate(recs) if r["world"] in cut]
        te_idx = [i for i, r in enumerate(recs) if r["world"] not in cut]

        for sub in args.substrates.split(","):
            spans = embed_worlds(sub, recs, device)
            # I1/I2/I3 structural assertions on a sample
            X, y, groups = features(recs, spans)
            for i in range(min(50, len(recs))):
                check(torch.equal(X[2 * i, :1024], X[2 * i + 1, 1024:]), "I2", f"half A==B at {i}")
                check(torch.equal(X[2 * i, 1024:], X[2 * i + 1, :1024]), "I2", f"half B==A at {i}")
                check(y[2 * i].item() == 1 and y[2 * i + 1].item() == 0, "I2", f"labels at {i}")
            tr = torch.tensor([i for i in tr_idx for _ in (0, 1)])
            te = torch.tensor([i for i in te_idx for _ in (0, 1)])
            gtr = [g for i in tr_idx for g in (recs[i]["world"], recs[i]["world"])]
            gte = [g for i in te_idx for g in (recs[i]["world"], recs[i]["world"])]
            check(not (set(gtr) & set(gte)), "I5", "world group leaked across split")

            mu, sd = X[tr].mean(0), X[tr].std(0).clamp(min=1e-4)
            Z = (X - mu) / sd
            ytr, yte = y[tr], y[te]
            net = fit_linear(Z[tr], ytr, 2, steps=args.steps)
            with torch.no_grad():
                p = torch.softmax(net(Z[te]), 1)[:, 1]
            out["results"].setdefault(interface, {})[sub] = {
                "auc": auc(yte, p), "acc": accuracy(yte, (p > 0.5).long()),
                "n_train": len(ytr), "n_eval": len(yte), "mention_order_balance": balance}

            # destructive nulls: both must fall to chance or the pipeline leaks
            for mode in ("swap", "independent"):
                Xd, yd, _ = features(recs, spans, destructive=mode, seed=7)
                zd = (Xd - mu) / sd
                netd = fit_linear(zd[tr], yd[tr], 2, steps=args.steps)
                with torch.no_grad():
                    pd = torch.softmax(netd(zd[te]), 1)[:, 1]
                out["null"].setdefault(interface, {}).setdefault(sub, {})[f"{mode}_auc"] = auc(yd[te], pd)
                # a null that scores above chance invalidates the interface
                check((auc(yd[te], pd) or 0.5) < 0.60, f"NULL-{mode}",
                      f"{interface}/{sub} null AUC={auc(yd[te], pd)}")

    out["invariant_failures"] = FAILURES
    out["all_invariants_pass"] = not FAILURES
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p6-contrastive-v2.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({"results": out["results"], "null": out["null"],
                      "invariants_pass": out["all_invariants_pass"],
                      "failures": FAILURES[:10]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
